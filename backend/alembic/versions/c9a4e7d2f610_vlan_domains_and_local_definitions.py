"""VLAN domains and device-local VLAN definitions

Revision ID: c9a4e7d2f610
Revises: b5e7c2d4a910
"""
from alembic import op
import sqlalchemy as sa

revision = "c9a4e7d2f610"
down_revision = "b5e7c2d4a910"
branch_labels = None
depends_on = None

def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "vlan_domains" not in tables:
        op.create_table(
            "vlan_domains",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False, unique=True),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("source_device_id", sa.String(36), nullable=True),
            sa.Column("auto_sync", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["source_device_id"], ["physical_devices.id"]),
        )

    if "vlan_domain_devices" not in tables:
        op.create_table(
            "vlan_domain_devices",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("domain_id", sa.String(36), nullable=False),
            sa.Column("physical_device_id", sa.String(36), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["domain_id"], ["vlan_domains.id"]),
            sa.ForeignKeyConstraint(["physical_device_id"], ["physical_devices.id"]),
            sa.UniqueConstraint("domain_id", "physical_device_id", name="uq_vlan_domain_device"),
        )

    # SQLite does not expose a stable name for the original UNIQUE(vlan_id)
    # constraint. Rebuild the small VLAN table so existing data is preserved
    # while global VLAN-ID uniqueness is removed.
    cols = {c["name"] for c in inspector.get_columns("vlans")}
    if "domain_id" not in cols:
        op.execute("PRAGMA foreign_keys=OFF")
        op.execute("""
            CREATE TABLE vlans_new (
                id VARCHAR(36) NOT NULL,
                vlan_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                domain_id VARCHAR(36),
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(domain_id) REFERENCES vlan_domains(id),
                UNIQUE(domain_id, vlan_id)
            )
        """)
        op.execute("""
            INSERT INTO vlans_new
                (id, vlan_id, name, description, domain_id, created_at, updated_at)
            SELECT id, vlan_id, name, description, NULL, created_at, updated_at
            FROM vlans
        """)
        op.execute("DROP TABLE vlans")
        op.execute("ALTER TABLE vlans_new RENAME TO vlans")
        op.execute("CREATE INDEX ix_vlans_domain_id ON vlans(domain_id)")
        op.execute("PRAGMA foreign_keys=ON")

def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "vlans" in inspector.get_table_names():
        op.execute("PRAGMA foreign_keys=OFF")
        op.execute("""
            CREATE TABLE vlans_old (
                id VARCHAR(36) NOT NULL,
                vlan_id INTEGER NOT NULL,
                name VARCHAR(255) NOT NULL,
                description TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                UNIQUE(vlan_id)
            )
        """)
        op.execute("""
            INSERT INTO vlans_old (id, vlan_id, name, description, created_at, updated_at)
            SELECT id, vlan_id, name, description, created_at, updated_at FROM vlans
        """)
        op.execute("DROP TABLE vlans")
        op.execute("ALTER TABLE vlans_old RENAME TO vlans")
        op.execute("PRAGMA foreign_keys=ON")
    op.drop_table("vlan_domain_devices")
    op.drop_table("vlan_domains")
