"""Add management flag to device interfaces.

Revision ID: 9e31b7c4a820
Revises: c4e8a7d91b20
"""
from alembic import op
import sqlalchemy as sa

revision = "9e31b7c4a820"
down_revision = "c4e8a7d91b20"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column(
        "device_interfaces",
        sa.Column("is_management", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

def downgrade():
    op.drop_column("device_interfaces", "is_management")
