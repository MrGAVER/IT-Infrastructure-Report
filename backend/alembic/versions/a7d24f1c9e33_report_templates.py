"""add report_templates table (custom report builder)

Revision ID: a7d24f1c9e33
Revises: b2f6a9c1d704
"""
import sqlalchemy as sa
from alembic import op

revision = 'a7d24f1c9e33'
down_revision = 'b2f6a9c1d704'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'report_templates',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False, unique=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('format', sa.String(length=10), nullable=False, server_default='xlsx'),
        sa.Column('config', sa.Text(), nullable=False, server_default='{}'),
    )


def downgrade():
    op.drop_table('report_templates')
