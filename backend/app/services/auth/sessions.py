"""Токены сессий: выпуск, проверка, отзыв и список активных сессий.

В БД хранится только sha256-хеш токена (AuthSession.token_hash); сам токен виден клиенту один раз — в ответе на вход.
Причины выбора непрозрачных токенов вместо JWT — в докстринге пакета (services/auth/__init__.py)."""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Optional

from fastapi import Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ...config import AUTH_SESSION_TTL_HOURS
from ...constants import MAX_SESSIONS_PER_USER
from ...models import AuthSession, User
from ..timeutil import iso_utc
from ._common import naive_utc_now


def _generate_token() -> str:
    return secrets.token_urlsafe(32)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(session: Session, user: User, *, request: Optional[Request] = None) -> str:
    """Заодно подчищает чужие истёкшие сессии (см. cleanup_expired_sessions) — ленивая уборка по
    месту, а не отдельный планировщик/cron: при нескольких процессах backend за одной БД (см.
    README, серверный вариант) каждый процесс подчищает независимо, DELETE идемпотентен — двум
    процессам, случайно попытавшимся убрать одну и ту же просроченную строку одновременно, ничего
    не грозит, второй просто удалит 0 строк. Без этого auth_sessions только растёт: строка
    сейчас удаляется явно лишь при logout или при попытке использовать именно этот истёкший
    токен (resolve_session) — большинство сессий тихо истекают, и это неизбежно копится."""
    cleanup_expired_sessions(session)
    # место под новую сессию: после входа у пользователя не больше MAX_SESSIONS_PER_USER
    _trim_user_sessions(session, user.id, keep=MAX_SESSIONS_PER_USER - 1)
    token = _generate_token()
    row = AuthSession(
        token_hash=_hash_token(token),
        user_id=user.id,
        expires_at=naive_utc_now() + timedelta(hours=AUTH_SESSION_TTL_HOURS),
        user_agent=(request.headers.get("user-agent", "")[:255] or None) if request else None,
        ip_address=(request.client.host if request and request.client else None),
    )
    session.add(row)
    session.commit()
    return token


def _trim_user_sessions(session: Session, user_id: str, *, keep: int) -> int:
    """Оставляет у пользователя не более `keep` самых новых сессий, остальные удаляет; возвращает число удалённых.

    Порядок — по времени создания, при равенстве по id, чтобы результат был детерминированным. Без коммита: его делает вызывающий
    create_session вместе с добавлением новой строки, и обрезка с входом либо проходят обе, либо ни одна."""
    # Одним запросом, без выборки лишних id в Python: при очень большом числе сессий список id в `IN (...)` упёрся бы в предел
    # параметров SQLite (999 в старых сборках). Подзапрос выбирает, какие сессии ОСТАЮТСЯ; keep=0 даёт пустой набор — удаляются все.
    keep_ids = (
        select(AuthSession.id)
        .where(AuthSession.user_id == user_id)
        .order_by(AuthSession.created_at.desc(), AuthSession.id.desc())
        .limit(max(keep, 0))
    )
    result = session.execute(delete(AuthSession).where(AuthSession.user_id == user_id, AuthSession.id.not_in(keep_ids)))
    return result.rowcount or 0


def cleanup_expired_sessions(session: Session) -> int:
    """Удаляет ВСЕ просроченные сессии (всех пользователей), не только текущего — вызывается на
    каждый логин (см. create_session). Возвращает количество удалённых строк (пригодится, если
    когда-нибудь понадобится залогировать/промониторить объём)."""
    result = session.execute(delete(AuthSession).where(AuthSession.expires_at < naive_utc_now()))
    session.commit()
    return result.rowcount or 0


def resolve_session(session: Session, token: str) -> Optional[User]:
    row = session.scalar(select(AuthSession).where(AuthSession.token_hash == _hash_token(token)))
    if row is None:
        return None
    if row.expires_at < naive_utc_now():
        session.delete(row)
        session.commit()
        return None
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return user


def revoke_session(session: Session, token: str) -> None:
    session.execute(delete(AuthSession).where(AuthSession.token_hash == _hash_token(token)))
    session.commit()


def revoke_all_sessions(session: Session, user_id: str, *, commit: bool = True) -> None:
    """commit=False — отзыв входит в транзакцию вызывающего (смена пароля, деактивация): коммит делает он, одним разом
    вместе с самим изменением и записью аудита."""
    session.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    if commit:
        session.commit()


def revoke_all_sessions_except(session: Session, user_id: str, keep_token: Optional[str], *, commit: bool = True) -> None:
    """Как revoke_all_sessions, но сохраняет одну сессию — ту, которой был вызван именно этот
    запрос (см. change_own_password). Иначе смена собственного пароля тут же выкидывала бы
    пользователя из только что открытой вкладки настроек."""
    stmt = delete(AuthSession).where(AuthSession.user_id == user_id)
    if keep_token:
        stmt = stmt.where(AuthSession.token_hash != _hash_token(keep_token))
    session.execute(stmt)
    if commit:
        session.commit()


def revoke_session_by_id(session: Session, user_id: str, session_id: str) -> bool:
    """Отзыв ОДНОЙ сессии по id, обязательно в рамках user_id — без этого условия пользователь
    мог бы подобрать чужой session_id и разлогинить произвольного человека. Возвращает False,
    если такой сессии нет (не найдена или принадлежит другому пользователю) — эндпоинт превращает
    это в 404, не различая эти два случая (чтобы не подтверждать существование чужих session_id)."""
    result = session.execute(delete(AuthSession).where(AuthSession.id == session_id, AuthSession.user_id == user_id))
    session.commit()
    return result.rowcount > 0


def list_active_sessions(session: Session, user_id: str) -> list[AuthSession]:
    return list(
        session.scalars(
            select(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.expires_at >= naive_utc_now())
            .order_by(AuthSession.created_at.desc())
        ).all()
    )


def serialize_session(row: AuthSession, *, current_token: Optional[str] = None) -> dict:
    return {
        "id": row.id,
        "created_at": iso_utc(row.created_at),
        "expires_at": iso_utc(row.expires_at),
        "user_agent": row.user_agent,
        "ip_address": row.ip_address,
        "current": bool(current_token) and row.token_hash == _hash_token(current_token),
    }
