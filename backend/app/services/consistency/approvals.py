"""Одобрение проблем проверки данных: человек признаёт находку допустимой, и она перестаёт требовать внимания.

Одобрение привязано к отпечатку находки (`Finding.fingerprint`) и теряет силу, когда проблема меняется: у адреса появился ещё один
владелец, не хватает другого поля. Так же работает одобрение расхождений портов (services/connection_review.py) — «одобрено то, что
видел человек, а не всё, что будет с этим объектом потом». Одобрять можно только проблему, которая есть СЕЙЧАС: сервер сам находит
её по отпечатку и берёт снимок текста, а не доверяет тому, что прислал клиент.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...constants import AuditAction
from ...models import ConsistencyApproval
from ..actor_context import current_actor
from ..crud import audit
from .engine import run_checks

AUDIT_ENTITY = "consistency-approvals"
MAX_COMMENT_LENGTH = 1000
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def approval_to_dict(row: ConsistencyApproval) -> dict[str, Any]:
    return {"id": row.id, "comment": row.comment, "approved_by": row.approved_by, "approved_at": row.created_at.isoformat()}


def load_approvals(session: Session) -> dict[str, ConsistencyApproval]:
    """Все одобрения по отпечатку находки. Их немного (по одному на сознательно принятую проблему), поэтому читаем целиком."""
    return {row.fingerprint: row for row in session.scalars(select(ConsistencyApproval))}


def parse_fingerprint(value: object) -> str:
    if not isinstance(value, str) or not _FINGERPRINT.fullmatch(value):
        raise HTTPException(422, "Отпечаток проблемы должен быть строкой из 64 шестнадцатеричных символов (a–f, 0–9)")
    return value


def parse_comment(value: object) -> str | None:
    """Необязательный комментарий («почему допустимо»): пробелы по краям убираются, пустой — как отсутствующий."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise HTTPException(422, "Комментарий должен быть строкой")
    text = value.strip()
    if len(text) > MAX_COMMENT_LENGTH:
        raise HTTPException(422, f"Комментарий длиннее {MAX_COMMENT_LENGTH} символов")
    return text or None


def approve_finding(session: Session, fingerprint: object, comment: object = None) -> dict[str, Any]:
    """Одобряет текущую проблему с этим отпечатком. Повторное одобрение ничего не меняет (created=False, комментарий прежний).

    404, если такой проблемы сейчас нет: её исправили или она изменилась, пока экран был открыт, — клиент перечитывает проверку.
    """
    fingerprint = parse_fingerprint(fingerprint)
    note = parse_comment(comment)
    current = next((item for item in run_checks(session) if item.fingerprint == fingerprint), None)
    if current is None:
        raise HTTPException(404, "Такой проблемы уже нет или она изменилась — обновите проверку")
    existing = session.scalar(select(ConsistencyApproval).where(ConsistencyApproval.fingerprint == fingerprint))
    if existing:
        return {"created": False, "approval": approval_to_dict(existing)}
    row = ConsistencyApproval(
        id=str(uuid.uuid4()),
        fingerprint=fingerprint,
        rule=current.rule,
        entity_type=current.entity_type,
        entity_id=current.entity_id,
        entity_name=current.entity_name,
        message=current.message,
        comment=note,
        approved_by=current_actor.get().username,
    )
    session.add(row)
    details = f"Одобрена проблема проверки данных: {current.message}" + (f" Комментарий: {note}" if note else "")
    try:
        session.flush()  # уникальный отпечаток срабатывает уже здесь
        audit(session, AUDIT_ENTITY, row.id, AuditAction.CREATE, details)
        session.commit()
    except IntegrityError:
        # Два одобрения одной проблемы одновременно: уникальный отпечаток пропустил одно — второе получает его запись.
        session.rollback()
        existing = session.scalar(select(ConsistencyApproval).where(ConsistencyApproval.fingerprint == fingerprint))
        if existing is None:
            raise
        return {"created": False, "approval": approval_to_dict(existing)}
    session.refresh(row)
    return {"created": True, "approval": approval_to_dict(row)}


def revoke_approval(session: Session, approval_id: str) -> None:
    """Отзывает одобрение: проблема снова требует внимания (если она ещё есть). 404, если одобрения нет."""
    row = session.get(ConsistencyApproval, approval_id)
    if row is None:
        raise HTTPException(404, "Одобрение не найдено")
    audit(session, AUDIT_ENTITY, row.id, AuditAction.DELETE, f"Отозвано одобрение проблемы проверки данных: {row.message}")
    session.delete(row)
    session.commit()
