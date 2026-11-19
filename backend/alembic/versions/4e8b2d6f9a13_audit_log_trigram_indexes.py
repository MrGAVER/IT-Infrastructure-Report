"""PostgreSQL: trigram-индексы поиска по журналу аудита (Н-4, часть П2)

Revision ID: 4e8b2d6f9a13
Revises: 7c3d9a5e1b24
Create Date: 2026-11-19 00:00:00.000000

Поиск ?q= в журнале аудита (services/audit_query.py) — `lower(details) LIKE '%…%' OR lower(entity_id) LIKE '%…%'`. Обычный B-tree
такой шаблон не обслуживает, поэтому каждый запрос читал всю таблицу, а журнал только растёт. Замер на PostgreSQL 16, 200 000 записей
(60 МБ): сам поисковый запрос по редкому фрагменту 293 мс → 0,65 мс (Bitmap Index Scan по обоим индексам), а весь `list_audit_log` (страница +
total + summary) 698 мс → 110 мс: оставшиеся ~110 мс — агрегаты summary и entity_types по ВСЕМУ журналу, они от поиска не зависят и этой
миграцией не меняются. Индексы занимают ~78 МБ (details 57 МБ, entity_id 21 МБ). Замер повторяет тест
test_review_p2_audit_search_trigram_indexes.py (метка slow).

Что делает миграция (только PostgreSQL; на SQLite ничего — там поиск остаётся перебором):
- включает расширение pg_trgm (с PostgreSQL 13 оно «доверенное»: создать его может владелец базы, суперпользователь не нужен);
- создаёт два GIN-индекса по ВЫРАЖЕНИЯМ `lower(details)` и `lower(entity_id)` с gin_trgm_ops — ровно те выражения, что строит запрос.

Безопасна без расширения: если pg_trgm создать нельзя (в сервере нет пакета contrib, у роли нет прав), миграция пишет предупреждение в лог и
завершается успешно, а поиск работает как раньше, только без ускорения. Попытка создать расширение идёт под SAVEPOINT: ошибка не
отравляет транзакцию миграции. Позже индексы создаются вручную (команды в предупреждении) или повторным запуском `alembic upgrade` после
установки пакета — для этого достаточно `alembic downgrade -1 && alembic upgrade head`. Обычный CREATE INDEX блокирует запись в таблицу на время
построения; миграции применяются при старте единственного экземпляра приложения до приёма запросов, так что писать в журнал в этот момент некому.

Устройства и остальные справочники не индексируются: их поиск идёт по 15 колонкам одновременно (ИЛИ по всем текстовым колонкам модели,
services/crud/generic.py), индекс пригодился бы только если проиндексировать каждую из них, а таблицы небольшие — полный перебор 50 000
устройств занимает ~95 мс, на реальных размерах реестра (сотни–тысячи) это единицы миллисекунд.

Индексы существуют только в БД, моделей у них нет (SQLAlchemy не умеет описать gin_trgm_ops выражением без расширения на SQLite),
поэтому `alembic check` пропускает их по имени — см. app/alembic_filters.py::POSTGRES_ONLY_INDEXES.

downgrade() удаляет индексы; расширение pg_trgm остаётся (его могут использовать другие объекты базы).
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

revision = "4e8b2d6f9a13"
down_revision = "7c3d9a5e1b24"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# (имя индекса, колонка audit_log). Выражение индекса — lower(колонка): так же строит условие поиска audit_query._conditions.
_TRIGRAM_INDEXES = (
    ("ix_audit_log_details_trgm", "details"),
    ("ix_audit_log_entity_id_trgm", "entity_id"),
)


def _create_statement(name: str, column: str) -> str:
    return f"CREATE INDEX IF NOT EXISTS {name} ON audit_log USING gin (lower({column}) gin_trgm_ops)"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    try:
        with bind.begin_nested():  # SAVEPOINT: неудача CREATE EXTENSION не должна обрывать транзакцию миграции
            bind.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    except sa.exc.DBAPIError as exc:
        manual = "; ".join(_create_statement(name, column) for name, column in _TRIGRAM_INDEXES)
        logger.warning(
            "Расширение pg_trgm недоступно (%s): индексы поиска по журналу аудита не созданы, поиск работает без ускорения. "
            "Когда расширение появится (CREATE EXTENSION pg_trgm), выполните: %s",
            str(exc.orig).splitlines()[0] if exc.orig else exc,
            manual,
        )
        return
    for name, column in _TRIGRAM_INDEXES:
        bind.execute(sa.text(_create_statement(name, column)))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for name, _ in _TRIGRAM_INDEXES:
        bind.execute(sa.text(f"DROP INDEX IF EXISTS {name}"))
