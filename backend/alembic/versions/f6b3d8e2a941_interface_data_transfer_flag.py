"""Add data-transfer flag to device interfaces

Revision ID: f6b3d8e2a941
Revises: e7a2c9f4d813
Create Date: 2026-08-08 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f6b3d8e2a941"
down_revision = "e7a2c9f4d813"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_interfaces",
        sa.Column("is_data_transfer", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("device_interfaces", "is_data_transfer")
