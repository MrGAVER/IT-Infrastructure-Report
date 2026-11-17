"""Подключение не соединяет порт с самим собой: CHECK ck_connections_distinct_ports (A-01 код-ревью main @ b375f58)

Revision ID: c4a9e2d7b185
Revises: a7d3f1c8e925
Create Date: 2026-11-14 00:00:00.000000

Правило «порт не может быть подключён сам к себе» проверял только services/validation.py:validate_connection, а в таблице connections не было
ни CHECK, ни UNIQUE: запись мимо проверки (прямой SQL, ошибка в новом коде) создавала такое подключение, и БД не возражала. Миграция добавляет
ограничение `source_interface_id <> destination_interface_id`; оно действует на все строки, активные и неактивные, — «порт сам с собой» не имеет смысла и в архиве.

Перед созданием ограничения миграция ищет такие подключения в данных. Если они есть, она ОСТАНАВЛИВАЕТСЯ с перечнем id и ничего не удаляет и не меняет
(схема остаётся прежней, версия не сдвигается): данные чинит человек — удаляет или исправляет подключение и повторяет миграцию. Образец —
b5d2f8a1c673 (uq_device_rack_slot), только там дубли можно было снять без потери смысла, а здесь неясно, какой из двух портов имелся в виду.

PostgreSQL добавляет ограничение командой ALTER TABLE. SQLite не умеет этого на месте, поэтому таблица пересобирается через batch_alter_table: Alembic отражает
её, создаёт копию с ограничением, переносит строки, удаляет оригинал и восстанавливает индексы и внешние ключи. Таблицы, ссылающейся на connections, нет, а триггеров
на ней нет, так что отключать внешние ключи (как в a7d3f1c8e925, где пересобирались родительские таблицы) не нужно.

Миграция идемпотентна, как соседние e3b7a15c9d42 и d6c1a8f3e594: ограничение, которое уже есть (база создана по моделям, а затем
получила штамп ревизии, либо миграция запущена повторно), пропускается. Без этого на PostgreSQL повторный
ALTER TABLE … ADD CONSTRAINT с занятым именем падает с DuplicateObject.

downgrade() удаляет ограничение; данные не меняются.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4a9e2d7b185"
down_revision = "a7d3f1c8e925"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "ck_connections_distinct_ports"
CONDITION = "source_interface_id <> destination_interface_id"
LOOP_QUERY = "SELECT id FROM connections WHERE source_interface_id = destination_interface_id ORDER BY id"
MAX_LISTED_IDS = 50  # в сообщении — не больше стольких id (дальше — «и ещё N»); полный список даёт запрос из текста ошибки


def _constraint_exists(bind: sa.Connection) -> bool:
    return any(constraint["name"] == CONSTRAINT_NAME for constraint in sa.inspect(bind).get_check_constraints("connections"))


def upgrade() -> None:
    bind = op.get_bind()
    if _constraint_exists(bind):  # ограничение на месте — данные ему уже соответствуют, искать и добавлять нечего
        return
    loops = bind.execute(sa.text(LOOP_QUERY)).scalars().all()
    if loops:
        listed = ", ".join(map(str, loops[:MAX_LISTED_IDS])) + (f" и ещё {len(loops) - MAX_LISTED_IDS}" if len(loops) > MAX_LISTED_IDS else "")
        raise RuntimeError(
            f"connections: найдены подключения «порт сам с собой» — {len(loops)} шт. (id: {listed}). Удалите или исправьте их вручную и повторите миграцию "
            f"(в БД ничего не изменено). Найти их можно запросом: {LOOP_QUERY}"
        )
    with op.batch_alter_table("connections") as batch:  # SQLite добавляет CHECK только пересборкой таблицы
        batch.create_check_constraint(CONSTRAINT_NAME, CONDITION)


def downgrade() -> None:
    with op.batch_alter_table("connections") as batch:
        batch.drop_constraint(CONSTRAINT_NAME, type_="check")
