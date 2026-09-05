"""Auth: users, sessions, settings toggle"""
from alembic import op
import sqlalchemy as sa

revision = '0fcebbb67ac0'
down_revision = '4ea6658f69bf'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        'users',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('username', sa.String(length=150), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('role', sa.String(length=20), nullable=False, server_default='viewer'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('failed_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('locked_until', sa.DateTime(), nullable=True),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('username', name='uq_users_username'),
    )
    op.create_table(
        'auth_sessions',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.String(length=36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('user_agent', sa.String(length=255), nullable=True),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.UniqueConstraint('token_hash', name='uq_auth_sessions_token_hash'),
    )
    op.create_index('ix_auth_sessions_user_id', 'auth_sessions', ['user_id'])
    op.create_index('ix_auth_sessions_expires_at', 'auth_sessions', ['expires_at'])
    op.create_table(
        'auth_settings',
        sa.Column('id', sa.String(length=20), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    # Единственная строка-синглтон заводится лениво при первом запросе (см.
    # services/auth.get_or_create_auth_settings) и дополнительно на старте приложения
    # (main.py:seed_catalogs_on_startup) — здесь её не создаём, чтобы не дублировать эту логику
    # в двух местах с разным риском рассинхронизации default-значения enabled.


def downgrade():
    op.drop_table('auth_settings')
    op.drop_index('ix_auth_sessions_expires_at', table_name='auth_sessions')
    op.drop_index('ix_auth_sessions_user_id', table_name='auth_sessions')
    op.drop_table('auth_sessions')
    op.drop_table('users')
