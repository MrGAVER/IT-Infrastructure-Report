"""Прямой запуск «uvicorn app.main:app» на пустой базе без миграций: понятное сообщение вместо «no such table» (код-ревью 2.158.0, ENV-1).

Раньше старт падал на первом запросе к БД ошибкой драйвера («sqlite3.OperationalError: no such table: catalog_seed_markers
[SQL: SELECT …]»), из которой неочевидно, что нужно выполнить `alembic upgrade head`. Теперь, если таблицы маркера сидирования нет
вовсе, приложение останавливается с RuntimeError, где названа причина и команда. Любая другая ошибка БД на старте не маскируется.
Docker и EXE миграции применяют сами, на них изменение не влияет.

Тесты работают на отдельной базе во временном файле SQLite (не на общей фикстуре) — им нужна именно пустая схема.

Запуск: pytest backend/tests/test_startup_without_migrations.py -v
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app import main as app_main
from app.models import Base, CatalogSeedMarker

pytestmark = pytest.mark.sqlite_only


@pytest.fixture()
def startup_session_factory(tmp_path, monkeypatch):
    """Пустая база во временном файле, подставленная в приложение вместо SessionLocal: (фабрика сессий, движок)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'startup_test.db'}", future=True)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(app_main, "SessionLocal", factory)
    yield factory, engine
    engine.dispose()


def test_empty_database_gives_actionable_message(startup_session_factory):
    with pytest.raises(RuntimeError) as caught:
        app_main.seed_catalogs_on_startup()

    message = str(caught.value)
    assert "alembic upgrade head" in message
    assert "catalog_seed_markers" in message
    assert "SELECT" not in message and "sqlite3" not in message  # без сырого SQL и текста драйвера
    # Цепочка причин не тянет за собой ошибку драйвера: в консоли uvicorn последняя строка — это сообщение
    assert caught.value.__cause__ is None and caught.value.__suppress_context__ is True


def test_message_is_the_module_constant_and_names_both_run_modes():
    assert app_main.SCHEMA_NOT_MIGRATED_MESSAGE.startswith("База данных не инициализирована")
    assert "Docker" in app_main.SCHEMA_NOT_MIGRATED_MESSAGE and "EXE" in app_main.SCHEMA_NOT_MIGRATED_MESSAGE


def test_failed_start_does_not_create_tables(startup_session_factory):
    _, engine = startup_session_factory
    with pytest.raises(RuntimeError):
        app_main.seed_catalogs_on_startup()
    assert inspect(engine).get_table_names() == []


def test_migrated_database_starts_normally(startup_session_factory):
    factory, engine = startup_session_factory
    Base.metadata.create_all(engine)

    app_main.seed_catalogs_on_startup()  # не должно падать

    with factory() as session:
        assert session.scalar(select(func.count()).select_from(CatalogSeedMarker)) == 1


def test_other_database_errors_are_not_masked(startup_session_factory, monkeypatch):
    """Схема есть, но запрос не удался по другой причине (блокировка, недоступность): исходная ошибка пробрасывается как есть."""
    _, engine = startup_session_factory
    Base.metadata.create_all(engine)

    def failing_seed(session, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("database is locked"))

    monkeypatch.setattr(app_main, "seed_defaults", failing_seed)

    with pytest.raises(OperationalError, match="database is locked"):
        app_main.seed_catalogs_on_startup()
