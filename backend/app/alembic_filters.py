"""Фильтр сравнения схемы для `alembic check` / `--autogenerate` (R1-02 код-ревью).

SQLite хранит ограничение UNIQUE, объявленное без имени (`UNIQUE(domain_id, vlan_id)` внутри CREATE TABLE), без имени — через
reflection оно приходит с `name=None`, а Alembic исходит из предположения «ограничение из базы всегда именованное». Поэтому каждое
такое ограничение моделей (`uq_vlan_domain_id` и т.п.) выглядело бы как «добавьте ограничение», хотя уникальность в базе есть
(проверено по PRAGMA index_list: автоиндекс типа `u` над теми же колонками). Это ложное срабатывание, исправить которое
переименованием в SQLite нельзя без пересборки таблиц. Поэтому на SQLite ограничения UNIQUE в сравнении пропускаются, а их
наличие проверяет отдельный тест (`test_migrations_match_models.py::test_sqlite_model_uniqueness_exists_in_the_database`):
он сверяет по колонкам, а не по именам. На PostgreSQL имена ограничений сохраняются, и сравнение полное.

Один и тот же фильтр подключён в `alembic/env.py` и в тесте-страже, поэтому `alembic check` и CI видят одно и то же.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

IncludeObject = Callable[[Any, str | None, str, bool, Any], bool]


def make_include_object(dialect_name: str) -> IncludeObject:
    """Возвращает `include_object` для `context.configure(...)` / `MigrationContext.configure(opts=...)` под диалект соединения."""

    def include_object(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
        if dialect_name == "sqlite" and type_ == "unique_constraint":
            return False
        return True

    return include_object
