"""Журнал аудита: индексы под постраничную выборку

Экран «Журнал аудита» теперь листает журнал на сервере (GET /api/v1/audit-log): страницы «новые
сверху», счётчики по действию, список разделов. Журнал только растёт, и без индексов каждая
страница сортировала бы всю таблицу, а счётчики и список разделов читали бы её целиком.

- ix_audit_log_created_at_id (created_at, id) — порядок «новые сверху, затем id» (читается индексом
  в обратном порядке без сортировки);
- ix_audit_log_action — счётчики по действию и фильтр по действию;
- ix_audit_log_entity_type — список разделов и фильтр по разделу.

Данные не меняются; downgrade() снимает индексы.

Revision ID: c2f8a6d4e917
Revises: a7c3e9d15b42
Create Date: 2026-10-02 00:00:00.000000
"""
from __future__ import annotations

from alembic import op

revision = "c2f8a6d4e917"
down_revision = "a7c3e9d15b42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_audit_log_created_at_id", "audit_log", ["created_at", "id"])
    op.create_index("ix_audit_log_action", "audit_log", ["action"])
    op.create_index("ix_audit_log_entity_type", "audit_log", ["entity_type"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_entity_type", table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_index("ix_audit_log_created_at_id", table_name="audit_log")
