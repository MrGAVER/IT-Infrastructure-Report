"""Add indexes on IP address search/filter columns

Revision ID: a1c7e5f3b208
Revises: f6b3d8e2a941
Create Date: 2026-08-09 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "a1c7e5f3b208"
down_revision = "f6b3d8e2a941"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_interface_ips_ip_address", "interface_ips", ["ip_address"])
    op.create_index("ix_vm_ips_ip_address", "vm_ips", ["ip_address"])


def downgrade() -> None:
    op.drop_index("ix_vm_ips_ip_address", table_name="vm_ips")
    op.drop_index("ix_interface_ips_ip_address", table_name="interface_ips")
