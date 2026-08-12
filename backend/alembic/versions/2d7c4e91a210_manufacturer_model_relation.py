"""add unique manufacturer/model relation

Revision ID: 2d7c4e91a210
Revises: f1c3ec81b502
"""
from alembic import op
import sqlalchemy as sa

revision = "2d7c4e91a210"
down_revision = "f1c3ec81b502"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # Remove exact duplicate model rows for the same manufacturer before adding the constraint.
    rows = bind.execute(sa.text("SELECT manufacturer_id, model, MIN(id) AS keep_id FROM device_models GROUP BY manufacturer_id, model HAVING COUNT(*) > 1")).fetchall()
    for manufacturer_id, model, keep_id in rows:
        bind.execute(sa.text("DELETE FROM device_models WHERE manufacturer_id=:m AND model=:model AND id<>:keep"), {"m": manufacturer_id, "model": model, "keep": keep_id})
    with op.batch_alter_table("device_models") as batch:
        batch.create_unique_constraint("uq_device_model_manufacturer_model", ["manufacturer_id", "model"])


def downgrade():
    with op.batch_alter_table("device_models") as batch:
        batch.drop_constraint("uq_device_model_manufacturer_model", type_="unique")
