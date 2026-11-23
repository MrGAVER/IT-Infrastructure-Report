"""Триггеры БД: удаление владельца убирает его полиморфных потомков; разовая чистка уже осиротевших записей

Revision ID: 7c3d9a5e1b24
Revises: d6c1a8f3e594
Create Date: 2026-11-19 00:00:00.000000

open_ports, deployed_software и ip_addresses ссылаются на владельца парой (owner_type, owner_id) — внешний ключ на такую пару в SQL
невозможен, и целостность до сих пор держал только код приложения: _POLYMORPHIC_OWNER_CLEANUP в services/crud/deletion.py, ORM-хуки
и поиск «осиротевших» записей (services/integrity.py). Любой путь, удаляющий владельца мимо ORM (ручной SQL, каскад внешнего ключа,
сторонний скрипт), оставлял сирот — каскад FK, например, убирает подинтерфейсы, но не их IP-адреса и открытые порты.

Что делает миграция:

1. Один раз удаляет уже существующих сирот: строки потомков, у которых owner_type известен, а владельца с таким id нет. Строки с
   неизвестным owner_type НЕ трогаются — это не «потерянный владелец», а ошибка данных, её показывает диагностика целостности
   (GET /api/v1/integrity). Сколько строк удалено, записывается в журнал аудита (по записи на таблицу, действие DELETE) и в лог Alembic.
2. Создаёт триггеры AFTER DELETE на таблицах владельцев (физические устройства, ВМ, порты, подинтерфейсы, источники ИС): удаляя строку
   владельца, БД удаляет всех её потомков по (owner_type, owner_id). Срабатывают и на каскад внешнего ключа (проверено на SQLite и
   PostgreSQL), поэтому цепочка «устройство → порты → подинтерфейсы → IP/открытые порты» очищается целиком.

Контейнеры в списке нет намеренно: у контейнера нет значения OwnerType (потомков он не имеет), на него лишь ссылаются источники ИС — это
обратная защита, её дают триггеры 5b1e7c94a2d8.

deletion.py остаётся первой линией защиты (понятные сообщения, порядок удаления) и не меняется. Триггеры — последний рубеж.
Тест test_review_p2_polymorphic_owner_triggers.py не даёт добавить новый тип владельца без защиты.

ВАЖНО для будущих миграций на SQLite: пересборка таблицы (CREATE new → INSERT → DROP → RENAME) безвозвратно удаляет её триггеры. Если
когда-нибудь будет пересобираться одна из таблиц владельцев — триггер нужно создать заново; тест проверяет их на head.

Производительность: у open_ports нет индекса по (owner_type, owner_id) (у ip_addresses и deployed_software он есть), поэтому удаление
владельца просматривает open_ports целиком. На размерах реестра инфраструктуры это единицы миллисекунд; индекс добавляется вместе с
правкой models.py (там же должен быть описан, иначе `alembic check` увидит расхождение).

upgrade() идемпотентна (CREATE TRIGGER IF NOT EXISTS / DROP + CREATE): повторный запуск ревизии на уже мигрированной базе — приём, который
использует test_the_index_migration_is_idempotent_on_sqlite, — ничего не ломает.

downgrade() работает: снимает триггеры и, на PostgreSQL, функцию. Удалённых сирот он не возвращает — это записи без владельца,
которых не видел ни один экран и ни один отчёт.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "7c3d9a5e1b24"
down_revision = "d6c1a8f3e594"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# (таблица владельца, значение owner_type). Значения заморожены здесь, а не берутся из app.constants: миграция описывает схему на момент
# своей ревизии. Новый тип владельца добавляется НОВОЙ миграцией; тест сверяет этот набор с app.constants.OwnerType.
_OWNERS = (
    ("physical_devices", "physical_device"),
    ("virtual_machines", "virtual_machine"),
    ("device_interfaces", "device_interface"),
    ("device_subinterfaces", "device_subinterface"),
    ("information_system_sources", "information_system_source"),
)
# (таблица потомка, ключ ресурса в журнале аудита — registry.MODEL_MAP)
_CHILDREN = (
    ("open_ports", "open-ports"),
    ("deployed_software", "deployed-software"),
    ("ip_addresses", "ip-addresses"),
)
_PG_FUNCTION = "fn_delete_polymorphic_owner_children"


def _trigger_name(table: str) -> str:
    return f"trg_owner_cleanup_{table}"


def _purge_orphans(bind) -> dict[str, dict[str, int]]:
    """{таблица потомка: {owner_type: сколько строк удалено}} — только ненулевые."""
    removed: dict[str, dict[str, int]] = {}
    for child, _ in _CHILDREN:
        for owner_table, owner_type in _OWNERS:
            result = bind.execute(
                sa.text(f"DELETE FROM {child} WHERE owner_type = :owner_type AND owner_id NOT IN (SELECT id FROM {owner_table})"),
                {"owner_type": owner_type},
            )
            if result.rowcount:
                removed.setdefault(child, {})[owner_type] = result.rowcount
    return removed


def _record_in_audit_log(bind, removed: dict[str, dict[str, int]]) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # в БД время хранится как naive UTC (services/timeutil.py)
    resource_keys = dict(_CHILDREN)
    for child, by_owner_type in removed.items():
        breakdown = "; ".join(f"{owner_type}: {count}" for owner_type, count in sorted(by_owner_type.items()))
        details = f"Миграция {revision}: удалены записи без владельца — {sum(by_owner_type.values())} ({breakdown})"
        logger.info("%s: %s", child, details)
        bind.execute(
            sa.text(
                "INSERT INTO audit_log (id, entity_type, entity_id, action, details, created_at, updated_at) "
                "VALUES (:id, :entity_type, :entity_id, 'DELETE', :details, :now, :now)"
            ),
            {"id": str(uuid.uuid4()), "entity_type": resource_keys[child], "entity_id": revision, "details": details, "now": now},
        )


def upgrade() -> None:
    bind = op.get_bind()
    removed = _purge_orphans(bind)
    if removed:
        _record_in_audit_log(bind, removed)

    if bind.dialect.name == "sqlite":
        for table, owner_type in _OWNERS:
            deletes = " ".join(f"DELETE FROM {child} WHERE owner_type = '{owner_type}' AND owner_id = OLD.id;" for child, _ in _CHILDREN)
            bind.execute(sa.text(f"CREATE TRIGGER IF NOT EXISTS {_trigger_name(table)} AFTER DELETE ON {table} BEGIN {deletes} END"))
        return

    deletes = " ".join(f"DELETE FROM {child} WHERE owner_type = TG_ARGV[0] AND owner_id = OLD.id;" for child, _ in _CHILDREN)
    bind.execute(sa.text(f"CREATE OR REPLACE FUNCTION {_PG_FUNCTION}() RETURNS trigger AS $fn$ BEGIN {deletes} RETURN OLD; END; $fn$ LANGUAGE plpgsql"))
    for table, owner_type in _OWNERS:
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {_trigger_name(table)} ON {table}"))
        bind.execute(sa.text(f"CREATE TRIGGER {_trigger_name(table)} AFTER DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {_PG_FUNCTION}('{owner_type}')"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for table, _ in _OWNERS:
            bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {_trigger_name(table)}"))
        return

    for table, _ in _OWNERS:
        bind.execute(sa.text(f"DROP TRIGGER IF EXISTS {_trigger_name(table)} ON {table}"))
    bind.execute(sa.text(f"DROP FUNCTION IF EXISTS {_PG_FUNCTION}()"))
