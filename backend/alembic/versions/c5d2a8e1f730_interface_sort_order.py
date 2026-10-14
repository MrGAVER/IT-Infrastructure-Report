"""Порядок портов устройства: device_interfaces.sort_order

Revision ID: c5d2a8e1f730
Revises: b8e4c2f6a109
Create Date: 2026-10-14 00:00:00.000000

Правка формы физического устройства: порты в блоке «Список интерфейсов» можно переставлять стрелками вверх/вниз, и порядок,
заданный пользователем, должен сохраняться. Раньше порядок нигде не хранился: форма читала порты в порядке создания, а
часть запросов — по имени.

sort_order — позиция порта среди портов ОДНОГО устройства (0, 1, 2, …). Форма присылает порты списком, и сервер записывает
в sort_order индекс элемента (services/crud/interfaces.py:sync_interfaces); чтение сортирует по (sort_order, created_at, id).

Перенос существующих данных. Заданного пользователем порядка у существующих портов нет, поэтому они расставляются по
«естественной» сортировке имени в пределах устройства: Gi0/2 раньше Gi0/10, регистр не важен; при равных именах — по времени
создания и id. Сортировка выполняется в Python внутри миграции (а не в SQL), чтобы результат не зависел от СУБД и сопоставления.
Алгоритм намеренно продублирован здесь, а не импортирован из приложения: миграция должна давать один и тот же результат,
даже если код приложения изменится.

downgrade() работает: снимает колонку, порядок портов возвращается к порядку создания.
"""
from __future__ import annotations

import re
from collections import defaultdict

import sqlalchemy as sa
from alembic import op

revision = "c5d2a8e1f730"
down_revision = "b8e4c2f6a109"
branch_labels = None
depends_on = None

_DIGITS = re.compile(r"(\d+)")


def _natural_key(name: str) -> list[tuple[int, int | str]]:
    """Ключ естественной сортировки: числа сравниваются как числа, текст — без учёта регистра.
    Элементы вида (0, число) и (1, текст) сравнимы между собой, т.к. тип определяется первым элементом пары."""
    return [(0, int(part)) if part.isdigit() else (1, part.casefold()) for part in _DIGITS.split(name or "") if part != ""]


def upgrade() -> None:
    with op.batch_alter_table("device_interfaces") as batch:
        batch.add_column(sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, physical_device_id, name, created_at FROM device_interfaces")).all()
    by_device: dict[str, list] = defaultdict(list)
    for row in rows:
        by_device[row.physical_device_id].append(row)

    updates: list[dict[str, object]] = []
    for ports in by_device.values():
        ports.sort(key=lambda r: (_natural_key(r.name), str(r.created_at or ""), r.id))
        updates.extend({"pos": position, "port_id": port.id} for position, port in enumerate(ports))
    if updates:
        bind.execute(sa.text("UPDATE device_interfaces SET sort_order = :pos WHERE id = :port_id"), updates)


def downgrade() -> None:
    with op.batch_alter_table("device_interfaces") as batch:
        batch.drop_column("sort_order")
