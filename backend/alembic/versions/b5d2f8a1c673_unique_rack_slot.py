"""Уникальный слот в стойке: частичный уникальный индекс uq_device_rack_slot

Занятость слота (rack_id + rack_position) проверялась только кодом «проверил, потом записал» без
ограничения в БД: два параллельных запроса создали бы два устройства в одном слоте.
Миграция добавляет частичный уникальный индекс — он затрагивает только устройства, у которых заданы и
стойка, и непустая позиция.

Если в БД уже есть дубли слота, индекс создать нельзя, поэтому сначала они устраняются: устройство,
созданное раньше всех, сохраняет позицию, у остальных позиция снимается (rack_position = NULL) — сами
устройства, их стойка и остальные данные не меняются. Это та же операция, что делает интерфейс при
«Переназначить позицию»; снятые позиции остаются в журнале только как отсутствие значения, поэтому перед
обновлением БД с дублями слотов их стоит проверить вручную.

downgrade() удаляет индекс; снятые позиции не возвращаются.

Revision ID: b5d2f8a1c673
Revises: a3e7c1d9b406
Create Date: 2026-10-05 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b5d2f8a1c673"
down_revision = "a3e7c1d9b406"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_device_rack_slot"
SLOT_FILLED = "rack_id IS NOT NULL AND rack_position IS NOT NULL AND rack_position <> ''"


def upgrade() -> None:
    # Коррелированный подзапрос годится и для SQLite, и для PostgreSQL: оставляем самое раннее устройство
    # слота (created_at, затем id — тот же порядок, что и у списков), остальным позицию снимаем.
    op.execute(
        sa.text(
            "UPDATE physical_devices SET rack_position = NULL "
            f"WHERE {SLOT_FILLED} "
            "AND id <> ("
            "  SELECT d2.id FROM physical_devices d2 "
            "  WHERE d2.rack_id = physical_devices.rack_id AND d2.rack_position = physical_devices.rack_position "
            "  ORDER BY d2.created_at, d2.id LIMIT 1"
            ")"
        )
    )
    op.create_index(
        INDEX_NAME,
        "physical_devices",
        ["rack_id", "rack_position"],
        unique=True,
        sqlite_where=sa.text(SLOT_FILLED),
        postgresql_where=sa.text(SLOT_FILLED),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="physical_devices")
