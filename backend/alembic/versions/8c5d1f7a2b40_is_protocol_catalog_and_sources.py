"""Common protocol/port catalog and unified IS source rows."""
from alembic import op
import sqlalchemy as sa

revision = '8c5d1f7a2b40'
down_revision = '6f4b2c8d1a90'
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    op.create_table(
        'protocol_port_catalogs',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('port', sa.Integer(), nullable=False),
        sa.Column('protocol_type', sa.String(100), nullable=False),
        sa.Column('description', sa.Text()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
        sa.UniqueConstraint('port', 'protocol_type', name='uq_protocol_port_catalog_port_type'),
    )
    with op.batch_alter_table('information_system_protocols') as batch:
        batch.add_column(sa.Column('protocol_catalog_id', sa.String(36), nullable=True))
        batch.create_foreign_key('fk_is_protocol_catalog', 'protocol_port_catalogs', ['protocol_catalog_id'], ['id'])
        batch.create_index('ix_information_system_protocols_protocol_catalog_id', ['protocol_catalog_id'])
    with op.batch_alter_table('open_ports') as batch:
        batch.add_column(sa.Column('protocol_catalog_id', sa.String(36), nullable=True))
        batch.create_foreign_key('fk_open_ports_protocol_catalog', 'protocol_port_catalogs', ['protocol_catalog_id'], ['id'])
        batch.create_index('ix_open_ports_protocol_catalog_id', ['protocol_catalog_id'])

    # Seed the common catalog from existing IS protocols and open ports.
    rows = bind.execute(sa.text("""
        SELECT port, protocol, description FROM information_system_protocols
        WHERE port IS NOT NULL AND protocol IS NOT NULL
        UNION
        SELECT port, COALESCE(protocol, transport_protocol), description FROM open_ports
        WHERE port IS NOT NULL AND COALESCE(protocol, transport_protocol) IS NOT NULL
    """)).fetchall()
    import uuid
    from datetime import datetime, timezone
    for port, proto, description in rows:
        exists = bind.execute(sa.text("SELECT id FROM protocol_port_catalogs WHERE port=:p AND protocol_type=:t"), {'p': port, 't': proto}).scalar()
        if not exists:
            bind.execute(sa.text("INSERT INTO protocol_port_catalogs (id,port,protocol_type,description,created_at,updated_at) VALUES (:id,:p,:t,:d,:c,:c)"), {
                'id': str(uuid.uuid4()), 'p': port, 't': proto, 'd': description, 'c': datetime.now(timezone.utc)
            })
    # Standard protocol/port values for a usable catalog on first launch.
    defaults = [(22,'SSH','Secure Shell'),(53,'DNS','Domain Name System'),(80,'HTTP','Web HTTP'),(123,'NTP','Network Time Protocol'),(161,'SNMP','Simple Network Management Protocol'),(389,'LDAP','Lightweight Directory Access Protocol'),(443,'HTTPS','Web HTTPS'),(445,'SMB','Server Message Block'),(636,'LDAPS','LDAP over TLS'),(1433,'MS SQL','Microsoft SQL Server'),(1521,'Oracle','Oracle Database'),(2049,'NFS','Network File System'),(3306,'MySQL','MySQL'),(3389,'RDP','Remote Desktop Protocol'),(5432,'PostgreSQL','PostgreSQL'),(5900,'VNC','Virtual Network Computing'),(8080,'HTTP-alt','Alternative HTTP'),(8443,'HTTPS-alt','Alternative HTTPS')]
    for port, proto, description in defaults:
        exists = bind.execute(sa.text("SELECT id FROM protocol_port_catalogs WHERE port=:p AND protocol_type=:t"), {'p':port,'t':proto}).scalar()
        if not exists:
            bind.execute(sa.text("INSERT INTO protocol_port_catalogs (id,port,protocol_type,description,created_at,updated_at) VALUES (:id,:p,:t,:d,:c,:c)"), {'id':str(uuid.uuid4()),'p':port,'t':proto,'d':description,'c':datetime.now(timezone.utc)})

    # Link existing rows where possible.
    bind.execute(sa.text("""
        UPDATE information_system_protocols SET protocol_catalog_id=(
            SELECT id FROM protocol_port_catalogs c WHERE c.port=information_system_protocols.port AND c.protocol_type=information_system_protocols.protocol LIMIT 1
        ) WHERE port IS NOT NULL AND protocol IS NOT NULL
    """))
    bind.execute(sa.text("""
        UPDATE open_ports SET protocol_catalog_id=(
            SELECT id FROM protocol_port_catalogs c WHERE c.port=open_ports.port AND c.protocol_type=COALESCE(open_ports.protocol, open_ports.transport_protocol) LIMIT 1
        ) WHERE port IS NOT NULL
    """))

    op.create_table(
        'information_system_sources',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('information_system_id', sa.String(36), nullable=False),
        sa.Column('source_type', sa.String(30), nullable=False),
        sa.Column('physical_device_id', sa.String(36)),
        sa.Column('virtual_machine_id', sa.String(36)),
        sa.Column('container_id', sa.String(36)),
        sa.Column('ip_address', sa.String(64)),
        sa.Column('purpose', sa.String(500)),
        sa.Column('role', sa.String(255)),
        sa.Column('external_interaction', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_at', sa.DateTime()),
        sa.Column('updated_at', sa.DateTime()),
        sa.ForeignKeyConstraint(['information_system_id'], ['information_systems.id']),
        sa.ForeignKeyConstraint(['physical_device_id'], ['physical_devices.id']),
        sa.ForeignKeyConstraint(['virtual_machine_id'], ['virtual_machines.id']),
        sa.ForeignKeyConstraint(['container_id'], ['containers.id']),
    )
    for col in ('information_system_id','physical_device_id','virtual_machine_id','container_id'):
        op.create_index('ix_information_system_sources_'+col, 'information_system_sources', [col])

    # Migrate existing separate IS relations into unified source rows.
    for row in bind.execute(sa.text('SELECT information_system_id, physical_device_id, role FROM information_system_devices')).fetchall():
        bind.execute(sa.text("INSERT INTO information_system_sources (id,information_system_id,source_type,physical_device_id,role,external_interaction) VALUES (:id,:sid,'device',:did,:role,:ext)"), {'id':str(uuid.uuid4()),'sid':row[0],'did':row[1],'role':row[2],'ext':False})
    for row in bind.execute(sa.text('SELECT information_system_id, virtual_machine_id, role FROM information_system_vms')).fetchall():
        bind.execute(sa.text("INSERT INTO information_system_sources (id,information_system_id,source_type,virtual_machine_id,role,external_interaction) VALUES (:id,:sid,'vm',:vid,:role,:ext)"), {'id':str(uuid.uuid4()),'sid':row[0],'vid':row[1],'role':row[2],'ext':False})
    for row in bind.execute(sa.text('SELECT information_system_id, container_id, role FROM information_system_containers')).fetchall():
        bind.execute(sa.text("INSERT INTO information_system_sources (id,information_system_id,source_type,container_id,role,external_interaction) VALUES (:id,:sid,'container',:cid,:role,:ext)"), {'id':str(uuid.uuid4()),'sid':row[0],'cid':row[1],'role':row[2],'ext':False})
    for row in bind.execute(sa.text('SELECT information_system_id,ip_address,purpose,external_interaction,physical_device_id,virtual_machine_id FROM information_system_ips')).fetchall():
        bind.execute(sa.text("INSERT INTO information_system_sources (id,information_system_id,source_type,physical_device_id,virtual_machine_id,ip_address,purpose,external_interaction) VALUES (:id,:sid,:stype,:did,:vid,:ip,:purpose,:external)"), {
            'id':str(uuid.uuid4()), 'sid':row[0], 'stype':'vm' if row[5] else ('device' if row[4] else 'manual'), 'did':row[4], 'vid':row[5], 'ip':row[1], 'purpose':row[2], 'external':row[3] or 0
        })

def downgrade():
    op.drop_index('ix_information_system_sources_container_id', table_name='information_system_sources')
    op.drop_index('ix_information_system_sources_virtual_machine_id', table_name='information_system_sources')
    op.drop_index('ix_information_system_sources_physical_device_id', table_name='information_system_sources')
    op.drop_index('ix_information_system_sources_information_system_id', table_name='information_system_sources')
    op.drop_table('information_system_sources')
    with op.batch_alter_table('open_ports') as batch:
        batch.drop_index('ix_open_ports_protocol_catalog_id')
        batch.drop_constraint('fk_open_ports_protocol_catalog', type_='foreignkey')
        batch.drop_column('protocol_catalog_id')
    with op.batch_alter_table('information_system_protocols') as batch:
        batch.drop_index('ix_information_system_protocols_protocol_catalog_id')
        batch.drop_constraint('fk_is_protocol_catalog', type_='foreignkey')
        batch.drop_column('protocol_catalog_id')
    op.drop_table('protocol_port_catalogs')
