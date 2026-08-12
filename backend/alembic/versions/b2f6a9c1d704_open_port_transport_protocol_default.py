"""Default transport_protocol to TCP on open_ports

Revision ID: b2f6a9c1d704
Revises: a1c7e5f3b208
Create Date: 2026-08-12 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b2f6a9c1d704"
down_revision = "a1c7e5f3b208"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backfill any rows that predate the default (shouldn't normally exist since the column was
    # NOT NULL, but a couple of client bugs let empty/invalid inserts slip through before this fix).
    op.execute("UPDATE open_ports SET transport_protocol = 'TCP' WHERE transport_protocol IS NULL OR transport_protocol = ''")
    with op.batch_alter_table("open_ports") as batch_op:
        batch_op.alter_column(
            "transport_protocol",
            existing_type=sa.String(length=10),
            nullable=False,
            server_default="TCP",
        )


def downgrade() -> None:
    with op.batch_alter_table("open_ports") as batch_op:
        batch_op.alter_column(
            "transport_protocol",
            existing_type=sa.String(length=10),
            nullable=False,
            server_default=None,
        )
