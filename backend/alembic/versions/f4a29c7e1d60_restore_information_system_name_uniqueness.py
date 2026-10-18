"""Restore UNIQUE(name) on information_systems

Revision ID: f4a29c7e1d60
Revises: d87b973c2415
Create Date: 2026-08-23 00:00:00.000000

The initial schema (f1c3ec81b502) created information_systems.name with an
UNNAMED UniqueConstraint. SQLite represents unnamed UNIQUE constraints as
autoindexes; when d3f9a1c6b750 later ran op.batch_alter_table() on this same
table (to add support_method_id / drop the old support_method column),
Alembic's SQLite batch mode rebuilt the table from a reflection that did not
carry the unnamed constraint over. This is the exact footgun already
documented and fixed for physical_devices.system_name in
c4e8a7d91b20 ("SQLite represents unnamed UNIQUE constraints as auto-indexes,
which cannot be dropped directly") -- it just wasn't caught here at the time,
because dropping a lost constraint raises no error; only adding data that
should have been rejected does, silently.

Net effect: two information systems could share the same name with no error.
That is not merely a display nuisance -- IS name is used as a lookup key in
report generation and cross-references, so a silent duplicate corrupts the
regulated Excel output (Лист 1) in ways that are hard to notice.

Verified live during frontend-vue development (2026-08): a freshly created
duplicate-named InformationSystem was accepted with HTTP 201 where a 409 was
expected.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f4a29c7e1d60"
down_revision = "d87b973c2415"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "uq_information_systems_name"


def upgrade() -> None:
    bind = op.get_bind()

    # Defensive: a live database may already contain accidental duplicates because
    # of this very bug. Don't crash the upgrade and don't silently delete data --
    # rename the extra copies with a distinguishing suffix so the constraint can be
    # added, and report what was renamed so the admin can review/re-merge if needed.
    duplicates = bind.execute(
        sa.text("SELECT name, COUNT(*) c FROM information_systems GROUP BY name HAVING COUNT(*) > 1")
    ).fetchall()
    for name, _count in duplicates:
        rows = bind.execute(
            sa.text("SELECT id FROM information_systems WHERE name = :name ORDER BY created_at, id"),
            {"name": name},
        ).fetchall()
        for i, (row_id,) in enumerate(rows[1:], start=2):
            new_name = f"{name} ({i})"
            bind.execute(
                sa.text("UPDATE information_systems SET name = :new_name WHERE id = :id"),
                {"new_name": new_name, "id": row_id},
            )
            print(f"[f4a29c7e1d60] Переименована дублирующаяся ИС {row_id}: {name!r} -> {new_name!r} "
                  f"— проверьте вручную, не нужно ли объединить записи.")

    if bind.dialect.name == "sqlite":
        # Same footgun as c4e8a7d91b20: rebuild the table manually with an EXPLICITLY
        # NAMED constraint instead of relying on batch_alter_table's reflection, so it
        # survives any future batch_alter_table on this table.
        bind.execute(sa.text("PRAGMA foreign_keys=OFF"))
        bind.execute(sa.text(f"""CREATE TABLE information_systems_new (
            id VARCHAR(36) NOT NULL PRIMARY KEY,
            number INTEGER,
            name VARCHAR(500) NOT NULL,
            type VARCHAR(100) NOT NULL,
            description TEXT,
            purpose TEXT,
            localization TEXT,
            support_organization_id VARCHAR(36),
            process_description TEXT,
            siem_enabled BOOLEAN NOT NULL,
            crypto_protection_enabled BOOLEAN NOT NULL,
            status VARCHAR(50) NOT NULL,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            support_method_id VARCHAR(36),
            crypto_protection_description_id VARCHAR(36),
            CONSTRAINT {CONSTRAINT_NAME} UNIQUE (name),
            CONSTRAINT fk_information_systems_crypto_means FOREIGN KEY(crypto_protection_description_id) REFERENCES crypto_protection_means (id),
            CONSTRAINT fk_information_systems_support_method FOREIGN KEY(support_method_id) REFERENCES support_methods (id),
            FOREIGN KEY(support_organization_id) REFERENCES support_organizations (id)
        )"""))
        bind.execute(sa.text("""INSERT INTO information_systems_new
            (id, number, name, type, description, purpose, localization, support_organization_id,
             process_description, siem_enabled, crypto_protection_enabled, status, created_at, updated_at,
             support_method_id, crypto_protection_description_id)
            SELECT id, number, name, type, description, purpose, localization, support_organization_id,
             process_description, siem_enabled, crypto_protection_enabled, status, created_at, updated_at,
             support_method_id, crypto_protection_description_id
            FROM information_systems"""))
        bind.execute(sa.text("DROP TABLE information_systems"))
        bind.execute(sa.text("ALTER TABLE information_systems_new RENAME TO information_systems"))
        bind.execute(sa.text("PRAGMA foreign_keys=ON"))
    else:
        # On PostgreSQL, op.batch_alter_table() executes native ALTER TABLE statements
        # rather than rebuilding the table, so this constraint was never silently lost
        # there in the first place -- just add it if it's somehow still missing.
        inspector = sa.inspect(bind)
        has_unique = any(uc["column_names"] == ["name"] for uc in inspector.get_unique_constraints("information_systems")) or any(
            ix.get("unique") and ix["column_names"] == ["name"] for ix in inspector.get_indexes("information_systems")
        )
        if not has_unique:  # на чистой PostgreSQL ограничение с начальной схемы уже есть — второе не нужно
            op.create_unique_constraint(CONSTRAINT_NAME, "information_systems", ["name"])


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        # Dropping a named constraint on SQLite requires another full table rebuild;
        # downgrading this migration only matters for local dev rollback, and there is
        # no practical benefit to reintroducing the bug this fixes.
        raise RuntimeError(
            "Downgrade not supported: would require another full SQLite table rebuild "
            "to reintroduce a constraint gap that was a bug, not a feature."
        )
    # На PostgreSQL ограничение с начальной схемы называется иначе и принадлежит ей — откатываем только своё.
    if any(uc["name"] == CONSTRAINT_NAME for uc in sa.inspect(op.get_bind()).get_unique_constraints("information_systems")):
        op.drop_constraint(CONSTRAINT_NAME, "information_systems", type_="unique")
