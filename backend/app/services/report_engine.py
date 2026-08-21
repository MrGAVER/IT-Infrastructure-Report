"""
Движок конструктора произвольных отчётов — общие примитивы (пути полей, фильтры, циклический
вывод по связям, подстановка параметров), используемые обоими форматами отчётов.

format == "docx": конфигурация — плоский список блоков документа:

{
  "params": [{"key": "report_date", "label": "Дата отчёта", "default": ""}],
  "blocks": [
    {"type": "heading", "level": 1, "text": "Отчёт по ИС {{org_name}}"},
    {"type": "paragraph", "text": "Дата формирования: {{report_date}}"},
    {"type": "table", "root_entity": "...", "expand": null, "filters": [], "sort_by": null, "columns": [...]},
    {"type": "page_break"}
  ]
}

format == "xlsx": начиная с grid-редактора конфигурация описывает лист как сетку ячеек (заголовок
"sheets", но структура внутри принципиально другая) — см. services/report_grid.py, там же
validate_grid_config()/build_xlsx_grid(), использующие функции этого модуля (ReportContext,
iter_report_rows, resolve_value, validate_path, substitute_params) как общий фундамент.

Путь поля ("path") — точечная нотация по графу связей entity_metadata, общая для обоих форматов:
  "field"                      — обычное поле корневой сущности
  "relation.field"              — поле связанной сущности через "многие-к-одному" (можно цепочкой)
  "relation[].field"            — поле через связь "один/многие-ко-многим"; значения собираются
                                   в список и склеиваются через separator. Ровно один сегмент "[]"
                                   на путь; связи "многие-ко-многим" пишутся цепочкой через
                                   промежуточную таблицу, например
                                   "information_system_departments[].department.name".
Если сегмент "[]" совпадает с активной expand-связью текущей строки, вместо повторного сбора всех
связанных записей используется тот единственный объект, на который эта строка была развёрнута —
иначе каждая строка развёрнутой таблицы содержала бы полный список вместо одного элемента.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .report_meta import build_entity_metadata

_PARAM_TOKEN_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
_FILENAME_UNSAFE = re.compile(r'[\\/:*?"<>|]+')


def safe_report_filename(name: str) -> str:
    """Общая для report_render.py/report_grid.py очистка имени шаблона под имя файла."""
    cleaned = _FILENAME_UNSAFE.sub("_", name).strip() or "Отчёт"
    return cleaned[:120]


class ReportBuilderError(ValueError):
    """Ошибка конфигурации шаблона отчёта, пригодная для показа пользователю."""


class ReportContext:
    """Кэширует все строки затронутых сущностей на время генерации одного отчёта.

    Типичный объём данных реестра инфраструктуры (сотни-тысячи строк на таблицу) укладывается в
    память, поэтому вместо точечных запросов на каждое поле каждой строки (N+1) таблицы целиком
    подгружаются один раз при первом обращении и переиспользуются между листами/блоками одного
    отчёта.

    structural_unit_ids — необязательный runtime-фильтр по структурным единицам (см.
    models.StructuralUnit/reporting.py), просачивается в virtual_loader "виртуальных" сущностей
    реестра (report_registry_rows.py: registry-is-rows/registry-device-rows/registry-connection-rows/
    registry-vm-rows), которые побитово переиспользуют reporting._load_report_data — так конструктор
    отчётов на основе этих сущностей фильтруется по оборудованию структурной единицы точно так же,
    как регламентированный отчёт. Для root_entity, не являющихся виртуальными (обычные MODEL_MAP-
    сущности типа 'devices'), этот фильтр не применяется автоматически — при необходимости его можно
    выразить статичным filter'ом в конфигурации листа (путь вида "building.structural_unit_id")."""

    def __init__(self, session: Session, structural_unit_ids: list[str] | None = None):
        self.session = session
        self.structural_unit_ids = structural_unit_ids
        self.meta = build_entity_metadata()
        self._tables: dict[str, dict[str, Any]] = {}
        self._by_fk: dict[tuple[str, str], dict[str, list[Any]]] = {}

    def entity(self, entity_key: str) -> dict[str, Any]:
        if entity_key not in self.meta:
            raise ReportBuilderError(f"Неизвестная сущность '{entity_key}'")
        return self.meta[entity_key]

    def all_rows(self, entity_key: str) -> dict[str, Any]:
        if entity_key not in self._tables:
            info = self.entity(entity_key)
            loader = info.get("virtual_loader")
            rows = loader(self.session, self.structural_unit_ids) if loader else self.session.scalars(select(info["model"])).all()
            self._tables[entity_key] = {r.id: r for r in rows}
        return self._tables[entity_key]

    def get_by_id(self, entity_key: str, obj_id: str | None):
        if not obj_id:
            return None
        return self.all_rows(entity_key).get(obj_id)

    def to_many(self, entity_key: str, obj_id: str, relation_name: str) -> list[Any]:
        rel = self.entity(entity_key)["to_many"].get(relation_name)
        if not rel:
            return []
        cache_key = (entity_key, relation_name)
        if cache_key not in self._by_fk:
            index: dict[str, list[Any]] = {}
            for row in self.all_rows(rel["source"]).values():
                fk_val = getattr(row, rel["fk_column"], None)
                if fk_val:
                    index.setdefault(fk_val, []).append(row)
            self._by_fk[cache_key] = index
        return self._by_fk[cache_key].get(obj_id, [])


def _split_path(path: str) -> list[str]:
    segments = [s for s in path.strip().split(".") if s]
    if not segments:
        raise ReportBuilderError("Пустой путь поля")
    many_count = sum(1 for s in segments if s.endswith("[]"))
    if many_count > 1:
        raise ReportBuilderError(
            f"Путь '{path}' содержит более одной связи \"многие\" ([]) — поддерживается только одна на путь"
        )
    if segments[-1].endswith("[]"):
        raise ReportBuilderError(f"Путь '{path}' не может заканчиваться связью \"[]\", укажите ещё и поле")
    return segments


def _resolve(ctx: ReportContext, entity_key: str, obj: Any, segments: list[str],
             expand_relation: str | None, expand_obj: Any) -> Any:
    if obj is None:
        return None
    seg = segments[0]
    is_many = seg.endswith("[]")
    name = seg[:-2] if is_many else seg

    if len(segments) == 1:
        return getattr(obj, name, None)

    info = ctx.entity(entity_key)
    if is_many:
        if expand_relation and name == expand_relation and expand_obj is not None:
            targets = [expand_obj]
            target_entity = info["to_many"].get(name, {}).get("source")
            if target_entity is None:
                return None
        else:
            rel = info["to_many"].get(name)
            if not rel:
                return None
            targets = ctx.to_many(entity_key, obj.id, name)
            target_entity = rel["source"]
        values = [_resolve(ctx, target_entity, t, segments[1:], expand_relation, expand_obj) for t in targets]
        flat: list[Any] = []
        for v in values:
            if isinstance(v, list):
                flat.extend(v)
            else:
                flat.append(v)
        return flat
    else:
        rel = info["to_one"].get(name)
        if not rel:
            return None
        target_obj = ctx.get_by_id(rel["target"], getattr(obj, rel["fk_column"], None))
        return _resolve(ctx, rel["target"], target_obj, segments[1:], expand_relation, expand_obj)


def _to_text(raw: Any, separator: str = "; ") -> str:
    if raw is None:
        return ""
    if isinstance(raw, list):
        vals = [_to_text(v, separator) for v in raw]
        vals = [v for v in vals if v != ""]
        return separator.join(dict.fromkeys(vals))
    if isinstance(raw, bool):
        return "Да" if raw else "Нет"
    if isinstance(raw, datetime):
        return raw.strftime("%d.%m.%Y %H:%M")
    return str(raw)


def render_field(ctx: ReportContext, entity_key: str, obj: Any, path: str, *, separator: str = "; ",
                  expand_relation: str | None = None, expand_obj: Any = None) -> str:
    segments = _split_path(path)
    raw = _resolve(ctx, entity_key, obj, segments, expand_relation, expand_obj)
    return _to_text(raw, separator)


def resolve_value(ctx: ReportContext, entity_key: str, obj: Any, path: str, *,
                   expand_relation: str | None = None, expand_obj: Any = None) -> Any:
    """Как render_field(), но возвращает "сырое" значение (число/дата/bool/None/список), а не
    готовую строку. Используется grid-движком (report_grid.py, только формат xlsx): числовые и
    датовые поля должны попадать в ячейку как настоящие Excel-значения — иначе в файле нельзя ни
    просуммировать колонку формулой, ни применить числовой формат/сортировку по значению."""
    segments = _split_path(path)
    return _resolve(ctx, entity_key, obj, segments, expand_relation, expand_obj)


def substitute_params(text: str | None, params: dict[str, Any]) -> str:
    if not text:
        return ""

    def repl(match: re.Match) -> str:
        key = match.group(1).strip()
        # datetime.now() здесь намеренно без timezone: это плейсхолдер даты для человека,
        # читающего готовый отчёт ({{report_date}}/{{now}}), а не хранимая метка времени — должен
        # показывать локальное время сервера, а не UTC.
        if key == "report_date":
            return datetime.now().strftime("%d.%m.%Y")
        if key in ("now", "datetime"):
            return datetime.now().strftime("%d.%m.%Y %H:%M")
        if key in params and params[key] not in (None, ""):
            return str(params[key])
        return ""

    return _PARAM_TOKEN_RE.sub(repl, text)


_FILTER_OPS = {"eq", "ne", "contains", "not_contains", "not_empty", "is_true", "is_false"}


def _matches_filters(ctx: ReportContext, entity_key: str, obj: Any, filters: list[dict[str, Any]] | None) -> bool:
    for f in filters or []:
        path = f.get("path")
        op = f.get("op", "eq")
        if not path or op not in _FILTER_OPS:
            raise ReportBuilderError(f"Некорректный фильтр: {f}")
        text = render_field(ctx, entity_key, obj, path).strip().lower()
        value = str(f.get("value", "")).strip().lower()
        if op == "eq" and text != value:
            return False
        if op == "ne" and text == value:
            return False
        if op == "contains" and value not in text:
            return False
        if op == "not_contains" and value in text:
            return False
        if op == "not_empty" and not text:
            return False
        if op == "is_true" and text != "да":
            return False
        if op == "is_false" and text == "да":
            return False
    return True


def iter_report_rows(ctx: ReportContext, root_entity: str, *, expand: str | None = None,
                      include_empty_expand: bool = True, filters: list[dict[str, Any]] | None = None,
                      sort_by: str | None = None) -> Iterable[tuple[Any, str | None, Any]]:
    """Возвращает (root_obj, expand_relation, expand_obj) для каждой строки будущего отчёта.

    Без expand — одна строка на запись корневой сущности. С expand — по одной строке на каждый
    связанный объект (циклический вывод), плюс одна пустая строка на записи без связанных объектов,
    если include_empty_expand=True (чтобы такие записи не пропадали из отчёта молча).
    """
    rows = list(ctx.all_rows(root_entity).values())
    rows = [r for r in rows if _matches_filters(ctx, root_entity, r, filters)]
    if sort_by:
        def sort_key(r):
            v = render_field(ctx, root_entity, r, sort_by)
            return (v is None, v)
        rows.sort(key=sort_key)

    for row in rows:
        if not expand:
            yield (row, None, None)
            continue
        targets = ctx.to_many(root_entity, row.id, expand)
        if not targets:
            if include_empty_expand:
                yield (row, expand, None)
            continue
        for t in targets:
            yield (row, expand, t)


def validate_path(meta: dict[str, dict[str, Any]], entity_key: str, path: str) -> None:
    """Проверяет путь поля на структурную корректность (не требует ни БД, ни строк данных) —
    используется при сохранении шаблона, чтобы поймать опечатки в связях/полях до генерации файла."""
    segments = _split_path(path)
    current_entity = entity_key
    for i, seg in enumerate(segments):
        is_many = seg.endswith("[]")
        name = seg[:-2] if is_many else seg
        if current_entity not in meta:
            raise ReportBuilderError(f"Путь '{path}': неизвестная сущность '{current_entity}'")
        info = meta[current_entity]
        is_last = i == len(segments) - 1
        if is_last:
            field_names = {f["name"] for f in info["fields"]}
            if name not in field_names:
                raise ReportBuilderError(f"Путь '{path}': у сущности '{current_entity}' нет поля '{name}'")
            return
        if is_many:
            rel = info["to_many"].get(name)
            if not rel:
                raise ReportBuilderError(f"Путь '{path}': у сущности '{current_entity}' нет связи-\"многие\" '{name}[]'")
            current_entity = rel["source"]
        else:
            rel = info["to_one"].get(name)
            if not rel:
                raise ReportBuilderError(f"Путь '{path}': у сущности '{current_entity}' нет связи '{name}'")
            current_entity = rel["target"]


def _validate_columns(meta: dict[str, dict[str, Any]], root_entity: str, columns: list[dict[str, Any]],
                       location: str) -> None:
    if not columns:
        raise ReportBuilderError(f"{location}: не задано ни одной колонки")
    for c in columns:
        if not c.get("header") and c.get("source") != "index":
            raise ReportBuilderError(f"{location}: у колонки без заголовка нужно хотя бы одно из полей")
        source = c.get("source", "field")
        if source == "field":
            validate_path(meta, root_entity, c.get("path", ""))
        elif source not in ("index", "static"):
            raise ReportBuilderError(f"{location}: неизвестный источник колонки '{source}'")


def _validate_table_like(meta: dict[str, dict[str, Any]], block: dict[str, Any], location: str) -> None:
    root_entity = block.get("root_entity")
    if not root_entity or root_entity not in meta:
        raise ReportBuilderError(f"{location}: не задана либо неизвестна исходная сущность")
    expand = block.get("expand")
    if expand and expand not in meta[root_entity]["to_many"]:
        raise ReportBuilderError(f"{location}: у сущности '{root_entity}' нет связи-\"многие\" '{expand}'")
    for f in block.get("filters") or []:
        if not f.get("path"):
            raise ReportBuilderError(f"{location}: у фильтра не задан путь поля")
        validate_path(meta, root_entity, f["path"])
        if f.get("op", "eq") not in _FILTER_OPS:
            raise ReportBuilderError(f"{location}: неизвестная операция фильтра '{f.get('op')}'")
    if block.get("sort_by"):
        validate_path(meta, root_entity, block["sort_by"])
    _validate_columns(meta, root_entity, block.get("columns") or [], location)


def validate_config(meta: dict[str, dict[str, Any]], fmt: str, config: dict[str, Any]) -> None:
    """Полная структурная проверка шаблона формата docx. Бросает ReportBuilderError с понятным
    сообщением.

    Формат xlsx с версии grid-редактора имеет другую структуру (см. services/report_grid.py:
    validate_grid_config) — эта функция для него не вызывается, см. диспетчеризацию по формату в
    api/report_builder.py."""
    if fmt == "docx":
        blocks = config.get("blocks") or []
        if not blocks:
            raise ReportBuilderError("В шаблоне не задано ни одного блока")
        for idx, block in enumerate(blocks, 1):
            btype = block.get("type")
            if btype in ("heading", "paragraph"):
                if not block.get("text"):
                    raise ReportBuilderError(f"Блок {idx} ({btype}): не задан текст")
            elif btype == "page_break":
                continue
            elif btype == "table":
                _validate_table_like(meta, block, f"Блок {idx} (таблица)")
            else:
                raise ReportBuilderError(f"Блок {idx}: неизвестный тип '{btype}'")
    else:
        raise ReportBuilderError(f"Неизвестный формат отчёта: '{fmt}' (ожидается xlsx или docx)")


def column_value(ctx: ReportContext, root_entity: str, row: Any, expand_relation: str | None, expand_obj: Any,
                  column: dict[str, Any], row_index: int, params: dict[str, Any]) -> Any:
    source = column.get("source", "field")
    if source == "index":
        return row_index
    if source == "static":
        return substitute_params(column.get("value", ""), params)
    if source == "field":
        path = column.get("path", "")
        if not path:
            raise ReportBuilderError(f"У колонки '{column.get('header')}' не задан путь поля")
        return render_field(
            ctx, root_entity, row, path,
            separator=column.get("separator", "; "),
            expand_relation=expand_relation, expand_obj=expand_obj,
        )
    raise ReportBuilderError(f"Неизвестный источник колонки: {source}")
