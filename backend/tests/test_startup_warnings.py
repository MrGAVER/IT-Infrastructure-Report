import logging

import app.main as main_module
from app.main import _warn_if_insecure_server_config


def test_no_warning_on_sqlite_regardless_of_auth_and_cors(monkeypatch, caplog):
    """Дефолтный локальный/EXE-сценарий (SQLite) — предупреждать не о чем, даже если auth
    выключена и CORS '*' (это и есть штатные дефолты для этого сценария)."""
    monkeypatch.setattr(main_module, "DATABASE_URL", "sqlite:///infra_registry.db")
    monkeypatch.setattr(main_module, "CORS_ALLOWED_ORIGINS", ["*"])
    with caplog.at_level(logging.WARNING):
        _warn_if_insecure_server_config(auth_enabled=False)
    assert caplog.records == []


def test_no_warning_on_postgres_when_secured(monkeypatch, caplog):
    """PostgreSQL сам по себе не проблема — проблема комбинация с выключенной auth и/или
    открытым CORS. Если оба ограничены, предупреждать не о чем."""
    monkeypatch.setattr(main_module, "DATABASE_URL", "postgresql://infra:secret@db/infra_registry")
    monkeypatch.setattr(main_module, "CORS_ALLOWED_ORIGINS", ["https://reestr.example.local"])
    with caplog.at_level(logging.WARNING):
        _warn_if_insecure_server_config(auth_enabled=True)
    assert caplog.records == []


def test_warns_on_postgres_with_auth_disabled(monkeypatch, caplog):
    monkeypatch.setattr(main_module, "DATABASE_URL", "postgresql://infra:secret@db/infra_registry")
    monkeypatch.setattr(main_module, "CORS_ALLOWED_ORIGINS", ["https://reestr.example.local"])
    with caplog.at_level(logging.WARNING):
        _warn_if_insecure_server_config(auth_enabled=False)
    assert len(caplog.records) == 1
    assert "аутентификация выключена" in caplog.records[0].message
    assert "secret" not in caplog.records[0].message  # пароль БД не должен попасть в лог


def test_warns_on_postgres_with_open_cors(monkeypatch, caplog):
    monkeypatch.setattr(main_module, "DATABASE_URL", "postgresql+psycopg2://infra:secret@db/infra_registry")
    monkeypatch.setattr(main_module, "CORS_ALLOWED_ORIGINS", ["*"])
    with caplog.at_level(logging.WARNING):
        _warn_if_insecure_server_config(auth_enabled=True)
    assert len(caplog.records) == 1
    assert "CORS" in caplog.records[0].message


def test_warns_once_listing_both_problems(monkeypatch, caplog):
    monkeypatch.setattr(main_module, "DATABASE_URL", "postgresql://infra:secret@db/infra_registry")
    monkeypatch.setattr(main_module, "CORS_ALLOWED_ORIGINS", ["*"])
    with caplog.at_level(logging.WARNING):
        _warn_if_insecure_server_config(auth_enabled=False)
    assert len(caplog.records) == 1  # одно предупреждение, а не по одному на каждую проблему
    message = caplog.records[0].message
    assert "аутентификация выключена" in message
    assert "CORS" in message
