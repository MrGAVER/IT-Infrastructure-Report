"""Device stacks (пункт 5 правки "создание физического устройства")

Revision ID: b3f6e1a9c704
Revises: a1b7c9d3e502
"""
from alembic import op
import sqlalchemy as sa

revision = "b3f6e1a9c704"
down_revision = "a1b7c9d3e502"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "device_stacks" not in tables:
        op.create_table(
            "device_stacks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False, unique=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if "device_stack_members" not in tables:
        op.create_table(
            "device_stack_members",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("stack_id", sa.String(36), nullable=False),
            sa.Column("physical_device_id", sa.String(36), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["stack_id"], ["device_stacks.id"]),
            sa.ForeignKeyConstraint(["physical_device_id"], ["physical_devices.id"]),
            # Устройство может состоять максимум в ОДНОМ стеке одновременно (в отличие от
            # vlan_domain_devices, где участие в нескольких доменов — обычный случай) — поэтому
            # unique именно на physical_device_id одной колонкой, не на паре (stack_id, device_id).
            sa.UniqueConstraint("physical_device_id", name="uq_device_stack_member_device"),
        )
        op.create_index("ix_device_stack_members_stack_id", "device_stack_members", ["stack_id"])
        op.create_index("ix_device_stack_members_physical_device_id", "device_stack_members", ["physical_device_id"])


def downgrade():
    op.drop_table("device_stack_members")
    op.drop_table("device_stacks")
