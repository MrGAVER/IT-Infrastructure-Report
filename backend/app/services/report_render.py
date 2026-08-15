"""Рендеринг шаблона произвольного отчёта (см. report_engine.py) в готовый файл xlsx или docx."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from .computed import local_timestamp_suffix
from .report_engine import ReportBuilderError, ReportContext, column_value, iter_report_rows, substitute_params

_FILENAME_UNSAFE = re.compile(r'[\\/:*?"<>|]+')


def _safe_filename(name: str) -> str:
    cleaned = _FILENAME_UNSAFE.sub("_", name).strip() or "Отчёт"
    return cleaned[:120]


def _sheet_rows(ctx: ReportContext, sheet: dict[str, Any], params: dict[str, Any]) -> list[list[Any]]:
    root_entity = sheet.get("root_entity")
    if not root_entity:
        raise ReportBuilderError(f"У листа '{sheet.get('title')}' не задана исходная сущность")
    columns = sheet.get("columns") or []
    if not columns:
        raise ReportBuilderError(f"У листа '{sheet.get('title')}' нет ни одной колонки")

    out: list[list[Any]] = []
    for i, (row, expand_rel, expand_obj) in enumerate(iter_report_rows(
        ctx, root_entity,
        expand=sheet.get("expand"),
        include_empty_expand=sheet.get("include_empty_expand", True),
        filters=sheet.get("filters"),
        sort_by=sheet.get("sort_by"),
    ), 1):
        out.append([column_value(ctx, root_entity, row, expand_rel, expand_obj, c, i, params) for c in columns])
    return out


def _setup_sheet(ws, headers: list[str]) -> None:
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.freeze_panes = "A2"


def _finalize_sheet(ws) -> None:
    for row in ws.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    for col in range(1, ws.max_column + 1):
        max_len = 12
        for cell in ws.iter_rows(min_col=col, max_col=col, values_only=True):
            max_len = max(max_len, min(len(str(cell[0] if cell else "" or "")), 55))
        ws.column_dimensions[get_column_letter(col)].width = min(max_len + 2, 55)
    ws.row_dimensions[1].height = 36
    if ws.max_row > 1:
        ws.auto_filter.ref = ws.dimensions


def build_xlsx(session: Session, config: dict[str, Any], report_dir: Path, *, template_name: str,
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
        headers = [substitute_params(c.get("header", ""), params) for c in sheet.get("columns") or []]
        _setup_sheet(ws, headers)
        for row in _sheet_rows(ctx, sheet, params):
            ws.append(row)
        _finalize_sheet(ws)

    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{_safe_filename(template_name)}_{local_timestamp_suffix()}.xlsx"
    wb.save(path)
    return path


def build_docx(session: Session, config: dict[str, Any], report_dir: Path, *, template_name: str,
                params: dict[str, Any] | None = None) -> Path:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    params = params or {}
    blocks = config.get("blocks") or []
    if not blocks:
        raise ReportBuilderError("В шаблоне не задано ни одного блока")

    ctx = ReportContext(session)
    doc = Document()

    for block in blocks:
        btype = block.get("type")
        if btype == "heading":
            level = max(0, min(int(block.get("level", 1)), 9))
            doc.add_heading(substitute_params(block.get("text", ""), params), level=level)
        elif btype == "paragraph":
            p = doc.add_paragraph(substitute_params(block.get("text", ""), params))
            if block.get("align") == "center":
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif btype == "page_break":
            doc.add_page_break()
        elif btype == "table":
            root_entity = block.get("root_entity")
            columns = block.get("columns") or []
            if not root_entity or not columns:
                raise ReportBuilderError("Блок-таблица должен содержать исходную сущность и хотя бы одну колонку")
            rows = _sheet_rows(ctx, block, params)
            table = doc.add_table(rows=1, cols=len(columns))
            table.style = "Light Grid Accent 1"
            hdr = table.rows[0].cells
            for i, c in enumerate(columns):
                hdr[i].text = substitute_params(c.get("header", ""), params)
            for data_row in rows:
                cells = table.add_row().cells
                for i, value in enumerate(data_row):
                    cells[i].text = "" if value is None else str(value)
        else:
            raise ReportBuilderError(f"Неизвестный тип блока: {btype}")

    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"{_safe_filename(template_name)}_{local_timestamp_suffix()}.docx"
    doc.save(path)
    return path


def build_report_from_template(session: Session, template, report_dir: Path,
                                params: dict[str, Any] | None = None) -> Path:
    """template — объект ReportTemplate (или любой с .format/.config/.name)."""
    import json
    config = json.loads(template.config or "{}")
    if template.format == "docx":
        return build_docx(session, config, report_dir, template_name=template.name, params=params)
    if template.format == "xlsx":
        return build_xlsx(session, config, report_dir, template_name=template.name, params=params)
    raise ReportBuilderError(f"Неизвестный формат отчёта: {template.format}")


def preview_rows(session: Session, config: dict[str, Any], *, limit: int = 20) -> dict[str, Any]:
    """Быстрый предпросмотр без сохранения файла: первые N строк каждого листа/блока-таблицы,
    для показа в UI конструктора до генерации итогового файла."""
    ctx = ReportContext(session)
    result: dict[str, Any] = {"sections": []}
    sections = config.get("sheets") if "sheets" in config else block_tables(config.get("blocks") or [])
    for sheet in sections:
        headers = [c.get("header", "") for c in sheet.get("columns") or []]
        try:
            rows = _sheet_rows(ctx, sheet, {})
        except ReportBuilderError as e:
            result["sections"].append({"title": sheet.get("title", ""), "error": str(e)})
            continue
        result["sections"].append({
            "title": sheet.get("title", ""), "headers": headers,
            "rows": rows[:limit], "total": len(rows),
        })
    return result


def block_tables(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [b for b in blocks if b.get("type") == "table"]
