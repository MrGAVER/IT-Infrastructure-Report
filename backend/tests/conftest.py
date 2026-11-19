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
import shutil
import sqlite3
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
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from skip_budget import POSTGRES_ONLY_REASON, SQLITE_ONLY_REASON, pytest_sessionfinish  # noqa: F401  (хук бюджета пропусков, ИА-08)


# Серверный режим приложения работает на PostgreSQL (docker-compose.yml), а по умолчанию тесты идут на SQLite.
# INFRA_REGISTRY_TEST_DATABASE_URL переключает ВСЕ фикстуры ниже на PostgreSQL, например:
#   INFRA_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/infra_test pytest backend/tests
# База должна быть пустой и принадлежать тестам: схема пересоздаётся при старте, а между тестами все таблицы
# очищаются (TRUNCATE ... CASCADE). Тесты, которым нужна именно SQLite (миграции на файле-БД), помечены
# @pytest.mark.sqlite_only и при этом режиме пропускаются, а тесты с @pytest.mark.postgres_only — наоборот,
# выполняются только в нём.
#
# По умолчанию схема PostgreSQL создаётся из моделей (create_all). INFRA_REGISTRY_TEST_SCHEMA=migrations собирает
# её цепочкой миграций Alembic (`alembic upgrade head`) — как при первом запуске docker-compose; так проверяется, что
# приложение работает на схеме, которую получат реальные установки, а не только на «идеальной» схеме из моделей.
TEST_DATABASE_URL = os.environ.get("INFRA_REGISTRY_TEST_DATABASE_URL", "").strip()
IS_POSTGRES = TEST_DATABASE_URL.startswith("postgresql")
SCHEMA_FROM_MIGRATIONS = os.environ.get("INFRA_REGISTRY_TEST_SCHEMA", "").strip() == "migrations"


def pytest_configure(config):
    config.addinivalue_line("markers", "sqlite_only: тест зависит от SQLite и пропускается при INFRA_REGISTRY_TEST_DATABASE_URL")
    config.addinivalue_line("markers", "slow: замер времени/нагрузочная проверка; по умолчанию выполняется, исключить можно ключом -m 'not slow'")
    config.addinivalue_line("markers", "postgres_only: тест требует PostgreSQL и выполняется только при INFRA_REGISTRY_TEST_DATABASE_URL")
    config.addinivalue_line("markers", "real_password_hashing: тест проверяет боевое число итераций PBKDF2 — ускорение хеширования в тестах (см. _fast_password_hashing) отключается")


def pytest_collection_modifyitems(config, items):
    # Причины — константы skip_budget: плагин не считает эти пропуски «неожиданными» (ИА-08 код-ревью r3).
    if IS_POSTGRES:
        skip = pytest.mark.skip(reason=SQLITE_ONLY_REASON)
        marker = "sqlite_only"
    else:
        skip = pytest.mark.skip(reason=POSTGRES_ONLY_REASON)
        marker = "postgres_only"
    for item in items:
        if marker in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def _postgres_engine():
    """Один движок PostgreSQL на весь прогон; схема создаётся заново — из моделей (как create_all у SQLite-фикстуры)
    или, при INFRA_REGISTRY_TEST_SCHEMA=migrations, цепочкой миграций Alembic."""
    from app.models import Base

    engine = create_engine(TEST_DATABASE_URL, future=True, pool_pre_ping=True)
    if SCHEMA_FROM_MIGRATIONS:
        _rebuild_schema_with_migrations(engine)
    else:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def _rebuild_schema_with_migrations(engine) -> None:
    """Пустая схема public → `alembic upgrade head`. env.py читает app.config.DATABASE_URL при каждом запуске команды
    (см. tests/test_migrations_diagram.py), поэтому адрес подставляется в сам модуль на время миграции."""
    from pathlib import Path

    import app.config as app_config
    from alembic import command
    from alembic.config import Config

    with engine.begin() as connection:
        connection.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
        connection.exec_driver_sql("CREATE SCHEMA public")
    backend_dir = Path(__file__).resolve().parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(backend_dir / "alembic"))
    cfg.attributes["configure_logger"] = False
    original = app_config.DATABASE_URL
    app_config.DATABASE_URL = TEST_DATABASE_URL
    try:
        command.upgrade(cfg, "head")
    finally:
        app_config.DATABASE_URL = original


def _truncate_all(engine) -> None:
    from app.models import Base

    names = ", ".join(f'"{table.name}"' for table in Base.metadata.sorted_tables)
    with engine.begin() as connection:
        # lock_timeout: сессия, забытая тестом внутри транзакции, не должна вешать весь прогон на TRUNCATE.
        connection.exec_driver_sql("SET LOCAL lock_timeout = '15s'")
        connection.exec_driver_sql(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE")


_SQLITE_SCHEMA_TEMPLATE: tuple | None = None


def _sqlite_schema_template() -> sqlite3.Connection:
    """In-memory SQLite со схемой из моделей (create_all) — создаётся один раз на процесс и копируется в БД каждого
    теста через sqlite3.Connection.backup(). Содержимое идентично тому, что дал бы create_all() в самом тесте: DDL, индексы
    и триггеры, заданные в моделях, уже в шаблоне. Движок держим в модульной переменной, иначе соединение закрылось бы."""
    global _SQLITE_SCHEMA_TEMPLATE
    if _SQLITE_SCHEMA_TEMPLATE is None:
        from app.db import configure_sqlite_connection
        from app.models import Base

        engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
        event.listen(engine, "connect", lambda dbapi_connection, _record: configure_sqlite_connection(dbapi_connection))
        Base.metadata.create_all(engine)
        _SQLITE_SCHEMA_TEMPLATE = (engine, engine.raw_connection().driver_connection)
    return _SQLITE_SCHEMA_TEMPLATE[1]


@pytest.fixture()
def db_session(request):
    """Свежая БД на каждый тест: in-memory SQLite (по умолчанию) или очищенный PostgreSQL (см. выше).

    SQLite: изолированный engine, а не общий app.db.engine, чтобы тесты не делили состояние друг с другом.
    poolclass=StaticPool заставляет SQLAlchemy держать одно и то же физическое соединение —
    без этого каждое новое соединение к 'sqlite:///:memory:' получает СВОЮ отдельную пустую БД,
    и созданные здесь таблицы были бы не видны внутри запросов, сделанных через TestClient."""
    if IS_POSTGRES:
        engine = request.getfixturevalue("_postgres_engine")
        _truncate_all(engine)
        SessionFactory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
        session = SessionFactory()
        try:
            yield session
        finally:
            session.close()
        return

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    schema_template = _sqlite_schema_template()

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, _record):
        # Тот же набор настроек, что у боевого движка (FK + Unicode-aware LOWER, см. app/db.py).
        from app.db import configure_sqlite_connection

        configure_sqlite_connection(dbapi_connection)
        # Схема из моделей берётся копией готового шаблона, а не create_all() на каждый тест (~25 мс × тысячи тестов).
        schema_template.backup(dbapi_connection)

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
def _fast_password_hashing(request, monkeypatch):
    """PBKDF2 на 600 000 итераций — ~0,3–0,4 с на каждое хеширование и проверку пароля; тесты авторизации делают их сотни.
    Корректность алгоритма от числа итераций не зависит (формат хеша самоописывающийся), поэтому в тестах итераций мало.
    Тесты, которым нужно именно боевое значение, помечаются @pytest.mark.real_password_hashing."""
    if request.node.get_closest_marker("real_password_hashing"):
        return
    from app.services.auth import passwords as passwords_module

    monkeypatch.setattr(passwords_module, "PBKDF2_ITERATIONS", 1_000)  # читает hash_password/needs_rehash — патч на модуле паролей


@pytest.fixture(autouse=True)
def _isolated_audit_archive_dir(tmp_path, monkeypatch):
    """Очистка журнала аудита перед удалением пишет архив в `<REPORT_DIR>/audit/` (services/audit_archive.py). Каталог читается при вызове
    из `app.config.REPORT_DIR`, поэтому каждому тесту — свой: файлы не копятся в общем каталоге данных и не попадают в проверки соседних
    тестов, которые считают содержимое `reports/audit/`. Модули, привязавшие REPORT_DIR при импорте
    (api/reports.py, api/report_builder.py), не затрагиваются — но только если они импортированы ДО подмены: иначе при запуске
    части тестов (`pytest tests/test_api.py -k TestReports`) первый же импорт происходил бы под подменой, и модуль писал бы отчёты
    в каталог первого теста, а не туда, откуда их читает test_api.py."""
    import app.api.report_builder  # noqa: F401  (привязывает боевой REPORT_DIR до подмены)
    import app.api.reports  # noqa: F401
    import app.config as app_config

    monkeypatch.setattr(app_config, "REPORT_DIR", tmp_path / "reports")


@pytest.fixture(scope="session", autouse=True)
def _reuse_alembic_upgrades_on_empty_sqlite(tmp_path_factory):
    """`alembic upgrade <ревизия>` на пустой файловой SQLite занимает 1–2 с (десятки миграций), а тесты миграций строят такую
    БД ~250 раз. Результат для пустой базы детерминирован, поэтому он запоминается один раз на процесс (ключ — ревизия и
    расположение скриптов) и дальше копируется файлом (~1 мс). Кэш применяется только когда файл БД ещё пуст/не существует:
    повторные upgrade поверх данных теста, downgrade и PostgreSQL идут как есть. Отключить: INFRA_REGISTRY_TEST_NO_UPGRADE_CACHE=1."""
    if IS_POSTGRES or os.environ.get("INFRA_REGISTRY_TEST_NO_UPGRADE_CACHE"):
        yield
        return

    import app.config as app_config
    from alembic import command

    original_upgrade = command.upgrade
    cache_dir = tmp_path_factory.mktemp("alembic_upgrade_cache")
    cached_files: dict[tuple, Path] = {}

    def _empty_sqlite_file() -> Path | None:
        url = make_url(app_config.DATABASE_URL)
        if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
            return None
        path = Path(url.database)
        return path if not path.exists() or path.stat().st_size == 0 else None

    def upgrade_with_cache(config, revision, sql=False, tag=None):
        target = _empty_sqlite_file()
        if sql or tag is not None or target is None or not isinstance(revision, str):
            return original_upgrade(config, revision, sql=sql, tag=tag)
        key = (revision, config.get_main_option("script_location"), config.get_main_option("version_locations"))
        cached = cached_files.get(key)
        if cached is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, target)
            return None
        result = original_upgrade(config, revision, sql=sql, tag=tag)
        leftovers = [target.with_name(target.name + suffix) for suffix in ("-wal", "-shm", "-journal")]
        if target.exists() and not any(path.exists() for path in leftovers):
            stored = cache_dir / f"{len(cached_files)}.db"
            shutil.copyfile(target, stored)
            cached_files[key] = stored
        return result

    command.upgrade = upgrade_with_cache
    try:
        yield
    finally:
        command.upgrade = original_upgrade


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """Троттлинг входа (services/login_throttle.py) держит состояние в памяти процесса — без сброса
    неудачные входы одного теста влияли бы на следующие (ключ — пара IP + логин, а IP у всех тестов один).
    Счётчик по адресу (ip_throttle) без сброса накапливал бы неудачи всех тестов и после порога давал бы 429."""
    from app.services.auth import guards as guards_module
    from app.services.auth import login as login_module

    # Счётчик неверных токенов установки (guards.setup_token_throttle, A-04) — тоже общий для процесса и ключуется адресом клиента.
    # Тест, подменивший его экземпляр (monkeypatch), возвращает исходный сам; здесь чистится тот, что назначен на момент вызова.
    throttles = (login_module.login_throttle, login_module.ip_throttle, guards_module.setup_token_throttle)
    for throttle in throttles:
        throttle.clear()
    yield
    for throttle in throttles:
        throttle.clear()


@pytest.fixture(autouse=True)
def _reset_auth_flag_cache(monkeypatch):
    """Кэш флага «аутентификация включена» (services/auth/settings.auth_enabled_cached) общий для процесса, а БД у каждого теста
    своя: без сброса значение из предыдущего теста (скажем, «включена») действовало бы до двух секунд и в следующем.

    Часы кэша заморожены: иначе тесты, сравнивающие число SQL-запросов двух соседних запросов (test_connection_query,
    test_code_review_correctness), зависели бы от того, истёк ли TTL между ними, — на медленном прогоне с покрытием
    нерегулярно получали бы лишний SELECT настроек. Срок действия и сброс проверяет test_auth_flag_cache.py на своих часах."""
    from app.services.auth import settings as settings_module

    monkeypatch.setattr(settings_module, "_flag_clock", lambda: 0.0)  # кэш и его часы живут в модуле настроек
    settings_module.reset_auth_enabled_cache()
    yield
    settings_module.reset_auth_enabled_cache()


@pytest.fixture(autouse=True)
def _reset_port_sync_plan_cache():
    """Кэш планов согласования (services/port_sync_plan_cache.py) живёт в памяти процесса — как и троттлинг
    входа, он не должен переносить снимки планов из одного теста в другой (у пустых планов один и тот же хеш)."""
    from app.services.port_sync_plan_cache import plan_cache

    plan_cache.clear()
    yield
    plan_cache.clear()


@pytest.fixture(autouse=True)
def _reset_export_cache():
    """Кэш готовых экспортов (services/export_cache.py) живёт в памяти процесса: тест, подменивший сериализатор и закэшировавший его
    ответ, не должен подсовывать этот ответ следующему тесту с таким же графом."""
    from app.services.export_cache import export_cache

    export_cache.clear()
    yield
    export_cache.clear()


@pytest.fixture()
def client_factory(db_session, monkeypatch):
    """Фабрика TestClient с app.db.get_db, подменённым на фикстурную сессию/движок выше, чтобы
    тесты не трогали настоящий infra_registry.db и не зависели друг от друга по данным.

    app.main.lifespan() вызывает seed_defaults() через собственный SessionLocal(), а не через
    get_db (это не FastAPI-зависимость) — поэтому его тоже подменяем на фабрику, привязанную
    к тому же engine, что и db_session, иначе стартовый seed уйдёт в другую БД.

    app.services.auth.gate.AuthGateMiddleware — из того же теста: это ASGI-мидлварь, а не
    FastAPI Depends, поэтому dependency_overrides её не касается; она открывает сессии через
    app.db.SessionLocal() (см. комментарий в services/auth/gate.py про `from X import Y`), которую
    подменяем здесь же на ту же тестовую фабрику.

    Адрес клиента задаётся параметром: первичная настройка аутентификации (см.
    services/auth/guards.require_admin) доступна только с localhost, поэтому по умолчанию — 127.0.0.1, а
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
