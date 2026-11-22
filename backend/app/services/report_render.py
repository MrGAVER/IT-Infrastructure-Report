"""Рендеринг шаблона произвольного отчёта формата docx (см. report_engine.py) в готовый файл.

Формат xlsx рендерится отдельным grid-движком — см. services/report_grid.py:build_xlsx_grid().
Обе функции используют одну и ту же таблицу report_templates/config (см. api/report_builder.py:
диспетчеризация по template.format), поэтому этот модуль по-прежнему содержит общую для обоих
форматов _sheet_rows() (нужна блокам-таблицам docx) и preview_rows() (нужна предпросмотру docx —
предпросмотр xlsx переехал в report_grid.preview_grid())."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from .computed import local_timestamp_suffix
from .report_engine import (
    ReportBuilderError,
    ReportContext,
    column_value,
    iter_report_rows,
    safe_report_filename,
    substitute_params,
)


def _sheet_rows(ctx: ReportContext, sheet: dict[str, Any], params: dict[str, Any]) -> list[list[Any]]:
    root_entity = sheet.get("root_entity")
    if not root_entity:
        raise ReportBuilderError(f"У листа '{sheet.get('title')}' не задана исходная сущность")
    columns = sheet.get("columns") or []
    if not columns:
        raise ReportBuilderError(f"У листа '{sheet.get('title')}' нет ни одной колонки")

    out: list[list[Any]] = []
    for i, (row, expand_rel, expand_obj) in enumerate(
        iter_report_rows(
            ctx,
            root_entity,
            expand=sheet.get("expand"),
            include_empty_expand=sheet.get("include_empty_expand", True),
            filters=sheet.get("filters"),
            sort_by=sheet.get("sort_by"),
        ),
        1,
    ):
        out.append([column_value(ctx, root_entity, row, expand_rel, expand_obj, c, i, params) for c in columns])
    return out


def build_docx(
    session: Session,
    config: dict[str, Any],
    report_dir: Path,
    *,
    template_name: str,
    params: dict[str, Any] | None = None,
    structural_unit_ids: list[str] | None = None,
) -> Path:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    params = params or {}
    blocks = config.get("blocks") or []
    if not blocks:
        raise ReportBuilderError("В шаблоне не задано ни одного блока")

    ctx = ReportContext(session, structural_unit_ids)
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
    path = report_dir / f"{safe_report_filename(template_name)}_{local_timestamp_suffix()}.docx"
    doc.save(path)
    return path


def build_report_from_template(
    session: Session, template, report_dir: Path, params: dict[str, Any] | None = None, structural_unit_ids: list[str] | None = None
) -> Path:
    """template — объект ReportTemplate (или любой с .format/.config/.name).

    structural_unit_ids — необязательный runtime-фильтр по структурным единицам размещения
    оборудования (см. ReportContext/reporting.py), просачивается до листов/блоков, построенных на
    "виртуальных" сущностях реестра (registry-is-rows и т.п., см. report_registry_rows.py) — так же,
    как фильтрует регламентированный отчёт. На листы/блоки с обычным root_entity не влияет."""
    import json

    config = json.loads(template.config or "{}")
    if template.format == "docx":
        return build_docx(session, config, report_dir, template_name=template.name, params=params, structural_unit_ids=structural_unit_ids)
    if template.format == "xlsx":
        from .report_grid import build_xlsx_grid  # локальный импорт: report_grid не зависит от этого модуля

        return build_xlsx_grid(
            session, config, report_dir, template_name=template.name, params=params, structural_unit_ids=structural_unit_ids
        )
    raise ReportBuilderError(f"Неизвестный формат отчёта: {template.format}")


def preview_rows(session: Session, config: dict[str, Any], *, limit: int = 20) -> dict[str, Any]:
    """Быстрый предпросмотр докс-блоков-таблиц без сохранения файла — для формата xlsx
    предпросмотр строит report_grid.preview_grid() (другая, grid-based структура ответа)."""
    ctx = ReportContext(session)
    result: dict[str, Any] = {"sections": []}
    for block in block_tables(config.get("blocks") or []):
        headers = [c.get("header", "") for c in block.get("columns") or []]
        try:
            rows = _sheet_rows(ctx, block, {})
        except ReportBuilderError as e:
            result["sections"].append({"title": block.get("title", ""), "error": str(e)})
            continue
        result["sections"].append(
            {
                "title": block.get("title", ""),
                "headers": headers,
                "rows": rows[:limit],
                "total": len(rows),
            }
        )
    return result


def block_tables(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [b for b in blocks if b.get("type") == "table"]
