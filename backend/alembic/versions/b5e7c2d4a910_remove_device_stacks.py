"""remove obsolete device stack implementation

Revision ID: b5e7c2d4a910
Revises: a4b8c2d1e690
"""
from alembic import op
import sqlalchemy as sa

revision = "b5e7c2d4a910"
down_revision = "a4b8c2d1e690"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "physical_devices" in tables:
        indexes = {i["name"] for i in inspector.get_indexes("physical_devices")}
        if "ix_physical_devices_stack_id" in indexes:
            op.drop_index("ix_physical_devices_stack_id", table_name="physical_devices")
        cols = {c["name"] for c in inspector.get_columns("physical_devices")}
        if "stack_id" in cols:
            with op.batch_alter_table("physical_devices") as batch:
                batch.drop_column("stack_id")
    if "device_stacks" in tables:
        op.drop_table("device_stacks")

def downgrade():
    op.create_table(
        "device_stacks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    with op.batch_alter_table("physical_devices") as batch:
        batch.add_column(sa.Column("stack_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_physical_devices_stack", "device_stacks", ["stack_id"], ["id"])
        batch.create_index("ix_physical_devices_stack_id", ["stack_id"])
