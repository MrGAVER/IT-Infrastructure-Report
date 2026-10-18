"""Crypto protection means catalog; drop VM administration_ip

Revision ID: e7a2c9f4d813
Revises: d3f9a1c6b750
Create Date: 2026-08-07 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "e7a2c9f4d813"
down_revision = "d3f9a1c6b750"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "crypto_protection_means",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
    )

    with op.batch_alter_table("information_systems") as batch:
        batch.add_column(sa.Column("crypto_protection_description_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_information_systems_crypto_means", "crypto_protection_means", ["crypto_protection_description_id"], ["id"])
        batch.create_index("ix_information_systems_crypto_protection_description_id", ["crypto_protection_description_id"])

    import uuid
    existing = bind.execute(sa.text("SELECT DISTINCT crypto_protection_description FROM information_systems WHERE crypto_protection_description IS NOT NULL AND TRIM(crypto_protection_description) != ''")).fetchall()
    for (value,) in existing:
        new_id = str(uuid.uuid4())
        bind.execute(
            sa.text("INSERT INTO crypto_protection_means (id, name, created_at, updated_at) VALUES (:id, :name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
            {"id": new_id, "name": value},
        )
        bind.execute(
            sa.text("UPDATE information_systems SET crypto_protection_description_id = :cid WHERE crypto_protection_description = :name"),
            {"cid": new_id, "name": value},
        )

    with op.batch_alter_table("information_systems") as batch:
        batch.drop_column("crypto_protection_description")

    # Move any existing VM administration_ip values into a designated (is_management) vm_ips row
    # before dropping the column, so the data isn't silently lost.
    vms = bind.execute(sa.text("SELECT id, administration_ip FROM virtual_machines WHERE administration_ip IS NOT NULL AND TRIM(administration_ip) != ''")).fetchall()
    for vm_id, admin_ip in vms:
        existing_ip = bind.execute(sa.text("SELECT id FROM vm_ips WHERE virtual_machine_id = :vid AND ip_address = :ip"), {"vid": vm_id, "ip": admin_ip}).fetchone()
        if existing_ip:
            bind.execute(sa.text("UPDATE vm_ips SET is_management = :t WHERE id = :id"), {"t": True, "id": existing_ip[0]})  # булев параметр: PostgreSQL не сравнивает boolean с 1
        else:
            import uuid as _uuid
            bind.execute(
                sa.text("INSERT INTO vm_ips (id, virtual_machine_id, ip_address, is_management, created_at, updated_at) VALUES (:id, :vid, :ip, :t, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
                {"id": str(_uuid.uuid4()), "vid": vm_id, "ip": admin_ip, "t": True},
            )

    with op.batch_alter_table("virtual_machines") as batch:
        batch.drop_column("administration_ip")


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("virtual_machines") as batch:
        batch.add_column(sa.Column("administration_ip", sa.String(length=64), nullable=True))
    bind.execute(sa.text(
        "UPDATE virtual_machines SET administration_ip = ("
        "SELECT ip_address FROM vm_ips WHERE vm_ips.virtual_machine_id = virtual_machines.id AND vm_ips.is_management = :t LIMIT 1)"
    ), {"t": True})

    with op.batch_alter_table("information_systems") as batch:
        batch.add_column(sa.Column("crypto_protection_description", sa.Text(), nullable=True))
    bind.execute(sa.text(
        "UPDATE information_systems SET crypto_protection_description = ("
        "SELECT name FROM crypto_protection_means WHERE crypto_protection_means.id = information_systems.crypto_protection_description_id)"
    ))
    with op.batch_alter_table("information_systems") as batch:
        batch.drop_index("ix_information_systems_crypto_protection_description_id")
        batch.drop_constraint("fk_information_systems_crypto_means", type_="foreignkey")
        batch.drop_column("crypto_protection_description_id")
    op.drop_table("crypto_protection_means")
