"""created_at/updated_at становятся обязательными (NOT NULL) там, где этого требует модель (R1-02 код-ревью)

Revision ID: a7d3f1c8e925
Revises: e4b1c7d9a362
Create Date: 2026-11-08 00:00:00.000000

Модели (`TimestampMixin`, `AuthSession.created_at`) объявляют метки времени обязательными, а ранние миграции создавали колонки без
NOT NULL. Значения проставляет приложение (default=utcnow_naive), но в базе из миграций колонки оставались NULLABLE, и
`alembic check` показывал 42 расхождения в 22 таблицах (на SQLite — 40 в 21: у `information_system_sources` SQLite-ветка одной из
миграций пересобирала таблицу уже с NOT NULL, поэтому список по SQLite неполон — он собран по обеим СУБД).

Что делает миграция, для каждой таблицы из TIMESTAMP_COLUMNS:
1. Заполняет NULL: `created_at` — текущим моментом UTC (настоящее время создания строки неизвестно), `updated_at` — значением
   `created_at` той же строки, а если и его нет — текущим моментом. Значение вычисляется в Python и передаётся параметром, а не
   выражением СУБД: так на SQLite и PostgreSQL в колонку попадает один и тот же наивный UTC, как пишет приложение.
2. Переводит колонку в NOT NULL. PostgreSQL — `ALTER COLUMN SET NOT NULL`. SQLite не умеет менять NOT NULL на месте, поэтому таблица
   пересобирается через `batch_alter_table(recreate="always")`: Alembic отражает таблицу, создаёт копию с новым ограничением,
   переносит строки, удаляет оригинал и восстанавливает индексы и внешние ключи. Перед пересборкой внешние ключи SQLite обязаны быть
   выключены: иначе `DROP TABLE` родительской таблицы (`users`, `saved_diagrams`…) каскадно удалил бы дочерние строки
   (`auth_sessions`, `diagram_layouts`…); если выключить не удалось, миграция останавливается, ничего не испортив.

Миграция идемпотентна: колонки, которые уже NOT NULL (например, на SQLite у `information_system_sources`), и отсутствующие таблицы
пропускаются. Триггеров у перечисленных таблиц нет (триггеры защиты источников ИС висят на physical_devices, containers и
virtual_machines и пересборкой не затрагиваются).

Downgrade возвращает колонки в NULLABLE; заполненные значения намеренно остаются — они не мешают прежней версии кода.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "a7d3f1c8e925"
down_revision = "e4b1c7d9a362"
branch_labels = None
depends_on = None

# Таблица → колонки меток времени, которые модель объявляет обязательными. Список собран по `alembic check` на SQLite и PostgreSQL
# и зафиксирован здесь намеренно: миграция не должна зависеть от текущих моделей.
TIMESTAMP_COLUMNS: dict[str, tuple[str, ...]] = {
    "auth_sessions": ("created_at",),
    "auth_settings": ("updated_at",),
    "crypto_protection_means": ("created_at", "updated_at"),
    "device_categories": ("created_at", "updated_at"),
    "device_type_vlans": ("created_at", "updated_at"),
    "diagram_group_states": ("created_at", "updated_at"),
    "diagram_icons": ("created_at", "updated_at"),
    "diagram_layouts": ("created_at", "updated_at"),
    "embedded_operating_systems": ("created_at", "updated_at"),
    "information_system_sources": ("created_at", "updated_at"),
    "interface_speeds": ("created_at", "updated_at"),
    "is_placement_assets": ("created_at", "updated_at"),
    "physical_device_vlans": ("created_at", "updated_at"),
    "placement_assets": ("created_at", "updated_at"),
    "port_sync_rules": ("created_at", "updated_at"),
    "protocol_port_catalogs": ("created_at", "updated_at"),
    "report_template_versions": ("created_at", "updated_at"),
    "saved_diagrams": ("created_at", "updated_at"),
    "structural_units": ("created_at", "updated_at"),
    "support_methods": ("created_at", "updated_at"),
    "support_organizations": ("created_at", "updated_at"),
    "users": ("created_at", "updated_at"),
}


def _utc_now() -> datetime:
    """Наивный UTC — как `app.services.timeutil.utcnow_naive` (приложение хранит время именно так)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _plan(inspector: sa.Inspector) -> dict[str, tuple[set[str], list[str]]]:
    """Таблица → (все её колонки, колонки из TIMESTAMP_COLUMNS, которые сейчас допускают NULL). Таблицы без таких колонок и
    отсутствующие таблицы в план не попадают."""
    plan: dict[str, tuple[set[str], list[str]]] = {}
    for table, wanted in TIMESTAMP_COLUMNS.items():
        if not inspector.has_table(table):
            continue
        by_name = {column["name"]: column for column in inspector.get_columns(table)}
        nullable = [name for name in wanted if name in by_name and by_name[name]["nullable"]]
        if nullable:
            plan[table] = (set(by_name), nullable)
    return plan


def _backfill(bind: sa.engine.Connection, table: str, all_columns: set[str], nullable: list[str]) -> None:
    """Заполняет NULL: created_at — текущим моментом, updated_at — created_at той же строки (или текущим моментом)."""
    ref = sa.table(table, sa.column("created_at", sa.DateTime()), sa.column("updated_at", sa.DateTime()))
    now = _utc_now()
    if "created_at" in nullable:
        bind.execute(sa.update(ref).where(ref.c.created_at.is_(None)).values(created_at=now))
    if "updated_at" in nullable:
        # created_at к этому моменту уже заполнен (см. выше), если он есть в таблице.
        fallback = sa.func.coalesce(ref.c.created_at, now) if "created_at" in all_columns else sa.literal(now, sa.DateTime())
        bind.execute(sa.update(ref).where(ref.c.updated_at.is_(None)).values(updated_at=fallback))


def _disable_sqlite_foreign_keys(bind: sa.engine.Connection) -> None:
    """Выключает внешние ключи SQLite на соединении миграции и убеждается, что они действительно выключены.

    PRAGMA foreign_keys внутри открытой транзакции ничего не меняет, поэтому проверяем результат: молча пересобрать родительскую таблицу
    с включёнными ключами значило бы каскадно стереть дочерние строки."""
    bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
    if bind.execute(sa.text("PRAGMA foreign_keys")).scalar():
        raise RuntimeError(
            "Не удалось выключить внешние ключи SQLite перед пересборкой таблиц: пересборка родительской таблицы каскадно удалила бы "
            "дочерние строки. Запустите миграцию на отдельном соединении без открытой транзакции (alembic upgrade head)."
        )


# На SQLite эти колонки уже были NOT NULL до этой миграции (SQLite-ветка ранней миграции пересобрала таблицу), на PostgreSQL —
# нет. Upgrade на SQLite их не трогает (они не nullable), поэтому и downgrade не должен ослаблять ограничение, которого не добавлял.
SQLITE_ALREADY_REQUIRED: frozenset[str] = frozenset({"information_system_sources"})


def _assert_no_triggers_on(bind: sa.engine.Connection, table: str) -> None:
    """Пересборка таблицы в SQLite удаляет её триггеры, а триггеры ДРУГИХ таблиц, упоминающие её, ломают переименование копии.
    У перечисленных таблиц триггеров нет; если появятся — миграцию нужно дополнить их сохранением, а не терять защиту молча."""
    rows = bind.execute(sa.text("SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger'")).all()
    touching = [name for name, tbl_name, sql in rows if tbl_name == table or table in (sql or "")]
    if touching:
        raise RuntimeError(f"Пересборка таблицы {table} затронула бы триггеры SQLite {touching}: сохраните и пересоздайте их в миграции.")


def _set_not_null(bind: sa.engine.Connection, table: str, columns: list[str], *, nullable: bool) -> None:
    if bind.dialect.name == "sqlite":
        # SQLite не меняет NOT NULL на месте — пересборка таблицы (внешние ключи уже выключены).
        _assert_no_triggers_on(bind, table)
        with op.batch_alter_table(table, recreate="always") as batch:
            for column in columns:
                batch.alter_column(column, existing_type=sa.DateTime(), nullable=nullable)
    else:
        for column in columns:
            op.alter_column(table, column, existing_type=sa.DateTime(), nullable=nullable)


def upgrade() -> None:
    bind = op.get_bind()
    plan = _plan(sa.inspect(bind))
    if not plan:
        return
    if bind.dialect.name == "sqlite":
        _disable_sqlite_foreign_keys(bind)
    for table, (all_columns, nullable) in plan.items():
        _backfill(bind, table, all_columns, nullable)
        _set_not_null(bind, table, nullable, nullable=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if bind.dialect.name == "sqlite":
        _disable_sqlite_foreign_keys(bind)
    for table, wanted in TIMESTAMP_COLUMNS.items():
        if not inspector.has_table(table) or (bind.dialect.name == "sqlite" and table in SQLITE_ALREADY_REQUIRED):
            continue
        by_name = {column["name"]: column for column in inspector.get_columns(table)}
        columns = [name for name in wanted if name in by_name and not by_name[name]["nullable"]]
        if columns:
            _set_not_null(bind, table, columns, nullable=True)
