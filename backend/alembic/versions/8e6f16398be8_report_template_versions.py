"""report_template_versions table (report builder version history)

Revision ID: 8e6f16398be8
Revises: 83c56c56b52d

Хранит снимки ReportTemplate, сделанные перед каждым обновлением/восстановлением — до этого
PUT /report-templates/{id} перезаписывал config без возможности отката к предыдущей версии.
"""
from alembic import op
import sqlalchemy as sa

revision = '8e6f16398be8'
down_revision = '83c56c56b52d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'report_template_versions',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('report_template_id', sa.String(length=36), sa.ForeignKey('report_templates.id'), nullable=False),
        sa.Column('version_number', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('format', sa.String(length=10), nullable=False),
        sa.Column('config', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_report_template_versions_report_template_id', 'report_template_versions', ['report_template_id'])


def downgrade():
    op.drop_index('ix_report_template_versions_report_template_id', table_name='report_template_versions')
    op.drop_table('report_template_versions')
