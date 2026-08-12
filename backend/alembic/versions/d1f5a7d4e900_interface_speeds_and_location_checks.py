"""interface speeds and location checks

Revision ID: d1f5a7d4e900
Revises: 9e31b7c4a820
Create Date: 2026-07-27 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "d1f5a7d4e900"
down_revision = "9e31b7c4a820"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "interface_speeds",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("interface_speeds")
