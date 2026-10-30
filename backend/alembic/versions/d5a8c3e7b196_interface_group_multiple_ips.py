"""Несколько общих IP-адресов у группы портов: таблица interface_group_ips вместо колонок ip_address/prefix_length/ip_purpose

Revision ID: d5a8c3e7b196
Revises: b3f7a2c91d54
Create Date: 2026-10-29 00:00:00.000000

Раньше группа портов задавала ОДИН общий IP-адрес (interface_groups.ip_address + prefix_length + ip_purpose). Теперь
группа задаёт список адресов (models.InterfaceGroupIP): каждому порту группы записываются все её адреса, лишние IP
порта удаляются.

Перенос данных. Каждая группа с заданным ip_address получает ровно одну строку interface_group_ips с тем же адресом,
префиксом и назначением — поведение существующих групп не меняется (на портах остаётся тот же единственный IP). После
переноса три колонки снимаются через batch_alter_table (на SQLite — пересборка таблицы, как в остальных миграциях
проекта).

downgrade() работает: возвращает колонки и записывает в них ПЕРВЫЙ адрес группы (по дате создания, затем по id);
остальные адреса групп теряются — в старой схеме у группы может быть только один. IP-адреса, уже записанные в порты,
остаются обычными данными портов.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "d5a8c3e7b196"
down_revision = "b3f7a2c91d54"
branch_labels = None
depends_on = None


def _utcnow_naive() -> datetime:
    """Как app.services.timeutil.utcnow_naive: наивное UTC-время (колонки DateTime проекта без часового пояса)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


LEGACY_COLUMNS = ("ip_address", "prefix_length", "ip_purpose")


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    """Идемпотентна (как соседние ревизии): на базе, где таблица уже создана и колонки сняты, ничего не делает и не
    плодит дубли — это проверяет test_the_index_migration_is_idempotent_on_sqlite, повторно накатывающий цепочку."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "interface_group_ips" not in inspector.get_table_names():
        op.create_table(
            "interface_group_ips",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("group_id", sa.String(length=36), nullable=False),
            sa.Column("ip_address", sa.String(length=64), nullable=False),
            sa.Column("prefix_length", sa.Integer(), nullable=True),
            sa.Column("purpose", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["group_id"], ["interface_groups.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_interface_group_ips_group_id", "interface_group_ips", ["group_id"])

    legacy = [column for column in LEGACY_COLUMNS if column in _columns(inspector, "interface_groups")]
    if "ip_address" in legacy:
        now = _utcnow_naive()
        ips = sa.table(
            "interface_group_ips",
            sa.column("id", sa.String), sa.column("group_id", sa.String), sa.column("ip_address", sa.String),
            sa.column("prefix_length", sa.Integer), sa.column("purpose", sa.String),
            sa.column("created_at", sa.DateTime), sa.column("updated_at", sa.DateTime),
        )
        # Группы, у которых строки уже перенесены, пропускаются: частично выполненная ревизия не удваивает адреса.
        purpose_select = "ip_purpose" if "ip_purpose" in legacy else "NULL"
        prefix_select = "prefix_length" if "prefix_length" in legacy else "NULL"
        rows = bind.execute(sa.text(
            f"SELECT id, ip_address, {prefix_select}, {purpose_select} FROM interface_groups "
            "WHERE ip_address IS NOT NULL AND ip_address <> '' "
            "AND NOT EXISTS (SELECT 1 FROM interface_group_ips WHERE interface_group_ips.group_id = interface_groups.id)"
        )).all()
        if rows:
            op.bulk_insert(ips, [
                {"id": str(uuid.uuid4()), "group_id": group_id, "ip_address": address, "prefix_length": prefix, "purpose": purpose, "created_at": now, "updated_at": now}
                for group_id, address, prefix, purpose in rows
            ])

    if legacy:
        with op.batch_alter_table("interface_groups") as batch:
            for column in legacy:
                batch.drop_column(column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = _columns(inspector, "interface_groups")
    column_types = {"ip_address": sa.String(length=64), "prefix_length": sa.Integer(), "ip_purpose": sa.String(length=255)}
    missing = [column for column in LEGACY_COLUMNS if column not in existing]
    if missing:
        with op.batch_alter_table("interface_groups") as batch:
            for column in missing:
                batch.add_column(sa.Column(column, column_types[column], nullable=True))

    if "interface_group_ips" in inspector.get_table_names():
        first: dict[str, tuple] = {}
        for group_id, address, prefix, purpose in bind.execute(sa.text("SELECT group_id, ip_address, prefix_length, purpose FROM interface_group_ips ORDER BY created_at, id")).all():
            first.setdefault(group_id, (address, prefix, purpose))
        for group_id, (address, prefix, purpose) in first.items():
            bind.execute(
                sa.text("UPDATE interface_groups SET ip_address = :address, prefix_length = :prefix, ip_purpose = :purpose WHERE id = :group_id"),
                {"address": address, "prefix": prefix, "purpose": purpose, "group_id": group_id},
            )
        op.drop_index("ix_interface_group_ips_group_id", table_name="interface_group_ips")
        op.drop_table("interface_group_ips")
