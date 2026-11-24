"""Ответ API проверок согласованности: фильтры, сводка и постраничная выдача находок."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .approvals import approval_to_dict, load_approvals
from .engine import RULES, run_checks, summarize
from .model import SHEETS, Category, Severity

APPROVAL_FILTERS = ("all", "active", "approved")


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
    approval: str = "all",
    limit: int = 500,
    offset: int = 0,
) -> dict[str, Any]:
    """Запускает проверки и возвращает сводку по ВСЕМ находкам выбора и страницу находок `[offset, offset + limit)`.

    `approval` отбирает по одобрению: `active` — требуют внимания, `approved` — одобренные, `all` — все. У каждой находки есть
    `approved` и `approval` (кто, когда и зачем одобрил). `summary.by_approval` считается по выбору ДО отбора по одобрению, чтобы
    клиент видел оба числа при любом значении `approval`. `ok` — в выборке нет находок, требующих внимания.
    `total` — число находок до разбиения на страницы, `truncated` — есть ли находки за пределами возвращённой страницы.
    Неизвестный код правила, номер листа или значение `approval` — 422.
    """
    bad_sheets = sorted(set(sheets or ()) - set(SHEETS))
    if bad_sheets:
        raise HTTPException(status_code=422, detail=f"неизвестные листы отчёта: {bad_sheets}; допустимы {list(SHEETS)}")
    if approval not in APPROVAL_FILTERS:
        raise HTTPException(status_code=422, detail=f"неизвестный отбор по одобрению: {approval!r}; допустимы {list(APPROVAL_FILTERS)}")
    try:
        findings = run_checks(session, rules=rules, categories=categories, severities=severities, sheets=sheets)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    approvals = load_approvals(session)
    pairs = [(item, item.fingerprint) for item in findings]
    approved_count = sum(1 for _, fingerprint in pairs if fingerprint in approvals)
    by_approval = {"active": len(pairs) - approved_count, "approved": approved_count}
    if approval != "all":
        pairs = [(item, fingerprint) for item, fingerprint in pairs if (fingerprint in approvals) == (approval == "approved")]
    selected = [item for item, _ in pairs]
    page = pairs[offset : offset + limit]
    summary = summarize(selected)
    summary["by_approval"] = by_approval
    return {
        "ok": not any(fingerprint not in approvals for _, fingerprint in pairs),
        "total": len(selected),
        "returned": len(page),
        "truncated": offset + len(page) < len(selected),
        "summary": summary,
        "findings": [
            {
                **item.to_dict(),
                "approved": fingerprint in approvals,
                "approval": approval_to_dict(approvals[fingerprint]) if fingerprint in approvals else None,
            }
            for item, fingerprint in page
        ],
    }
