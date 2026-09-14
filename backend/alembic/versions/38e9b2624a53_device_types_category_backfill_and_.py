"""device types category backfill and destructive cleanup

Revision ID: 38e9b2624a53
Revises: d359e0bd414c
Create Date: 2026-09-08 00:00:01.000000

Миграция 2/4 фичи "Диаграмма топологии сети" (ТЗ, раздел 5, п.2). ЕДИНСТВЕННАЯ деструктивная
ревизия в этой фиче — перед выполнением на РЕАЛЬНОЙ БД с данными нужно явное подтверждение
(раздел 14 ТЗ): любые PhysicalDevice с device_type в {'Сетевое оборудование', 'Средство защиты
информации'}, а также ВСЕ их зависимые записи (интерфейсы и подключения через них, VLAN-привязки,
размещённые на них ВМ и их зависимости, контейнеры, ПО устройства, связи с ИС) удаляются вместе
с этими двумя типами. На уже эксплуатируемых инсталляциях это настоящая потеря данных.

Что делает эта миграция:
1. Добавляет device_types.category_id (пока nullable) + FK на device_categories + индекс.
2. Каскадно удаляет всё, что ссылается на устройства типов 'Сетевое оборудование'/'Средство
   защиты информации' (полный список — раздел 4.2 ТЗ), затем сами эти два типа (и неиспользуемые
   DeviceModel/DeviceTypeVLAN на них). Если этих типов в БД нет (новая инсталляция, миграция
   выполняется до первого запуска приложения, когда device_types ещё вообще пуст) — шаг no-op.
3. Backfill category_id для ОСТАВШИХСЯ типов устройств по карте "имя -> категория" (раздел 4.1
   ТЗ). Тип устройства, не входящий в карту (заведён администратором вручную до этой миграции,
   переименование стандартных типов не ожидается) — получает категорию-fallback
   'Другое оборудование', заведённую миграцией d359e0bd414c. Без явного fallback'а обязательный
   NOT NULL ниже не на что было бы опереться для произвольного кастомного типа.
4. Переводит category_id в NOT NULL. На SQLite — полной пересборкой таблицы с ИМЕНОВАННЫМИ
   констрейнтами (тот же приём, что c4e8a7d91b20/f4a29c7e1d60: batch_alter_table на SQLite не
   гарантированно переносит существующие ограничения через reflection — см. НЕ ТОЛЬКО метаданные
   SQLAlchemy, но и `PRAGMA table_info` в tests/test_migrations_diagram.py, который проверяет
   итоговый DDL напрямую, как того требует раздел 13 ТЗ). На PostgreSQL — обычный
   ALTER COLUMN SET NOT NULL, ADD COLUMN/ALTER COLUMN там не теряют существующие ограничения.

Добавление 7 новых типов устройств (раздел 4.2 ТЗ) сознательно НЕ входит в эту миграцию: как и
исходные 12 типов до этой фичи, состав device_types — прикладной каталог, идемпотентно
досеиваемый services/catalogs.py:_seed_device_types() при каждом старте приложения (тот же
принцип, что и для остальных DEFAULT_NAMES-каталогов). Единственное, что обязано произойти
именно в МИГРАЦИИ, а не при следующем старте — backfill category_id уже существующих строк
(seed_defaults() только добавляет отсутствующие по имени записи, не трогая уже существующие) и
удаление двух устаревших типов вместе с их данными.

Downgrade не поддерживается (как и в c4e8a7d91b20) — удалённые в п.2 данные восстановить
невозможно, откат одной лишь схемы дал бы ложное ощущение обратимости.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "38e9b2624a53"
down_revision = "d359e0bd414c"
branch_labels = None
depends_on = None

REMOVED_DEVICE_TYPE_NAMES = ("Сетевое оборудование", "Средство защиты информации")
FALLBACK_DEVICE_CATEGORY_NAME = "Другое оборудование"

# Должно оставаться в синхроне с app/services/catalogs.py:DEVICE_TYPE_CATEGORY (сверяется
# tests/test_migrations_diagram.py) — карта используется только для backfill УЖЕ существующих
# строк device_types на upgrade апгрейдящейся БД; 7 новых типов из этой карты, отсутствующих в
# БД на момент миграции, добавит следующий старт приложения через _seed_device_types().
DEVICE_TYPE_CATEGORY = {
    "Сервер": "Серверы и СХД",
    "Система хранения данных": "Серверы и СХД",
    "Точка доступа Wi-Fi": "Сетевая инфраструктура",
    "GSM-модем": "Сетевая инфраструктура",
    "Радиомост": "Сетевая инфраструктура",
    "Маршрутизатор": "Сетевая инфраструктура",
    "Коммутатор L2": "Коммутаторы",
    "Коммутатор L3": "Коммутаторы",
    "Межсетевой экран": "Средства защиты информации",
    "Программно-аппаратный комплекс": "Средства защиты информации",
    "Рабочая станция пользователя": "Рабочие места",
    "Рабочий ПК системного администратора": "Администраторские рабочие места",
    "Рабочий ПК сетевого администратора": "Администраторские рабочие места",
    "Рабочий ПК администратора безопасности": "Администраторские рабочие места",
    "IP-телефон": "Периферия и вспомогательное оборудование",
    "ИБП": "Периферия и вспомогательное оборудование",
    "Принтер/МФУ": "Периферия и вспомогательное оборудование",
}


def _delete_in(bind, table: str, column: str, ids: list[str]) -> None:
    if not ids:
        return
    stmt = sa.text(f"DELETE FROM {table} WHERE {column} IN :ids").bindparams(sa.bindparam("ids", expanding=True))
    bind.execute(stmt, {"ids": ids})


def _cascade_delete_devices_of_removed_types(bind, removed_type_ids: list[str]) -> None:
    """Полный каскад раздела 4.2 ТЗ для устройств удаляемых типов — порядок снизу вверх
    (сначала записи, ссылающиеся на устройство/ВМ/контейнер/интерфейс, потом сами они)."""
    if not removed_type_ids:
        return

    device_ids = [row[0] for row in bind.execute(
        sa.text("SELECT id FROM physical_devices WHERE device_type_id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
        {"ids": removed_type_ids},
    ).fetchall()]

    if not device_ids:
        vm_ids: list[str] = []
        container_ids: list[str] = []
        interface_ids: list[str] = []
    else:
        vm_ids = [row[0] for row in bind.execute(
            sa.text("SELECT id FROM virtual_machines WHERE physical_device_id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": device_ids},
        ).fetchall()]
        container_id_rows = bind.execute(
            sa.text(
                "SELECT id FROM containers WHERE physical_device_id IN :device_ids "
                "OR virtual_machine_id IN :vm_ids"
            ).bindparams(sa.bindparam("device_ids", expanding=True), sa.bindparam("vm_ids", expanding=True)),
            {"device_ids": device_ids, "vm_ids": vm_ids or [""]},
        ).fetchall()
        container_ids = [row[0] for row in container_id_rows]
        interface_ids = [row[0] for row in bind.execute(
            sa.text("SELECT id FROM device_interfaces WHERE physical_device_id IN :ids").bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": device_ids},
        ).fetchall()]

    # 1. Связи ИС (унифицированные источники + устаревшие таблицы) и открытые порты.
    if device_ids or vm_ids or container_ids:
        bind.execute(
            sa.text(
                "DELETE FROM information_system_sources WHERE "
                "physical_device_id IN :device_ids OR virtual_machine_id IN :vm_ids OR container_id IN :container_ids"
            ).bindparams(
                sa.bindparam("device_ids", expanding=True),
                sa.bindparam("vm_ids", expanding=True),
                sa.bindparam("container_ids", expanding=True),
            ),
            {"device_ids": device_ids or [""], "vm_ids": vm_ids or [""], "container_ids": container_ids or [""]},
        )
    _delete_in(bind, "information_system_devices", "physical_device_id", device_ids)
    _delete_in(bind, "information_system_vms", "virtual_machine_id", vm_ids)
    _delete_in(bind, "information_system_containers", "container_id", container_ids)
    if device_ids or vm_ids:
        bind.execute(
            sa.text(
                "DELETE FROM information_system_ips WHERE physical_device_id IN :device_ids OR virtual_machine_id IN :vm_ids"
            ).bindparams(sa.bindparam("device_ids", expanding=True), sa.bindparam("vm_ids", expanding=True)),
            {"device_ids": device_ids or [""], "vm_ids": vm_ids or [""]},
        )
    if device_ids or vm_ids:
        bind.execute(
            sa.text(
                "DELETE FROM open_ports WHERE (owner_type = 'physical_device' AND owner_id IN :device_ids) "
                "OR (owner_type = 'virtual_machine' AND owner_id IN :vm_ids)"
            ).bindparams(sa.bindparam("device_ids", expanding=True), sa.bindparam("vm_ids", expanding=True)),
            {"device_ids": device_ids or [""], "vm_ids": vm_ids or [""]},
        )

    # 2. ПО, IP и сами ВМ/контейнеры.
    _delete_in(bind, "vm_software", "virtual_machine_id", vm_ids)
    _delete_in(bind, "device_software", "physical_device_id", device_ids)
    _delete_in(bind, "vm_ips", "virtual_machine_id", vm_ids)
    _delete_in(bind, "containers", "id", container_ids)

    # 3. Подключения и VLAN-привязки интерфейсов, сами интерфейсы.
    if interface_ids:
        bind.execute(
            sa.text(
                "DELETE FROM connections WHERE source_interface_id IN :ids OR destination_interface_id IN :ids"
            ).bindparams(sa.bindparam("ids", expanding=True)),
            {"ids": interface_ids},
        )
    _delete_in(bind, "interface_vlans", "interface_id", interface_ids)
    _delete_in(bind, "interface_ips", "interface_id", interface_ids)
    _delete_in(bind, "device_interfaces", "id", interface_ids)

    # 4. VLAN-привязки устройства, ссылка домена VLAN на устройство-источник (не удаляем сам
    #    домен — только обнуляем источник, см. VLANDomain.source_device_id nullable).
    _delete_in(bind, "physical_device_vlans", "physical_device_id", device_ids)
    if device_ids:
        bind.execute(
            sa.text("UPDATE vlan_domains SET source_device_id = NULL WHERE source_device_id IN :ids").bindparams(
                sa.bindparam("ids", expanding=True)
            ),
            {"ids": device_ids},
        )

    # 5. Сами ВМ и устройства.
    _delete_in(bind, "virtual_machines", "id", vm_ids)
    _delete_in(bind, "physical_devices", "id", device_ids)

    # 6. Неиспользуемые каталожные записи, ссылающиеся на удаляемые типы устройств.
    _delete_in(bind, "device_models", "device_type_id", removed_type_ids)
    _delete_in(bind, "device_type_vlans", "device_type_id", removed_type_ids)
    _delete_in(bind, "device_types", "id", removed_type_ids)


def _rebuild_device_types_not_null_sqlite(bind) -> None:
    bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
    bind.execute(sa.text("""CREATE TABLE device_types_new (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        allows_vm_hosting BOOLEAN NOT NULL DEFAULT 0,
        category_id VARCHAR(36) NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        CONSTRAINT uq_device_types_name UNIQUE (name),
        CONSTRAINT fk_device_types_category FOREIGN KEY(category_id) REFERENCES device_categories (id)
    )"""))
    bind.execute(sa.text(
        "INSERT INTO device_types_new (id, name, allows_vm_hosting, category_id, created_at, updated_at) "
        "SELECT id, name, allows_vm_hosting, category_id, created_at, updated_at FROM device_types"
    ))
    bind.execute(sa.text("DROP TABLE device_types"))
    bind.execute(sa.text("ALTER TABLE device_types_new RENAME TO device_types"))
    bind.execute(sa.text("CREATE INDEX ix_device_types_category_id ON device_types (category_id)"))
    bind.execute(sa.text("PRAGMA foreign_keys=ON"))


def upgrade() -> None:
    bind = op.get_bind()

    op.add_column("device_types", sa.Column("category_id", sa.String(length=36), nullable=True))

    removed_type_ids = [
        row[0] for row in bind.execute(
            sa.text("SELECT id FROM device_types WHERE name IN :names").bindparams(sa.bindparam("names", expanding=True)),
            {"names": list(REMOVED_DEVICE_TYPE_NAMES)},
        ).fetchall()
    ]
    _cascade_delete_devices_of_removed_types(bind, removed_type_ids)

    categories = dict(bind.execute(sa.text("SELECT name, id FROM device_categories")).fetchall())
    fallback_id = categories.get(FALLBACK_DEVICE_CATEGORY_NAME)
    remaining = bind.execute(sa.text("SELECT id, name FROM device_types")).fetchall()
    for device_type_id, name in remaining:
        category_name = DEVICE_TYPE_CATEGORY.get(name)
        category_id = categories.get(category_name) if category_name else None
        category_id = category_id or fallback_id
        bind.execute(
            sa.text("UPDATE device_types SET category_id = :category_id WHERE id = :id"),
            {"category_id": category_id, "id": device_type_id},
        )

    if bind.dialect.name == "sqlite":
        _rebuild_device_types_not_null_sqlite(bind)
    else:
        op.alter_column("device_types", "category_id", existing_type=sa.String(length=36), nullable=False)
        op.create_foreign_key("fk_device_types_category", "device_types", "device_categories", ["category_id"], ["id"])
        op.create_index("ix_device_types_category_id", "device_types", ["category_id"])


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade миграции 38e9b2624a53 не поддерживается: устройства типов "
        "'Сетевое оборудование'/'Средство защиты информации' и все их зависимые записи "
        "удаляются безвозвратно (см. docstring модуля) — откат одной лишь схемы "
        "(category_id/NOT NULL) создал бы ложное ощущение обратимости этой миграции."
    )
