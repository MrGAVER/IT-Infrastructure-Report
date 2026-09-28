"""device_software/vm_software объединены в deployed_software (owner_type/owner_id)

Revision ID: c4a91e6f2b83
Revises: b7f2c1e5a904
Create Date: 2026-09-20 00:00:00.000000

Правка "переработка структуры БД", вопрос 2 отчёта по анализу БД (согласовано с заказчиком: "да,
DeviceSoftware/VMSoftware можно объединять — в обеих может быть одинаковое ПО").

device_software (владелец — физическое устройство) и vm_software (владелец — виртуальная машина)
— две отдельные таблицы с идентичным по смыслу содержимым: «на этом владельце развёрнут вот такой
программный актив из справочника software_assets, вот в такой версии» (Лист 4 отчёта, столбец
«Какие программные активы развёрнуты: 1С, веб-сервер, файловый и т. п.»). Отличались только именем
FK-колонки владельца — тот же случай, что уже решён для OpenPort (миграция a1b7c9d3e502) через
owner_type/owner_id.

В отличие от миграций b7f2c1e5a904/a1b7c9d3e502, здесь не нужна ручная пересборка таблицы на
SQLite: единая deployed_software создаётся заново (CREATE TABLE, а не ALTER существующей), данные
переносятся INSERT ... SELECT, старые таблицы удаляются целиком — все три операции одинаковы на
SQLite и на PostgreSQL, batch_alter_table не требуется.

Downgrade не поддерживается (RuntimeError) — тот же принцип, что в 38e9b2624a53/b7f2c1e5a904:
таблицы device_software/vm_software удаляются безвозвратно, откат одной лишь схемы создал бы
ложное ощущение обратимости.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c4a91e6f2b83"
down_revision = "b7f2c1e5a904"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "deployed_software",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("owner_type", sa.String(length=50), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("software_asset_id", sa.String(length=36), sa.ForeignKey("software_assets.id"), nullable=False, index=True),
        sa.Column("version", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_deployed_software_owner", "deployed_software", ["owner_type", "owner_id"])

    bind = op.get_bind()
    bind.execute(sa.text(
        "INSERT INTO deployed_software (id, owner_type, owner_id, software_asset_id, version, created_at, updated_at) "
        "SELECT id, 'physical_device', physical_device_id, software_asset_id, version, created_at, updated_at FROM device_software"
    ))
    bind.execute(sa.text(
        "INSERT INTO deployed_software (id, owner_type, owner_id, software_asset_id, version, created_at, updated_at) "
        "SELECT id, 'virtual_machine', virtual_machine_id, software_asset_id, version, created_at, updated_at FROM vm_software"
    ))

    op.drop_table("device_software")
    op.drop_table("vm_software")


def downgrade() -> None:
    raise RuntimeError(
        "Downgrade миграции c4a91e6f2b83 не поддерживается: таблицы device_software/vm_software "
        "удаляются безвозвратно (см. docstring модуля) — откат одной лишь схемы создал бы ложное "
        "ощущение обратимости этой миграции."
    )
