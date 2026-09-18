"""Split switch/router device categories for distinct diagram icons (item 5)

Revision ID: c8d15d8bc6b4
Revises: ceb6ca304157
Create Date: 2026-09-18 00:00:00.000000

Раньше 'Коммутатор L2' и 'Коммутатор L3' указывали на одну и ту же категорию 'Коммутаторы' —
получали одинаковый значок на диаграмме топологии сети, различить уровень коммутации на глаз
было нельзя. 'Маршрутизатор' указывал прямо на 'Сетевая инфраструктура' (shape='generic') вместе
с точками Wi-Fi/GSM-модемами/радиомостами — вообще без своего значка. См. services/diagram_icons.
py:resolve_category_style и обновлённую DEVICE_CATEGORY_HIERARCHY/DEVICE_TYPE_CATEGORY в
services/catalogs.py — та же иерархия здесь применяется к УЖЕ существующим базам (сама
catalogs.py-таблица использует _seed_..., проверяющий существование ПО ИМЕНИ и потому не
перекладывающий category_id у уже заведённых типов устройств).

Специально НЕ трогает свежую/ещё не разу не стартовавшую базу (нет ни 'Коммутаторы', ни
'Сетевая инфраструктура' — seed_defaults() при первом старте приложения и так заведёт всё верно
сразу по обновлённой иерархии, без участия этой миграции).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "c8d15d8bc6b4"
down_revision = "ceb6ca304157"
branch_labels = None
depends_on = None

_device_categories = sa.table(
    "device_categories",
    sa.column("id", sa.String),
    sa.column("parent_id", sa.String),
    sa.column("name", sa.String),
    sa.column("description", sa.Text),
    sa.column("diagram_shape", sa.String),
    sa.column("diagram_color", sa.String),
    sa.column("created_at", sa.DateTime),
    sa.column("updated_at", sa.DateTime),
)
_device_types = sa.table(
    "device_types",
    sa.column("id", sa.String),
    sa.column("name", sa.String),
    sa.column("category_id", sa.String),
)

# (новая категория, родитель, описание, diagram_shape, тип устройства, который на неё переводим)
_NEW_CATEGORIES = [
    ("Коммутаторы L2", "Коммутаторы", "Коммутаторы уровня доступа (L2)", "switch_l2", "Коммутатор L2"),
    ("Коммутаторы L3", "Коммутаторы", "Коммутаторы с маршрутизацией (L3)", "switch_l3", "Коммутатор L3"),
    ("Маршрутизаторы", "Сетевая инфраструктура", "Маршрутизаторы", "router", "Маршрутизатор"),
]


def upgrade() -> None:
    bind = op.get_bind()
    now = datetime.now(timezone.utc)

    parent_ids = {
        row.name: row.id
        for row in bind.execute(
            sa.select(_device_categories.c.id, _device_categories.c.name).where(
                _device_categories.c.name.in_({parent for _, parent, *_ in _NEW_CATEGORIES})
            )
        )
    }
    if len(parent_ids) < 2:
        # Свежая база — seed_defaults() при первом старте заведёт категории верно сразу.
        return

    for name, parent_name, description, shape, device_type_name in _NEW_CATEGORIES:
        existing = bind.execute(sa.select(_device_categories.c.id).where(_device_categories.c.name == name)).first()
        if existing:
            category_id = existing.id
        else:
            category_id = str(uuid.uuid4())
            op.bulk_insert(
                _device_categories,
                [{
                    "id": category_id,
                    "parent_id": parent_ids[parent_name],
                    "name": name,
                    "description": description,
                    "diagram_shape": shape,
                    "diagram_color": None,
                    "created_at": now,
                    "updated_at": now,
                }],
            )
        op.execute(_device_types.update().where(_device_types.c.name == device_type_name).values(category_id=category_id))


def downgrade() -> None:
    bind = op.get_bind()
    old_parent_ids = {
        row.name: row.id
        for row in bind.execute(
            sa.select(_device_categories.c.id, _device_categories.c.name).where(
                _device_categories.c.name.in_(["Коммутаторы", "Сетевая инфраструктура"])
            )
        )
    }
    for name, parent_name, _description, _shape, device_type_name in _NEW_CATEGORIES:
        category = bind.execute(sa.select(_device_categories.c.id).where(_device_categories.c.name == name)).first()
        if not category:
            continue
        old_parent_id = old_parent_ids.get(parent_name)
        if old_parent_id:
            op.execute(_device_types.update().where(_device_types.c.name == device_type_name).values(category_id=old_parent_id))
        # Удаляем категорию, только если на неё уже ничего не ссылается (после переноса выше —
        # не должно, но не разрушаем данные, если что-то успело сослаться на неё за это время).
        still_referenced = bind.execute(
            sa.select(sa.func.count()).select_from(_device_types).where(_device_types.c.category_id == category.id)
        ).scalar()
        if not still_referenced:
            op.execute(_device_categories.delete().where(_device_categories.c.id == category.id))
