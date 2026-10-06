"""
Метаданные сущностей для конструктора отчётов.

Модели проекта (models.py) описывают связи как обычные внешние ключи, без ORM-уровневых
relationship() — тот же подход уже используется в registry.py/crud/ для generic CRUD. Здесь
по тому же MODEL_MAP автоматически выводится граф связей "многие-к-одному" (по колонке с FK) и
обратных связей "один-ко-многим" (по тем же колонкам, в обратную сторону), без ручного описания
каждой пары таблиц. Связи "многие-ко-многим" (например, ИС ↔ подразделения через ISDepartment)
не требуют отдельной обработки: они выражаются как цепочка из двух связей в пути поля конструктора
(например, "information_system_departments[].department.name" — см. report_engine.py).

Полученная структура используется и для API отдачи списка полей/связей в UI конструктора, и
самим движком рендеринга (report_engine.py) для обхода путей вида "relation[].field".
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from sqlalchemy.inspection import inspect

from ..registry import DISPLAY_NAMES, MODEL_MAP
from .report_registry_rows import VIRTUAL_ENTITIES

# Поля, которые не имеет смысла показывать в конструкторе отчётов (служебные/технические).
_HIDDEN_FIELDS = {"created_at", "updated_at"}

_RU_FIELD_LABELS: dict[str, str] = {
    "id": "ID", "name": "Наименование", "description": "Описание", "short_name": "Краткое наименование",
    "number": "№", "type": "Тип", "purpose": "Назначение", "localization": "Локализация",
    "system_name": "Системное имя", "serial_number": "Серийный номер", "status": "Состояние",
    "siem_enabled": "SIEM", "crypto_protection_enabled": "СКЗИ", "process_description": "Процесс функционирования",
    "ip_address": "IP-адрес", "prefix_length": "Префикс (CIDR)", "is_management": "Управление",
    "is_data_transfer": "Передача данных", "mac_address": "MAC-адрес", "protocol": "Протокол",
    "port": "Порт", "transport_protocol": "Транспортный протокол", "version": "Версия",
    "vendor": "Производитель", "model": "Модель", "address": "Адрес", "height_u": "Высота, U",
    "rack_position": "Позиция в стойке", "role": "Роль", "runtime": "Runtime", "runtime_version": "Версия runtime",
    "vlan_id": "VLAN ID", "mode": "Режим", "category": "Категория",
    "external_interaction": "Внешнее взаимодействие", "auto_sync": "Автосинхронизация", "action": "Действие",
    "entity_type": "Тип сущности", "entity_id": "ID сущности", "details": "Подробности",
}


def _field_label(name: str) -> str:
    return _RU_FIELD_LABELS.get(name, name)


def _table_to_resource_key() -> dict[str, str]:
    return {model.__tablename__: key for key, model in MODEL_MAP.items()}


@lru_cache(maxsize=1)
def build_entity_metadata() -> dict[str, dict[str, Any]]:
    """Строит {entity_key: {label, model, fields:[...], to_one:{}, to_many:{}}} по MODEL_MAP.

    to_one[relation_name]  = {'target': entity_key, 'fk_column': col_name}
    to_many[relation_name] = {'source': entity_key, 'fk_column': col_name, 'via_relation': relation_name}
    """
    table_to_key = _table_to_resource_key()
    meta: dict[str, dict[str, Any]] = {}

    for key, model in MODEL_MAP.items():
        if key == "audit-log":
            continue
        fields = []
        to_one: dict[str, dict[str, str]] = {}
        for col in inspect(model).columns:
            if col.key in _HIDDEN_FIELDS:
                continue
            fields.append({
                "name": col.key,
                "label": _field_label(col.key),
                "type": str(col.type),
                "is_foreign_key": bool(col.foreign_keys),
            })
            if col.foreign_keys:
                fk = next(iter(col.foreign_keys))
                target_key = table_to_key.get(fk.column.table.name)
                if target_key and target_key != "audit-log":
                    rel_name = col.key[:-3] if col.key.endswith("_id") else f"{col.key}_ref"
                    to_one[rel_name] = {"target": target_key, "fk_column": col.key}
        meta[key] = {
            "label": DISPLAY_NAMES.get(key, key),
            "model": model,
            "fields": fields,
            "to_one": to_one,
            "to_many": {},
        }

    # Обратные связи "один-ко-многим": для каждой to-one связи A.rel -> B регистрируем на B
    # обратную связь "все строки A, ссылающиеся на эту строку B". Если у A на B ссылается
    # несколько разных колонок (например, Connection.source_interface_id и
    # destination_interface_id — обе на device_interfaces), имя обратной связи включает имя
    # колонки, чтобы не потерять одну из них при совпадении.
    target_counts: dict[tuple[str, str], int] = {}
    for key, info in meta.items():
        for rel in info["to_one"].values():
            target_counts[(key, rel["target"])] = target_counts.get((key, rel["target"]), 0) + 1

    for key, info in meta.items():
        for rel_name, rel in info["to_one"].items():
            target = rel["target"]
            multi = target_counts[(key, target)] > 1
            base_name = key.replace("-", "_")
            reverse_name = f"{base_name}_via_{rel_name}" if multi else base_name
            meta[target]["to_many"][reverse_name] = {
                "source": key, "fk_column": rel["fk_column"], "via_relation": rel_name,
            }

    # "Виртуальные" сущности report_registry_rows.py — плоские, уже полностью посчитанные строки
    # (побитово повторяющие вывод регламентированного отчёта), без модели БД и без связей: строки
    # поставляет функция-загрузчик (см. ReportContext.all_rows() в report_engine.py), а не SELECT
    # по таблице. Добавляются после вычисления обратных связей выше — у них нет ни своих to_one
    # (не участвуют в подсчёте target_counts), ни входящих to_many от MODEL_MAP-сущностей.
    for ve in VIRTUAL_ENTITIES.values():
        meta[ve.key] = {
            "label": ve.label,
            "model": None,
            "virtual_loader": ve.loader,
            "fields": [{"name": f.name, "label": f.label, "type": "String", "is_foreign_key": False} for f in ve.fields],
            "to_one": {},
            "to_many": {},
        }

    return meta


def entity_metadata_public() -> list[dict[str, Any]]:
    """JSON-совместимая версия метаданных для эндпоинта /report-builder/entities (без класса модели)."""
    meta = build_entity_metadata()
    out = []
    for key, info in sorted(meta.items(), key=lambda kv: kv[1]["label"]):
        out.append({
            "key": key,
            "label": info["label"],
            "fields": info["fields"],
            "to_one": [{"name": n, "target": r["target"]} for n, r in sorted(info["to_one"].items())],
            "to_many": [{"name": n, "target": r["source"]} for n, r in sorted(info["to_many"].items())],
        })
    return out
