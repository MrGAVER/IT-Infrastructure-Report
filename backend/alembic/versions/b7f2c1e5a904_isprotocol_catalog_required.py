"""information_system_protocols.protocol_catalog_id — обязателен; текстовые port/protocol удалены
из open_ports и information_system_protocols; legacy-таблицы связей ИС удалены

Revision ID: b7f2c1e5a904
Revises: 811f39a40ec7
Create Date: 2026-09-19 00:00:00.000000

Правка "переработка структуры БД" (согласовано с заказчиком — см. отчёт по анализу от 19.09.2026,
все пункты "Вопросы для согласования" подтверждены: удаление текстовых port/protocol, удаление
legacy-таблиц ИС без переноса их как отдельного шага, хранение IP не трогаем, шаблоны конструктора
не нужно чистить отдельно — пользовательских ещё не было).

Что делает эта миграция:

1. information_system_protocols.protocol_catalog_id становится обязательным — тот же приём
   бэкфилла по (port, protocol), что и в a1b7c9d3e502 для open_ports (там сама колонка уже NOT
   NULL с 2.72.0 — трогать её схему здесь не нужно, только убрать текстовые port/protocol, они
   больше не источник данных ни в каком случае). Строки information_system_protocols, для которых
   подходящую запись справочника подобрать/завести невозможно (protocol_catalog_id уже NULL И
   port тоже NULL — совсем свободный текст без порта, привязать было не к чему даже в принципе),
   удаляются: единственная альтернатива — заводить в protocol_port_catalogs записи с фиктивным
   номером порта, что портит сам справочник ради данных, которые всё равно нельзя было показать
   иначе как текстом.

2. Удаляются столбцы open_ports.port/.protocol и information_system_protocols.protocol/.port/
   .version/.direction — все значения теперь читаются join'ом к protocol_port_catalogs по
   protocol_catalog_id при каждом чтении (см. services/serialization.py:enrich_open_port(s),
   reporting.py:_open_port_label/_is_row_values) — правка записи справочника отражается на уже
   созданных портах/протоколах сразу, без их отдельного пересохранения. version/direction были
   помечены в models.py как отключённые от интерфейса ещё до этой правки — ни одна форма их не
   показывала и не заполняла.

3. Удаляются целиком таблицы information_system_devices/vms/containers/ips: форма ИС
   (InformationSystemFormModal.vue) уже не пишет в них новых данных — см. её прежнюю функцию
   migrateLegacyToSources(), переносившую их в information_system_sources при первом
   открытии/сохранении карточки через актуальный интерфейс; в registry.py они были помечены как
   "устарело, только чтение истории". Перед удалением таблиц эта миграция переносит в
   information_system_sources ту же логику одним разовым шагом для ВСЕХ ИС сразу (а не лениво, по
   одной карточке за раз, как раньше) — см. _migrate_legacy_is_links_to_sources. Для ИС, у
   которых unified-источники уже есть (хотя бы один), legacy-строки этой ИС пропускаются: источники
   полностью замещают legacy-таблицы для конкретной ИС, а не дополняют их (см. _is_source_links в
   reporting.py) — перенос ещё и legacy-строк для такой ИС создал бы дубли.

На SQLite — пересборка open_ports/information_system_protocols вручную с именованными
ограничениями (тот же приём, что и в a1b7c9d3e502/38e9b2624a53: batch_alter_table на SQLite не
гарантированно переносит существующие FK/индексы через reflection). На PostgreSQL — обычные
ALTER COLUMN/DROP COLUMN, они не теряют уже существующие ограничения.

Downgrade не поддерживается (RuntimeError) — столбцы port/protocol/version/direction и сами
таблицы information_system_devices/vms/containers/ips удаляются безвозвратно, откат одной лишь
схемы создал бы ложное ощущение обратимости (тот же принцип, что в 38e9b2624a53).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa

revision = "b7f2c1e5a904"
down_revision = "811f39a40ec7"
branch_labels = None
depends_on = None


def _migrate_legacy_is_links_to_sources(bind) -> None:
    """См. п.3 в docstring модуля."""
    now = datetime.now(timezone.utc)
    has_sources = {
        r[0] for r in bind.execute(
            sa.text("SELECT DISTINCT information_system_id FROM information_system_sources")
        ).fetchall()
    }

    def _insert_source(is_id, source_type, *, physical_device_id=None, virtual_machine_id=None,
                        container_id=None, ip_address=None, purpose=None, role=None,
                        external_interaction=0):
        bind.execute(
            sa.text(
                "INSERT INTO information_system_sources (id, information_system_id, source_type, "
                "physical_device_id, virtual_machine_id, container_id, ip_address, purpose, role, "
                "external_interaction, created_at, updated_at) VALUES (:id, :is_id, :st, :dev, :vm, "
                ":cont, :ip, :purpose, :role, :ext, :c, :c)"
            ),
            {
                "id": str(uuid.uuid4()), "is_id": is_id, "st": source_type,
                "dev": physical_device_id, "vm": virtual_machine_id, "cont": container_id,
                "ip": ip_address, "purpose": purpose, "role": role,
                "ext": 1 if external_interaction else 0, "c": now,
            },
        )

    for is_id, device_id, role in bind.execute(
        sa.text("SELECT information_system_id, physical_device_id, role FROM information_system_devices")
    ).fetchall():
        if is_id not in has_sources:
            _insert_source(is_id, "device", physical_device_id=device_id, role=role)
    for is_id, vm_id, role in bind.execute(
        sa.text("SELECT information_system_id, virtual_machine_id, role FROM information_system_vms")
    ).fetchall():
        if is_id not in has_sources:
            _insert_source(is_id, "vm", virtual_machine_id=vm_id, role=role)
    for is_id, container_id, role in bind.execute(
        sa.text("SELECT information_system_id, container_id, role FROM information_system_containers")
    ).fetchall():
        if is_id not in has_sources:
            _insert_source(is_id, "container", container_id=container_id, role=role)
    for is_id, ip_address, purpose, external in bind.execute(
        sa.text("SELECT information_system_id, ip_address, purpose, external_interaction FROM information_system_ips")
    ).fetchall():
        if is_id not in has_sources:
            _insert_source(is_id, "manual", ip_address=ip_address, purpose=purpose, external_interaction=external)


def _backfill_is_protocol_catalog_id(bind) -> None:
    """См. п.1 в docstring модуля. Тот же приём, что _backfill_protocol_catalog_id в
    a1b7c9d3e502, плюс удаление строк, которые подобрать/завести в справочник невозможно."""
    now = datetime.now(timezone.utc)
    rows = bind.execute(
        sa.text("SELECT id, port, protocol FROM information_system_protocols WHERE protocol_catalog_id IS NULL")
    ).fetchall()
    for row_id, port, protocol in rows:
        if port is None or not protocol:
            bind.execute(sa.text("DELETE FROM information_system_protocols WHERE id=:i"), {"i": row_id})
            continue
        catalog_id = bind.execute(
            sa.text("SELECT id FROM protocol_port_catalogs WHERE port=:p AND protocol_type=:t"),
            {"p": port, "t": protocol},
        ).scalar()
        if not catalog_id:
            catalog_id = str(uuid.uuid4())
            bind.execute(
                sa.text(
                    "INSERT INTO protocol_port_catalogs (id, port, protocol_type, created_at, updated_at) "
                    "VALUES (:id, :p, :t, :c, :c)"
                ),
                {"id": catalog_id, "p": port, "t": protocol, "c": now},
            )
        bind.execute(
            sa.text("UPDATE information_system_protocols SET protocol_catalog_id=:c WHERE id=:i"),
            {"c": catalog_id, "i": row_id},
        )


def _rebuild_open_ports_sqlite(bind) -> None:
    bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
    bind.execute(sa.text("""CREATE TABLE open_ports_new (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        owner_type VARCHAR(50) NOT NULL,
        owner_id VARCHAR(36) NOT NULL,
        transport_protocol VARCHAR(10) NOT NULL DEFAULT 'TCP',
        protocol_catalog_id VARCHAR(36) NOT NULL,
        ip_address VARCHAR(64),
        description TEXT,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        CONSTRAINT fk_open_ports_protocol_catalog FOREIGN KEY(protocol_catalog_id) REFERENCES protocol_port_catalogs (id)
    )"""))
    bind.execute(sa.text(
        "INSERT INTO open_ports_new (id, owner_type, owner_id, transport_protocol, protocol_catalog_id, "
        "ip_address, description, created_at, updated_at) "
        "SELECT id, owner_type, owner_id, transport_protocol, protocol_catalog_id, ip_address, description, "
        "created_at, updated_at FROM open_ports"
    ))
    bind.execute(sa.text("DROP TABLE open_ports"))
    bind.execute(sa.text("ALTER TABLE open_ports_new RENAME TO open_ports"))
    bind.execute(sa.text("CREATE INDEX ix_open_ports_protocol_catalog_id ON open_ports (protocol_catalog_id)"))
    bind.execute(sa.text("PRAGMA foreign_keys=ON"))


def _rebuild_is_protocols_sqlite(bind) -> None:
    bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
    bind.execute(sa.text("""CREATE TABLE information_system_protocols_new (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        information_system_id VARCHAR(36) NOT NULL,
        protocol_catalog_id VARCHAR(36) NOT NULL,
        description TEXT,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        CONSTRAINT fk_is_protocols_protocol_catalog FOREIGN KEY(protocol_catalog_id) REFERENCES protocol_port_catalogs (id),
        FOREIGN KEY(information_system_id) REFERENCES information_systems (id)
    )"""))
    bind.execute(sa.text(
        "INSERT INTO information_system_protocols_new (id, information_system_id, protocol_catalog_id, "
        "description, created_at, updated_at) "
        "SELECT id, information_system_id, protocol_catalog_id, description, created_at, updated_at "
        "FROM information_system_protocols"
    ))
    bind.execute(sa.text("DROP TABLE information_system_protocols"))
    bind.execute(sa.text("ALTER TABLE information_system_protocols_new RENAME TO information_system_protocols"))
    bind.execute(sa.text(
        "CREATE INDEX ix_information_system_protocols_information_system_id "
        "ON information_system_protocols (information_system_id)"
    ))
    bind.execute(sa.text(
        "CREATE INDEX ix_information_system_protocols_protocol_catalog_id "
        "ON information_system_protocols (protocol_catalog_id)"
    ))
    bind.execute(sa.text("PRAGMA foreign_keys=ON"))


def upgrade() -> None:
    bind = op.get_bind()
    _migrate_legacy_is_links_to_sources(bind)
    _backfill_is_protocol_catalog_id(bind)

    if bind.dialect.name == "sqlite":
        _rebuild_open_ports_sqlite(bind)
        _rebuild_is_protocols_sqlite(bind)
    else:
        op.drop_column("open_ports", "port")
        op.drop_column("open_ports", "protocol")
        op.alter_column("information_system_protocols", "protocol_catalog_id",
                         existing_type=sa.String(length=36), nullable=False)
        op.drop_column("information_system_protocols", "protocol")
        op.drop_column("information_system_protocols", "port")
        op.drop_column("information_system_protocols", "version")
        op.drop_column("information_system_protocols", "direction")

    op.drop_table("information_system_devices")
    op.drop_table("information_system_vms")
    op.drop_table("information_system_containers")
    op.drop_table("information_system_ips")


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade миграции b7f2c1e5a904 не поддерживается: столбцы open_ports.port/.protocol, "
        "information_system_protocols.protocol/.port/.version/.direction и таблицы "
        "information_system_devices/vms/containers/ips удаляются безвозвратно (см. docstring "
        "модуля) — откат одной лишь схемы создал бы ложное ощущение обратимости этой миграции."
    )
