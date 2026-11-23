"""Проверки согласованности и полноты данных реестра: противоречия между записями и пробелы, из-за которых отчёт будет неполным.

Обработчики только разбирают запрос и вызывают services/consistency — вся логика там. Только чтение: ничего не исправляется.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.consistency import Category, Severity
from ..services.consistency.report import build_consistency_report, list_rules

router = APIRouter(tags=["Consistency"])


@router.get("/api/v1/integrity/consistency")
def consistency_report(
    rule: list[str] | None = Query(None, description="Коды правил; без параметра — все правила"),
    category: list[Category] | None = Query(None, description="consistency — противоречия, completeness — пробелы в данных"),
    severity: list[Severity] | None = Query(None, description="error, warning, info"),
    sheet: list[int] | None = Query(None, description="Лист отчёта (1–4) для проверок полноты"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db),
):
    """Находки проверок с фильтрами по правилу, категории, важности и листу отчёта. `summary` считается по всему выбору, а не
    по одной странице; `total` — число находок до разбиения на страницы. ok=True и пустой список — исправлять нечего."""
    return build_consistency_report(session, rules=rule, categories=category, severities=severity, sheets=sheet, limit=limit, offset=offset)


@router.get("/api/v1/integrity/consistency/rules")
def consistency_rules():
    """Каталог правил проверки: код, название, важность по умолчанию, категория и лист отчёта."""
    return list_rules()
