"""interface_ips/vm_ips и information_system_sources.ip_address объединены в ip_addresses
(owner_type/owner_id); containers.management_ip удалена как неиспользуемая

Revision ID: d8e35a1c7f60
Revises: c4a91e6f2b83
Create Date: 2026-09-21 00:00:00.000000

Правка "переработка структуры БД", вопросы 1/3/5 отчёта по анализу БД (согласовано с заказчиком:
"давай пробовать" по объединению interface_ips/vm_ips; "можно менять фронтенд, чтобы добавлять
несколько полей ip вместо одного текстового" по information_system_sources.ip_address;
"можно пробовать" по переводу InformationSystemSource на тот же паттерн).

Что делает эта миграция:

1. interface_ips и vm_ips — идентичный по смыслу набор данных (IP-адрес + необязательные
   префикс/назначение/признак IP администрирования у конкретного владельца), отличавшийся только
   именем FK-колонки владельца. Тот же случай, что уже решён для OpenPort (a1b7c9d3e502) и
   DeployedSoftware (c4a91e6f2b83): объединены в единую ip_addresses с owner_type/owner_id.

2. information_system_sources.ip_address хранила НЕСКОЛЬКО IP-адресов одной строкой через запятую
   (единственное место в проекте с таким форматом) — согласовано заменить на отдельные строки
   ip_addresses (owner_type="information_system_source", owner_id=<id строки source>), по одной
   на адрес, чтобы фронтенд мог показывать несколько независимых полей ввода вместо одного
   текстового. Пустые фрагменты после разбiения по запятой отбрасываются.

3. containers.management_ip удалена целиком (без переноса данных, даже если у какой-то строки
   было значение): подтверждено, что поле не редактировалось ни через один UI (см. комментарий в
   ContainerFormModal.vue "у контейнера нет своего IP на уровне отчёта") — решение заказчика:
   "удалить как мёртвое поле вместе с объединением", а не активировать его через миграцию на
   тот же список IP, что у интерфейса/ВМ.

На SQLite — пересборка containers/information_system_sources вручную (тот же приём, что и в
a1b7c9d3e502/b7f2c1e5a904: batch_alter_table на SQLite не гарантированно переносит существующие
FK/индексы через reflection); interface_ips/vm_ips удаляются целиком через op.drop_table — это не
требует пересборки ни на одном диалекте. На PostgreSQL — обычный DROP COLUMN для обеих таблиц.

Downgrade не поддерживается (RuntimeError) — тот же принцип, что в 38e9b2624a53/b7f2c1e5a904:
данные (включая исходный текстовый формат IP источников ИС через запятую) теряются безвозвратно.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "d8e35a1c7f60"
down_revision = "c4a91e6f2b83"
branch_labels = None
depends_on = None


def _migrate_source_ip_addresses(bind) -> None:
    """См. п.2 в docstring модуля. Разбивает information_system_sources.ip_address по запятой на
    отдельные строки ip_addresses — тот же Python-цикл (а не чистый SQL), что и в других местах
    проекта, где нужно распарсить составное текстовое поле построчно (см. _backfill_is_protocol_
    catalog_id в b7f2c1e5a904)."""
    now = datetime.now(timezone.utc)
    rows = bind.execute(sa.text("SELECT id, ip_address FROM information_system_sources WHERE ip_address IS NOT NULL")).fetchall()
    for source_id, raw in rows:
        for part in (raw or "").split(","):
            ip = part.strip()
            if not ip:
                continue
            bind.execute(
                sa.text(
                    "INSERT INTO ip_addresses (id, owner_type, owner_id, ip_address, is_management, created_at, updated_at) "
                    "VALUES (:id, 'information_system_source', :owner_id, :ip, :mgmt, :c, :c)"
                ),
                {"id": str(uuid.uuid4()), "owner_id": source_id, "ip": ip, "mgmt": False, "c": now},  # булево: PostgreSQL не принимает 0
            )


def _rebuild_containers_sqlite(bind) -> None:
    bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
    bind.execute(sa.text("""CREATE TABLE containers_new (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        name VARCHAR(255) NOT NULL,
        virtual_machine_id VARCHAR(36),
        physical_device_id VARCHAR(36),
        runtime VARCHAR(100),
        runtime_version VARCHAR(100),
        purpose TEXT,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        FOREIGN KEY(virtual_machine_id) REFERENCES virtual_machines (id),
        FOREIGN KEY(physical_device_id) REFERENCES physical_devices (id)
    )"""))
    bind.execute(sa.text(
        "INSERT INTO containers_new (id, name, virtual_machine_id, physical_device_id, runtime, "
        "runtime_version, purpose, created_at, updated_at) "
        "SELECT id, name, virtual_machine_id, physical_device_id, runtime, runtime_version, purpose, "
        "created_at, updated_at FROM containers"
    ))
    bind.execute(sa.text("DROP TABLE containers"))
    bind.execute(sa.text("ALTER TABLE containers_new RENAME TO containers"))
    bind.execute(sa.text("CREATE INDEX ix_containers_virtual_machine_id ON containers (virtual_machine_id)"))
    bind.execute(sa.text("PRAGMA foreign_keys=ON"))


def _rebuild_information_system_sources_sqlite(bind) -> None:
    bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
    bind.execute(sa.text("""CREATE TABLE information_system_sources_new (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        information_system_id VARCHAR(36) NOT NULL,
        source_type VARCHAR(30) NOT NULL,
        physical_device_id VARCHAR(36),
        virtual_machine_id VARCHAR(36),
        container_id VARCHAR(36),
        purpose VARCHAR(500),
        role VARCHAR(255),
        external_interaction BOOLEAN NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        FOREIGN KEY(container_id) REFERENCES containers (id),
        FOREIGN KEY(virtual_machine_id) REFERENCES virtual_machines (id),
        FOREIGN KEY(physical_device_id) REFERENCES physical_devices (id),
        FOREIGN KEY(information_system_id) REFERENCES information_systems (id)
    )"""))
    bind.execute(sa.text(
        "INSERT INTO information_system_sources_new (id, information_system_id, source_type, "
        "physical_device_id, virtual_machine_id, container_id, purpose, role, external_interaction, "
        "created_at, updated_at) "
        "SELECT id, information_system_id, source_type, physical_device_id, virtual_machine_id, "
        "container_id, purpose, role, external_interaction, created_at, updated_at "
        "FROM information_system_sources"
    ))
    bind.execute(sa.text("DROP TABLE information_system_sources"))
    bind.execute(sa.text("ALTER TABLE information_system_sources_new RENAME TO information_system_sources"))
    bind.execute(sa.text("CREATE INDEX ix_information_system_sources_container_id ON information_system_sources (container_id)"))
    bind.execute(sa.text("CREATE INDEX ix_information_system_sources_virtual_machine_id ON information_system_sources (virtual_machine_id)"))
    bind.execute(sa.text("CREATE INDEX ix_information_system_sources_physical_device_id ON information_system_sources (physical_device_id)"))
    bind.execute(sa.text("CREATE INDEX ix_information_system_sources_information_system_id ON information_system_sources (information_system_id)"))
    bind.execute(sa.text("PRAGMA foreign_keys=ON"))


def upgrade() -> None:
    op.create_table(
        "ip_addresses",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_type", sa.String(length=50), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("ip_address", sa.String(length=64), nullable=False, index=True),
        sa.Column("prefix_length", sa.Integer(), nullable=True),
        sa.Column("purpose", sa.String(length=255), nullable=True),
        sa.Column("is_management", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_ip_addresses_owner", "ip_addresses", ["owner_type", "owner_id"])

    bind = op.get_bind()
    bind.execute(sa.text(
        "INSERT INTO ip_addresses (id, owner_type, owner_id, ip_address, prefix_length, purpose, "
        "is_management, created_at, updated_at) "
        "SELECT id, 'device_interface', interface_id, ip_address, prefix_length, purpose, "
        "is_management, created_at, updated_at FROM interface_ips"
    ))
    bind.execute(sa.text(
        "INSERT INTO ip_addresses (id, owner_type, owner_id, ip_address, prefix_length, purpose, "
        "is_management, created_at, updated_at) "
        "SELECT id, 'virtual_machine', virtual_machine_id, ip_address, prefix_length, purpose, "
        "is_management, created_at, updated_at FROM vm_ips"
    ))
    _migrate_source_ip_addresses(bind)

    op.drop_table("interface_ips")
    op.drop_table("vm_ips")

    if bind.dialect.name == "sqlite":
        _rebuild_containers_sqlite(bind)
        _rebuild_information_system_sources_sqlite(bind)
    else:
        op.drop_column("containers", "management_ip")
        op.drop_column("information_system_sources", "ip_address")


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade миграции d8e35a1c7f60 не поддерживается: таблицы interface_ips/vm_ips, столбцы "
        "containers.management_ip и information_system_sources.ip_address удаляются безвозвратно "
        "(см. docstring модуля) — откат одной лишь схемы создал бы ложное ощущение обратимости "
        "этой миграции."
    )
