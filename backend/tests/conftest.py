"""
Общие фикстуры pytest для интеграционных тестов (test_api.py и подобных).

В отличие от test_reporting.py / test_report_builder.py (используют облегчённый
mock_sqlalchemy.py, чтобы не требовать установленных зависимостей), эти тесты требуют
реально установленных fastapi/sqlalchemy/httpx (см. backend/requirements-dev.txt) и
используют настоящую SQLAlchemy-сессию на in-memory SQLite, а также fastapi.TestClient —
то есть проверяют реальные запросы, FK-констрейнты и полный путь через HTTP-слой,
а не только бизнес-логику форматирования.

Запуск:  pip install -r backend/requirements-dev.txt && pytest backend/tests -v
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Must be set before importing app.config/app.db, which read these at import time.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
# Keeps generated reports (see TestReports in test_api.py) out of the real project
# directory/reports folder — app.config.REPORT_DIR defaults to <project>/reports otherwise.
os.environ.setdefault("INFRA_REGISTRY_DATA_DIR", tempfile.mkdtemp(prefix="infra_registry_tests_"))
# TrustedHostMiddleware (app/main.py) по умолчанию пускает только localhost/127.0.0.1, а TestClient ходит на
# Host: testserver — разрешаем его явно, как оператор разрешил бы своё имя хоста.
os.environ.setdefault("INFRA_REGISTRY_ALLOWED_HOSTS", "testserver,localhost,127.0.0.1")

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def db_session():
    """Свежая in-memory SQLite БД на каждый тест (изолированный engine, а не общий app.db.engine,
    чтобы тесты не делили состояние друг с другом и с другими файлами тестов).

    poolclass=StaticPool заставляет SQLAlchemy держать одно и то же физическое соединение —
    без этого каждое новое соединение к 'sqlite:///:memory:' получает СВОЮ отдельную пустую БД,
    и созданные здесь таблицы были бы не видны внутри запросов, сделанных через TestClient."""
    from app.models import Base

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _record):
        # Тот же набор настроек, что у боевого движка (FK + Unicode-aware LOWER, см. app/db.py).
        from app.db import configure_sqlite_connection

        configure_sqlite_connection(dbapi_connection)

    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def sql_log(db_session):
    """Список текстов всех SQL-запросов, выполненных через db_session.engine, пока фикстура
    активна — используется регрессионными тестами на N+1 (TestNPlusOneRegressions в test_api.py),
    которые проверяют, что запросы к конкретным таблицам не растут пропорционально размеру
    входных данных (число портов устройства, число участников VLAN-домена и т.п.)."""
    statements: list[str] = []
    engine = db_session.get_bind()

    def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """Троттлинг входа (services/login_throttle.py) держит состояние в памяти процесса — без сброса
    неудачные входы одного теста влияли бы на следующие (ключ — пара IP + логин, а IP у всех тестов один)."""
    from app.services import auth as auth_module

    auth_module.login_throttle.clear()
    yield
    auth_module.login_throttle.clear()


@pytest.fixture()
def client_factory(db_session, monkeypatch):
    """Фабрика TestClient с app.db.get_db, подменённым на фикстурную сессию/движок выше, чтобы
    тесты не трогали настоящий infra_registry.db и не зависели друг от друга по данным.

    app.main.lifespan() вызывает seed_defaults() через собственный SessionLocal(), а не через
    get_db (это не FastAPI-зависимость) — поэтому его тоже подменяем на фабрику, привязанную
    к тому же engine, что и db_session, иначе стартовый seed уйдёт в другую БД.

    app.services.auth.auth_gate_middleware — из того же теста: это ASGI-мидлварь, а не
    FastAPI Depends, поэтому dependency_overrides её не касается; она открывает сессии через
    app.db.SessionLocal() (см. комментарий в services/auth.py про `from X import Y`), которую
    подменяем здесь же на ту же тестовую фабрику.

    Адрес клиента задаётся параметром: первичная настройка аутентификации (см.
    services/auth.require_admin) доступна только с localhost, поэтому по умолчанию — 127.0.0.1, а
    тесты «удалённого» доступа просят другой адрес."""
    from fastapi.testclient import TestClient

    from app import db as app_db
    from app import main as app_main
    from app.db import get_db

    test_session_factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(app_main, "SessionLocal", test_session_factory)
    monkeypatch.setattr(app_db, "SessionLocal", test_session_factory)

    def _override_get_db():
        yield db_session

    app_main.app.dependency_overrides[get_db] = _override_get_db
    opened: list = []

    def _make(client_host: str = "127.0.0.1"):
        test_client = TestClient(app_main.app, client=(client_host, 50000))
        test_client.__enter__()
        opened.append(test_client)
        return test_client

    try:
        yield _make
    finally:
        for test_client in reversed(opened):
            test_client.__exit__(None, None, None)
        app_main.app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
def client(client_factory):
    return client_factory()
