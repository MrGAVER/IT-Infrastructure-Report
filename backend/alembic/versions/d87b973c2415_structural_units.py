"""Structural units catalog; link buildings to their structural unit

Revision ID: d87b973c2415
Revises: b44cd42f9fa0
Create Date: 2026-08-21 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d87b973c2415"
down_revision = "b44cd42f9fa0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "structural_units",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=False, unique=True),
        sa.Column("parent_id", sa.String(length=36), sa.ForeignKey("structural_units.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
    )
    op.create_index("ix_structural_units_parent_id", "structural_units", ["parent_id"])

    with op.batch_alter_table("buildings") as batch:
        batch.add_column(sa.Column("structural_unit_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_buildings_structural_unit", "structural_units", ["structural_unit_id"], ["id"])
        batch.create_index("ix_buildings_structural_unit_id", ["structural_unit_id"])


def downgrade() -> None:
    with op.batch_alter_table("buildings") as batch:
        batch.drop_index("ix_buildings_structural_unit_id")
        batch.drop_constraint("fk_buildings_structural_unit", type_="foreignkey")
        batch.drop_column("structural_unit_id")
    op.drop_index("ix_structural_units_parent_id", table_name="structural_units")
    op.drop_table("structural_units")
