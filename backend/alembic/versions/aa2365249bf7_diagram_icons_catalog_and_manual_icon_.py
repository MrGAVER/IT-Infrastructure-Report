"""diagram icons catalog and manual icon overrides

Revision ID: aa2365249bf7
Revises: 38e9b2624a53
Create Date: 2026-09-08 00:00:02.000000

Миграция 3/4 фичи "Диаграмма топологии сети" (ТЗ, раздел 5, п.3). Полностью аддитивна: новая
таблица diagram_icons (каталог пользовательских SVG-иконок, раздел 4.3 ТЗ) + nullable
diagram_icon_id на device_models и physical_devices — ручное переопределение автогенерируемой
иконки узла (PhysicalDevice.diagram_icon_id побеждает DeviceModel.diagram_icon_id, который в
свою очередь побеждает автогенерацию по DeviceCategory — см. services/diagram_icons.py).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "aa2365249bf7"
down_revision = "38e9b2624a53"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "diagram_icons",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("svg_markup", sa.Text(), nullable=False),
    )

    with op.batch_alter_table("device_models") as batch:
        batch.add_column(sa.Column("diagram_icon_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_device_models_diagram_icon", "diagram_icons", ["diagram_icon_id"], ["id"])
    op.create_index("ix_device_models_diagram_icon_id", "device_models", ["diagram_icon_id"])

    with op.batch_alter_table("physical_devices") as batch:
        batch.add_column(sa.Column("diagram_icon_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_physical_devices_diagram_icon", "diagram_icons", ["diagram_icon_id"], ["id"])
    op.create_index("ix_physical_devices_diagram_icon_id", "physical_devices", ["diagram_icon_id"])


def downgrade() -> None:
    op.drop_index("ix_physical_devices_diagram_icon_id", table_name="physical_devices")
    with op.batch_alter_table("physical_devices") as batch:
        batch.drop_constraint("fk_physical_devices_diagram_icon", type_="foreignkey")
        batch.drop_column("diagram_icon_id")

    op.drop_index("ix_device_models_diagram_icon_id", table_name="device_models")
    with op.batch_alter_table("device_models") as batch:
        batch.drop_constraint("fk_device_models_diagram_icon", type_="foreignkey")
        batch.drop_column("diagram_icon_id")

    op.drop_table("diagram_icons")
