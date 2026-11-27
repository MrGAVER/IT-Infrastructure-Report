"""Одобрение проблем проверки данных: человек признаёт находку допустимой, и она перестаёт требовать внимания.

Одобрение привязано к отпечатку находки (`Finding.fingerprint`) и теряет силу, когда проблема меняется: у адреса появился ещё один
владелец, не хватает другого поля. Так же работает одобрение расхождений портов (services/connection_review.py) — «одобрено то, что
видел человек, а не всё, что будет с этим объектом потом». Одобрять можно только проблему, которая есть СЕЙЧАС: сервер сам находит
её по отпечатку и берёт снимок текста, а не доверяет тому, что прислал клиент.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...constants import AuditAction
from ...models import ConsistencyApproval
from ..actor_context import current_actor
from ..crud import audit
from ._support import chunked
from .engine import run_checks
from .model import Finding

AUDIT_ENTITY = "consistency-approvals"
MAX_COMMENT_LENGTH = 1000
# Предел пакетного одобрения за один запрос: ограничивает размер транзакции и записей в журнале аудита; клиент режет длинные списки сам.
MAX_BATCH = 500
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


def _new_approval(current: Finding, note: str | None) -> ConsistencyApproval:
    return ConsistencyApproval(
        id=str(uuid.uuid4()),
        fingerprint=current.fingerprint,
        rule=current.rule,
        entity_type=current.entity_type,
        entity_id=current.entity_id,
        entity_name=current.entity_name,
        message=current.message,
        comment=note,
        approved_by=current_actor.get().username,
    )


def _audit_text(current: Finding, note: str | None, *, batch: bool = False) -> str:
    kind = "Одобрена проблема проверки данных" + (" (пакетное одобрение)" if batch else "")
    return f"{kind}: {current.message}" + (f" Комментарий: {note}" if note else "")


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
    row = _new_approval(current, note)
    session.add(row)
    details = _audit_text(current, note)
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


def parse_fingerprints(value: object) -> list[str]:
    """Список отпечатков для пакетного одобрения: непустой, не длиннее MAX_BATCH; повторы убираются с сохранением порядка."""
    if not isinstance(value, list) or not value:
        raise HTTPException(422, "Нужен непустой список отпечатков проблем")
    if len(value) > MAX_BATCH:
        raise HTTPException(422, f"За один раз можно одобрить не больше {MAX_BATCH} проблем")
    return list(dict.fromkeys(parse_fingerprint(item) for item in value))


def approve_findings(session: Session, fingerprints: object, comment: object = None) -> dict[str, Any]:
    """Одобряет сразу несколько текущих проблем одной транзакцией и одним комментарием.

    Проблемы, которых уже нет или которые изменились (отпечаток не нашёлся), не одобряются, а возвращаются в `missing`; остальные
    одобряются — всё-или-ничего здесь вредило бы: из 200 выбранных одна исправленная проблема отменила бы остальные 199. Уже
    одобренные считаются в `already` и не дублируются. `approvals` — отпечаток → одобрение для всех одобренных (новых и прежних),
    чтобы клиент обновил строки без перечитывания проверки. Проверки запускаются один раз на весь список.
    """
    wanted = parse_fingerprints(fingerprints)
    note = parse_comment(comment)
    for attempt in (1, 2):
        current = {item.fingerprint: item for item in run_checks(session)}
        existing = load_approvals(session)
        created = [
            _new_approval(current[fingerprint], note) for fingerprint in wanted if fingerprint in current and fingerprint not in existing
        ]
        session.add_all(created)
        try:
            session.flush()  # уникальный отпечаток срабатывает уже здесь
            for row in created:
                audit(session, AUDIT_ENTITY, row.id, AuditAction.CREATE, _audit_text(current[row.fingerprint], note, batch=True))
            approvals = {fingerprint: approval_to_dict(existing[fingerprint]) for fingerprint in wanted if fingerprint in existing}
            approvals.update({row.fingerprint: approval_to_dict(row) for row in created})
            session.commit()
        except IntegrityError:
            # Параллельный запрос одобрил часть тех же проблем между чтением и записью: откатываем и считаем заново с их записями.
            session.rollback()
            if attempt == 2:
                raise
            continue
        return {
            "approved": len(created),
            "already": sum(1 for fingerprint in wanted if fingerprint in existing),
            "missing": [fingerprint for fingerprint in wanted if fingerprint not in current],
            "approvals": approvals,
        }
    raise AssertionError("недостижимо: вторая попытка либо возвращает результат, либо поднимает исключение")  # pragma: no cover


def stale_approvals(session: Session, findings: Iterable[Finding] | None = None) -> list[ConsistencyApproval]:
    """Одобрения, которым не соответствует ни одна текущая проблема: проблему исправили или она изменилась (отпечаток другой).

    Они ничего не скрывают, но подействуют снова, если точно такая же проблема появится вновь — поэтому их стоит убирать. Чтобы
    судить, нужен ПОЛНЫЙ набор текущих находок (все правила): по набору, суженному фильтрами, одобрение «исчезнувшей» проблемы
    нельзя отличить от одобрения проблемы, чьё правило просто не запускали. Без `findings` проверки запускаются здесь.
    """
    current = {item.fingerprint for item in (findings if findings is not None else run_checks(session))}
    return [row for fingerprint, row in load_approvals(session).items() if fingerprint not in current]


def remove_stale_approvals(session: Session) -> dict[str, int]:
    """Удаляет устаревшие одобрения одной транзакцией; на каждое — запись аудита. Что устарело, решает сервер, а не клиент."""
    rows = stale_approvals(session)
    for row in rows:
        audit(
            session,
            AUDIT_ENTITY,
            row.id,
            AuditAction.DELETE,
            f"Удалено устаревшее одобрение проблемы проверки данных (проблемы уже нет или она изменилась): {row.message}",
        )
        session.delete(row)
    session.commit()
    return {"removed": len(rows)}


def parse_ids(value: object) -> list[str]:
    """Идентификаторы одобрений для пакетного отзыва: непустой список не длиннее MAX_BATCH из непустых строк; повторы убираются."""
    if not isinstance(value, list) or not value:
        raise HTTPException(422, "Нужен непустой список идентификаторов одобрений")
    if len(value) > MAX_BATCH:
        raise HTTPException(422, f"За один раз можно отозвать не больше {MAX_BATCH} одобрений")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise HTTPException(422, "Идентификатор одобрения должен быть непустой строкой")
    return list(dict.fromkeys(value))


def revoke_approvals(session: Session, ids: object) -> dict[str, Any]:
    """Отзывает сразу несколько одобрений одной транзакцией; на каждое — запись аудита. Несуществующие (уже отозваны другим
    пользователем) возвращаются в `missing` и не мешают остальным."""
    wanted = parse_ids(ids)
    rows: dict[str, ConsistencyApproval] = {}
    for batch in chunked(wanted):
        rows.update({row.id: row for row in session.scalars(select(ConsistencyApproval).where(ConsistencyApproval.id.in_(batch)))})
    for approval_id in wanted:
        row = rows.get(approval_id)
        if row is not None:
            audit(
                session,
                AUDIT_ENTITY,
                row.id,
                AuditAction.DELETE,
                f"Отозвано одобрение проблемы проверки данных (пакетный отзыв): {row.message}",
            )
            session.delete(row)
    session.commit()
    return {"revoked": len(rows), "missing": [approval_id for approval_id in wanted if approval_id not in rows]}
