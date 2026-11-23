"""Trigram-индексы поиска по журналу аудита (миграция 4e8b2d6f9a13, только PostgreSQL).

Что проверяется:
- без расширения pg_trgm миграция НЕ падает (предупреждение в лог, индексы не создаются) — на заглушке соединения, любая СУБД;
- на SQLite миграция ничего не делает;
- на PostgreSQL индексы создаются, downgrade их убирает, а настоящий запрос `list_audit_log(q=…)` выполняется по ним (EXPLAIN запроса,
  который реально отправило приложение) и быстрее полного перебора минимум вдвое (замер, метка slow: 200 000 записей; решает не
  он, а планы EXPLAIN).

Запуск: pytest backend/tests/test_review_p2_audit_search_trigram_indexes.py -v   (PostgreSQL-часть: INFRA_REGISTRY_TEST_DATABASE_URL)
"""

from __future__ import annotations

import contextlib
import importlib.util
import logging
import os
import sys
import time
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.alembic_filters import POSTGRES_ONLY_INDEXES
from app.services.audit_query import AuditQuery, list_audit_log
from migration_support import migrate

BACKEND_DIR = Path(__file__).resolve().parent.parent
REVISION, PREVIOUS_REVISION = "4e8b2d6f9a13", "7c3d9a5e1b24"
INDEXES = {"ix_audit_log_details_trgm", "ix_audit_log_entity_id_trgm"}
SEARCH = "sn1a2b"  # редкий фрагмент: совпадает с единицами записей из 200 000


def _migration_module():
    path = next((BACKEND_DIR / "alembic" / "versions").glob(f"{REVISION}_*.py"))
    spec = importlib.util.spec_from_file_location("trigram_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeBind:
    """Минимальная замена Connection: журнал выполненных SQL; CREATE EXTENSION можно заставить упасть."""

    def __init__(self, dialect: str, extension_error: Exception | None = None) -> None:
        self.dialect = type("Dialect", (), {"name": dialect})()
        self.statements: list[str] = []
        self._extension_error = extension_error

    @contextlib.contextmanager
    def begin_nested(self):
        yield

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if "CREATE EXTENSION" in sql and self._extension_error is not None:
            raise self._extension_error


def _run(monkeypatch, direction: str, bind: _FakeBind) -> None:
    module = _migration_module()
    monkeypatch.setattr(module.op, "get_bind", lambda: bind)
    getattr(module, direction)()


def test_the_migration_names_match_the_alembic_check_filter():
    assert {name for name, _ in _migration_module()._TRIGRAM_INDEXES} == INDEXES == set(POSTGRES_ONLY_INDEXES)


def test_without_the_extension_the_migration_succeeds_and_tells_how_to_finish_manually(monkeypatch, caplog):
    unavailable = sa.exc.NotSupportedError(
        "CREATE EXTENSION", {}, Exception('extension "pg_trgm" is not available\nHINT: install postgresql-contrib')
    )
    bind = _FakeBind("postgresql", extension_error=unavailable)

    with caplog.at_level(logging.WARNING, logger="alembic.runtime.migration"):
        _run(monkeypatch, "upgrade", bind)  # не должна бросать исключение

    assert not any("CREATE INDEX" in sql for sql in bind.statements), "без расширения индексы не создаются"
    warning = next(record.getMessage() for record in caplog.records if record.levelno == logging.WARNING)
    assert (
        "pg_trgm" in warning and "CREATE INDEX IF NOT EXISTS ix_audit_log_details_trgm" in warning and "работает без ускорения" in warning
    )


def test_with_the_extension_it_creates_both_expression_indexes(monkeypatch):
    bind = _FakeBind("postgresql")
    _run(monkeypatch, "upgrade", bind)
    indexes = [sql for sql in bind.statements if "CREATE INDEX" in sql]
    assert [sql.split()[5] for sql in indexes] == ["ix_audit_log_details_trgm", "ix_audit_log_entity_id_trgm"]
    assert all("USING gin (lower(" in sql and "gin_trgm_ops" in sql for sql in indexes), (
        "выражение lower(колонка) — то, что строит audit_query"
    )


@pytest.mark.parametrize("direction", ["upgrade", "downgrade"])
def test_on_sqlite_the_migration_does_nothing(monkeypatch, direction):
    bind = _FakeBind("sqlite")
    _run(monkeypatch, direction, bind)
    assert bind.statements == []


# ---------------------------------------------------------------------------------------------------------------------
# PostgreSQL: настоящая база
# ---------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pg_database():
    admin = make_url(os.environ["INFRA_REGISTRY_TEST_DATABASE_URL"])
    name = f"infra_trgm_{uuid.uuid4().hex[:10]}"
    url = admin.set(database=name).render_as_string(hide_password=False)
    admin_engine = sa.create_engine(admin.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as connection:
        connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
    engine = sa.create_engine(url)
    try:
        migrate(url, "head")
        yield url, engine
    finally:
        engine.dispose()
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin_engine.dispose()


def _index_names(engine) -> set[str]:
    with engine.connect() as connection:
        rows = connection.execute(
            sa.text("SELECT indexname FROM pg_indexes WHERE tablename = 'audit_log' AND indexdef LIKE '%gin_trgm_ops%'")
        )
        return {row[0] for row in rows}


@pytest.mark.postgres_only
def test_postgres_head_has_the_trigram_indexes(pg_database):
    _, engine = pg_database
    assert _index_names(engine) == INDEXES


@pytest.mark.postgres_only
def test_postgres_downgrade_drops_the_indexes_and_upgrade_restores_them(pg_database):
    url, engine = pg_database
    migrate(url, PREVIOUS_REVISION, downgrade=True)
    assert _index_names(engine) == set()
    migrate(url, "head")
    assert _index_names(engine) == INDEXES


def _seed_audit_log(engine, rows: int) -> None:
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                INSERT INTO audit_log (id, entity_type, entity_id, action, details, actor_id, actor_username, actor_ip,
                                       created_at, updated_at)
                SELECT gen_random_uuid()::text, (ARRAY['devices','vms','connections','interfaces','vlans'])[1 + (g % 5)],
                       gen_random_uuid()::text,
                       (ARRAY['CREATE','UPDATE','DELETE'])[1 + (g % 3)],
                       'name: Устройство-' || g || ' → Коммутатор-' || (g * 7) || '; serial: SN' || md5(g::text),
                       gen_random_uuid()::text, 'user' || (g % 20), '10.0.' || (g % 250) || '.' || (g % 200),
                       now() - (g || ' seconds')::interval, now()
                FROM generate_series(1, :rows) g
                """
            ),
            {"rows": rows},
        )
        connection.execute(sa.text("ANALYZE audit_log"))


def _timed_search(engine) -> tuple[float, str, int]:
    """(секунды, план EXPLAIN того самого запроса, который отправил list_audit_log, число найденных). Лучшее из трёх прогонов."""
    sent: list[tuple[str, dict]] = []

    def capture(_connection, _cursor, statement, parameters, _context, _executemany):
        if (
            "audit_log" in statement
            and "LIKE" in statement
            and statement.lstrip().upper().startswith("SELECT")
            and "count(" not in statement.lower()
        ):
            sent.append((statement, parameters))

    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        best, total = float("inf"), 0
        for _ in range(3):
            started = time.perf_counter()
            with Session(engine) as session:
                total = list_audit_log(session, AuditQuery(q=SEARCH), offset=0, limit=50)["total"]
            best = min(best, time.perf_counter() - started)
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)
    assert sent, "запрос поиска не перехвачен"
    statement, parameters = sent[-1]
    with engine.connect() as connection:
        plan = "\n".join(row[0] for row in connection.exec_driver_sql("EXPLAIN " + statement, parameters))
    return best, plan, total


@pytest.mark.slow
@pytest.mark.postgres_only
def test_search_uses_the_trigram_indexes_and_is_much_faster_than_a_full_scan(pg_database):
    url, engine = pg_database
    _seed_audit_log(engine, 200_000)

    indexed_seconds, indexed_plan, found = _timed_search(engine)
    assert found >= 1, "поисковый фрагмент должен находить записи"
    assert "ix_audit_log_details_trgm" in indexed_plan and "ix_audit_log_entity_id_trgm" in indexed_plan and "Bitmap" in indexed_plan, (
        indexed_plan
    )

    migrate(url, PREVIOUS_REVISION, downgrade=True)  # те же данные без индексов
    try:
        with engine.begin() as connection:
            connection.execute(sa.text("ANALYZE audit_log"))
        scan_seconds, scan_plan, found_without_index = _timed_search(engine)
    finally:
        migrate(url, "head")
    assert "Seq Scan" in scan_plan and found_without_index == found, "индексы ускоряют поиск, но не меняют его результат"
    print(f"\nпоиск по журналу аудита (200 000 записей): с индексами {indexed_seconds * 1000:.1f} мс, без — {scan_seconds * 1000:.1f} мс")
    # Главные гарантии — планы EXPLAIN выше (индексы использованы / Seq Scan без них, результат тот же): они детерминированы.
    # Замер времени лишь страхует от индекса, который есть, но не помогает; на общем раннере он шумит (в CI одного и того же кода:
    # 4,5 раза при
    # пороге 5), поэтому порог — 2.
    assert indexed_seconds * 2 < scan_seconds, f"ожидалось ускорение минимум в 2 раза: {indexed_seconds:.4f} с против {scan_seconds:.4f} с"
