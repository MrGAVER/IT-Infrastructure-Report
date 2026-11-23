"""Тесты сетевого доступа: список разрешённых клиентов (IP/подсети) и проверка заголовка Host.

Фильтр клиентов — самый внешний слой HTTP-защиты (app.services.network_access): адрес вне списка получает 403
до проверки Host и аутентификации. Запуск: pytest backend/tests/test_network_access.py -v
"""

from __future__ import annotations

import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.main as main_module
from app.constants import ErrorCode
from app.main import _warn_if_remote_access_without_auth, install_http_security
from app.services import network_access
from app.services.network_access import (
    has_remote_clients,
    is_client_allowed,
    is_ip_literal_host,
    parse_client_networks,
)

LOOPBACK = "127.0.0.0/8"


def _networks(*entries: str):
    return parse_client_networks(entries)


def _app_with_security(*, clients: list[str] | None, hosts: list[str] | None = None) -> FastAPI:
    app = FastAPI()

    @app.get("/ping")
    def ping() -> dict:
        return {"ok": True}

    install_http_security(
        app,
        allowed_hosts=hosts if hosts is not None else ["localhost", "127.0.0.1"],
        cors_origins=[],
        allowed_clients=_networks(*clients) if clients is not None else None,
    )
    return app


def _client(app: FastAPI, ip: str, host: str = "127.0.0.1") -> TestClient:
    """Клиент с заданным адресом TCP-соединения (его видит middleware в scope['client']) и заголовком Host."""
    return TestClient(app, base_url=f"http://{host}", client=(ip, 50000))


# ---------------------------------------------------------------------------
# Разбор списка адресов и подсетей
# ---------------------------------------------------------------------------
class TestParseClientNetworks:
    def test_single_address_and_subnet(self):
        networks = _networks("192.168.1.15", "10.0.5.0/24")
        assert [str(n) for n in networks] == ["192.168.1.15/32", "10.0.5.0/24"]

    def test_host_bits_in_mask_are_tolerated(self):
        assert [str(n) for n in _networks("192.168.1.5/24")] == ["192.168.1.0/24"]

    def test_surrounding_spaces_are_ignored(self):
        assert [str(n) for n in _networks("  192.168.1.15  ")] == ["192.168.1.15/32"]

    @pytest.mark.parametrize("bad", ["192.168.1", "abc", "192.168.1.0/33", "192.168.1.256", "192.168.1.0/24/8", ""])
    def test_invalid_entry_raises_with_the_offending_text(self, bad):
        with pytest.raises(ValueError, match="Некорректный IP-адрес или подсеть"):
            parse_client_networks([bad])

    def test_ipv6_is_parsed(self):
        assert [str(n) for n in _networks("fd00::/8")] == ["fd00::/8"]


class TestIsClientAllowed:
    def test_address_inside_and_outside_the_subnet(self):
        networks = _networks("192.168.1.0/24")
        assert is_client_allowed("192.168.1.77", networks)
        assert not is_client_allowed("192.168.2.77", networks)

    def test_exact_address_entry_allows_only_that_computer(self):
        networks = _networks("192.168.1.15")
        assert is_client_allowed("192.168.1.15", networks)
        assert not is_client_allowed("192.168.1.16", networks)

    def test_ipv4_mapped_ipv6_client_matches_an_ipv4_subnet(self):
        assert is_client_allowed("::ffff:192.168.1.77", _networks("192.168.1.0/24"))

    def test_address_family_mismatch_is_not_allowed(self):
        assert not is_client_allowed("::1", _networks("192.168.1.0/24"))
        assert not is_client_allowed("192.168.1.1", _networks("fd00::/8"))

    @pytest.mark.parametrize("host", [None, "", "testclient", "not-an-ip"])
    def test_client_without_an_ip_address_is_rejected(self, host):
        assert not is_client_allowed(host, _networks("0.0.0.0/0"))

    def test_empty_list_allows_nobody(self):
        assert not is_client_allowed("127.0.0.1", [])

    def test_loopback_variants(self):
        networks = _networks(LOOPBACK, "::1")
        assert is_client_allowed("127.0.0.1", networks)
        assert is_client_allowed("127.5.5.5", networks)
        assert is_client_allowed("::1", networks)
        assert is_client_allowed("::ffff:127.0.0.1", networks)


class TestHasRemoteClients:
    def test_loopback_only_is_not_network_access(self):
        assert not has_remote_clients(_networks(LOOPBACK, "::1"))
        assert not has_remote_clients([])

    def test_any_non_loopback_entry_is_network_access(self):
        assert has_remote_clients(_networks(LOOPBACK, "192.168.1.15"))


class TestIpLiteralHost:
    @pytest.mark.parametrize("header", ["192.168.1.10", "192.168.1.10:8000", "[::1]:8000", "[fd00::5]", "127.0.0.1"])
    def test_ip_addresses(self, header):
        assert is_ip_literal_host(header)

    @pytest.mark.parametrize(
        "header", ["", "localhost", "reestr.corp.local:8000", "evil.example", "192.168.1.10.evil.example", "[unclosed"]
    )
    def test_names_are_not_ip_literals(self, header):
        assert not is_ip_literal_host(header)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
class TestClientAccessMiddleware:
    def test_allowed_client_passes_and_foreign_client_gets_403(self):
        app = _app_with_security(clients=[LOOPBACK, "192.168.1.0/24"])
        assert _client(app, "127.0.0.1").get("/ping").status_code == 200
        assert _client(app, "192.168.1.50", host="192.168.1.10").get("/ping").status_code == 200
        denied = _client(app, "203.0.113.7", host="192.168.1.10").get("/ping")
        assert denied.status_code == 403
        assert denied.json()["detail"]["code"] == ErrorCode.CLIENT_NOT_ALLOWED

    def test_default_loopback_only_list_rejects_every_other_address(self):
        app = _app_with_security(clients=[LOOPBACK])
        assert _client(app, "127.0.0.1").get("/ping").status_code == 200
        assert _client(app, "192.168.1.50").get("/ping").status_code == 403

    def test_filter_runs_before_the_host_check(self):
        app = _app_with_security(clients=[LOOPBACK])
        # Чужой адрес с чужим Host получает именно 403 клиента, а не 400 по Host: адрес отсекается первым.
        r = _client(app, "203.0.113.7", host="rebind.evil.example").get("/ping")
        assert r.status_code == 403

    def test_no_list_means_no_filter(self):
        for clients in (None, []):
            app = _app_with_security(clients=clients)
            assert _client(app, "203.0.113.7").get("/ping").status_code == 200

    def test_every_method_is_filtered_not_only_get(self):
        app = _app_with_security(clients=[LOOPBACK])
        denied = _client(app, "203.0.113.7")
        assert denied.post("/ping").status_code == 403
        assert denied.delete("/ping").status_code == 403

    def test_rejected_address_is_logged_once(self, caplog):
        network_access._log_rejected_client.cache_clear()
        app = _app_with_security(clients=[LOOPBACK])
        with caplog.at_level(logging.WARNING, logger=network_access.logger.name):
            for _ in range(3):
                _client(app, "203.0.113.7").get("/ping")
        messages = [r.getMessage() for r in caplog.records if "203.0.113.7" in r.getMessage()]
        assert len(messages) == 1


class TestHostCheckInNetworkMode:
    def test_ip_literal_host_is_accepted_when_remote_clients_are_allowed(self):
        app = _app_with_security(clients=[LOOPBACK, "192.168.1.0/24"])
        assert _client(app, "192.168.1.50", host="192.168.1.10:8000").get("/ping").status_code == 200
        assert _client(app, "192.168.1.50", host="[fd00::5]:8000").get("/ping").status_code == 200

    def test_names_still_need_to_be_listed_in_network_mode(self):
        app = _app_with_security(clients=[LOOPBACK, "192.168.1.0/24"])
        assert _client(app, "192.168.1.50", host="reestr-pc").get("/ping").status_code == 400
        app = _app_with_security(clients=[LOOPBACK, "192.168.1.0/24"], hosts=["localhost", "127.0.0.1", "reestr-pc"])
        assert _client(app, "192.168.1.50", host="reestr-pc:8000").get("/ping").status_code == 200

    def test_foreign_name_is_rejected_even_from_an_allowed_address(self):
        app = _app_with_security(clients=[LOOPBACK, "192.168.1.0/24"])
        assert _client(app, "192.168.1.50", host="rebind.evil.example").get("/ping").status_code == 400

    def test_local_only_mode_keeps_the_strict_host_list(self):
        # Без клиентов из сети поведение прежнее: Host вне списка отвергается, в том числе IP-адрес.
        app = _app_with_security(clients=[LOOPBACK])
        assert _client(app, "127.0.0.1", host="localhost:8000").get("/ping").status_code == 200
        assert _client(app, "127.0.0.1", host="192.168.1.10").get("/ping").status_code == 400

    def test_default_install_without_clients_is_unchanged(self):
        app = _app_with_security(clients=None)
        assert _client(app, "203.0.113.7", host="192.168.1.10").get("/ping").status_code == 400


# ---------------------------------------------------------------------------
# Реальное приложение и предупреждение при выключенной аутентификации
# ---------------------------------------------------------------------------
class TestRealAppAndWarning:
    def test_real_app_without_env_has_no_client_filter(self):
        # Переменная INFRA_REGISTRY_ALLOWED_CLIENTS в тестах не задана: Docker и разработка не ограничиваются.
        assert main_module.ALLOWED_CLIENT_NETWORKS == []

    def test_warns_when_remote_access_is_open_and_auth_is_off(self, monkeypatch, caplog):
        monkeypatch.setattr(main_module, "ALLOWED_CLIENT_NETWORKS", _networks(LOOPBACK, "192.168.1.0/24"))
        with caplog.at_level(logging.WARNING):
            _warn_if_remote_access_without_auth(auth_enabled=False)
        assert len(caplog.records) == 1
        assert "аутентификация выключена" in caplog.records[0].message
        assert "Настройки → Аутентификация" in caplog.records[0].message

    def test_no_warning_when_auth_is_on_or_access_is_local(self, monkeypatch, caplog):
        with caplog.at_level(logging.WARNING):
            monkeypatch.setattr(main_module, "ALLOWED_CLIENT_NETWORKS", _networks(LOOPBACK, "192.168.1.0/24"))
            _warn_if_remote_access_without_auth(auth_enabled=True)
            monkeypatch.setattr(main_module, "ALLOWED_CLIENT_NETWORKS", _networks(LOOPBACK))
            _warn_if_remote_access_without_auth(auth_enabled=False)
            monkeypatch.setattr(main_module, "ALLOWED_CLIENT_NETWORKS", [])
            _warn_if_remote_access_without_auth(auth_enabled=False)
        assert caplog.records == []
