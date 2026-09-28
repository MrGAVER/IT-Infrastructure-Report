"""information_system_sources: physical_device_id/virtual_machine_id/container_id объединены
в owner_id (source_type играет роль owner_type)

Revision ID: 944bd490d967
Revises: d8e35a1c7f60
Create Date: 2026-09-27 00:00:00.000000

Правка "переработка структуры БД", последний (п.5) из 9 вопросов отчёта по анализу БД,
согласовано с заказчиком. У information_system_sources было три nullable FK-колонки
(physical_device_id/virtual_machine_id/container_id), у любой строки реально заполнена от силы
одна — какая именно, всегда однозначно определяется уже существующим source_type
('device'/'vm'/'container'/'manual'). Тот же случай "условно-обязательное поле, размазанное по
нескольким колонкам", что уже решён для OpenPort (a1b7c9d3e502), DeployedSoftware (c4a91e6f2b83)
и IPAddress (d8e35a1c7f60) через owner_type/owner_id — здесь роль owner_type играет само поле
source_type, отдельная колонка под него была бы чистым дублированием.

Ключевое отличие от тех трёх миграций (обязательно к прочтению перед изменением этой миграции или
кода, который её использует): там полиморфный владелец ВЛАДЕЕТ дочерней записью (порт/ПО/IP
принадлежат устройству и должны удаляться вместе с ним, см. _POLYMORPHIC_OWNER_CLEANUP в
services/crud.py) — здесь семантика ОБРАТНАЯ: ИС лишь ССЫЛАЕТСЯ на оборудование как на место
размещения. Три настоящих FK обеспечивали защиту целостности на уровне БД (нельзя удалить
устройство/ВМ/контейнер, пока на него ссылается ИС) — эта защита важна для точности регуляторного
отчёта. owner_id НЕ является настоящим FK (одна колонка не может физически ссылаться на три разные
таблицы), поэтому эта миграция убирает защиту на уровне БД, но защита в этом же коммите воссоздана
вручную в services/crud.py:delete_resource() (см. assert_deletable и services/integrity.py) — решение
заказчика по итогам рассмотрения архитектурной развилки, НЕ откладывать на потом.

На SQLite — пересборка information_system_sources вручную (тот же приём, что и в d8e35a1c7f60/
b7f2c1e5a904: batch_alter_table на SQLite не гарантированно переносит существующие FK/индексы через
reflection). На PostgreSQL — обычный ADD COLUMN + backfill + DROP COLUMN на все три колонки:
однозначный (single-column) FK-констрейнт удаляется автоматически вместе с колонкой, на которой он
определён, CASCADE для этого не требуется (CASCADE нужен только для объектов, ссылающихся НА эту
таблицу/колонку извне, а не для FK, определённых на самой удаляемой колонке).

Downgrade не поддерживается (RuntimeError) — тот же принцип, что и в остальных миграциях этой
серии: owner_id разложить обратно на три колонки формально можно (source_type однозначно указывает
целевую колонку), но откат одной лишь схемы вернул бы настоящие FK без каких-либо гарантий, что
данные, накопленные после этой миграции, всё ещё им удовлетворяют — ложное ощущение обратимости.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "944bd490d967"
down_revision = "d8e35a1c7f60"
branch_labels = None
depends_on = None


def _rebuild_information_system_sources_sqlite(bind) -> None:
    bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
    bind.execute(sa.text("""CREATE TABLE information_system_sources_new (
        id VARCHAR(36) NOT NULL PRIMARY KEY,
        information_system_id VARCHAR(36) NOT NULL,
        source_type VARCHAR(30) NOT NULL,
        owner_id VARCHAR(36),
        purpose VARCHAR(500),
        role VARCHAR(255),
        external_interaction BOOLEAN NOT NULL,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL,
        FOREIGN KEY(information_system_id) REFERENCES information_systems (id)
    )"""))
    bind.execute(sa.text(
        "INSERT INTO information_system_sources_new (id, information_system_id, source_type, "
        "owner_id, purpose, role, external_interaction, created_at, updated_at) "
        "SELECT id, information_system_id, source_type, "
        "COALESCE(physical_device_id, virtual_machine_id, container_id), "
        "purpose, role, external_interaction, created_at, updated_at "
        "FROM information_system_sources"
    ))
    bind.execute(sa.text("DROP TABLE information_system_sources"))
    bind.execute(sa.text("ALTER TABLE information_system_sources_new RENAME TO information_system_sources"))
    bind.execute(sa.text("CREATE INDEX ix_information_system_sources_information_system_id ON information_system_sources (information_system_id)"))
    bind.execute(sa.text("CREATE INDEX ix_information_system_sources_owner_id ON information_system_sources (owner_id)"))
    bind.execute(sa.text("PRAGMA foreign_keys=ON"))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _rebuild_information_system_sources_sqlite(bind)
    else:
        op.add_column("information_system_sources", sa.Column("owner_id", sa.String(length=36), nullable=True))
        op.create_index("ix_information_system_sources_owner_id", "information_system_sources", ["owner_id"])
        bind.execute(sa.text(
            "UPDATE information_system_sources SET owner_id = COALESCE(physical_device_id, virtual_machine_id, container_id)"
        ))
        op.drop_column("information_system_sources", "physical_device_id")
        op.drop_column("information_system_sources", "virtual_machine_id")
        op.drop_column("information_system_sources", "container_id")


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade миграции 944bd490d967 не поддерживается: physical_device_id/virtual_machine_id/"
        "container_id заменены единой owner_id безвозвратно (см. docstring модуля) — откат одной "
        "лишь схемы создал бы ложное ощущение обратимости этой миграции."
    )
