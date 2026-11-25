"""Проверки согласованности и полноты данных реестра: противоречия между записями и пробелы, из-за которых отчёт будет неполным.

Обработчики только разбирают запрос и вызывают services/consistency — вся логика там. Только чтение: ничего не исправляется.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.consistency import Category, Severity
from ..services.consistency.approvals import approve_finding, approve_findings, revoke_approval
from ..services.consistency.readiness import build_report_readiness
from ..services.consistency.report import build_consistency_report, list_rules
from .consistency_schemas import ApproveFindingBody, ApproveFindingsBody

router = APIRouter(tags=["Consistency"])


@router.get("/api/v1/integrity/consistency")
def consistency_report(
    rule: list[str] | None = Query(None, description="Коды правил; без параметра — все правила"),
    category: list[Category] | None = Query(None, description="consistency — противоречия, completeness — пробелы в данных"),
    severity: list[Severity] | None = Query(None, description="error, warning, info"),
    sheet: list[int] | None = Query(None, description="Лист отчёта (1–4) для проверок полноты"),
    approval: Literal["all", "active", "approved"] = Query("all", description="active — требуют внимания, approved — одобренные"),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db),
):
    """Находки проверок с фильтрами по правилу, категории, важности, листу отчёта и одобрению. `summary` считается по всему выбору, а не
    по одной странице; `total` — число находок до разбиения на страницы. ok=True и пустой список — исправлять нечего."""
    return build_consistency_report(
        session, rules=rule, categories=category, severities=severity, sheets=sheet, approval=approval, limit=limit, offset=offset
    )


@router.get("/api/v1/integrity/consistency/rules")
def consistency_rules():
    """Каталог правил проверки: код, название, важность по умолчанию, категория и лист отчёта."""
    return list_rules()


@router.post("/api/v1/integrity/consistency/approvals")
def approve_consistency_finding(body: ApproveFindingBody, session: Session = Depends(get_db)):
    """Одобряет проблему (признаёт допустимой) по отпечатку из отчёта. Повторное одобрение ничего не меняет. 404 — проблемы уже нет
    или она изменилась. Одобрение теряет силу, когда проблема меняется."""
    return approve_finding(session, body.fingerprint, body.comment)


@router.post("/api/v1/integrity/consistency/approvals/batch")
def approve_consistency_findings(body: ApproveFindingsBody, session: Session = Depends(get_db)):
    """Одобряет сразу несколько проблем одной транзакцией. Проблемы, которых уже нет или которые изменились, возвращаются в `missing`, а не
    отменяют остальные; уже одобренные считаются в `already`. За один запрос — не больше 500 отпечатков."""
    return approve_findings(session, body.fingerprints, body.comment)


@router.delete("/api/v1/integrity/consistency/approvals/{approval_id}", status_code=204)
def revoke_consistency_approval(approval_id: str, session: Session = Depends(get_db)):
    """Отзывает одобрение: проблема снова требует внимания."""
    return revoke_approval(session, approval_id)


@router.get("/api/v1/integrity/consistency/readiness")
def report_readiness(session: Session = Depends(get_db)):
    """Готовность отчёта: по каждому листу — сколько объектов не имеют незакрытых проблем проверки данных. Лист 3 пока не проверяется."""
    return build_report_readiness(session)
