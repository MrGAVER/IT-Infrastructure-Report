from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.audit_query import AuditQuery, MAX_SEARCH_LENGTH, list_audit_log

# Только чтение: журнал аудита изменяется исключительно самим приложением (crud.audit()).
router = APIRouter(prefix='/api/v1', tags=['Audit'])


@router.get('/audit-log')
def audit_log_page(
    q: str | None = Query(None, max_length=MAX_SEARCH_LENGTH),
    action: str | None = Query(None, max_length=50),
    entity_type: str | None = Query(None, max_length=100),
    offset: int = Query(0, ge=0),
    limit: int = Query(24, ge=1, le=200),
    session: Session = Depends(get_db),
):
    """Страница журнала аудита (новые сверху): поиск по деталям и id записи, фильтры по действию и
    разделу считаются на сервере. `total` — под теми же условиями; `summary` (всего и по действиям)
    и `entity_types` (разделы, встречающиеся в журнале) — по всему журналу."""
    return list_audit_log(session, AuditQuery(q=q, action=action, entity_type=entity_type), offset=offset, limit=limit)
