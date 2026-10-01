"""Connections: drop duplicated purpose, add port-config approval signature

Назначение линии связи (управление / передача данных) уже хранится на самих портах
(device_interfaces.is_management / is_data_transfer), отчёты и схема сети берут его оттуда, а
connections.purpose лишь дублировал эти флаги вручную и расходился с ними. Колонка удаляется;
вместо неё добавляется подпись одобренного расхождения ролей портов-соседей.

Ручной текст назначения, не совпадающий с тремя типовыми значениями формы, при upgrade не
теряется — переносится в описание подключения. downgrade() возвращает колонку и заполняет её
типовым значением для подключений, у которых роли обоих портов совпадают (как это делала форма).

Revision ID: c5d2a8f1e703
Revises: 5b1e7c94a2d8
Create Date: 2026-09-30 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "c5d2a8f1e703"
down_revision = "5b1e7c94a2d8"
branch_labels = None
depends_on = None

# Типовые значения поля «Назначение линии связи» прежней формы подключения.
_PRESET_PURPOSES = ("Передача данных", "Управление активами", "Передача данных и управление активами")


def _purpose_from_flags(is_management: bool, is_data_transfer: bool) -> str | None:
    if is_management and is_data_transfer:
        return "Передача данных и управление активами"
    if is_management:
        return "Управление активами"
    if is_data_transfer:
        return "Передача данных"
    return None


def upgrade() -> None:
    bind = op.get_bind()
    custom = bind.execute(
        sa.text("SELECT id, purpose, description FROM connections WHERE purpose IS NOT NULL AND TRIM(purpose) <> ''")
    ).fetchall()
    for conn_id, purpose, description in custom:
        if purpose.strip() in _PRESET_PURPOSES:
            continue
        note = f"Назначение: {purpose.strip()}"
        merged = f"{note}\n{description}" if description else note
        bind.execute(sa.text("UPDATE connections SET description = :d WHERE id = :i"), {"d": merged, "i": conn_id})

    with op.batch_alter_table("connections") as batch:
        batch.add_column(sa.Column("port_config_approved_signature", sa.String(64), nullable=True))
        batch.drop_column("purpose")


def downgrade() -> None:
    with op.batch_alter_table("connections") as batch:
        batch.add_column(sa.Column("purpose", sa.String(500), nullable=True))
        batch.drop_column("port_config_approved_signature")

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT c.id, s.is_management, s.is_data_transfer, d.is_management, d.is_data_transfer "
            "FROM connections c "
            "JOIN device_interfaces s ON s.id = c.source_interface_id "
            "JOIN device_interfaces d ON d.id = c.destination_interface_id"
        )
    ).fetchall()
    for conn_id, s_mgmt, s_data, d_mgmt, d_data in rows:
        if bool(s_mgmt) != bool(d_mgmt) or bool(s_data) != bool(d_data):
            continue  # роли портов расходятся — прежняя форма тоже не выбирала значение сама
        purpose = _purpose_from_flags(bool(s_mgmt), bool(s_data))
        if purpose:
            bind.execute(sa.text("UPDATE connections SET purpose = :p WHERE id = :i"), {"p": purpose, "i": conn_id})
