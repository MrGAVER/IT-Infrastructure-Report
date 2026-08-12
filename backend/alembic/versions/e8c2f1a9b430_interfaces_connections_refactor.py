"""refactor interface ports, management IPs and connection catalog

Revision ID: e8c2f1a9b430
Revises: d1f5a7d4e900
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
import uuid

revision = "e8c2f1a9b430"
down_revision = "d1f5a7d4e900"
branch_labels = None
depends_on = None

def uid(): return str(uuid.uuid4())

def upgrade():
    bind = op.get_bind()
    # Catalogs for interface type and connection/cable type.
    op.create_table(
        "interface_types",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_interface_types_name"),
    )
    op.create_table(
        "connection_types",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_connection_types_name"),
    )
    now_sql = "CURRENT_TIMESTAMP"
    for name in ["Ethernet", "SFP", "SFP+", "SFP28", "QSFP", "QSFP28", "Management", "Console", "Fiber", "Virtual", "Другое"]:
        bind.execute(sa.text(f"INSERT INTO interface_types(id,name,created_at,updated_at) VALUES (:id,:name,{now_sql},{now_sql})"), {"id":uid(),"name":name})
    for name in ["Витая пара", "Оптическое волокно", "Медный патч-корд", "Оптический патч-корд", "Прямая связь", "Агрегированный канал", "Другое"]:
        bind.execute(sa.text(f"INSERT INTO connection_types(id,name,created_at,updated_at) VALUES (:id,:name,{now_sql},{now_sql})"), {"id":uid(),"name":name})

    # Add new FK columns and preserve old values through catalog migration.
    with op.batch_alter_table("device_interfaces") as batch:
        batch.add_column(sa.Column("interface_type_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("speed_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_device_interfaces_interface_type", "interface_types", ["interface_type_id"], ["id"])
        batch.create_foreign_key("fk_device_interfaces_speed", "interface_speeds", ["speed_id"], ["id"])

    it_rows = bind.execute(sa.text("SELECT id, interface_type FROM device_interfaces WHERE interface_type IS NOT NULL AND TRIM(interface_type) <> ''")).fetchall()
    for iid, name in it_rows:
        row = bind.execute(sa.text("SELECT id FROM interface_types WHERE lower(name)=lower(:n)"), {"n":name}).fetchone()
        if not row:
            new_id=uid(); bind.execute(sa.text(f"INSERT INTO interface_types(id,name,created_at,updated_at) VALUES (:id,:name,{now_sql},{now_sql})"), {"id":new_id,"name":name}); row=(new_id,)
        bind.execute(sa.text("UPDATE device_interfaces SET interface_type_id=:tid WHERE id=:iid"), {"tid":row[0],"iid":iid})
    sp_rows = bind.execute(sa.text("SELECT id, speed FROM device_interfaces WHERE speed IS NOT NULL AND TRIM(speed) <> ''")).fetchall()
    for iid, name in sp_rows:
        row = bind.execute(sa.text("SELECT id FROM interface_speeds WHERE lower(name)=lower(:n)"), {"n":name}).fetchone()
        if not row:
            new_id=uid(); bind.execute(sa.text(f"INSERT INTO interface_speeds(id,name,created_at,updated_at) VALUES (:id,:name,{now_sql},{now_sql})"), {"id":new_id,"name":name}); row=(new_id,)
        bind.execute(sa.text("UPDATE device_interfaces SET speed_id=:sid WHERE id=:iid"), {"sid":row[0],"iid":iid})

    # Connection type becomes one field. Prefer cable_type when present because it is the physical medium.
    with op.batch_alter_table("connections") as batch:
        batch.add_column(sa.Column("connection_type_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_connections_connection_type", "connection_types", ["connection_type_id"], ["id"])
    default_ct = bind.execute(sa.text("SELECT id FROM connection_types WHERE name='Другое' LIMIT 1")).fetchone()[0]
    conn_rows = bind.execute(sa.text("SELECT id, connection_type, cable_type FROM connections")).fetchall()
    for cid, old_type, cable in conn_rows:
        value = cable or old_type or "Другое"
        row = bind.execute(sa.text("SELECT id FROM connection_types WHERE lower(name)=lower(:n)"), {"n":value}).fetchone()
        if not row:
            new_id=uid(); bind.execute(sa.text(f"INSERT INTO connection_types(id,name,created_at,updated_at) VALUES (:id,:name,{now_sql},{now_sql})"), {"id":new_id,"name":value}); row=(new_id,)
        bind.execute(sa.text("UPDATE connections SET connection_type_id=:tid WHERE id=:cid"), {"tid":row[0],"cid":cid})
    bind.execute(sa.text("UPDATE connections SET connection_type_id=:d WHERE connection_type_id IS NULL"), {"d":default_ct})

    # Old physical-device management fields are now derived from interfaces.
    # Migrate management_port to the first management interface when possible.
    # management_ip is copied to that interface's first IP when an interface exists.
    try:
        rows = bind.execute(sa.text("SELECT id, management_port, management_ip FROM physical_devices")).fetchall()
        for did, port, mip in rows:
            if not port and not mip: continue
            iface = bind.execute(sa.text("SELECT id FROM device_interfaces WHERE physical_device_id=:d ORDER BY id LIMIT 1"), {"d":did}).fetchone()
            if iface:
                iid=iface[0]
                bind.execute(sa.text("UPDATE device_interfaces SET is_management=1 WHERE id=:i"), {"i":iid})
                if mip:
                    exists=bind.execute(sa.text("SELECT id FROM interface_ips WHERE interface_id=:i AND ip_address=:ip"), {"i":iid,"ip":mip}).fetchone()
                    if not exists:
                        bind.execute(sa.text(f"INSERT INTO interface_ips(id,interface_id,ip_address,prefix_length,purpose,is_management,created_at,updated_at) VALUES (:id,:i,:ip,NULL,'Управление',1,{now_sql},{now_sql})"), {"id":uid(),"i":iid,"ip":mip})
    except Exception:
        pass

    # Remove obsolete fields. SQLite uses batch_alter_table internally.
    with op.batch_alter_table("device_interfaces") as batch:
        for col in ["interface_type", "port_number", "speed", "admin_status", "oper_status"]:
            try: batch.drop_column(col)
            except Exception: pass
    with op.batch_alter_table("connections") as batch:
        for col in ["connection_type", "cable_type"]:
            try: batch.drop_column(col)
            except Exception: pass
    with op.batch_alter_table("physical_devices") as batch:
        for col in ["management_port", "management_ip", "physical_port_count"]:
            try: batch.drop_column(col)
            except Exception: pass

    # All IPs on a management interface are management IPs.
    bind.execute(sa.text("UPDATE interface_ips SET is_management=1 WHERE interface_id IN (SELECT id FROM device_interfaces WHERE is_management=1)"))

def downgrade():
    # Recreate legacy columns and restore best-effort values.
    bind=op.get_bind()
    with op.batch_alter_table("physical_devices") as batch:
        batch.add_column(sa.Column("management_port", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("management_ip", sa.String(64), nullable=True))
        batch.add_column(sa.Column("physical_port_count", sa.Integer(), nullable=True))
    with op.batch_alter_table("device_interfaces") as batch:
        batch.add_column(sa.Column("interface_type", sa.String(50), nullable=True))
        batch.add_column(sa.Column("port_number", sa.String(100), nullable=True))
        batch.add_column(sa.Column("speed", sa.String(50), nullable=True))
        batch.add_column(sa.Column("admin_status", sa.String(30), nullable=True))
        batch.add_column(sa.Column("oper_status", sa.String(30), nullable=True))
        batch.drop_constraint("fk_device_interfaces_interface_type", type_="foreignkey")
        batch.drop_constraint("fk_device_interfaces_speed", type_="foreignkey")
        batch.drop_column("interface_type_id")
        batch.drop_column("speed_id")
    with op.batch_alter_table("connections") as batch:
        batch.add_column(sa.Column("connection_type", sa.String(50), nullable=True))
        batch.add_column(sa.Column("cable_type", sa.String(100), nullable=True))
        batch.drop_constraint("fk_connections_connection_type", type_="foreignkey")
        batch.drop_column("connection_type_id")
    bind.execute(sa.text("UPDATE physical_devices SET physical_port_count=(SELECT count(*) FROM device_interfaces WHERE physical_device_id=physical_devices.id)"))
    op.drop_table("connection_types")
    op.drop_table("interface_types")
