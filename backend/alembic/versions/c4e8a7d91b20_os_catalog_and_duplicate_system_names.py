"""move OS/hypervisors to common catalog, make device status optional, allow duplicate system names

Revision ID: c4e8a7d91b20
Revises: 7b1f8c2d4e60
"""
from alembic import op
import sqlalchemy as sa
import uuid

revision = "c4e8a7d91b20"
down_revision = "7b1f8c2d4e60"
branch_labels = None
depends_on = None


def _id():
    return str(uuid.uuid4())


def upgrade():
    bind = op.get_bind()

    op.create_table(
        "operating_system_categories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_operating_system_categories_name"),
    )
    op.create_table(
        "operating_systems",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("category_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("version", sa.String(255), nullable=True),
        sa.Column("vendor", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["category_id"], ["operating_system_categories.id"]),
        sa.UniqueConstraint("category_id", "name", "version", name="uq_operating_system_category_name_version"),
    )

    categories = [
        ("Гипервизор", "Гипервизоры и платформы виртуализации"),
        ("Серверная ОС", "Операционные системы серверов"),
        ("Клиентская ОС", "Операционные системы пользовательских рабочих станций"),
        ("Сетевая ОС", "Операционные системы сетевого оборудования"),
        ("ОС средства защиты", "Операционные системы средств защиты информации"),
        ("Другое", "Прочие операционные системы"),
    ]
    category_ids = {}
    for name, description in categories:
        cid = _id(); category_ids[name] = cid
        bind.execute(sa.text("INSERT INTO operating_system_categories (id,name,description,created_at,updated_at) VALUES (:id,:name,:description,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {"id": cid, "name": name, "description": description})

    # Preserve old hypervisor catalog entries.
    old_platforms = bind.execute(sa.text("SELECT id,name,vendor,version FROM virtualization_platforms")).fetchall()
    hyper_id = category_ids["Гипервизор"]
    platform_to_os = {}
    for old_id, name, vendor, version in old_platforms:
        osid = _id(); platform_to_os[old_id] = osid
        bind.execute(sa.text("INSERT INTO operating_systems (id,category_id,name,version,vendor,created_at,updated_at) VALUES (:id,:category_id,:name,:version,:vendor,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {"id": osid, "category_id": hyper_id, "name": name, "version": version, "vendor": vendor})

    # Preserve legacy free-text OS values in the generic 'Другое' category.
    other_id = category_ids["Другое"]
    def get_or_create_os(name, version):
        if not name and not version:
            return None
        name = name or "Не указано"
        row = bind.execute(sa.text("SELECT id FROM operating_systems WHERE category_id=:cat AND name=:name AND version IS :version"), {"cat": other_id, "name": name, "version": version}).fetchone()
        if row:
            return row[0]
        osid = _id()
        bind.execute(sa.text("INSERT INTO operating_systems (id,category_id,name,version,created_at,updated_at) VALUES (:id,:category_id,:name,:version,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {"id": osid, "category_id": other_id, "name": name, "version": version})
        return osid

    old_devices = bind.execute(sa.text("SELECT id,os_name,os_version FROM physical_devices")).fetchall()
    old_vms = bind.execute(sa.text("SELECT id,os_name,os_version,virtualization_platform_id FROM virtual_machines")).fetchall()

    with op.batch_alter_table("physical_devices") as batch:
        batch.add_column(sa.Column("operating_system_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_physical_devices_operating_system", "operating_systems", ["operating_system_id"], ["id"])
        batch.alter_column("status", existing_type=sa.String(50), nullable=True)

    # SQLite represents unnamed UNIQUE constraints as auto-indexes, which cannot be dropped directly.
    # Rebuild the table without UNIQUE(system_name), retaining legacy OS columns for backward compatibility.
    if bind.dialect.name == "sqlite":
        bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
        bind.execute(sa.text("""CREATE TABLE physical_devices_new (
            id VARCHAR(36) NOT NULL PRIMARY KEY, device_type_id VARCHAR(36) NOT NULL, manufacturer_id VARCHAR(36), model_id VARCHAR(36),
            serial_number VARCHAR(255) NOT NULL UNIQUE, system_name VARCHAR(255), os_name VARCHAR(255), os_version VARCHAR(255),
            operating_system_id VARCHAR(36), management_port INTEGER, management_ip VARCHAR(64), siem_enabled BOOLEAN NOT NULL,
            physical_port_count INTEGER, building_id VARCHAR(36), room_id VARCHAR(36), rack_id VARCHAR(36), rack_position VARCHAR(50),
            status VARCHAR(50), description TEXT, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL,
            FOREIGN KEY(device_type_id) REFERENCES device_types(id), FOREIGN KEY(manufacturer_id) REFERENCES manufacturers(id),
            FOREIGN KEY(model_id) REFERENCES device_models(id), FOREIGN KEY(building_id) REFERENCES buildings(id), FOREIGN KEY(room_id) REFERENCES rooms(id),
            FOREIGN KEY(rack_id) REFERENCES racks(id), FOREIGN KEY(operating_system_id) REFERENCES operating_systems(id)
        )"""))
        bind.execute(sa.text("""INSERT INTO physical_devices_new
            (id,device_type_id,manufacturer_id,model_id,serial_number,system_name,os_name,os_version,operating_system_id,management_port,management_ip,siem_enabled,physical_port_count,building_id,room_id,rack_id,rack_position,status,description,created_at,updated_at)
            SELECT id,device_type_id,manufacturer_id,model_id,serial_number,system_name,os_name,os_version,operating_system_id,management_port,management_ip,siem_enabled,physical_port_count,building_id,room_id,rack_id,rack_position,status,description,created_at,updated_at FROM physical_devices"""))
        bind.execute(sa.text("DROP TABLE physical_devices"))
        bind.execute(sa.text("ALTER TABLE physical_devices_new RENAME TO physical_devices"))
        bind.execute(sa.text("PRAGMA foreign_keys=ON"))
    else:
        # PostgreSQL names the implicit unique constraint from the column; remove it if present.
        bind.execute(sa.text("ALTER TABLE physical_devices DROP CONSTRAINT IF EXISTS physical_devices_system_name_key"))

    for device_id, name, version in old_devices:
        osid = get_or_create_os(name, version)
        if osid:
            bind.execute(sa.text("UPDATE physical_devices SET operating_system_id=:osid WHERE id=:id"), {"osid": osid, "id": device_id})

    with op.batch_alter_table("virtual_machines") as batch:
        batch.add_column(sa.Column("operating_system_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("hypervisor_os_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_virtual_machines_operating_system", "operating_systems", ["operating_system_id"], ["id"])
        batch.create_foreign_key("fk_virtual_machines_hypervisor_os", "operating_systems", ["hypervisor_os_id"], ["id"])

    for vm_id, name, version, platform_id in old_vms:
        osid = get_or_create_os(name, version)
        if osid:
            bind.execute(sa.text("UPDATE virtual_machines SET operating_system_id=:osid WHERE id=:id"), {"osid": osid, "id": vm_id})
        if platform_id and platform_id in platform_to_os:
            bind.execute(sa.text("UPDATE virtual_machines SET hypervisor_os_id=:osid WHERE id=:id"), {"osid": platform_to_os[platform_id], "id": vm_id})

    # The legacy virtualization_platforms table is retained physically for backward compatibility,
    # but it is no longer exposed by the application. All new hypervisor records live in operating_systems.


def downgrade():
    raise RuntimeError("Downgrade of OS catalog migration is intentionally unsupported because legacy free-text OS values cannot be restored losslessly.")
