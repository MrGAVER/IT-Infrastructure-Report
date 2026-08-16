"""
Grid-движок конструктора произвольных отчётов — формат xlsx.

Заменяет прежний табличный движок (лист = список колонок с путями к полям, авто-раскладка в
таблицу) на визуальную сетку ячеек — то, что видно и редактируется в UI (report_builder.js) как
реальный лист Excel: произвольная позиция, объединение ячеек, стили, число/дата-формат, формулы.

Формат конфигурации листа (ReportTemplate.config["sheets"][i], JSON):

{
  "title": "Лист 1",
  "columns": [{"width": 22}, {"width": 30}, {"width": 14}],   # ширина колонок листа, по числу колонок
  "rows": [
    {
      "height": 22,
      "repeat": false,                 # false — строка выводится один раз как есть (заголовок/название)
      "cells": [
        {"col": 0, "colspan": 3, "kind": "static", "text": "Отчёт по ИС {{org_name}}",
         "style": {"bold": true, "align": "center", "bg": "#EEF2FF"}}
      ]
    },
    {
      "height": 18,
      "repeat": true,                  # true — строка клонируется по одной на каждую запись данных
      "data_source": {                 # обязателен при repeat=true
        "root_entity": "information-systems",   # ключ из /report-builder/entities
        "expand": null,                # опц.: связь "многие" — строка размножается по её элементам
        "include_empty_expand": true,
        "filters": [{"path": "status", "op": "eq", "value": "active"}],
        "sort_by": "name"
      },
      "cells": [
        {"col": 0, "kind": "index"},
        {"col": 1, "kind": "field", "path": "name", "separator": "; "},
        {"col": 2, "kind": "formula", "text": "=LEN(B{row})"}
      ]
    }
  ]
}

Типы ячеек (cell.kind):
  "static"  — статический текст, поддерживает {{параметр}}/{{report_date}}; допустим в любой строке.
  "field"   — значение поля БД по пути (нотация как в report_engine.py); только в repeat-строке,
              резолвится через resolve_value() относительно data_source.root_entity этой строки.
  "index"   — порядковый номер записи внутри повторения (с 1); только в repeat-строке.
  "formula" — сырая формула Excel ("=..."), записывается в ячейку как есть — Excel вычислит её сам
              при открытии файла (openpyxl формулы не считает); допустима в любой строке.

Объединение: colspan/rowspan ≥ 1. rowspan > 1 допустим только в НЕ повторяющихся строках (в
повторяющейся строке ровно одна физическая строка на запись — вертикальное объединение внутри неё
не имеет смысла) и может охватывать только последующие тоже не повторяющиеся строки.

style — необязательный объект на ячейке: bold/italic/underline (bool), align ("left"/"center"/
"right"), valign ("top"/"middle"/"bottom"), wrap (bool, по умолчанию true), bg/color (строка формата
"#RRGGBB"), number_format (строка формата Excel, например "0.00" или "DD.MM.YYYY"), border (bool,
тонкая рамка со всех сторон).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from .computed import local_timestamp_suffix
from .report_engine import (
    ReportBuilderError, ReportContext, iter_report_rows, resolve_value, safe_report_filename,
    substitute_params, validate_path,
)

_CELL_KINDS = {"static", "field", "index", "formula"}
_ALIGN_H = {"left", "center", "right"}
_ALIGN_V = {"top", "middle", "bottom"}
_FILTER_OPS = {"eq", "ne", "contains", "not_contains", "not_empty", "is_true", "is_false"}


# --------------------------------------------------------------------------------------------
# Валидация
# --------------------------------------------------------------------------------------------

def _validate_data_source(meta: dict[str, dict[str, Any]], ds: Any, location: str) -> str:
    if not isinstance(ds, dict):
        raise ReportBuilderError(f"{location}: у повторяющейся строки не задан источник данных")
    root_entity = ds.get("root_entity")
    if not root_entity or root_entity not in meta:
        raise ReportBuilderError(f"{location}: не задана либо неизвестна исходная сущность")
    expand = ds.get("expand")
    if expand and expand not in meta[root_entity]["to_many"]:
        raise ReportBuilderError(f"{location}: у сущности '{root_entity}' нет связи-\"многие\" '{expand}'")
    for f in ds.get("filters") or []:
        if not f.get("path"):
            raise ReportBuilderError(f"{location}: у фильтра не задан путь поля")
        validate_path(meta, root_entity, f["path"])
        if f.get("op", "eq") not in _FILTER_OPS:
            raise ReportBuilderError(f"{location}: неизвестная операция фильтра '{f.get('op')}'")
    if ds.get("sort_by"):
        validate_path(meta, root_entity, ds["sort_by"])
    return root_entity


def _validate_style(style: Any, location: str) -> None:
    if style is None:
        return
    if not isinstance(style, dict):
        raise ReportBuilderError(f"{location}: стиль ячейки должен быть объектом")
    align = style.get("align")
    if align and align not in _ALIGN_H:
        raise ReportBuilderError(f"{location}: неизвестное горизонтальное выравнивание '{align}'")
    valign = style.get("valign")
    if valign and valign not in _ALIGN_V:
        raise ReportBuilderError(f"{location}: неизвестное вертикальное выравнивание '{valign}'")
    for key in ("bg", "color"):
        val = style.get(key)
        if val and not (isinstance(val, str) and len(val) == 7 and val.startswith("#")):
            raise ReportBuilderError(f"{location}: цвет '{key}' должен быть в формате #RRGGBB")


def _validate_row(meta: dict[str, dict[str, Any]], n_cols: int, rows: list[Any], ri: int,
                   pending_spans: list[tuple[int, int, int]], location: str) -> None:
    row = rows[ri]
    if not isinstance(row, dict):
        raise ReportBuilderError(f"{location}: строка {ri + 1} задана некорректно")
    cells = row.get("cells") or []
    if not cells:
        raise ReportBuilderError(f"{location}: строка {ri + 1} без единой ячейки")
    repeat = bool(row.get("repeat"))
    root_entity = _validate_data_source(meta, row.get("data_source"), f"{location}, строка {ri + 1}") if repeat else None

    # Пришедшие "сверху" объединения по вертикали занимают часть колонок этой строки — по
    # построению (обрабатываем строки по порядку) все элементы pending_spans относятся к строкам
    # ДО ri, так что достаточно проверить, что их действие ещё не закончилось (end_row > ri).
    consumed_above = {c for (end_row, start, stop) in pending_spans if end_row > ri for c in range(start, stop)}
    occupied: list[tuple[int, int]] = []
    for cell in cells:
        if not isinstance(cell, dict):
            raise ReportBuilderError(f"{location}: строка {ri + 1} содержит некорректную ячейку")
        col = cell.get("col")
        if not isinstance(col, int) or isinstance(col, bool) or col < 0 or col >= n_cols:
            raise ReportBuilderError(f"{location}: строка {ri + 1} — некорректный номер колонки {col!r}")
        colspan = int(cell.get("colspan") or 1)
        rowspan = int(cell.get("rowspan") or 1)
        if colspan < 1 or rowspan < 1:
            raise ReportBuilderError(f"{location}: строка {ri + 1}, колонка {col} — colspan/rowspan должны быть ≥ 1")
        end_col = col + colspan
        if end_col > n_cols:
            raise ReportBuilderError(f"{location}: строка {ri + 1}, колонка {col} — объединение выходит за границы листа")
        if rowspan > 1:
            if repeat:
                raise ReportBuilderError(
                    f"{location}: строка {ri + 1} — объединение по вертикали недопустимо в повторяющейся строке"
                )
            if ri + rowspan > len(rows):
                raise ReportBuilderError(
                    f"{location}: строка {ri + 1}, колонка {col} — объединение выходит за последнюю строку листа"
                )
            for j in range(ri + 1, ri + rowspan):
                if bool(rows[j].get("repeat")):
                    raise ReportBuilderError(
                        f"{location}: строка {ri + 1} — объединение по вертикали не может охватывать повторяющуюся строку"
                    )
        if any(c in consumed_above for c in range(col, end_col)):
            raise ReportBuilderError(f"{location}: строка {ri + 1}, колонка {col} уже занята объединением из строки выше")
        if any(col < e and s < end_col for s, e in occupied):
            raise ReportBuilderError(f"{location}: строка {ri + 1} — ячейки в колонке {col} перекрываются")
        occupied.append((col, end_col))

        kind = cell.get("kind", "static")
        if kind not in _CELL_KINDS:
            raise ReportBuilderError(f"{location}: строка {ri + 1}, колонка {col} — неизвестный тип ячейки '{kind}'")
        if kind == "field":
            if not repeat:
                raise ReportBuilderError(
                    f"{location}: строка {ri + 1}, колонка {col} — поле из БД допустимо только в повторяющейся строке"
                )
            if not cell.get("path"):
                raise ReportBuilderError(f"{location}: строка {ri + 1}, колонка {col} — не задан путь поля")
            validate_path(meta, root_entity, cell["path"])
        elif kind == "index" and not repeat:
            raise ReportBuilderError(
                f"{location}: строка {ri + 1}, колонка {col} — «№ строки» допустим только в повторяющейся строке"
            )
        elif kind == "formula" and not cell.get("text"):
            raise ReportBuilderError(f"{location}: строка {ri + 1}, колонка {col} — не задана формула")
        _validate_style(cell.get("style"), f"{location}, строка {ri + 1}, колонка {col}")

        if rowspan > 1:
            pending_spans.append((ri + rowspan, col, end_col))


def validate_sheet(meta: dict[str, dict[str, Any]], sheet: dict[str, Any], location: str) -> None:
    if not isinstance(sheet, dict):
        raise ReportBuilderError(f"{location}: лист задан некорректно")
    columns = sheet.get("columns") or []
    if not columns:
        raise ReportBuilderError(f"{location}: не задано ни одной колонки")
    for i, c in enumerate(columns):
        width = c.get("width", 15) if isinstance(c, dict) else None
        if not isinstance(width, (int, float)) or isinstance(width, bool) or width <= 0:
            raise ReportBuilderError(f"{location}: колонка {i + 1} — некорректная ширина")
    rows = sheet.get("rows") or []
    if not rows:
        raise ReportBuilderError(f"{location}: не задано ни одной строки")

    n_cols = len(columns)
    pending_spans: list[tuple[int, int, int]] = []
    for ri in range(len(rows)):
        _validate_row(meta, n_cols, rows, ri, pending_spans, location)


def validate_grid_config(meta: dict[str, dict[str, Any]], config: dict[str, Any]) -> None:
    """Полная структурная проверка grid-шаблона xlsx. Бросает ReportBuilderError с понятным
    сообщением, пригодным для показа пользователю в редакторе."""
    if not isinstance(config, dict):
        raise ReportBuilderError("Конфигурация шаблона должна быть объектом")
    sheets = config.get("sheets") or []
    if not sheets:
        raise ReportBuilderError("В шаблоне не задано ни одного листа")
    for sheet in sheets:
        validate_sheet(meta, sheet, f"Лист «{sheet.get('title', '?')}»" if isinstance(sheet, dict) else "Лист")


# --------------------------------------------------------------------------------------------
# Материализация: конфигурация листа + данные БД -> физические строки/ячейки
# --------------------------------------------------------------------------------------------

def _normalize_field_value(raw: Any, separator: str) -> Any:
    """Приводит "сырое" значение поля к тому, что можно записать в ячейку Excel: списки (из полей
    вида relation[].field) склеиваются в текст, bool — в "Да"/"Нет" (как и в старом движке отчётов),
    а числа/даты/строки остаются "как есть" — чтобы в файле работали числовой формат и формулы."""
    if isinstance(raw, list):
        parts = [_normalize_field_value(v, separator) for v in raw]
        seen: list[str] = []
        for p in parts:
            text = "" if p is None else str(p)
            if text and text not in seen:
                seen.append(text)
        return separator.join(seen)
    if isinstance(raw, bool):
        return "Да" if raw else "Нет"
    return raw


def _cell_geometry(cell: dict[str, Any]) -> dict[str, int]:
    return {
        "col": cell["col"],
        "colspan": int(cell.get("colspan") or 1),
        "rowspan": int(cell.get("rowspan") or 1),
    }


def _formula_value(cell: dict[str, Any], params: dict[str, Any]) -> str:
    text = substitute_params(cell.get("text", ""), params)
    return text if text.startswith("=") else f"={text}"


def _physical_rows(ctx: ReportContext, sheet: dict[str, Any], params: dict[str, Any], *,
                    limit: int | None) -> tuple[list[dict[str, Any]], list[int]]:
    """Возвращает (физические строки листа, список total-ов по каждой повторяющейся строке —
    сколько записей нашлось ДО применения limit, для предпросмотра "показаны N из M")."""
    physical: list[dict[str, Any]] = []
    totals: list[int] = []

    for row in sheet.get("rows") or []:
        height = row.get("height") or 18
        cells = row.get("cells") or []

        if not row.get("repeat"):
            resolved = []
            for cell in cells:
                kind = cell.get("kind", "static")
                value = _formula_value(cell, params) if kind == "formula" else substitute_params(cell.get("text", ""), params)
                resolved.append({**_cell_geometry(cell), "value": value, "is_datetime": False, "style": cell.get("style") or {}})
            physical.append({"height": height, "cells": resolved})
            continue

        ds = row.get("data_source") or {}
        root_entity = ds["root_entity"]
        matches = list(iter_report_rows(
            ctx, root_entity,
            expand=ds.get("expand"),
            include_empty_expand=ds.get("include_empty_expand", True),
            filters=ds.get("filters"),
            sort_by=ds.get("sort_by"),
        ))
        totals.append(len(matches))
        subset = matches if limit is None else matches[:limit]

        for i, (obj, expand_rel, expand_obj) in enumerate(subset, 1):
            resolved = []
            for cell in cells:
                kind = cell.get("kind", "static")
                is_dt = False
                if kind == "index":
                    value: Any = i
                elif kind == "formula":
                    value = _formula_value(cell, params)
                elif kind == "field":
                    raw = resolve_value(ctx, root_entity, obj, cell["path"],
                                         expand_relation=expand_rel, expand_obj=expand_obj)
                    value = _normalize_field_value(raw, cell.get("separator", "; "))
                    is_dt = isinstance(value, datetime)
                else:  # static — например, постоянная подпись рядом с данными в той же строке
                    value = substitute_params(cell.get("text", ""), params)
                resolved.append({**_cell_geometry(cell), "value": value, "is_datetime": is_dt, "style": cell.get("style") or {}})
            physical.append({"height": height, "cells": resolved})

    return physical, totals


# --------------------------------------------------------------------------------------------
# Рендеринг в файл xlsx
# --------------------------------------------------------------------------------------------

def _hex(value: str | None) -> str | None:
    return value.lstrip("#").upper() if value else None


def _apply_style(xl_cell, style: dict[str, Any] | None, *, is_datetime: bool) -> None:
    style = style or {}
    xl_cell.font = Font(bold=bool(style.get("bold")), italic=bool(style.get("italic")),
                         underline="single" if style.get("underline") else None,
                         color=_hex(style.get("color")))
    align_v = {"top": "top", "middle": "center", "bottom": "bottom"}.get(style.get("valign"), "top")
    xl_cell.alignment = Alignment(horizontal=style.get("align") or "left", vertical=align_v,
                                   wrap_text=bool(style.get("wrap", True)))
    bg = _hex(style.get("bg"))
    if bg:
        xl_cell.fill = PatternFill(fill_type="solid", start_color=bg, end_color=bg)
    if style.get("border"):
        side = Side(style="thin", color="94A3B8")
        xl_cell.border = Border(left=side, right=side, top=side, bottom=side)
    if style.get("number_format"):
        xl_cell.number_format = style["number_format"]
    elif is_datetime:
        xl_cell.number_format = "DD.MM.YYYY HH:MM"


def build_xlsx_grid(session: Session, config: dict[str, Any], report_dir: Path, *, template_name: str,
                     params: dict[str, Any] | None = None) -> Path:
    params = params or {}
    sheets = config.get("sheets") or []
    if not sheets:
        raise ReportBuilderError("В шаблоне не задано ни одного листа")

    ctx = ReportContext(session)
    wb = Workbook()
    wb.remove(wb.active)
    used_titles: set[str] = set()

    for sheet in sheets:
        title = (substitute_params(sheet.get("title", "Лист"), params) or "Лист")[:31]
        base, n = title, 2
        while title in used_titles:
            title = f"{base[:28]}({n})"; n += 1
        used_titles.add(title)
        ws = wb.create_sheet(title)

        for i, col in enumerate(sheet.get("columns") or [], 1):
            ws.column_dimensions[get_column_letter(i)].width = col.get("width", 15)

        physical_rows, _ = _physical_rows(ctx, sheet, params, limit=None)
        for ri, prow in enumerate(physical_rows, 1):
            ws.row_dimensions[ri].height = prow["height"]
            for cell in prow["cells"]:
                xl_cell = ws.cell(row=ri, column=cell["col"] + 1)
                xl_cell.value = cell["value"] if cell["value"] != "" else None
                _apply_style(xl_cell, cell["style"], is_datetime=cell["is_datetime"])
                if cell["colspan"] > 1 or cell["rowspan"] > 1:
                    ws.merge_cells(
                        start_row=ri, start_column=cell["col"] + 1,
                        end_row=ri + cell["rowspan"] - 1, end_column=cell["col"] + cell["colspan"],
                    )

    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{safe_report_filename(template_name)}_{local_timestamp_suffix()}.xlsx"
    wb.save(path)
    return path


def preview_grid(session: Session, config: dict[str, Any], *, limit: int = 15) -> dict[str, Any]:
    """Материализованный предпросмотр листов без сохранения файла: те же физические строки/ячейки,
    что уйдут в итоговый xlsx, но каждая повторяющаяся строка урезана до `limit` записей — полный
    объём данных для предпросмотра в браузере не нужен и утяжелил бы ответ API."""
    ctx = ReportContext(session)
    sections = []
    for sheet in config.get("sheets") or []:
        try:
            physical_rows, totals = _physical_rows(ctx, sheet, {}, limit=limit)
        except ReportBuilderError as e:
            sections.append({"title": sheet.get("title", ""), "error": str(e)})
            continue
        sections.append({
            "title": sheet.get("title", ""),
            "n_cols": len(sheet.get("columns") or []),
            "rows": physical_rows,
            "total_records": sum(totals) if totals else 0,
        })
    return {"sections": sections}
