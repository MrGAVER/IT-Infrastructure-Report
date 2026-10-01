"""Merge migration heads: сверка ролей портов подключений + группы портов устройства

Ветка feature/connections-port-config-review (c5d2a8f1e703 — удалено connections.purpose, добавлена
подпись одобренного расхождения ролей портов) и main с группами портов (c7e2a91d4b35 —
interface_groups, device_interfaces.group_id) независимо ответвились от ревизии 5b1e7c94a2d8.
После слияния `alembic heads` показывал два head'а, а `alembic upgrade head` отказывался работать
(«Multiple head revisions are present»). Цепочки не пересекаются по таблицам и колонкам, поэтому
стандартная merge-ревизия без собственных операций над схемой (upgrade()/downgrade() — no-op).
База, уже обновлённая до c5d2a8f1e703 на ветке, при upgrade head получит недостающую c7e2a91d4b35.
Тот же приём, что в ceb6ca304157 и 1e7441f45639.

Revision ID: d9a4f2c8b516
Revises: c7e2a91d4b35, c5d2a8f1e703
Create Date: 2026-09-30 00:00:00.000000
"""
from __future__ import annotations

revision = "d9a4f2c8b516"
down_revision = ("c7e2a91d4b35", "c5d2a8f1e703")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
