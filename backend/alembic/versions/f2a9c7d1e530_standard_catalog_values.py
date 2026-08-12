"""add standard catalog values

Revision ID: f2a9c7d1e530
Revises: e8c2f1a9b430
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
import uuid

revision = "f2a9c7d1e530"
down_revision = "e8c2f1a9b430"
branch_labels = None
depends_on = None

def uid():
    return str(uuid.uuid4())

def insert_names(bind, table, names):
    for name in names:
        row = bind.execute(sa.text(f"SELECT id FROM {table} WHERE name=:name LIMIT 1"), {"name": name}).fetchone()
        if not row:
            bind.execute(sa.text(f"INSERT INTO {table}(id,name,created_at,updated_at) VALUES (:id,:name,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {"id": uid(), "name": name})

def upgrade():
    bind = op.get_bind()
    insert_names(bind, "device_types", [
        "Сервер", "Сетевое оборудование", "Средство защиты информации",
        "Рабочий ПК системного администратора", "Рабочий ПК сетевого администратора",
        "Рабочий ПК администратора безопасности", "Рабочая станция пользователя",
        "Система хранения данных", "Точка доступа Wi-Fi", "IP-телефон", "ИБП", "Принтер/МФУ"
    ])
    insert_names(bind, "interface_speeds", [
        "10 Mbps", "100 Mbps", "1 Gbps", "2.5 Gbps", "5 Gbps", "10 Gbps", "25 Gbps", "40 Gbps", "50 Gbps", "100 Gbps", "200 Gbps", "400 Gbps", "Auto"
    ])
    categories = ["Гипервизор", "Серверная ОС", "Клиентская ОС", "Сетевая ОС", "ОС средства защиты", "Мобильная ОС", "Другое"]
    insert_names(bind, "operating_system_categories", categories)
    cat = {}
    for name in categories:
        cat[name] = bind.execute(sa.text("SELECT id FROM operating_system_categories WHERE name=:name LIMIT 1"), {"name":name}).fetchone()[0]
    os_defaults = [
        ("Серверная ОС", "Windows Server", "Microsoft", "2016"), ("Серверная ОС", "Windows Server", "Microsoft", "2019"),
        ("Серверная ОС", "Windows Server", "Microsoft", "2022"), ("Серверная ОС", "Windows Server", "Microsoft", "2025"),
        ("Серверная ОС", "Ubuntu Server", "Canonical", "20.04 LTS"), ("Серверная ОС", "Ubuntu Server", "Canonical", "22.04 LTS"),
        ("Серверная ОС", "Ubuntu Server", "Canonical", "24.04 LTS"), ("Серверная ОС", "Debian", "Debian", "11"),
        ("Серверная ОС", "Debian", "Debian", "12"), ("Серверная ОС", "Red Hat Enterprise Linux", "Red Hat", "8"),
        ("Серверная ОС", "Red Hat Enterprise Linux", "Red Hat", "9"), ("Клиентская ОС", "Windows 10", "Microsoft", "22H2"),
        ("Клиентская ОС", "Windows 11", "Microsoft", "23H2"), ("Клиентская ОС", "Windows 11", "Microsoft", "24H2"),
        ("Клиентская ОС", "Windows 11", "Microsoft", "25H2"), ("Сетевая ОС", "Cisco IOS XE", "Cisco", "17"),
        ("Сетевая ОС", "Cisco IOS", "Cisco", "15"), ("Сетевая ОС", "RouterOS", "MikroTik", "7"),
        ("ОС средства защиты", "FortiOS", "Fortinet", "7"), ("Гипервизор", "VMware ESXi", "VMware", "7.0"),
        ("Гипервизор", "VMware ESXi", "VMware", "8.0"), ("Гипервизор", "Microsoft Hyper-V", "Microsoft", "2022"),
        ("Гипервизор", "Microsoft Hyper-V", "Microsoft", "2025"), ("Гипервизор", "Proxmox VE", "Proxmox", "8"),
        ("Гипервизор", "Proxmox VE", "Proxmox", "9"),
    ]
    for category, name, vendor, version in os_defaults:
        row=bind.execute(sa.text("SELECT id FROM operating_systems WHERE category_id=:cid AND name=:name AND version=:version LIMIT 1"), {"cid":cat[category],"name":name,"version":version}).fetchone()
        if not row:
            bind.execute(sa.text("INSERT INTO operating_systems(id,category_id,name,version,vendor,description,created_at,updated_at) VALUES (:id,:cid,:name,:version,:vendor,NULL,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"), {"id":uid(),"cid":cat[category],"name":name,"version":version,"vendor":vendor})

def downgrade():
    # Data-only migration: do not remove catalog values because they may have been used by users.
    pass
