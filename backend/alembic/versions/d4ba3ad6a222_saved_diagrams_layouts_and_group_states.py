"""saved diagrams layouts and group states

Revision ID: d4ba3ad6a222
Revises: aa2365249bf7
Create Date: 2026-09-08 00:00:03.000000

Миграция 4/4 фичи "Диаграмма топологии сети" (ТЗ, раздел 5, п.4). Полностью аддитивна: три
новые таблицы, ничего не меняет в существующей схеме.

- saved_diagrams — независимая сущность реестра (unique(name), НЕ синглтон, раздел 6 ТЗ):
  своя область охвата, группировка и порог сворачивания у каждой сохранённой диаграммы.
- diagram_layouts — раскладка узлов, 1:1 к saved_diagrams (unique FK), переживает
  POST /diagrams/{id}/regenerate (раздел 4.6 ТЗ).
- diagram_group_states — явное состояние сворачивания одной группы одной диаграммы, 1:N к
  saved_diagrams, с уникальностью (saved_diagram_id, group_key) — раздел 4.7/8 ТЗ.

DELETE /diagrams/{id} каскадно удаляет diagram_layouts/diagram_group_states (раздел 7 ТЗ,
таблица маршрутов) — на уровне БД это ON DELETE CASCADE у соответствующих FK, а не логика в
Python-роутере, чтобы удаление было атомарным независимо от точки входа.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "d4ba3ad6a222"
down_revision = "aa2365249bf7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_diagrams",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("scope_filter", sa.Text(), nullable=False),
        sa.Column("group_by", sa.String(length=30), nullable=False, server_default="structural_unit"),
        sa.Column("collapse_threshold", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("last_export_format", sa.String(length=10), nullable=True),
    )

    op.create_table(
        "diagram_layouts",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("saved_diagram_id", sa.String(length=36), sa.ForeignKey("saved_diagrams.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("node_positions", sa.Text(), nullable=False),
        sa.Column("viewport", sa.Text(), nullable=True),
        sa.Column("auto_layout_algorithm", sa.String(length=30), nullable=False, server_default="hierarchical"),
    )
    op.create_index("ix_diagram_layouts_saved_diagram_id", "diagram_layouts", ["saved_diagram_id"])

    op.create_table(
        "diagram_group_states",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("saved_diagram_id", sa.String(length=36), sa.ForeignKey("saved_diagrams.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_key", sa.String(length=255), nullable=False),
        sa.Column("is_collapsed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("device_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("custom_threshold", sa.Integer(), nullable=True),
        sa.UniqueConstraint("saved_diagram_id", "group_key", name="uq_diagram_group_state"),
    )
    op.create_index("ix_diagram_group_states_saved_diagram_id", "diagram_group_states", ["saved_diagram_id"])


def downgrade() -> None:
    op.drop_index("ix_diagram_group_states_saved_diagram_id", table_name="diagram_group_states")
    op.drop_table("diagram_group_states")
    op.drop_index("ix_diagram_layouts_saved_diagram_id", table_name="diagram_layouts")
    op.drop_table("diagram_layouts")
    op.drop_table("saved_diagrams")
