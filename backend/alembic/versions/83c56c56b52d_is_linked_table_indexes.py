"""add missing indexes on information_system_id / virtual_machine_id FKs

Revision ID: 83c56c56b52d
Revises: a7d24f1c9e33

The "legacy linked" IS tables (information_system_departments/ips/protocols/devices/vms/
containers) are always queried filtered by information_system_id — both one row at a time
(services/crud.get_information_system_details) and batched across many IDs at once
(services/serialization._load_information_systems_links, reporting.py). ISPlacementAsset and
InformationSystemSource already had this FK indexed; these tables didn't, inconsistently.
containers.virtual_machine_id is queried the same way (e.g. filtering containers by their VM)
and had no index either, unlike the sibling physical_device_id column on the same table.
"""
from alembic import op

revision = '83c56c56b52d'
down_revision = 'a7d24f1c9e33'
branch_labels = None
depends_on = None

INDEXES = [
    ('ix_information_system_departments_information_system_id', 'information_system_departments', ['information_system_id']),
    ('ix_information_system_ips_information_system_id', 'information_system_ips', ['information_system_id']),
    ('ix_information_system_protocols_information_system_id', 'information_system_protocols', ['information_system_id']),
    ('ix_information_system_devices_information_system_id', 'information_system_devices', ['information_system_id']),
    ('ix_information_system_vms_information_system_id', 'information_system_vms', ['information_system_id']),
    ('ix_information_system_containers_information_system_id', 'information_system_containers', ['information_system_id']),
    ('ix_containers_virtual_machine_id', 'containers', ['virtual_machine_id']),
]

def upgrade():
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)

def downgrade():
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
