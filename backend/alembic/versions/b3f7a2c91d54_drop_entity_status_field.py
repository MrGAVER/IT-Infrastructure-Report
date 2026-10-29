"""Удаление поля status у физических устройств, информационных систем и виртуальных машин

Revision ID: b3f7a2c91d54
Revises: e9b4c2a7d136
Create Date: 2026-10-21 00:00:00.000000

Поле `status` (свободная строка до 50 символов, у ИС и ВМ по умолчанию «active») не редактировалось ни в одной форме,
не проверялось на backend и нигде не использовалось в логике — владелец решил удалить его целиком.

Что делает миграция, по порядку.

1. Переписывает сохранённые шаблоны конструктора отчётов (`report_templates.config` и история `report_template_versions.config`),
   потому что конструктор строит список полей из колонок моделей, и «Состояние» было доступно в нём для этих трёх сущностей.
   Резолвер пути берёт `getattr(obj, name, None)`, то есть после удаления колонки поле «пустое», а фильтр `status = active` отсёк бы
   ВСЕ строки — отчёт молча стал бы пустым (проверка путей `validate_path` срабатывает только при сохранении шаблона, не при
   построении отчёта). Поэтому ссылки на `status` убираются из шаблонов:
     • фильтры по `status` (в `filters`) удаляются — отчёт показывает все записи, как и до появления фильтра;
     • `sort_by` по `status` сбрасывается в null;
     • колонки таблицы документа Word (`columns`) по `status` удаляются; если колонка была единственной, она заменяется
       пустой статической (`source` = static, `value` = ""), чтобы блок остался корректным;
     • ячейка сетки Excel (`cells`, kind = field) по `status` становится пустой статической ячейкой с теми же положением и стилем.
   Путь считается ссылкой на `status`, если его последний сегмент — `status` (в том числе через связи, например
   `physical_device.status`): других таких полей в моделях не было. Историю версий переписываем тоже, чтобы «восстановить версию»
   не возвращала шаблон, который больше нельзя сохранить.

2. Удаляет три колонки обычным `ALTER TABLE … DROP COLUMN` (без пересборки таблиц, она на SQLite с включёнными внешними ключами
   опасна). SQLite умеет это с версии 3.35; на более старой миграция останавливается с понятным сообщением.

Повторный запуск безопасен: нет колонки или ссылок в шаблонах — ничего не происходит.

downgrade() возвращает колонки: у устройств необязательную, у ИС и ВМ — обязательную со значением «active» (значения, которые
были в колонках, и убранные из шаблонов фильтры не восстанавливаются).
"""
from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "b3f7a2c91d54"
down_revision = "e9b4c2a7d136"
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

_TABLES = ("physical_devices", "information_systems", "virtual_machines")
_CONFIG_TABLES = ("report_templates", "report_template_versions")


def _is_status_path(path: Any) -> bool:
    return isinstance(path, str) and path.strip().split(".")[-1] == "status"


def strip_status_paths(config: Any) -> tuple[Any, bool]:
    """Копия config без ссылок на поле status и признак «что-то изменилось». Чистая функция: БД не трогает."""
    changed = False

    def empty_static(item: dict) -> dict:
        """Пустая статическая замена: у ячейки сетки Excel (есть kind) текст в `text`, у колонки таблицы Word — в `value`."""
        placeholder = {key: value for key, value in item.items() if key not in ("path", "separator", "source")}
        if "kind" in item:
            placeholder["kind"], placeholder["text"] = "static", ""
        else:
            placeholder["source"], placeholder["value"] = "static", ""
        return placeholder

    def walk(node: Any, key: str | None = None) -> Any:
        nonlocal changed
        if isinstance(node, list):
            kept = []
            dropped = []
            for item in node:
                if isinstance(item, dict) and _is_status_path(item.get("path")):
                    if key == "filters":
                        changed = True
                        continue
                    if key == "columns":
                        changed = True
                        dropped.append(item)
                        continue
                    if key == "cells" and item.get("kind") == "field":
                        changed = True
                        kept.append(walk(empty_static(item)))
                        continue
                kept.append(walk(item, key))
            if dropped and not kept:  # единственная колонка/поле — не оставляем блок без колонок
                kept = [walk(empty_static(item)) for item in dropped]
            return kept
        if isinstance(node, dict):
            result = {}
            for name, value in node.items():
                if name == "sort_by" and _is_status_path(value):
                    changed = True
                    result[name] = None
                else:
                    result[name] = walk(value, name)
            return result
        return node

    return walk(config), changed


def _rewrite_templates(bind) -> None:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table in _CONFIG_TABLES:
        if table not in tables:
            continue
        rewritten = 0
        for row in bind.execute(sa.text(f"SELECT id, config FROM {table}")).all():
            try:
                config = json.loads(row.config)
            except (TypeError, ValueError):
                continue  # не JSON — не наше, оставляем как есть
            new_config, changed = strip_status_paths(config)
            if changed:
                bind.execute(sa.text(f"UPDATE {table} SET config = :config WHERE id = :id"), {"config": json.dumps(new_config, ensure_ascii=False), "id": row.id})
                rewritten += 1
        if rewritten:
            log.info("Из конфигураций убраны ссылки на поле status: %s — записей: %s", table, rewritten)


def _drop_status_column(bind, table: str) -> None:
    if table not in sa.inspect(bind).get_table_names() or "status" not in {c["name"] for c in sa.inspect(bind).get_columns(table)}:
        return
    if bind.dialect.name == "sqlite" and sqlite3.sqlite_version_info < (3, 35, 0):
        raise RuntimeError(f"Для удаления колонки {table}.status нужна SQLite 3.35 или новее (установлена {sqlite3.sqlite_version}).")
    op.execute(sa.text(f"ALTER TABLE {table} DROP COLUMN status"))


def upgrade() -> None:
    bind = op.get_bind()
    _rewrite_templates(bind)
    for table in _TABLES:
        _drop_status_column(bind, table)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "status" not in {c["name"] for c in inspector.get_columns("physical_devices")}:
        op.add_column("physical_devices", sa.Column("status", sa.String(50), nullable=True))
    for table in ("information_systems", "virtual_machines"):
        if "status" not in {c["name"] for c in inspector.get_columns(table)}:
            op.add_column(table, sa.Column("status", sa.String(50), nullable=False, server_default="active"))
