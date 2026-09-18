"""Merge duplicate embedded OS catalog entries (SONiC re-seeded on every startup)

Revision ID: 811f39a40ec7
Revises: c8d15d8bc6b4
Create Date: 2026-09-19 00:00:00.000000

Баг в services/catalogs.py:_seed_operating_systems — у SONiC version='' в EMBEDDED_OS_DEFAULTS,
а хранится он как version=None (version or None при создании). Сравнение "уже существует?" на
следующем запуске сверяло СЫРОЕ '' с уже сохранённым None и не находило совпадения (SQL и Python
одинаково считают '' != None) — SONiC заводился заново при каждом старте приложения. Сам баг в
seed-функции уже исправлен отдельно (version нормализуется ДО сравнения); эта миграция сливает
уже накопленные на существующих базах дубликаты — SQL UNIQUE(name, version) не спасал, потому
что NULL никогда не равен NULL ни в SQLite, ни в PostgreSQL, так что constraint не мешал
дублям накапливаться.

Полностью общая (не завязана конкретно на "SONiC") — group by (name, version) в Python (где
None==None, в отличие от SQL), а не в SQL: ловит вообще любой случайно образовавшийся дубль в
этом справочнике, а не только этот один известный случай. Для каждой группы дублей оставляет
самую старую запись (по created_at) как каноническую, переносит на неё ссылки
PhysicalDevice.embedded_os_id с удаляемых дублей и уже потом удаляет дубли.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "811f39a40ec7"
down_revision = "c8d15d8bc6b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, name, version FROM embedded_operating_systems ORDER BY name, version, created_at")
    ).fetchall()

    groups: dict[tuple[str, str | None], list[str]] = {}
    for row_id, name, version in rows:
        groups.setdefault((name, version), []).append(row_id)

    for ids in groups.values():
        if len(ids) <= 1:
            continue
        canonical_id, *duplicate_ids = ids  # первая — самая старая по created_at (см. ORDER BY)
        for duplicate_id in duplicate_ids:
            bind.execute(
                sa.text("UPDATE physical_devices SET embedded_os_id = :canonical WHERE embedded_os_id = :duplicate"),
                {"canonical": canonical_id, "duplicate": duplicate_id},
            )
            bind.execute(sa.text("DELETE FROM embedded_operating_systems WHERE id = :duplicate"), {"duplicate": duplicate_id})


def downgrade() -> None:
    # Слияние дублей необратимо — они физически неотличимы от единственной изначально верной
    # записи после переноса ссылок (тот же принцип, что и в
    # c4e8a7d91b20_os_catalog_and_duplicate_system_names.py: downgrade для потери данных, которую
    # нельзя восстановить лоссless, оставлен неподдержанным явно, а не тихим no-op).
    raise RuntimeError("Downgrade не поддерживается: слияние дублей справочника необратимо")
