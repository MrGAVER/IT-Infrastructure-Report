"""Ответ API проверок согласованности: фильтры, сводка и постраничная выдача находок."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .engine import RULES, run_checks, summarize
from .model import SHEETS, Category, Severity


def list_rules() -> dict[str, Any]:
    """Каталог правил для фильтров на странице: код, название, важность по умолчанию, категория и лист отчёта."""
    return {"rules": [spec.describe() for spec in RULES.values()]}


def build_consistency_report(
    session: Session,
    *,
    rules: Collection[str] | None = None,
    categories: Collection[Category] | None = None,
    severities: Collection[Severity] | None = None,
    sheets: Collection[int] | None = None,
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    """Запускает проверки и возвращает сводку по ВСЕМ находкам выбора и страницу находок `[offset, offset + limit)`.

    `total` — число находок до разбиения на страницы, `truncated` — есть ли находки за пределами возвращённой страницы.
    Неизвестный код правила или номер листа — 422.
    """
    bad_sheets = sorted(set(sheets or ()) - set(SHEETS))
    if bad_sheets:
        raise HTTPException(status_code=422, detail=f"неизвестные листы отчёта: {bad_sheets}; допустимы {list(SHEETS)}")
    try:
        findings = run_checks(session, rules=rules, categories=categories, severities=severities, sheets=sheets)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    page = findings[offset : offset + limit]
    return {
        "ok": not findings,
        "total": len(findings),
        "returned": len(page),
        "truncated": offset + len(page) < len(findings),
        "summary": summarize(findings),
        "findings": [item.to_dict() for item in page],
    }
