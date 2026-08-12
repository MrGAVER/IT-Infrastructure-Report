"""add indexes for frequent FK and lookup queries

Revision ID: 3a7c1e5d9b20
Revises: f2a9c7d1e530
"""
from alembic import op

revision = '3a7c1e5d9b20'
down_revision = 'f2a9c7d1e530'
branch_labels = None
depends_on = None

INDEXES = [
    ('ix_rooms_building_id', 'rooms', ['building_id']),
    ('ix_racks_room_id', 'racks', ['room_id']),
    ('ix_device_models_manufacturer_id', 'device_models', ['manufacturer_id']),
    ('ix_device_models_device_type_id', 'device_models', ['device_type_id']),
    ('ix_physical_devices_device_type_id', 'physical_devices', ['device_type_id']),
    ('ix_physical_devices_manufacturer_id', 'physical_devices', ['manufacturer_id']),
    ('ix_physical_devices_model_id', 'physical_devices', ['model_id']),
    ('ix_physical_devices_system_name', 'physical_devices', ['system_name']),
    ('ix_physical_devices_operating_system_id', 'physical_devices', ['operating_system_id']),
    ('ix_physical_devices_building_id', 'physical_devices', ['building_id']),
    ('ix_physical_devices_room_id', 'physical_devices', ['room_id']),
    ('ix_physical_devices_rack_id', 'physical_devices', ['rack_id']),
    ('ix_device_interfaces_physical_device_id', 'device_interfaces', ['physical_device_id']),
    ('ix_device_interfaces_interface_type_id', 'device_interfaces', ['interface_type_id']),
    ('ix_device_interfaces_speed_id', 'device_interfaces', ['speed_id']),
    ('ix_interface_ips_interface_id', 'interface_ips', ['interface_id']),
    ('ix_interface_vlans_interface_id', 'interface_vlans', ['interface_id']),
    ('ix_interface_vlans_vlan_id', 'interface_vlans', ['vlan_id']),
    ('ix_connections_source_interface_id', 'connections', ['source_interface_id']),
    ('ix_connections_destination_interface_id', 'connections', ['destination_interface_id']),
    ('ix_virtual_machines_operating_system_id', 'virtual_machines', ['operating_system_id']),
    ('ix_virtual_machines_physical_device_id', 'virtual_machines', ['physical_device_id']),
    ('ix_virtual_machines_hypervisor_os_id', 'virtual_machines', ['hypervisor_os_id']),
    ('ix_vm_ips_virtual_machine_id', 'vm_ips', ['virtual_machine_id']),
    ('ix_operating_systems_category_id', 'operating_systems', ['category_id']),
]

def upgrade():
    for name, table, columns in INDEXES:
        op.create_index(name, table, columns)

def downgrade():
    for name, table, _ in reversed(INDEXES):
        op.drop_index(name, table_name=table)
