"""serial_number физического устройства больше не уникален

Revision ID: b3f7a1d95c24
Revises: a9e3d4f17b26
Create Date: 2026-10-22 00:00:00.000000

Серийные номера разных производителей совпадают, поэтому глобальная уникальность — ошибка модели предметной области:
второе законное устройство с тем же номером получало 409 `INTEGRITY_ERROR` с общим текстом. Для `system_name` ограничение
уже снято миграцией c4e8a7d91b20 (дубли допустимы); серийный номер приводится к тому же правилу.

Состояние до миграции зависело от СУБД:
  • PostgreSQL: ограничение `physical_devices_serial_number_key` создала начальная миграция f1c3ec81b502 и оно сохранилось —
    `batch_alter_table` в PostgreSQL таблицу не пересобирает. Здесь его и снимаем.
  • SQLite: ограничение потерялось случайно на e8c2f1a9b430 (пересборка таблицы не переносит безымянный UNIQUE),
    в базах из миграций его нет — миграция ничего не меняет.

Миграция определяет состояние по схеме, а не по диалекту, поэтому идемпотентна: повторный запуск и база без ограничения —
ничего не происходит. Ограничение снимается только на одной колонке `serial_number`; остальные ограничения и индексы
(в том числе частичный `uq_device_rack_slot`) не затрагиваются. Данные не меняются.

downgrade() намеренно ничего не делает и не падает: глобальную уникальность не возвращаем — в данных уже могут быть
законные дубли, а само ограничение владелец продукта признал ошибкой. Составное ограничение «производитель + серийный
номер» не вводится (отдельное решение владельца).
"""
import sqlalchemy as sa
from alembic import op

revision = 'b3f7a1d95c24'
down_revision = 'a9e3d4f17b26'
branch_labels = None
depends_on = None

TABLE = 'physical_devices'


def _only_serial_number(columns) -> bool:
    return list(columns) == ['serial_number']


def upgrade():
    bind = op.get_bind()

    named = [
        constraint['name']
        for constraint in sa.inspect(bind).get_unique_constraints(TABLE)
        if _only_serial_number(constraint['column_names']) and constraint.get('name')
    ]
    if named:
        # batch_alter_table: на PostgreSQL это обычный ALTER TABLE, на SQLite (если именованное ограничение всё же есть)
        # — пересборка таблицы.
        with op.batch_alter_table(TABLE) as batch_op:
            for name in named:
                batch_op.drop_constraint(name, type_='unique')

    # Отдельный уникальный индекс по serial_number (если он создан вне ограничения). Инспектор создаётся заново: индекс
    # ограничения исчезает вместе с ним и в старом снимке остался бы.
    for index in sa.inspect(bind).get_indexes(TABLE):
        if index.get('unique') and _only_serial_number(index['column_names']):
            op.drop_index(index['name'], table_name=TABLE)


def downgrade():
    """Глобальную уникальность не возвращаем (см. docstring модуля): ничего не делаем."""
