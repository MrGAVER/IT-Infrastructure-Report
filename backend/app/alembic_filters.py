"""Фильтр сравнения схемы для `alembic check` / `--autogenerate`.

SQLite хранит ограничение UNIQUE, объявленное без имени (`UNIQUE(domain_id, vlan_id)` внутри CREATE TABLE), без имени — через
reflection оно приходит с `name=None`, а Alembic исходит из предположения «ограничение из базы всегда именованное». Поэтому каждое
такое ограничение моделей (`uq_vlan_domain_id` и т.п.) выглядело бы как «добавьте ограничение», хотя уникальность в базе есть
(проверено по PRAGMA index_list: автоиндекс типа `u` над теми же колонками). Это ложное срабатывание, исправить которое
переименованием в SQLite нельзя без пересборки таблиц. Поэтому на SQLite ограничения UNIQUE в сравнении пропускаются, а их
наличие проверяет отдельный тест (`test_migrations_match_models.py::test_sqlite_model_uniqueness_exists_in_the_database`):
он сверяет по колонкам, а не по именам. На PostgreSQL имена ограничений сохраняются, и сравнение полное.

Индексы, которые существуют только в PostgreSQL и не описаны в моделях (trigram-индексы поиска по журналу аудита, миграция
4e8b2d6f9a13), в сравнении пропускаются по имени: SQLite их не имеет, а выражение `lower(колонка) gin_trgm_ops` моделью не выражается.
Их наличие и использование планировщиком проверяет test_review_p2_audit_search_trigram_indexes.py.

Один и тот же фильтр подключён в `alembic/env.py` и в тесте-страже, поэтому `alembic check` и CI видят одно и то же.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

IncludeObject = Callable[[Any, str | None, str, bool, Any], bool]

# Индексы только для PostgreSQL, созданные миграциями и отсутствующие в моделях (см. докстринг модуля).
POSTGRES_ONLY_INDEXES = frozenset({"ix_audit_log_details_trgm", "ix_audit_log_entity_id_trgm"})


def make_include_object(dialect_name: str) -> IncludeObject:
    """Возвращает `include_object` для `context.configure(...)` / `MigrationContext.configure(opts=...)` под диалект соединения."""

    def include_object(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
        if dialect_name == "sqlite" and type_ == "unique_constraint":
            return False
        if type_ == "index" and name in POSTGRES_ONLY_INDEXES:
            return False
        return True

    return include_object
