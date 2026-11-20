"""Сборка адреса базы данных из переменных окружения (app/config.py: _database_url).

docker-compose.yml подставлял пароль в DATABASE_URL строкой, и пароль с «@» ломал разбор адреса (хост становился
«ssword@db»), а «%41» тихо превращался в «A». Теперь compose передаёт части, а экранирует SQLAlchemy.
Тесты чистые (без БД): проверяется разбор итогового адреса, как его разберёт движок.
Запуск: pytest backend/tests/test_database_url.py -v
"""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from app.config import APP_DATA_DIR, _database_url

PARTS = ("DATABASE_URL", "INFRA_REGISTRY_DB_HOST", "INFRA_REGISTRY_DB_PORT", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in PARTS:
        monkeypatch.delenv(name, raising=False)


def _server(monkeypatch, **values):
    monkeypatch.setenv("INFRA_REGISTRY_DB_HOST", "db")
    for name, value in values.items():
        monkeypatch.setenv(name, value)


class TestPriority:
    def test_sqlite_file_in_the_data_directory_is_the_default(self):
        assert _database_url() == f"sqlite:///{APP_DATA_DIR / 'infra_registry.db'}"

    def test_explicit_url_wins_over_parts(self, monkeypatch):
        _server(monkeypatch, POSTGRES_PASSWORD="ignored")
        monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@external:5433/other")
        assert _database_url() == "postgresql+psycopg://u:p@external:5433/other"

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_blank_explicit_url_falls_through(self, monkeypatch, blank):
        _server(monkeypatch, POSTGRES_PASSWORD="secret")
        monkeypatch.setenv("DATABASE_URL", blank)  # docker-compose передаёт пустое значение, если DATABASE_URL не задан
        assert make_url(_database_url()).host == "db"

    def test_parts_without_a_host_do_not_switch_to_postgresql(self, monkeypatch):
        monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
        assert _database_url().startswith("sqlite:///")


class TestParts:
    def test_defaults_match_docker_compose(self, monkeypatch):
        _server(monkeypatch, POSTGRES_PASSWORD="secret")
        url = make_url(_database_url())
        assert (url.drivername, url.username, url.password, url.host, url.port, url.database) == ("postgresql+psycopg", "infra", "secret", "db", 5432, "infra_registry")

    def test_every_part_can_be_overridden(self, monkeypatch):
        _server(monkeypatch, POSTGRES_USER="reestr", POSTGRES_PASSWORD="x", POSTGRES_DB="inventory", INFRA_REGISTRY_DB_PORT="6543")
        url = make_url(_database_url())
        assert (url.username, url.database, url.port) == ("reestr", "inventory", 6543)

    def test_missing_password_is_allowed(self, monkeypatch):
        _server(monkeypatch)
        assert make_url(_database_url()).password is None

    @pytest.mark.parametrize(
        "password",
        [
            "simple",
            "p@ssword",
            "a/b",
            "p:w",
            "x#y",
            "100%sure",
            "a%41b",
            "q?z",
            "пароль",
            "with space",
            "a@b@c",
            "%40",
            "+-=&;",
            "'\"\\",
        ],
    )
    def test_any_password_survives_the_round_trip(self, monkeypatch, password):
        _server(monkeypatch, POSTGRES_PASSWORD=password, POSTGRES_USER="us@er")
        url = make_url(_database_url())
        assert (url.password, url.username, url.host, url.database) == (password, "us@er", "db", "infra_registry")

    def test_the_raw_interpolation_that_compose_used_before_breaks_on_at_sign(self):
        """Фиксирует исходную проблему: так адрес строил прежний docker-compose.yml."""
        assert make_url("postgresql+psycopg://infra:p@ssword@db:5432/infra_registry").host != "db"
