"""Предупреждение о прокси, которому не доверяет uvicorn (services/auth.py, ревью 2.158.0, П-3).

Если обратный прокси не перечислен в FORWARDED_ALLOW_IPS, адрес клиента у всех — адрес прокси: троттлинг входа и «знакомые
адреса» становятся общими. Сервер один раз за процесс пишет предупреждение, когда приходит заголовок прокси от адреса,
которому uvicorn не доверяет. Запрос при этом не меняется и не блокируется.

Признак «uvicorn не доверяет» — адреса соединения нет среди записей X-Forwarded-For (см. _untrusted_proxy_header): за
доверенным прокси uvicorn сам подставляет в request.client адрес из заголовка. Тест такого соединения: TestClient с адресом
клиента, равным записи заголовка (client_factory("203.0.113.5") + X-Forwarded-For: 203.0.113.5).
"""
from __future__ import annotations

import logging

import pytest
from starlette.requests import Request

from app.services import auth as auth_module

LOGGER_NAME = auth_module.__name__
HEALTH_URL = "/api/v1/health"


@pytest.fixture(autouse=True)
def _fresh_warning_flag(monkeypatch):
    """Флаг «уже предупредили» живёт в процессе: каждый тест начинает с невыданного предупреждения и не оставляет следа."""
    monkeypatch.setattr(auth_module, "_proxy_headers_warned", False)


def _warnings(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == LOGGER_NAME and r.levelno == logging.WARNING]


def _request(headers: dict[str, str], client: tuple[str, int] | None = ("127.0.0.1", 50000)) -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/api/v1/health", "query_string": b"",
        "headers": [(k.lower().encode("latin1"), v.encode("latin1")) for k, v in headers.items()],
        "client": client,
    })


class TestWarningOnUntrustedProxy:
    def test_one_record_for_x_forwarded_for_from_an_untrusted_address(self, client, caplog):
        """Соединение с 127.0.0.1, а в заголовке — другой адрес: uvicorn его не подставил, значит прокси ему не доверен."""
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert client.get(HEALTH_URL, headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 200
        records = _warnings(caplog)
        assert len(records) == 1
        message = records[0].getMessage()
        assert "X-Forwarded-For" in message and "FORWARDED_ALLOW_IPS" in message
        assert "127.0.0.1" in message  # адрес соединения — то, что администратору нужно добавить в список

    def test_the_message_is_issued_once_per_process(self, client, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            for _ in range(5):
                assert client.get(HEALTH_URL, headers={"X-Forwarded-For": "203.0.113.5"}).status_code == 200
        assert len(_warnings(caplog)) == 1

    def test_header_value_is_not_written_to_the_log(self, client, caplog):
        """Заголовок присылает кто угодно: его содержимое в журнал сервера не попадает."""
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            client.get(HEALTH_URL, headers={"X-Forwarded-For": "198.51.100.77, evil-value"})
        assert len(_warnings(caplog)) == 1
        assert "198.51.100.77" not in _warnings(caplog)[0].getMessage()
        assert "evil-value" not in _warnings(caplog)[0].getMessage()

    def test_forwarded_header_alone_warns_with_a_hint(self, client, caplog):
        """Forwarded (RFC 7239) uvicorn не разбирает вовсе: за ним адрес клиента всегда адрес прокси."""
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert client.get(HEALTH_URL, headers={"Forwarded": "for=203.0.113.5"}).status_code == 200
        records = _warnings(caplog)
        assert len(records) == 1
        assert "Forwarded" in records[0].getMessage() and "X-Forwarded-For" in records[0].getMessage()

    def test_request_outcome_is_unchanged(self, client):
        """Предупреждение — подсказка, а не защита: ответ с заголовком и без него одинаков."""
        plain = client.get(HEALTH_URL)
        with_header = client.get(HEALTH_URL, headers={"X-Forwarded-For": "203.0.113.5"})
        assert plain.status_code == with_header.status_code == 200
        assert plain.json() == with_header.json()


class TestNoWarningWhenNothingIsWrong:
    def test_no_proxy_headers_no_record(self, client, caplog):
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert client.get(HEALTH_URL).status_code == 200
        assert _warnings(caplog) == []

    @pytest.mark.parametrize("header_value", [
        "203.0.113.5",                    # одиночная запись
        "198.51.100.7, 203.0.113.5",      # цепочка прокси: адрес клиента — одна из записей
        "203.0.113.5:4711",               # запись с портом: uvicorn отбрасывает порт
    ])
    def test_correctly_trusted_proxy_does_not_warn(self, client_factory, caplog, header_value):
        """uvicorn уже подставил адрес клиента из заголовка (прокси есть в FORWARDED_ALLOW_IPS): подозревать нечего."""
        behind_proxy = client_factory("203.0.113.5")
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert behind_proxy.get(HEALTH_URL, headers={"X-Forwarded-For": header_value}).status_code == 200
        assert _warnings(caplog) == []

    def test_trusted_ipv6_client_does_not_warn(self, client_factory, caplog):
        behind_proxy = client_factory("2001:db8::7")
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert behind_proxy.get(HEALTH_URL, headers={"X-Forwarded-For": "[2001:db8::7]:4711"}).status_code == 200
            assert behind_proxy.get(HEALTH_URL, headers={"X-Forwarded-For": "2001:db8:0:0:0:0:0:7"}).status_code == 200
        assert _warnings(caplog) == []

    def test_empty_header_value_does_not_warn(self, client, caplog):
        """Пустой X-Forwarded-For uvicorn тоже не использует, но предупреждать не о чем: адреса для подмены нет."""
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            assert client.get(HEALTH_URL, headers={"X-Forwarded-For": " , "}).status_code == 200
        assert _warnings(caplog) == []

    def test_static_files_do_not_trigger_the_check(self, client, caplog):
        """Проверка стоит только на /api/*: раздача интерфейса мимо неё (как и аутентификация)."""
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            client.get("/some-page", headers={"X-Forwarded-For": "203.0.113.5"})
        assert _warnings(caplog) == []


class TestUntrustedProxyHeaderHelper:
    @pytest.mark.parametrize("headers, client, expected", [
        ({}, ("127.0.0.1", 1), None),
        ({"X-Forwarded-For": "203.0.113.5"}, ("127.0.0.1", 1), "X-Forwarded-For"),
        ({"X-Forwarded-For": "203.0.113.5"}, ("203.0.113.5", 0), None),
        ({"X-Forwarded-For": "10.0.0.9, 203.0.113.5"}, ("203.0.113.5", 0), None),
        ({"Forwarded": "for=203.0.113.5"}, ("127.0.0.1", 1), "Forwarded"),
        ({"X-Forwarded-For": "203.0.113.5", "Forwarded": "for=203.0.113.5"}, ("203.0.113.5", 0), None),
        ({"X-Forwarded-For": "203.0.113.5"}, None, None),
    ])
    def test_detection(self, headers, client, expected):
        assert auth_module._untrusted_proxy_header(_request(headers, client)) == expected

    @pytest.mark.parametrize("raw, expected", [
        ("1.2.3.4", "1.2.3.4"), (" 1.2.3.4 ", "1.2.3.4"), ("1.2.3.4:80", "1.2.3.4"),
        ("[::1]:8080", "::1"), ("[::1]", "::1"), ("2001:db8::7", "2001:db8::7"), ("", ""),
    ])
    def test_normalize_host_matches_uvicorn_parsing(self, raw, expected):
        assert auth_module._normalize_host(raw) == expected

    def test_equivalent_ipv6_spellings_are_the_same_host(self):
        assert auth_module._same_host("2001:db8::7", "2001:DB8:0:0:0:0:0:7")
        assert not auth_module._same_host("2001:db8::7", "2001:db8::8")
        assert auth_module._same_host("Proxy.Local", "proxy.local")  # не IP-литерал: сравнение строк без регистра
