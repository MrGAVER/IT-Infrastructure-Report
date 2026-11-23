"""Порт — не более чем в одном активном подключении своей роли: частичные уникальные индексы

Revision ID: e3b7a15c9d42
Revises: c4a9e2d7b185
Create Date: 2026-11-14 00:00:00.000000

Правило «порт участвует только в одном активном подключении» проверял лишь services/validation.py:validate_connection по схеме «прочитал — проверил — записал».
Этап 1 (c4a9e2d7b185 и блокировка строк портов на PostgreSQL) закрыл гонку на уровне кода; эта миграция добавляет последний рубеж в самой БД — два частичных
уникальных индекса по активным строкам:

* uq_connections_source_active      — порт не может быть источником двух активных подключений;
* uq_connections_destination_active — порт не может быть назначением двух активных подключений.

Неактивные подключения индексы не видят: архив может хранить сколько угодно строк с одним портом. Колонка is_active NOT NULL, поэтому предикат `is_active`
эквивалентен `is_active IS NOT FALSE` из validate_connection и одинаков для SQLite и PostgreSQL. Случай «порт — источник в одном подключении и назначение в другом»
индексом по одной колонке не выразить — его по-прежнему держат validate_connection и блокировка строк портов.

Перед созданием индексов миграция ищет в данных активные подключения с общим портом в одной роли. Если они есть, она ОСТАНАВЛИВАЕТСЯ с перечнем портов
и id подключений и ничего не удаляет и не меняет (версия схемы не сдвигается): какое из двух подключений настоящее, решает человек — отключает или удаляет лишнее
и повторяет миграцию. Автоматически «выбрать победителя», как для слота стойки в b5d2f8a1c673, здесь нельзя: подключение — это физический кабель, и потеря верного
теряет сведения о сети.

Обмен соседями в форме устройства переставляет подключения по одному, а уникальный индекс проверяется на каждой строке сразу, поэтому вместе с индексами меняется
services/interface_connections.py: переставляемые подключения на время применения плана выключаются и затем включаются снова.

Миграция идемпотентна, как и соседние: индекс, который уже есть (база создана по моделям или ревизия запущена повторно), пропускается.

downgrade() удаляет оба индекса; данные не меняются.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e3b7a15c9d42"
down_revision = "c4a9e2d7b185"
branch_labels = None
depends_on = None

ACTIVE = "is_active"
INDEXES = (
    ("uq_connections_source_active", "source_interface_id", "источник"),
    ("uq_connections_destination_active", "destination_interface_id", "назначение"),
)
MAX_LISTED_PORTS = 20  # в сообщении — не больше стольких портов на роль (дальше — «и ещё N»); полный список даёт запрос из текста ошибки

_connections = sa.table(
    "connections",
    sa.column("id", sa.String),
    sa.column("source_interface_id", sa.String),
    sa.column("destination_interface_id", sa.String),
    sa.column("is_active", sa.Boolean),
)


def _shared_ports(bind: sa.Connection, column_name: str) -> dict[str, list[str]]:
    """{порт: [id активных подключений]} для портов, занятых в этой роли более чем одним активным подключением."""
    column = _connections.c[column_name]
    active = _connections.c.is_active.is_not(False)  # NULL считался бы активным, как в validate_connection
    shared = sa.select(column).where(active).group_by(column).having(sa.func.count() > 1)
    rows = bind.execute(sa.select(column, _connections.c.id).where(active, column.in_(shared)).order_by(column, _connections.c.id)).all()
    found: dict[str, list[str]] = {}
    for port_id, connection_id in rows:
        found.setdefault(port_id, []).append(connection_id)
    return found


def _existing_indexes(bind: sa.Connection) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes("connections")}


def _describe(role: str, shared: dict[str, list[str]]) -> str:
    items = [f"порт {port} (подключения {', '.join(ids)})" for port, ids in list(shared.items())[:MAX_LISTED_PORTS]]
    more = f" и ещё {len(shared) - MAX_LISTED_PORTS}" if len(shared) > MAX_LISTED_PORTS else ""
    return f"как {role} — {len(shared)} шт.: " + "; ".join(items) + more


def upgrade() -> None:
    bind = op.get_bind()
    problems = [_describe(role, shared) for _, column_name, role in INDEXES if (shared := _shared_ports(bind, column_name))]
    if problems:
        raise RuntimeError(
            "connections: порт занят несколькими активными подключениями в одной роли — " + " | ".join(problems) + ". "
            "Отключите или удалите лишние подключения (экран «Подключения») и повторите миграцию; в БД ничего не изменено."
        )
    existing = _existing_indexes(bind)
    for name, column_name, _ in INDEXES:
        if name not in existing:
            op.create_index(name, "connections", [column_name], unique=True, sqlite_where=sa.text(ACTIVE), postgresql_where=sa.text(ACTIVE))


def downgrade() -> None:
    existing = _existing_indexes(op.get_bind())
    for name, _, _ in reversed(INDEXES):
        if name in existing:
            op.drop_index(name, table_name="connections")
