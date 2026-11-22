"""Блокировка учётной записи после серии неверных паролей — общая для входа и смены пароля.

Счётчик неудач считается атомарным UPDATE в самой БД, при пороге AUTH_MAX_FAILED_ATTEMPTS запись блокируется на
AUTH_LOCKOUT_MINUTES, каждая неудача попадает в журнал аудита. Троттлинг по адресу и логину (в памяти процесса) — отдельная
защита, она живёт рядом со входом (auth/login.py)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...config import AUTH_KNOWN_CLIENT_DAYS, AUTH_LOCKOUT_MINUTES, AUTH_MAX_FAILED_ATTEMPTS
from ...constants import AuditAction, ErrorCode
from ...models import AuditLog, User
from ..actor_context import Actor
from ..crud import audit


def _increment_failed_attempts(session: Session, user_id: str) -> int:
    """Атомарный `UPDATE ... SET failed_attempts = failed_attempts + 1` в самой БД — а не
    read-modify-write в Python (было: `user.failed_attempts += 1; session.commit()`). При
    нескольких процессах backend за общей БД (см. README — серверный вариант, Docker+PostgreSQL)
    два параллельных неверных пароля от ОДНОГО пользователя, обработанные разными процессами
    почти одновременно, иначе могли оба прочитать один и тот же старый счётчик и оба записать
    n+1 вместо n+2 — теряя попытку из порога AUTH_MAX_FAILED_ATTEMPTS. Postgres выполняет такой
    UPDATE атомарно на уровне строки независимо от уровня изоляции; на SQLite вопрос не стоит —
    она и так сериализует писателей на уровне файла БД целиком. Возвращает значение после
    инкремента (отдельным SELECT, не RETURNING — совместимо со старыми сборками SQLite)."""
    session.execute(update(User).where(User.id == user_id).values(failed_attempts=User.failed_attempts + 1))
    session.commit()
    return session.scalar(select(User.failed_attempts).where(User.id == user_id)) or 0


def is_known_client(session: Session, user_id: str, client_ip: Optional[str], now: datetime) -> bool:
    """Входил ли этот пользователь успешно с этого адреса за последние AUTH_KNOWN_CLIENT_DAYS дней.

    Источник — записи LOGIN журнала аудита (в них хранится адрес входа), а не таблица сессий: просроченные сессии удаляются при
    каждом входе любого пользователя (cleanup_expired_sessions), так что «память» об адресе жила бы часы, а не дни. Журнал только
    растёт. Неизвестный адрес (нет данных о клиенте) знакомым не считается; неудачные входы и чужие входы с того же адреса — тоже."""
    if not client_ip:
        return False
    since = now - timedelta(days=AUTH_KNOWN_CLIENT_DAYS)
    found = session.scalar(
        select(AuditLog.id)
        .where(
            AuditLog.action == AuditAction.LOGIN,
            AuditLog.entity_type == "auth",
            AuditLog.actor_id == user_id,
            AuditLog.actor_ip == client_ip,
            AuditLog.created_at >= since,
        )
        .limit(1)
    )
    return found is not None


def account_locked(locked_until: datetime, now: datetime) -> HTTPException:
    remaining_minutes = max(1, int((locked_until - now).total_seconds() // 60) + 1)
    return HTTPException(
        423,
        {
            "message": (
                "Учётная запись временно заблокирована после серии неудачных попыток входа. Повторите попытку через "
                f"{remaining_minutes} мин."
            ),
            "code": ErrorCode.ACCOUNT_LOCKED,
        },
    )


def register_failed_password(
    session: Session,
    user: User,
    *,
    details: str,
    now: datetime,
    actor: Optional[Actor] = None,
) -> bool:
    """Учёт неверного пароля — общий для входа и смены пароля: атомарный инкремент `failed_attempts`, блокировка учётной записи на
    AUTH_LOCKOUT_MINUTES при достижении AUTH_MAX_FAILED_ATTEMPTS, запись LOGIN_FAILED в журнал аудита. Возвращает True, если эта
    попытка заблокировала учётную запись. actor не передан — автор берётся из контекста запроса (см. crud.audit)."""
    new_attempts = _increment_failed_attempts(session, user.id)
    locked_now = new_attempts >= AUTH_MAX_FAILED_ATTEMPTS
    if locked_now:
        # Тоже атомарный UPDATE, не user.locked_until = ...; session.commit() — user здесь
        # уже мог устареть относительно счётчика, только что изменённого выше отдельным
        # запросом (см. _increment_failed_attempts); пишем оба поля явным UPDATE по id.
        session.execute(
            update(User)
            .where(User.id == user.id)
            .values(
                locked_until=now + timedelta(minutes=AUTH_LOCKOUT_MINUTES),
                failed_attempts=0,
            )
        )
        session.commit()
    audit(
        session, "auth", user.id, AuditAction.LOGIN_FAILED, details + (" — учётная запись заблокирована" if locked_now else ""), actor=actor
    )
    session.commit()
    return locked_now
