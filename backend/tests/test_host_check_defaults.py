"""R1-01 код-ревью: проверка заголовка Host по умолчанию включена и в Docker.

Раньше docker-compose.yml задавал INFRA_REGISTRY_ALLOWED_HOSTS=* (проверка Host выключена), а аутентификация по умолчанию выключена,
поэтому при DNS-rebinding страница злоумышленника приходила с Host и Origin = evil.example:8000, оба заголовка совпадали, и запрос
читал и менял весь реестр. Теперь умолчание compose — локальные имена, а доступ по IP-адресу сервера (подменить его через DNS нельзя)
разрешает отдельный переключатель INFRA_REGISTRY_ACCEPT_IP_HOSTS. Предупреждение о «*» при выключенной аутентификации пишется
независимо от типа БД.

Запуск: pytest backend/tests/test_host_check_defaults.py -v
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.config as app_config
import app.main as main_module
from app.main import install_http_security

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_ENV = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))["services"]["app"]["environment"]


def _compose_default(name: str) -> str:
    """Значение по умолчанию переменной из compose: ``${NAME:-значение}`` → ``значение``."""
    match = re.fullmatch(r"\$\{" + re.escape(name) + r":-([^}]*)\}", COMPOSE_ENV[name])
    assert match, f"{name} в docker-compose.yml должна быть задана как ${{{name}:-значение}}"
    return match.group(1)


def _compose_hosts() -> list[str]:
    return [item.strip() for item in _compose_default("INFRA_REGISTRY_ALLOWED_HOSTS").split(",") if item.strip()]


def _compose_accepts_ip_hosts() -> bool:
    return _compose_default("INFRA_REGISTRY_ACCEPT_IP_HOSTS").strip().lower() in {"1", "true", "yes", "on"}


def _app(*, hosts: list[str], accept_ip_hosts: bool | None = None) -> FastAPI:
    app = FastAPI()

    @app.get("/api/v1/resources/manufacturers")
    def list_manufacturers() -> dict:
        return {"items": []}

    @app.post("/api/v1/resources/manufacturers", status_code=201)
    def create_manufacturer() -> dict:
        return {"id": "m1"}

    @app.get("/api/v1/health")
    def health() -> dict:
        return {"ok": True}

    kwargs = {} if accept_ip_hosts is None else {"accept_ip_hosts": accept_ip_hosts}
    install_http_security(app, allowed_hosts=hosts, cors_origins=[], **kwargs)
    return app


def _client(app: FastAPI, host: str) -> TestClient:
    return TestClient(app, base_url=f"http://{host}")


# --- Умолчания docker-compose.yml и .env.example ----------------------------------------------------------------------------
def test_compose_default_does_not_disable_the_host_check():
    assert "*" not in _compose_hosts(), "проверка Host не должна быть выключена по умолчанию (DNS-rebinding)"
    assert {"localhost", "127.0.0.1"} <= set(_compose_hosts())


def test_compose_default_accepts_the_servers_ip_address():
    assert _compose_accepts_ip_hosts(), "доступ по IP-адресу сервера должен работать без настройки: так обновление не ломает доступ"


def test_env_example_does_not_switch_the_host_check_off():
    # Скопированный .env.example перекрывает умолчание compose: активное «=*» вернуло бы уязвимость.
    active = {}
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            active[key.strip()] = value.strip()
    assert "*" not in [item.strip() for item in active.get("INFRA_REGISTRY_ALLOWED_HOSTS", "").split(",")]


def test_readme_documents_the_accept_ip_hosts_switch():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "INFRA_REGISTRY_ACCEPT_IP_HOSTS" in readme


# --- Поведение при конфигурации «как в compose» -----------------------------------------------------------------------------
def test_foreign_host_is_rejected_with_the_compose_defaults():
    # Воспроизведение из отчёта: Host и Origin совпадают (evil.example:8000), аутентификация выключена.
    app = _app(hosts=_compose_hosts(), accept_ip_hosts=_compose_accepts_ip_hosts())
    headers = {"Origin": "http://evil.example:8000"}
    client = _client(app, "evil.example:8000")
    assert client.get("/api/v1/resources/manufacturers", headers=headers).status_code == 400
    assert client.post("/api/v1/resources/manufacturers", json={"name": "Rebind-Test"}, headers=headers).status_code == 400


def test_ip_literal_host_is_accepted_when_enabled():
    app = _app(hosts=["localhost", "127.0.0.1"], accept_ip_hosts=True)
    assert _client(app, "10.0.0.5:8000").get("/api/v1/health").status_code == 200
    assert _client(app, "[fd00::5]:8000").get("/api/v1/health").status_code == 200


def test_ip_literal_host_is_rejected_when_disabled():
    app = _app(hosts=["localhost", "127.0.0.1"], accept_ip_hosts=False)
    assert _client(app, "10.0.0.5:8000").get("/api/v1/health").status_code == 400


def test_ip_literals_are_not_accepted_by_default_without_the_flag():
    # Прежнее поведение install_http_security без новой настройки: Host вне списка отвергается, в том числе IP-адрес.
    app = _app(hosts=["localhost", "127.0.0.1"])
    assert _client(app, "10.0.0.5:8000").get("/api/v1/health").status_code == 400


def test_names_are_still_checked_when_ip_literals_are_accepted():
    app = _app(hosts=["localhost", "reestr.corp.local"], accept_ip_hosts=True)
    assert _client(app, "reestr.corp.local:8000").get("/api/v1/health").status_code == 200
    assert _client(app, "evil.example:8000").get("/api/v1/health").status_code == 400
    # Имя, похожее на адрес, — всё равно имя.
    assert _client(app, "10.0.0.5.evil.example").get("/api/v1/health").status_code == 400


# --- Разбор переключателя в config.py ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
def test_flag_env_true_values(monkeypatch, value):
    monkeypatch.setenv("X_TEST_FLAG", value)
    assert app_config._flag_env("X_TEST_FLAG") is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "2", "tru"])
def test_flag_env_false_values(monkeypatch, value):
    monkeypatch.setenv("X_TEST_FLAG", value)
    assert app_config._flag_env("X_TEST_FLAG") is False


def test_flag_env_unset_is_false(monkeypatch):
    monkeypatch.delenv("X_TEST_FLAG", raising=False)
    assert app_config._flag_env("X_TEST_FLAG") is False


def test_accept_ip_hosts_is_off_without_env():
    assert app_config.ACCEPT_IP_HOSTS is False


# --- Предупреждение при «*» и выключенной аутентификации ---------------------------------------------------------------------
def _warnings(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]


def test_warning_is_logged_for_wildcard_without_auth(monkeypatch, caplog):
    monkeypatch.setattr(main_module, "ALLOWED_HOSTS", ["*"])
    with caplog.at_level(logging.WARNING):
        main_module._warn_if_host_check_disabled(auth_enabled=False)
    messages = _warnings(caplog)
    assert len(messages) == 1
    assert "INFRA_REGISTRY_ALLOWED_HOSTS" in messages[0] and "DNS-rebinding" in messages[0]


def test_warning_does_not_depend_on_the_database_type(monkeypatch, caplog):
    # Прежний _warn_if_insecure_server_config выходил сразу, если БД не PostgreSQL; для «*» так быть не должно.
    monkeypatch.setattr(main_module, "DATABASE_URL", "sqlite:///infra_registry.db")
    monkeypatch.setattr(main_module, "ALLOWED_HOSTS", ["reestr.corp.local", "*"])
    with caplog.at_level(logging.WARNING):
        main_module._warn_if_host_check_disabled(auth_enabled=False)
    assert len(_warnings(caplog)) == 1


def test_no_warning_when_auth_is_enabled_or_hosts_are_listed(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING):
        monkeypatch.setattr(main_module, "ALLOWED_HOSTS", ["*"])
        main_module._warn_if_host_check_disabled(auth_enabled=True)
        monkeypatch.setattr(main_module, "ALLOWED_HOSTS", ["localhost", "127.0.0.1"])
        main_module._warn_if_host_check_disabled(auth_enabled=False)
    assert _warnings(caplog) == []


def test_startup_runs_the_host_check_warning(client, monkeypatch, caplog):
    # Фикстура client подменяет SessionLocal на тестовую БД; аутентификация в ней выключена.
    monkeypatch.setattr(main_module, "ALLOWED_HOSTS", ["*"])
    with caplog.at_level(logging.WARNING):
        main_module.seed_catalogs_on_startup()
    assert any("INFRA_REGISTRY_ALLOWED_HOSTS" in message for message in _warnings(caplog))
