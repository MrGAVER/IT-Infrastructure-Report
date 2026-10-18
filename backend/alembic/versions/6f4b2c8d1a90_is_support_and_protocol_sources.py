"""IS support catalog, protocol ports and source-linked IPs"""
from alembic import op
import sqlalchemy as sa

revision = '6f4b2c8d1a90'
down_revision = '3a7c1e5d9b20'
branch_labels = None
depends_on = None

def _repoint_support_organization_fk(bind, target_table):
    """PostgreSQL: переставить внешний ключ information_systems.support_organization_id на target_table.
    Имя прежнего ключа не фиксируем (оно авто-сгенерировано) — находим через инспектор."""
    for fk in sa.inspect(bind).get_foreign_keys('information_systems'):
        if fk['constrained_columns'] == ['support_organization_id']:
            op.drop_constraint(fk['name'], 'information_systems', type_='foreignkey')
    op.create_foreign_key('information_systems_support_organization_id_fkey', 'information_systems', target_table, ['support_organization_id'], ['id'])


def upgrade():
    bind = op.get_bind()
    op.create_table(
        'support_organizations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(500), nullable=False),
        sa.Column('short_name', sa.String(200)),
        sa.Column('description', sa.Text),
        sa.Column('created_at', sa.DateTime, nullable=True),
        sa.Column('updated_at', sa.DateTime, nullable=True),
        sa.UniqueConstraint('name', name='uq_support_organizations_name'),
    )
    # Existing support organization values historically pointed at organizations.
    bind.execute(sa.text('INSERT INTO support_organizations (id,name,short_name,description,created_at,updated_at) SELECT id,name,short_name,description,created_at,updated_at FROM organizations'))

    if bind.dialect.name == 'postgresql':
        # PostgreSQL меняет внешний ключ на месте: пересборка таблицы (ниже, для SQLite) не нужна.
        _repoint_support_organization_fk(bind, 'support_organizations')
        op.execute('CREATE INDEX IF NOT EXISTS ix_information_systems_support_organization_id ON information_systems (support_organization_id)')
    else:
        # SQLite cannot drop an unnamed FK in-place, so rebuild information_systems.
        bind.execute(sa.text('PRAGMA foreign_keys=OFF'))
        bind.execute(sa.text('''CREATE TABLE information_systems_new (
            id VARCHAR(36) NOT NULL PRIMARY KEY,
            number INTEGER,
            name VARCHAR(500) NOT NULL UNIQUE,
            type VARCHAR(100) NOT NULL,
            description TEXT,
            purpose TEXT,
            localization TEXT,
            support_organization_id VARCHAR(36),
            support_method VARCHAR(500),
            process_description TEXT,
            siem_enabled BOOLEAN NOT NULL,
            crypto_protection_enabled BOOLEAN NOT NULL,
            crypto_protection_description TEXT,
            status VARCHAR(50) NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            FOREIGN KEY(support_organization_id) REFERENCES support_organizations(id)
        )'''))
        bind.execute(sa.text('''INSERT INTO information_systems_new
            (id,number,name,type,description,purpose,localization,support_organization_id,support_method,process_description,siem_enabled,crypto_protection_enabled,crypto_protection_description,status,created_at,updated_at)
            SELECT id,number,name,type,description,purpose,localization,support_organization_id,support_method,process_description,siem_enabled,crypto_protection_enabled,crypto_protection_description,status,created_at,updated_at
            FROM information_systems'''))
        bind.execute(sa.text('DROP TABLE information_systems'))
        bind.execute(sa.text('ALTER TABLE information_systems_new RENAME TO information_systems'))
        bind.execute(sa.text('CREATE INDEX ix_information_systems_support_organization_id ON information_systems (support_organization_id)'))
        bind.execute(sa.text('PRAGMA foreign_keys=ON'))

    with op.batch_alter_table('information_system_ips') as batch:
        batch.add_column(sa.Column('physical_device_id', sa.String(36), nullable=True))
        batch.add_column(sa.Column('virtual_machine_id', sa.String(36), nullable=True))
        batch.create_foreign_key('fk_is_ips_physical_device', 'physical_devices', ['physical_device_id'], ['id'])
        batch.create_foreign_key('fk_is_ips_virtual_machine', 'virtual_machines', ['virtual_machine_id'], ['id'])
        batch.create_index('ix_information_system_ips_physical_device_id', ['physical_device_id'])
        batch.create_index('ix_information_system_ips_virtual_machine_id', ['virtual_machine_id'])
    with op.batch_alter_table('information_system_protocols') as batch:
        batch.add_column(sa.Column('port', sa.Integer(), nullable=True))

def downgrade():
    # Keep downgrade conservative: restore support IDs into organizations and point the FK back.
    bind = op.get_bind()
    with op.batch_alter_table('information_system_protocols') as batch:
        batch.drop_column('port')
    with op.batch_alter_table('information_system_ips') as batch:
        batch.drop_index('ix_information_system_ips_virtual_machine_id')
        batch.drop_index('ix_information_system_ips_physical_device_id')
        batch.drop_constraint('fk_is_ips_virtual_machine', type_='foreignkey')
        batch.drop_constraint('fk_is_ips_physical_device', type_='foreignkey')
        batch.drop_column('virtual_machine_id')
        batch.drop_column('physical_device_id')
    if bind.dialect.name == 'postgresql':
        _repoint_support_organization_fk(bind, 'organizations')
    else:
        bind.execute(sa.text('PRAGMA foreign_keys=OFF'))
        bind.execute(sa.text('''CREATE TABLE information_systems_old (
            id VARCHAR(36) NOT NULL PRIMARY KEY, number INTEGER, name VARCHAR(500) NOT NULL UNIQUE, type VARCHAR(100) NOT NULL,
            description TEXT, purpose TEXT, localization TEXT, support_organization_id VARCHAR(36), support_method VARCHAR(500),
            process_description TEXT, siem_enabled BOOLEAN NOT NULL, crypto_protection_enabled BOOLEAN NOT NULL,
            crypto_protection_description TEXT, status VARCHAR(50) NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
            FOREIGN KEY(support_organization_id) REFERENCES organizations(id)
        )'''))
        bind.execute(sa.text('''INSERT INTO information_systems_old SELECT id,number,name,type,description,purpose,localization,support_organization_id,support_method,process_description,siem_enabled,crypto_protection_enabled,crypto_protection_description,status,created_at,updated_at FROM information_systems'''))
        bind.execute(sa.text('DROP TABLE information_systems'))
        bind.execute(sa.text('ALTER TABLE information_systems_old RENAME TO information_systems'))
        bind.execute(sa.text('PRAGMA foreign_keys=ON'))
    op.drop_table('support_organizations')
