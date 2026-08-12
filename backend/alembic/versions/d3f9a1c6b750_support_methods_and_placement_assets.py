"""Support methods catalog and IS placement assets catalog

Revision ID: d3f9a1c6b750
Revises: c9a4e7d2f610
Create Date: 2026-08-06 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d3f9a1c6b750"
down_revision = "c9a4e7d2f610"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "support_methods",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
    )

    op.create_table(
        "placement_assets",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
    )

    op.create_table(
        "is_placement_assets",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("information_system_id", sa.String(length=36), sa.ForeignKey("information_systems.id"), nullable=False),
        sa.Column("placement_asset_id", sa.String(length=36), sa.ForeignKey("placement_assets.id"), nullable=False),
        sa.UniqueConstraint("information_system_id", "placement_asset_id", name="uq_is_placement_asset"),
    )
    op.create_index("ix_is_placement_assets_information_system_id", "is_placement_assets", ["information_system_id"])
    op.create_index("ix_is_placement_assets_placement_asset_id", "is_placement_assets", ["placement_asset_id"])

    with op.batch_alter_table("information_systems") as batch:
        batch.add_column(sa.Column("support_method_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_information_systems_support_method", "support_methods", ["support_method_id"], ["id"])
        batch.create_index("ix_information_systems_support_method_id", ["support_method_id"])

    # Migrate the free-text values that already exist into the new catalog.
    import uuid
    existing = bind.execute(sa.text("SELECT DISTINCT support_method FROM information_systems WHERE support_method IS NOT NULL AND TRIM(support_method) != ''")).fetchall()
    now = sa.func.now()
    for (value,) in existing:
        new_id = str(uuid.uuid4())
        bind.execute(
            sa.text("INSERT INTO support_methods (id, name, created_at, updated_at) VALUES (:id, :name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
            {"id": new_id, "name": value},
        )
        bind.execute(
            sa.text("UPDATE information_systems SET support_method_id = :sid WHERE support_method = :name"),
            {"sid": new_id, "name": value},
        )

    with op.batch_alter_table("information_systems") as batch:
        batch.drop_column("support_method")


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("information_systems") as batch:
        batch.add_column(sa.Column("support_method", sa.String(length=500), nullable=True))
    bind.execute(sa.text(
        "UPDATE information_systems SET support_method = ("
        "SELECT name FROM support_methods WHERE support_methods.id = information_systems.support_method_id)"
    ))
    with op.batch_alter_table("information_systems") as batch:
        batch.drop_index("ix_information_systems_support_method_id")
        batch.drop_constraint("fk_information_systems_support_method", type_="foreignkey")
        batch.drop_column("support_method_id")
    op.drop_index("ix_is_placement_assets_placement_asset_id", table_name="is_placement_assets")
    op.drop_index("ix_is_placement_assets_information_system_id", table_name="is_placement_assets")
    op.drop_table("is_placement_assets")
    op.drop_table("placement_assets")
    op.drop_table("support_methods")
