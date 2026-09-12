"""device categories hierarchy and diagram style

Revision ID: d359e0bd414c
Revises: 0fcebbb67ac0
Create Date: 2026-09-08 00:00:00.000000

Миграция 1/4 фичи "Диаграмма топологии сети" (ТЗ, раздел 5). Заводит иерархический справочник
DeviceCategory (тот же паттерн parent_id, что structural_units/operating_system_categories) и
засеивает его стандартной иерархией из раздела 4.1 ТЗ прямо здесь — так же, как
c4e8a7d91b20 засеяла operating_system_categories, а не полагается на services/catalogs.py
(тот перезасеивается на каждом старте приложения и может измениться позже; сама миграция должна
остаться неизменным историческим снимком). Полностью аддитивна: новых NOT NULL-колонок на
существующих таблицах здесь нет — миграция 2 добавляет обязательный device_types.category_id
отдельным шагом, т.к. это требует более осторожного backfill/удаления (раздел 5, п.2 ТЗ).

'Другое оборудование' — не часть таблицы раздела 4.1 ТЗ: технический fallback для типов устройств,
уже добавленных администратором вручную до этой миграции и не покрытых стандартной картой
"тип -> категория" (используется миграцией 2 при backfill). Без него NOT NULL category_id было бы
нечем заполнить для произвольного кастомного типа устройства.
"""
from __future__ import annotations

import uuid

from alembic import op
import sqlalchemy as sa

revision = "d359e0bd414c"
down_revision = "0fcebbb67ac0"
branch_labels = None
depends_on = None

# (name, parent_name, description, diagram_shape, diagram_color) — порядок важен: родители
# перечислены раньше своих подкатегорий. Должно оставаться в синхроне с
# app/services/catalogs.py:DEVICE_CATEGORY_HIERARCHY (сверяется тестами, см.
# tests/test_diagram_catalogs.py и tests/test_migrations_diagram.py).
DEVICE_CATEGORY_HIERARCHY = [
    ("Серверы и СХД", None, "Серверы и системы хранения данных", "server", "#4f7cff"),
    ("Сетевая инфраструктура", None, "Активное сетевое оборудование", "generic", "#2fa86a"),
    ("Коммутаторы", "Сетевая инфраструктура", "Коммутаторы уровня доступа/ядра", "switch", None),
    ("Средства защиты информации", None, "Межсетевые экраны и программно-аппаратные комплексы защиты", "firewall", "#d9534f"),
    ("Рабочие места", None, "Рабочие станции и администраторские ПК", "workstation", "#8a8f98"),
    ("Администраторские рабочие места", "Рабочие места", "Рабочие ПК системного/сетевого администратора и администратора безопасности", None, None),
    ("Периферия и вспомогательное оборудование", None, "IP-телефоны, ИБП, принтеры/МФУ", "peripheral", "#b08b3a"),
    ("Другое оборудование", None, "Технический fallback для типов устройств без сопоставленной категории", "generic", None),
]


def upgrade() -> None:
    bind = op.get_bind()

    op.create_table(
        "device_categories",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False, unique=True),
        sa.Column("parent_id", sa.String(length=36), sa.ForeignKey("device_categories.id"), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("diagram_shape", sa.String(length=30), nullable=True),
        sa.Column("diagram_color", sa.String(length=20), nullable=True),
    )
    op.create_index("ix_device_categories_parent_id", "device_categories", ["parent_id"])

    name_to_id: dict[str, str] = {}
    for name, parent_name, description, shape, color in DEVICE_CATEGORY_HIERARCHY:
        cid = str(uuid.uuid4())
        name_to_id[name] = cid
        bind.execute(
            sa.text(
                "INSERT INTO device_categories "
                "(id, name, parent_id, description, diagram_shape, diagram_color, created_at, updated_at) "
                "VALUES (:id, :name, :parent_id, :description, :shape, :color, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "id": cid,
                "name": name,
                "parent_id": name_to_id.get(parent_name) if parent_name else None,
                "description": description,
                "shape": shape,
                "color": color,
            },
        )


def downgrade() -> None:
    op.drop_index("ix_device_categories_parent_id", table_name="device_categories")
    op.drop_table("device_categories")
