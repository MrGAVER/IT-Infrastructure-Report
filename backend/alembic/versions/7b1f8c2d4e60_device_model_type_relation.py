"""add device type relation to device models

Revision ID: 7b1f8c2d4e60
Revises: 2d7c4e91a210
"""
from alembic import op
import sqlalchemy as sa

revision = "7b1f8c2d4e60"
down_revision = "2d7c4e91a210"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    with op.batch_alter_table("device_models") as batch:
        batch.add_column(sa.Column("device_type_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_device_models_device_type", "device_types", ["device_type_id"], ["id"])

    # Try to infer the type for models already used by physical devices.
    # If a model was used with exactly one device type, assign that type.
    rows = bind.execute(sa.text("""
        SELECT model_id, MIN(device_type_id) AS device_type_id
        FROM physical_devices
        WHERE model_id IS NOT NULL AND device_type_id IS NOT NULL
        GROUP BY model_id
        HAVING COUNT(DISTINCT device_type_id) = 1
    """)).fetchall()
    for model_id, device_type_id in rows:
        bind.execute(sa.text("UPDATE device_models SET device_type_id=:t WHERE id=:m AND device_type_id IS NULL"),
                     {"t": device_type_id, "m": model_id})

    # Models without enough historical information remain NULL and can be
    # completed from the Models directory before they are used for new devices.
    with op.batch_alter_table("device_models") as batch:
        batch.drop_constraint("uq_device_model_manufacturer_model", type_="unique")
        batch.create_unique_constraint("uq_device_model_manufacturer_type_model",
                                       ["manufacturer_id", "device_type_id", "model"])


def downgrade():
    with op.batch_alter_table("device_models") as batch:
        batch.drop_constraint("uq_device_model_manufacturer_type_model", type_="unique")
        batch.create_unique_constraint("uq_device_model_manufacturer_model", ["manufacturer_id", "model"])
        batch.drop_constraint("fk_device_models_device_type", type_="foreignkey")
        batch.drop_column("device_type_id")
