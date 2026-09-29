"""Триггеры БД: запрет удаления устройства/ВМ/контейнера, на который ссылается источник ИС

Revision ID: 5b1e7c94a2d8
Revises: 944bd490d967
Create Date: 2026-09-28 00:00:00.000000

Пятый (последний) уровень защиты для information_system_sources.owner_id — единой колонки без
настоящего FK (см. models.InformationSystemSource и services/integrity.py). Прикладные уровни
(assert_deletable, before_delete) не видят прямой SQL и массовое Core-удаление; триггер БД видит
любой DELETE, откуда бы он ни пришёл (psql, стороннее приложение, ручная правка).

Поведение: BEFORE DELETE на physical_devices / virtual_machines / containers — если в
information_system_sources есть строка с подходящим source_type ('device' / 'vm' / 'container')
и owner_id = id удаляемой записи, удаление отклоняется. На SQLite — RAISE(ABORT) (в SQLAlchemy это
IntegrityError), на PostgreSQL — RAISE EXCEPTION с SQLSTATE 23503 (foreign_key_violation, тоже
IntegrityError), то есть существующий обработчик IntegrityError в crud.delete_resource() отвечает
на них так же, как на обычное FK-нарушение.

ВАЖНО для будущих миграций на SQLite: пересборка таблицы (CREATE new → INSERT → DROP → RENAME, как
в d8e35a1c7f60/944bd490d967) безвозвратно удаляет триггеры этой таблицы. Если когда-нибудь будет
пересобираться physical_devices/virtual_machines/containers — триггер нужно создать заново; это
ловит tests/test_migrations_information_system_source_delete_guard_triggers.py (проверяет
триггеры и их поведение на head).

downgrade() РАБОТАЕТ (требование проекта: «в дальнейшем даунгрейд должен работать»): снимает
триггеры и, на PostgreSQL, функцию. Данных миграция не меняет, поэтому откат ничего не теряет.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "5b1e7c94a2d8"
down_revision = "944bd490d967"
branch_labels = None
depends_on = None

_MESSAGE = "Нельзя удалить: на запись ссылается источник информационной системы (information_system_sources.owner_id)"
_PG_FUNCTION = "fn_block_delete_referenced_by_is_source"

# (таблица владельца, значение source_type)
_GUARDED = (
    ("physical_devices", "device"),
    ("virtual_machines", "vm"),
    ("containers", "container"),
)


def _trigger_name(table: str) -> str:
    return f"trg_is_source_guard_{table}"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for table, source_type in _GUARDED:
            bind.execute(sa.text(
                f"CREATE TRIGGER {_trigger_name(table)} BEFORE DELETE ON {table} "
                f"WHEN EXISTS (SELECT 1 FROM information_system_sources "
                f"WHERE source_type = '{source_type}' AND owner_id = OLD.id) "
                f"BEGIN SELECT RAISE(ABORT, '{_MESSAGE}'); END"
            ))
        return

    bind.execute(sa.text(
        f"CREATE OR REPLACE FUNCTION {_PG_FUNCTION}() RETURNS trigger AS $fn$ "
        f"BEGIN "
        f"IF EXISTS (SELECT 1 FROM information_system_sources "
        f"WHERE source_type = TG_ARGV[0] AND owner_id = OLD.id) THEN "
        f"RAISE EXCEPTION '{_MESSAGE}' USING ERRCODE = '23503'; "
        f"END IF; "
        f"RETURN OLD; "
        f"END; $fn$ LANGUAGE plpgsql"
    ))
    for table, source_type in _GUARDED:
        bind.execute(sa.text(
            f"CREATE TRIGGER {_trigger_name(table)} BEFORE DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {_PG_FUNCTION}('{source_type}')"
        ))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for table, _ in _GUARDED:
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {_trigger_name(table)}"))
        return

    for table, _ in _GUARDED:
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {_trigger_name(table)} ON {table}"))
    bind.execute(sa.text(f"DROP FUNCTION IF EXISTS {_PG_FUNCTION}()"))
