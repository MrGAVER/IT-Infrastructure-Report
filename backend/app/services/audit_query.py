"""Серверная выборка журнала аудита для экрана «Журнал аудита»: поиск, фильтры, пагинация,
счётчики по действию и список разделов.

Раньше экран читал последние 1000 записей одним запросом и фильтровал/листал в браузере: журнал
только растёт, поэтому всё, что старше тысячи последних записей, было недоступно ни в таблице,
ни в счётчиках («Создано», «Удалено»…), а поиск шёл лишь по этим 1000. Теперь клиент держит одну
страницу, а `summary` и `entity_types` приходят по всему журналу независимо от фильтров.

Правила поиска те же, что были на клиенте: подстрока без учёта регистра в тексте деталей или в id
записи (для кириллицы в SQLite `LOWER()` подменён Unicode-aware, см. app/db.py). Порядок фиксирован
«новые сверху, затем id»: без второго ключа записи с одинаковым временем могли бы «переезжать»
между страницами при листании.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import Session

from ..models import AuditLog
from .serialization import serialize

MAX_SEARCH_LENGTH = 200


@dataclass(frozen=True)
class AuditQuery:
    q: str | None = None
    action: str | None = None
    entity_type: str | None = None


def _conditions(query: AuditQuery) -> list[ColumnElement[bool]]:
    result: list[ColumnElement[bool]] = []
    needle = (query.q or "").strip().lower()
    if needle:
        # autoescape: «%» и «_» из поля поиска — обычные символы, а не шаблон LIKE.
        result.append(
            or_(
                func.lower(AuditLog.details).contains(needle, autoescape=True),
                func.lower(AuditLog.entity_id).contains(needle, autoescape=True),
            )
        )
    if query.action:
        result.append(AuditLog.action == query.action)
    if query.entity_type:
        result.append(AuditLog.entity_type == query.entity_type)
    return result


def list_audit_log(session: Session, query: AuditQuery, *, offset: int, limit: int) -> dict[str, Any]:
    """Страница записей по условиям + total под теми же условиями + summary и entity_types по
    ВСЕМУ журналу (не зависят от поиска и фильтров)."""
    where = _conditions(query)
    total = session.scalar(select(func.count(AuditLog.id)).where(*where)) or 0
    rows = session.scalars(
        select(AuditLog).where(*where).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).offset(offset).limit(limit)
    ).all()
    return {
        "items": [serialize(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "summary": summarize_audit_log(session),
        "entity_types": audit_entity_types(session),
    }


def summarize_audit_log(session: Session) -> dict[str, Any]:
    """Сколько записей в журнале всего и по каждому действию (`by_action`: CREATE, UPDATE, DELETE,
    SYNC, LOGIN…). Один запрос по индексу action."""
    counts = {action: int(count) for action, count in session.execute(select(AuditLog.action, func.count(AuditLog.id)).group_by(AuditLog.action)).all()}
    return {"total": sum(counts.values()), "by_action": counts}


def audit_entity_types(session: Session) -> list[str]:
    """Разделы, которые реально встречаются в журнале, — для фильтра «Раздел» (вместо всех ~30
    ресурсов реестра, из которых в журнале бывает от силы десяток)."""
    return list(session.scalars(select(AuditLog.entity_type).distinct().order_by(AuditLog.entity_type)).all())
