"""Merge migration heads: feature/support-link-crypto-device-oac-cert + device stacks (п.5)

Обе ветки независимо ответвили свои цепочки миграций от общей ревизии 1e7441f45639 и не знали
друг о друге — после слияния веток `alembic heads` показывал два независимых head'а
(5ba0edd4e7d4 — связь техподдержки/СКЗИ/сертификат ОАЦ, b3f6e1a9c704 — стек устройств), а
`alembic upgrade head` отказывался работать ("Multiple head revisions are present"). Обе цепочки
физически совместимы — не пересекаются по таблицам/колонкам (проверено чистым
`alembic upgrade heads` на изолированной SQLite-базе перед созданием этой ревизии). Стандартная
merge-ревизия без собственных операций над схемой (upgrade()/downgrade() — no-op) — линеаризует
граф миграций в одну цепочку. Тот же приём, что и в 1e7441f45639 (см. её комментарий).

Revision ID: ceb6ca304157
Revises: 5ba0edd4e7d4, b3f6e1a9c704
Create Date: 2026-09-16 00:00:00.000000
"""
from __future__ import annotations

revision = "ceb6ca304157"
down_revision = ("5ba0edd4e7d4", "b3f6e1a9c704")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
