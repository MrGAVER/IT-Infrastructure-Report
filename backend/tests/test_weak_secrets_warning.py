"""
Код-ревью, BE-03: предупреждение при старте, если токен первичной настройки или пароль БД — заглушка из .env.example либо слишком
короткое значение.

docker-compose.yml требует лишь непустое значение, поэтому не отредактированный .env запускался без возражений. Запуск по-прежнему не
блокируется (существующие установки не ломаются) — в журнал пишется предупреждение, а само значение секрета в него не попадает.

Запуск: pytest backend/tests/test_weak_secrets_warning.py -v
"""
from __future__ import annotations

import logging
import secrets

import pytest

import app.main as main_module
from app.config import MIN_DB_PASSWORD_LENGTH, MIN_SETUP_TOKEN_LENGTH, weak_db_password, weak_secret, weak_setup_token
from app.main import _warn_if_weak_secrets

STRONG_TOKEN = secrets.token_hex(24)  # как советует .env.example: openssl rand -hex 24, 48 символов
STRONG_DB_URL = "postgresql+psycopg://infra:Xk9-vT2m-Qa7w@db:5432/infra_registry"


@pytest.fixture
def secrets_config(monkeypatch):
    """Задаёт токен и адрес БД, которые читает _warn_if_weak_secrets."""

    def apply(token: str = STRONG_TOKEN, database_url: str = STRONG_DB_URL) -> None:
        monkeypatch.setattr(main_module, "SETUP_TOKEN", token)
        monkeypatch.setattr(main_module, "DATABASE_URL", database_url)

    return apply


def _warnings(caplog) -> list[str]:
    return [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]


# --- Чистые функции проверки ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("token", ["change_me", "change_me_long_random_string", "ChangeMe", "  CHANGE_ME  ", "changeme", "secret", "password"])
def test_placeholders_are_weak_regardless_of_case_and_padding(token):
    assert weak_setup_token(token) and weak_db_password(token)


def test_the_length_limits_are_inclusive_of_the_minimum():
    assert weak_setup_token("a" * (MIN_SETUP_TOKEN_LENGTH - 1))
    assert not weak_setup_token("a" * MIN_SETUP_TOKEN_LENGTH)
    assert weak_db_password("a" * (MIN_DB_PASSWORD_LENGTH - 1))
    assert not weak_db_password("a" * MIN_DB_PASSWORD_LENGTH)


def test_an_empty_secret_is_not_reported_as_weak():
    # «Не задан» — другой случай (токен выключен, у SQLite нет пароля): предупреждать о нём как о слабом значении неверно.
    assert not weak_secret("", 16)
    assert not weak_setup_token("")
    assert not weak_db_password("")


def test_a_generated_token_is_strong():
    assert len(STRONG_TOKEN) == 48
    assert not weak_setup_token(STRONG_TOKEN)


# --- Предупреждение при старте -------------------------------------------------------------------------------------------

def test_a_placeholder_token_produces_a_warning_without_the_value(secrets_config, caplog):
    secrets_config(token="change_me_long_random_string")
    with caplog.at_level(logging.WARNING):
        _warn_if_weak_secrets()
    messages = _warnings(caplog)
    assert len(messages) == 1
    assert "INFRA_REGISTRY_SETUP_TOKEN" in messages[0]
    assert "openssl rand -hex 24" in messages[0]
    assert "change_me_long_random_string" not in messages[0]  # значение секрета в журнал не попадает


def test_a_short_token_produces_a_warning(secrets_config, caplog):
    secrets_config(token="abc123")
    with caplog.at_level(logging.WARNING):
        _warn_if_weak_secrets()
    messages = _warnings(caplog)
    assert len(messages) == 1 and "INFRA_REGISTRY_SETUP_TOKEN" in messages[0]
    assert "abc123" not in messages[0]


def test_a_strong_token_and_password_are_silent(secrets_config, caplog):
    secrets_config()
    with caplog.at_level(logging.WARNING):
        _warn_if_weak_secrets()
    assert _warnings(caplog) == []


def test_no_token_and_sqlite_are_silent(secrets_config, caplog):
    # Однопользовательская EXE-версия: токена нет, у SQLite нет пароля — предупреждать не о чем.
    secrets_config(token="", database_url="sqlite:///infra_registry.db")
    with caplog.at_level(logging.WARNING):
        _warn_if_weak_secrets()
    assert _warnings(caplog) == []


def test_a_placeholder_database_password_produces_a_warning_without_the_value(secrets_config, caplog):
    secrets_config(database_url="postgresql+psycopg://infra:change_me@db:5432/infra_registry")
    with caplog.at_level(logging.WARNING):
        _warn_if_weak_secrets()
    messages = _warnings(caplog)
    assert len(messages) == 1
    assert "POSTGRES_PASSWORD" in messages[0]
    assert "change_me" not in messages[0]


def test_both_weak_secrets_give_two_separate_warnings(secrets_config, caplog):
    secrets_config(token="change_me", database_url="postgresql+psycopg://infra:short@db/infra_registry")
    with caplog.at_level(logging.WARNING):
        _warn_if_weak_secrets()
    messages = _warnings(caplog)
    assert len(messages) == 2
    assert any("INFRA_REGISTRY_SETUP_TOKEN" in message for message in messages)
    assert any("POSTGRES_PASSWORD" in message for message in messages)


def test_a_password_with_special_characters_is_read_decoded(secrets_config, caplog):
    # В адресе пароль экранирован (@ → %40): проверяется настоящий пароль «p@ss#w0rd-long», а не его запись в URL.
    secrets_config(database_url="postgresql+psycopg://infra:p%40ss%23w0rd-long@db/infra_registry")
    with caplog.at_level(logging.WARNING):
        _warn_if_weak_secrets()
    assert _warnings(caplog) == []


def test_startup_runs_the_check_without_blocking(client, monkeypatch, caplog):
    # Запуск не блокируется: seed_catalogs_on_startup доходит до конца и пишет предупреждение, а не поднимает исключение.
    # Фикстура client подменяет SessionLocal на тестовую БД (как в test_catalog_seed_marker.py) — стартовый seed идёт в неё.
    monkeypatch.setattr(main_module, "SETUP_TOKEN", "change_me")
    with caplog.at_level(logging.WARNING):
        main_module.seed_catalogs_on_startup()
    assert any("INFRA_REGISTRY_SETUP_TOKEN" in message for message in _warnings(caplog))
