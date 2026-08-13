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
os.environ.setdefault("INFRA_REGISTRY_ENABLE_TEST_DATA", "1")
# Keeps generated reports (see TestReports in test_api.py) out of the real project
# directory/reports folder — app.config.REPORT_DIR defaults to <project>/reports otherwise.
os.environ.setdefault("INFRA_REGISTRY_DATA_DIR", tempfile.mkdtemp(prefix="infra_registry_tests_"))

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
    def _enable_fk(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = SessionFactory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session, monkeypatch):
    """TestClient с app.db.get_db, подменённым на фикстурную сессию/движок выше, чтобы
    тесты не трогали настоящий infra_registry.db и не зависели друг от друга по данным.

    app.main.lifespan() вызывает seed_defaults() через собственный SessionLocal(), а не через
    get_db (это не FastAPI-зависимость) — поэтому его тоже подменяем на фабрику, привязанную
    к тому же engine, что и db_session, иначе стартовый seed уйдёт в другую БД."""
    from fastapi.testclient import TestClient

    from app import main as app_main
    from app.db import get_db

    test_session_factory = sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False, expire_on_commit=False)
    monkeypatch.setattr(app_main, "SessionLocal", test_session_factory)

    def _override_get_db():
        yield db_session

    app_main.app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app_main.app) as c:
            yield c
    finally:
        app_main.app.dependency_overrides.pop(get_db, None)
