"""Merge migration heads: feature/network-topology-diagram + fix/usability-batch4

Обе ветки независимо ответвили свои цепочки миграций от общей ревизии 0fcebbb67ac0
("Auth: users, sessions, settings toggle") и не знали друг о друге — после слияния веток
`alembic heads` показывал два независимых head'а (1475ab03debc — батч4/открытые порты на уровне
интерфейса, d4ba3ad6a222 — диаграмма топологии сети), а `alembic upgrade head` отказывался
работать ("Multiple head revisions are present"). Обе цепочки физически совместимы — не
пересекаются по таблицам/колонкам, проверено чистым `alembic upgrade heads` на изолированной
SQLite-базе перед созданием этой ревизии. Стандартная merge-ревизия без собственных операций
над схемой (upgrade()/downgrade() — no-op) — линеаризует граф миграций в одну цепочку.

Revision ID: 1e7441f45639
Revises: 1475ab03debc, d4ba3ad6a222
Create Date: 2026-09-12 00:00:00.000000
"""
from __future__ import annotations

revision = "1e7441f45639"
down_revision = ("1475ab03debc", "d4ba3ad6a222")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
