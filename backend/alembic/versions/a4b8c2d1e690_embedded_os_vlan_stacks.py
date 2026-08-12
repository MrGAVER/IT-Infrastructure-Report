"""embedded OS, VLAN assignments and device stacks

Revision ID: a4b8c2d1e690
Revises: f2a9c7d1e530
"""
from alembic import op
import sqlalchemy as sa

revision = "a4b8c2d1e690"
down_revision = "8c5d1f7a2b40"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "embedded_operating_systems",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(255), nullable=True),
        sa.Column("vendor", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("name", "version", name="uq_embedded_os_name_version"),
    )
    op.create_table(
        "device_type_vlans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("device_type_id", sa.String(36), nullable=False),
        sa.Column("vlan_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["device_type_id"], ["device_types.id"]),
        sa.ForeignKeyConstraint(["vlan_id"], ["vlans.id"]),
        sa.UniqueConstraint("device_type_id", "vlan_id", name="uq_device_type_vlan"),
    )
    op.create_index("ix_device_type_vlans_device_type_id", "device_type_vlans", ["device_type_id"])
    op.create_index("ix_device_type_vlans_vlan_id", "device_type_vlans", ["vlan_id"])
    op.create_table(
        "physical_device_vlans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("physical_device_id", sa.String(36), nullable=False),
        sa.Column("vlan_id", sa.String(36), nullable=False),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("prefix_length", sa.Integer(), nullable=True),
        sa.Column("is_management", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["physical_device_id"], ["physical_devices.id"]),
        sa.ForeignKeyConstraint(["vlan_id"], ["vlans.id"]),
        sa.UniqueConstraint("physical_device_id", "vlan_id", name="uq_physical_device_vlan"),
    )
    op.create_index("ix_physical_device_vlans_device_id", "physical_device_vlans", ["physical_device_id"])
    op.create_index("ix_physical_device_vlans_vlan_id", "physical_device_vlans", ["vlan_id"])
    op.create_table(
        "device_stacks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table("physical_devices") as batch:
        batch.add_column(sa.Column("embedded_os_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("stack_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_physical_devices_embedded_os", "embedded_operating_systems", ["embedded_os_id"], ["id"])
        batch.create_foreign_key("fk_physical_devices_stack", "device_stacks", ["stack_id"], ["id"])
    op.create_index("ix_physical_devices_embedded_os_id", "physical_devices", ["embedded_os_id"])
    op.create_index("ix_physical_devices_stack_id", "physical_devices", ["stack_id"])


def downgrade():
    with op.batch_alter_table("physical_devices") as batch:
        batch.drop_constraint("fk_physical_devices_stack", type_="foreignkey")
        batch.drop_constraint("fk_physical_devices_embedded_os", type_="foreignkey")
        batch.drop_column("stack_id")
        batch.drop_column("embedded_os_id")
    op.drop_index("ix_physical_devices_stack_id", table_name="physical_devices")
    op.drop_index("ix_physical_devices_embedded_os_id", table_name="physical_devices")
    op.drop_table("device_stacks")
    op.drop_index("ix_physical_device_vlans_vlan_id", table_name="physical_device_vlans")
    op.drop_index("ix_physical_device_vlans_device_id", table_name="physical_device_vlans")
    op.drop_table("physical_device_vlans")
    op.drop_index("ix_device_type_vlans_vlan_id", table_name="device_type_vlans")
    op.drop_index("ix_device_type_vlans_device_type_id", table_name="device_type_vlans")
    op.drop_table("device_type_vlans")
    op.drop_table("embedded_operating_systems")
