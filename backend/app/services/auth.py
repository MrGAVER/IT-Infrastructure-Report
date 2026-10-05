"""Аутентификация/авторизация: хеширование паролей, непрозрачные токены сессий, блокировка после
серии неудачных попыток входа, и единая точка контроля доступа — ASGI-middleware auth_gate_middleware
(регистрируется в main.py).

Архитектурные решения:
- Токен сессии — случайная строка (secrets.token_urlsafe), а не JWT. В БД хранится только её
  sha256-хеш (AuthSession.token_hash), сам токен виден клиенту ровно один раз — в ответе на
  /api/v1/auth/login. Это делает logout/принудительный сброс сессий тривиальным (удалить строку),
  не требует секретного ключа подписи и не хранит в БД ничего, что само по себе годится для входа —
  в отличие от JWT, кража дампа БД не даёт готовых к использованию токенов.
- Пароли — hashlib.pbkdf2_hmac(sha256), самоописывающийся формат хеша (см. hash_password) без
  сторонних библиотек: requirements.txt проекта сознательно короткий, а bcrypt/argon2 — это ещё и
  нативные расширения, которые дороже поддерживать в PyInstaller-сборке (infra_registry.spec).
- Единая точка применения — HTTP-middleware в main.py, а не Depends() на каждом роутере: бизнес-
  роутеры (devices.py, resources.py, report_builder.py, часть system.py) сегодня ничего не знают
  про аутентификацию, и не должны — добавление/выключение фичи не требует трогать их сигнатуры.
  Middleware решает по пути и методу запроса, не заглядывая в конкретный роутер.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import math
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import db as db_module
from ..config import (
    AUTH_LOCKOUT_MINUTES,
    AUTH_MAX_FAILED_ATTEMPTS,
    AUTH_MIN_PASSWORD_LENGTH,
    AUTH_SESSION_TTL_HOURS,
    CSP_POLICY,
    SETUP_TOKEN,
)
from ..constants import AuditAction, ErrorCode, UserRole
from ..models import AuthSession, AuthSettings, User
from .actor_context import Actor, current_actor
from .crud import audit
from .login_throttle import LoginThrottle

__all__ = ["Actor", "current_actor"]  # реэкспорт: тесты и роутеры берут актора отсюда

# ---------------------------------------------------------------------------
# Время: SQLite/SQLAlchemy отбрасывают tzinfo при round-trip через DateTime без
# timezone=True (проверено эмпирически), поэтому все datetime здесь — naive UTC.
# Сравнение naive с aware кидает TypeError, а не тихо считает их равными — лучше
# держать всё в одном представлении, чем ловить это в проде на первой проверке
# истечения сессии.
# ---------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Пароли
# ---------------------------------------------------------------------------
PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000  # рекомендация OWASP для PBKDF2-HMAC-SHA256; хеши с меньшим числом итераций пересчитываются при входе
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """'<алгоритм>$<итерации>$<соль-b64>$<хеш-b64>' — самоописывающийся формат: при повышении
    PBKDF2_ITERATIONS в будущей версии старые хеши не ломаются, а прозрачно пересчитываются на
    следующий успешный вход (см. _needs_rehash + authenticate)."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    """hmac.compare_digest — таймингобезопасное сравнение: посимвольный '==' на разной длине
    совпадения давал бы микроскопическую, но реальную для локальной сети утечку через тайминг."""
    try:
        algorithm, iterations_s, salt_b64, hash_b64 = stored.split("$")
        if algorithm != PBKDF2_ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        iterations = int(iterations_s)
    except (ValueError, TypeError):
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(candidate, expected)


def _needs_rehash(stored: str) -> bool:
    try:
        algorithm, iterations_s, _salt, _hash = stored.split("$")
        return algorithm != PBKDF2_ALGORITHM or int(iterations_s) < PBKDF2_ITERATIONS
    except ValueError:
        return True


def validate_password_strength(password: str, *, username: Optional[str] = None) -> None:
    if len(password) < AUTH_MIN_PASSWORD_LENGTH:
        raise HTTPException(422, {
            "message": f"Пароль должен быть не короче {AUTH_MIN_PASSWORD_LENGTH} символов.",
            "code": ErrorCode.WEAK_PASSWORD,
        })
    if username and password.casefold() == username.strip().casefold():
        raise HTTPException(422, {
            "message": "Пароль не должен совпадать с именем пользователя.",
            "code": ErrorCode.WEAK_PASSWORD,
        })
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        raise HTTPException(422, {
            "message": "Пароль должен содержать и буквы, и цифры.",
            "code": ErrorCode.WEAK_PASSWORD,
        })


# ---------------------------------------------------------------------------
# Пользователи
# ---------------------------------------------------------------------------
def find_user_by_username(session: Session, username: str) -> Optional[User]:
    """Регистронезависимый поиск на стороне Python, а не через SQL lower() — тот же принцип, что
    в миграциях/бэкфиллах справочников (SQLite lower() не умеет в кириллицу; см. память проекта).
    Таблица пользователей на практике маленькая (единицы-десятки учётных записей), полный перебор
    дешевле, чем заводить ради этого объёма регистронезависимый индекс."""
    normalized = username.strip().casefold()
    if not normalized:
        return None
    for user in session.scalars(select(User)).all():
        if user.username.casefold() == normalized:
            return user
    return None


def _lock_active_admins(session: Session) -> list[User]:
    """SELECT ... FOR UPDATE по ВСЕМ активным администраторам (не исключая никого) — задел на
    многопроцессный деплой (см. README: серверный вариант — Docker + PostgreSQL, несколько
    процессов backend за одной БД). Без блокировки строк «проверить количество, затем изменить»
    — это классический TOCTOU: два администратора A и B, каждый на СВОЁМ процессе одновременно
    разжалуют/удаляют себя или друг друга — оба параллельно читают «остался ещё один админ» (видя
    ДРУГ ДРУГА как безопасную гарантию) и оба проходят проверку, итог — ноль администраторов.

    Лочить нужно ВЕСЬ набор активных админов, а не «остальных, кроме текущего» — иначе транзакция
    над A блокирует только строку B, транзакция над B блокирует только строку A: блокировки не
    пересекаются, гонка никуда не уходит. Блокируя одинаковый набор строк в обеих транзакциях,
    вторая обязана дождаться коммита первой и затем увидит уже актуальное (после первого
    изменения) состояние — что и требуется для корректной проверки.

    На SQLite FOR UPDATE — безопасный no-op (проверено эмпирически, диалект просто не рендерит
    предложение): гонка там и так невозможна — SQLite сериализует писателей на уровне файла БД
    целиком, а не по строкам. Полноценный эффект блокировки нужен и проявляется только на
    PostgreSQL при нескольких одновременно пишущих процессах/инстансах backend."""
    return list(session.scalars(
        select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True)).with_for_update()
    ).all())


def ensure_not_last_admin(session: Session, user: User) -> None:
    """Запрещает удалить/деактивировать/понизить в правах единственную оставшуюся активную
    учётную запись администратора — иначе при включённой аутентификации администрировать её
    (в т.ч. снова выключить переключатель) стало бы физически некому, включая того, кто совершает
    это действие. Вызывающий должен находиться в той же транзакции, что и последующая мутация
    (см. _lock_active_admins) — только тогда блокировка строк реально что-то гарантирует."""
    if user.role != UserRole.ADMIN or not user.is_active:
        return
    remaining_others = sum(1 for admin in _lock_active_admins(session) if admin.id != user.id)
    if remaining_others == 0:
        raise HTTPException(400, {
            "message": "Нельзя удалить или лишить прав последнего активного администратора.",
            "code": ErrorCode.LAST_ADMIN_ACCOUNT,
        })


def create_user(session: Session, *, username: str, password: str, role: str) -> User:
    username = username.strip()
    if not username:
        raise HTTPException(422, "Имя пользователя не может быть пустым")
    if role not in UserRole.ALL:
        raise HTTPException(422, f"Недопустимая роль: {role!r}")
    if find_user_by_username(session, username) is not None:
        raise HTTPException(409, {"message": f"Пользователь «{username}» уже существует.", "code": ErrorCode.DUPLICATE_USERNAME})
    validate_password_strength(password, username=username)
    user = User(username=username, password_hash=hash_password(password), role=role, is_active=True)
    session.add(user)
    session.commit()
    session.refresh(user)
    audit(session, "users", user.id, AuditAction.CREATE, f"Создана учётная запись «{username}» (роль: {role})")
    session.commit()
    return user


def update_user(
    session: Session, user: User, *,
    username: Optional[str] = None, password: Optional[str] = None,
    role: Optional[str] = None, is_active: Optional[bool] = None,
) -> User:
    if role is not None and role not in UserRole.ALL:
        raise HTTPException(422, f"Недопустимая роль: {role!r}")
    demoting = (role is not None and role != UserRole.ADMIN and user.role == UserRole.ADMIN) or (is_active is False)
    if demoting:
        ensure_not_last_admin(session, user)

    changes: list[str] = []
    if username is not None:
        new_username = username.strip()
        if not new_username:
            raise HTTPException(422, "Имя пользователя не может быть пустым")
        existing = find_user_by_username(session, new_username)
        if existing is not None and existing.id != user.id:
            raise HTTPException(409, {"message": f"Пользователь «{new_username}» уже существует.", "code": ErrorCode.DUPLICATE_USERNAME})
        if new_username != user.username:
            changes.append(f"имя: «{user.username}» → «{new_username}»")
            user.username = new_username
    if role is not None and role != user.role:
        changes.append(f"роль: «{user.role}» → «{role}»")
        user.role = role
    if is_active is not None and is_active != user.is_active:
        changes.append("активирована" if is_active else "деактивирована")
        user.is_active = is_active
    security_sensitive = is_active is False
    if password is not None:
        validate_password_strength(password, username=user.username)
        user.password_hash = hash_password(password)
        user.failed_attempts = 0
        user.locked_until = None
        changes.append("сменён пароль")
        security_sensitive = True

    session.commit()
    session.refresh(user)
    if changes:
        audit(session, "users", user.id, AuditAction.UPDATE, "; ".join(changes))
        session.commit()
    if security_sensitive:
        # Смена пароля или деактивация должны немедленно аннулировать уже выданные токены —
        # иначе украденный/оставленный открытым токен продолжал бы работать до истечения TTL.
        revoke_all_sessions(session, user.id)
    return user


def delete_user(session: Session, user: User) -> None:
    ensure_not_last_admin(session, user)
    username = user.username
    session.delete(user)  # ON DELETE CASCADE (AuthSession.user_id) снимает и его сессии
    audit(session, "users", user.id, AuditAction.DELETE, f"Удалена учётная запись «{username}»")
    session.commit()


def change_own_password(
    session: Session, user: User, *, current_password: str, new_password: str, keep_token: Optional[str] = None,
) -> User:
    """Самостоятельная смена ПОЛЬЗОВАТЕЛЕМ СВОЕГО пароля — доступна любой роли, включая viewer
    (см. ROLE_CHECK_EXEMPT_PATHS), в отличие от update_user (смена ЧУЖОГО пароля — только admin).
    Требует текущий пароль: иначе кратковременно угнанная сессия (расшаренный компьютер,
    забытая открытой вкладка) позволяла бы захватить учётку насовсем, просто задав новый пароль.
    keep_token — токен запроса, которым вызвана сама эта смена: его сессия не отзывается, иначе
    пользователь тут же вылетел бы из только что открытой вкладки настроек; отзываются все
    ОСТАЛЬНЫЕ его сессии — тот же принцип, что и при смене пароля администратором в update_user."""
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(401, "Текущий пароль указан неверно.")
    validate_password_strength(new_password, username=user.username)
    user.password_hash = hash_password(new_password)
    user.failed_attempts = 0
    user.locked_until = None
    session.commit()
    session.refresh(user)
    audit(session, "users", user.id, AuditAction.UPDATE, f"«{user.username}» сменил(а) собственный пароль")
    session.commit()
    revoke_all_sessions_except(session, user.id, keep_token)
    return user


def serialize_user(user: User) -> dict:
    """Публичное представление пользователя — намеренно без password_hash/failed_attempts."""
    return {
        "id": user.id, "username": user.username, "role": user.role, "is_active": user.is_active,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "locked": bool(user.locked_until and user.locked_until > _now()),
        "created_at": user.created_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Настройки (тумблер) и bootstrap
# ---------------------------------------------------------------------------
def get_or_create_auth_settings(session: Session) -> AuthSettings:
    row = session.get(AuthSettings, "singleton")
    if row is not None:
        return row
    row = AuthSettings(id="singleton", enabled=False)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        # Гонка на самом первом запросе к пустой БД: два конкурентных запроса не увидели строку
        # и оба попытались её создать — проигравший просто перечитывает то, что вставил первый.
        session.rollback()
        row = session.get(AuthSettings, "singleton")
    else:
        session.refresh(row)
    return row


def set_auth_enabled(session: Session, enabled: bool, *, actor: Optional[User] = None) -> AuthSettings:
    settings_row = get_or_create_auth_settings(session)
    if enabled and not settings_row.enabled and len(_lock_active_admins(session)) == 0:
        raise HTTPException(400, {
            "message": "Нельзя включить аутентификацию: сначала создайте хотя бы одного активного "
                       "пользователя с ролью «Администратор» (раздел «Пользователи» в настройках).",
            "code": ErrorCode.AUTH_REQUIRES_ADMIN,
        })
    if settings_row.enabled != enabled:
        settings_row.enabled = enabled
        session.commit()
        session.refresh(settings_row)
        who = f" ({actor.username})" if actor else ""
        audit(session, "auth", "singleton", AuditAction.UPDATE, f"Аутентификация {'включена' if enabled else 'выключена'}{who}")
        session.commit()
    return settings_row


# ---------------------------------------------------------------------------
# Токены сессий
# ---------------------------------------------------------------------------
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
    token = _generate_token()
    row = AuthSession(
        token_hash=_hash_token(token),
        user_id=user.id,
        expires_at=_now() + timedelta(hours=AUTH_SESSION_TTL_HOURS),
        user_agent=(request.headers.get("user-agent", "")[:255] or None) if request else None,
        ip_address=(request.client.host if request and request.client else None),
    )
    session.add(row)
    session.commit()
    return token


def cleanup_expired_sessions(session: Session) -> int:
    """Удаляет ВСЕ просроченные сессии (всех пользователей), не только текущего — вызывается на
    каждый логин (см. create_session). Возвращает количество удалённых строк (пригодится, если
    когда-нибудь понадобится залогировать/промониторить объём)."""
    result = session.execute(delete(AuthSession).where(AuthSession.expires_at < _now()))
    session.commit()
    return result.rowcount or 0


def resolve_session(session: Session, token: str) -> Optional[User]:
    row = session.scalar(select(AuthSession).where(AuthSession.token_hash == _hash_token(token)))
    if row is None:
        return None
    if row.expires_at < _now():
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


def revoke_all_sessions(session: Session, user_id: str) -> None:
    session.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    session.commit()


def revoke_all_sessions_except(session: Session, user_id: str, keep_token: Optional[str]) -> None:
    """Как revoke_all_sessions, но сохраняет одну сессию — ту, которой был вызван именно этот
    запрос (см. change_own_password). Иначе смена собственного пароля тут же выкидывала бы
    пользователя из только что открытой вкладки настроек."""
    stmt = delete(AuthSession).where(AuthSession.user_id == user_id)
    if keep_token:
        stmt = stmt.where(AuthSession.token_hash != _hash_token(keep_token))
    session.execute(stmt)
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
    return list(session.scalars(
        select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.expires_at >= _now())
        .order_by(AuthSession.created_at.desc())
    ).all())


def serialize_session(row: AuthSession, *, current_token: Optional[str] = None) -> dict:
    return {
        "id": row.id, "created_at": row.created_at.isoformat() if row.created_at else None,
        "expires_at": row.expires_at.isoformat(), "user_agent": row.user_agent, "ip_address": row.ip_address,
        "current": bool(current_token) and row.token_hash == _hash_token(current_token),
    }


# ---------------------------------------------------------------------------
# Вход: блокировка после серии неудачных попыток
# ---------------------------------------------------------------------------
# Один на процесс: состояние троттлинга (см. services/login_throttle.py) живёт в памяти.
login_throttle = LoginThrottle()


def _invalid_credentials() -> HTTPException:
    """Новый экземпляр на каждый отказ: повторный raise одного и того же объекта накапливал бы в нём
    traceback всех прошлых отказов (утечка памяти и чужие стеки в логах)."""
    return HTTPException(401, "Неверное имя пользователя или пароль.")


def _client_ip(request: Optional[Request]) -> Optional[str]:
    return request.client.host if request is not None and request.client else None


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


def authenticate(session: Session, username: str, password: str, *, request: Optional[Request] = None) -> tuple[User, str]:
    """Возвращает (пользователь, токен сессии) либо кидает HTTPException. Намеренно не различает
    в тексте ошибки «нет такого пользователя» и «неверный пароль» (защита от перебора логинов) —
    но блокировка (423) неизбежно подтверждает существование аккаунта, это осознанный компромисс
    между защитой от перебора паролей и полной анонимностью логинов."""
    client_ip = _client_ip(request)
    throttle_key = (client_ip, username.strip().casefold())
    wait = login_throttle.retry_after(throttle_key)
    if wait > 0:
        # До любой работы с БД и хешированием: отбиваем перебор дёшево, не тратя CPU на PBKDF2.
        retry_after = max(1, math.ceil(wait))
        raise HTTPException(
            429,
            {
                "message": f"Слишком много неудачных попыток входа. Повторите через {retry_after} с.",
                "code": ErrorCode.TOO_MANY_ATTEMPTS,
            },
            headers={"Retry-After": str(retry_after)},
        )

    user = find_user_by_username(session, username)
    if user is None or not user.is_active:
        # Тратим примерно то же время, что и на реальную проверку пароля — чтобы «нет такого
        # пользователя» не отвечал заметно быстрее «пароль неверный» (ещё один timing-сигнал).
        hash_password(password)
        login_throttle.record_failure(throttle_key)
        raise _invalid_credentials()

    now = _now()
    if user.locked_until and user.locked_until > now:
        remaining_minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise HTTPException(423, {
            "message": f"Учётная запись временно заблокирована после серии неудачных попыток входа. "
                       f"Повторите попытку через {remaining_minutes} мин.",
            "code": ErrorCode.ACCOUNT_LOCKED,
        })

    if not verify_password(password, user.password_hash):
        new_attempts = _increment_failed_attempts(session, user.id)
        locked_now = new_attempts >= AUTH_MAX_FAILED_ATTEMPTS
        if locked_now:
            # Тоже атомарный UPDATE, не user.locked_until = ...; session.commit() — user здесь
            # уже мог устареть относительно счётчика, только что изменённого выше отдельным
            # запросом (см. _increment_failed_attempts); пишем оба поля явным UPDATE по id.
            session.execute(update(User).where(User.id == user.id).values(
                locked_until=now + timedelta(minutes=AUTH_LOCKOUT_MINUTES), failed_attempts=0,
            ))
            session.commit()
        login_throttle.record_failure(throttle_key)
        audit(session, "auth", user.id, AuditAction.LOGIN_FAILED,
              f"Неудачная попытка входа «{user.username}»" + (" — учётная запись заблокирована" if locked_now else ""),
              actor=Actor(user.id, user.username, client_ip))
        session.commit()
        raise _invalid_credentials()

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    if _needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    session.commit()

    login_throttle.reset(throttle_key)
    token = create_session(session, user, request=request)
    audit(session, "auth", user.id, AuditAction.LOGIN, f"Вход «{user.username}»", actor=Actor(user.id, user.username, client_ip))
    session.commit()
    return user, token


# ---------------------------------------------------------------------------
# Middleware: единая точка применения доступа для /api/*
# ---------------------------------------------------------------------------
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Публичны всегда, независимо от AuthSettings.enabled — без них не работает ни health-check,
# ни сама форма логина, ни виджет "включена ли аутентификация" на экране входа.
PUBLIC_API_PATHS = frozenset({"/api/v1/health", "/api/v1/auth/status", "/api/v1/auth/login"})

# Исключения из проверки роли на запись — действия, которые обязаны быть доступны ЛЮБОЙ
# аутентифицированной роли, включая viewer, которому в остальном запрещены методы записи:
# выйти из своей же сессии, сменить свой же пароль, отозвать свою же сессию из списка.
ROLE_CHECK_EXEMPT_PATHS = frozenset({"/api/v1/auth/logout", "/api/v1/auth/me/password"})
ROLE_CHECK_EXEMPT_PREFIXES = ("/api/v1/auth/sessions/",)


def _is_role_check_exempt(path: str) -> bool:
    return path in ROLE_CHECK_EXEMPT_PATHS or path.startswith(ROLE_CHECK_EXEMPT_PREFIXES)


# POST-запросы, которые данных реестра не меняют: они только формируют файл отчёта или предпросмотр, а
# метод POST выбран из-за тела запроса (параметры, выбор структурных единиц). Роль viewer («только чтение»)
# должна уметь формировать отчёты — иначе просмотр без выгрузки теряет смысл. Допускаются точные пути:
# создание, правка, удаление и дублирование шаблонов, как и /seed, остаются только для администратора.
READ_ONLY_POST_PATHS = frozenset({
    "/api/v1/reports/inventory",
    "/api/v1/reports/audit-log",
    "/api/v1/report-builder/preview",
})
_TEMPLATE_GENERATE_PATH = re.compile(r"^/api/v1/report-templates/[^/]+/generate$")


def _is_read_only_post(method: str, path: str) -> bool:
    if method != "POST":
        return False
    return path in READ_ONLY_POST_PATHS or _TEMPLATE_GENERATE_PATH.match(path) is not None


def _extract_bearer_token(header_value: Optional[str]) -> Optional[str]:
    if not header_value or not header_value.startswith("Bearer "):
        return None
    token = header_value[len("Bearer "):].strip()
    return token or None


_SECURITY_HEADERS = {
    # Базовый набор против MIME-sniffing и кликджекинга для встроенного Vue-интерфейса.
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}

# Swagger UI/ReDoc подгружают скрипты и стили со сторонних CDN — строгая политика сломала бы
# страницы документации, а данных реестра на них нет.
_CSP_EXEMPT_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect", "/openapi.json"})


def _with_security_headers(response, path: str = ""):
    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    # Content-Security-Policy — второй рубеж после DOMPurify: токен сессии лежит в localStorage, и любая
    # XSS означала бы его кражу. Политику можно заменить или отключить через INFRA_REGISTRY_CSP
    # (см. config.CSP_POLICY) — например, когда её выставляет обратный прокси.
    if CSP_POLICY and path not in _CSP_EXEMPT_PATHS:
        response.headers.setdefault("Content-Security-Policy", CSP_POLICY)
    return response


async def auth_gate_middleware(request: Request, call_next):
    """Раздача Vue-оболочки (`/`, `/assets/*`, SPA-фоллбэк в main.py) не проходит проверку
    доступа — статика всегда отдаётся, экран логина рисует сам Vue-роутер на клиенте (см.
    frontend-vue/src/router/index.ts). Контроль — только над `/api/*`, и только над данными, а не
    над тем, загрузится ли вообще интерфейс. Базовые security-заголовки (см. _SECURITY_HEADERS)
    добавляются на ВСЕ ответы, включая статику и короткое замыкание на 401/403.

    request.state.user / request.state.auth_enabled выставляются здесь для ЛЮБОГО запроса к
    /api/* (в т.ч. публичных) — api/auth.py читает их напрямую вместо повторного похода в БД.

    На время запроса выставляется current_actor (адрес клиента, а после проверки токена — ещё и
    пользователь): из него crud.audit() берёт автора действия для журнала аудита."""
    path = request.url.path
    if not path.startswith("/api/"):
        return _with_security_headers(await call_next(request), path)

    actor_token = current_actor.set(Actor(ip=_client_ip(request)))
    try:
        response = await _gate_api_request(request, call_next)
    finally:
        current_actor.reset(actor_token)
    return _with_security_headers(response, path)


async def _gate_api_request(request: Request, call_next):
    path = request.url.path
    # db_module.SessionLocal, а не `from ..db import SessionLocal` в заголовке файла: это
    # мидлварь, а не FastAPI Depends — тесты (backend/tests/conftest.py:client) подменяют
    # SessionLocal через monkeypatch.setattr(app.db, "SessionLocal", ...) на своё in-memory
    # StaticPool-соединение, а `from X import Y` создал бы отдельную, непропатчиваемую ссылку.
    db_session = db_module.SessionLocal()
    try:
        settings_row = get_or_create_auth_settings(db_session)
        request.state.auth_enabled = settings_row.enabled
        request.state.user = None

        if not settings_row.enabled or path in PUBLIC_API_PATHS:
            return await call_next(request)

        token = _extract_bearer_token(request.headers.get("authorization"))
        user = resolve_session(db_session, token) if token else None
        if user is None:
            return JSONResponse({"detail": "Требуется аутентификация."}, status_code=401)
        request.state.user = user
        current_actor.set(Actor(user.id, user.username, _client_ip(request)))

        if (
            user.role != UserRole.ADMIN
            and request.method in WRITE_METHODS
            and not _is_role_check_exempt(path)
            and not _is_read_only_post(request.method, path)
        ):
            return JSONResponse({"detail": "Недостаточно прав: требуется роль администратора."}, status_code=403)
    finally:
        db_session.close()

    return await call_next(request)


# Заголовки, которые добавляет обратный прокси: если они есть, TCP-адрес клиента — это адрес прокси,
# а не пользователя, и «пришёл с localhost» ничего не доказывает.
_PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip")
_LOCALHOST_ADDRESSES = frozenset({"127.0.0.1", "::1", "::ffff:127.0.0.1"})


def _is_direct_localhost(request: Request) -> bool:
    client = request.client
    if client is None or client.host not in _LOCALHOST_ADDRESSES:
        return False
    return not any(header in request.headers for header in _PROXY_HEADERS)


def require_setup_access(request: Request) -> None:
    """Первичная настройка аутентификации (пока она выключена): создание пользователей и сам
    переключатель. Без этой проверки любой, кто достаёт до порта, мог создать администратора, включить
    аутентификацию и тем самым закрыть реестр от его владельца.

    Пускаем либо по токену установки (INFRA_REGISTRY_SETUP_TOKEN, заголовок X-Setup-Token) — если он
    задан, то он нужен всем, включая localhost, — либо, если токена нет, только прямое соединение с
    localhost без прокси-заголовков. Остальной реестр при выключенной аутентификации по-прежнему открыт.
    """
    if SETUP_TOKEN:
        supplied = request.headers.get("x-setup-token", "")
        if hmac.compare_digest(supplied.encode("utf-8"), SETUP_TOKEN.encode("utf-8")):
            return
    elif _is_direct_localhost(request):
        return
    raise HTTPException(403, {
        "message": "Первичная настройка аутентификации доступна только с localhost или по токену установки "
                   "(заголовок X-Setup-Token, переменная INFRA_REGISTRY_SETUP_TOKEN).",
        "code": ErrorCode.SETUP_ACCESS_DENIED,
    })


def require_admin(request: Request) -> None:
    """Явная проверка внутри конкретных эндпоинтов управления пользователями/настройками —
    вторым слоем поверх middleware (которое пропускает viewer'а на безопасные GET-методы; здесь
    же список пользователей и переключатель должны быть недоступны viewer'у ни на чтение, ни на
    запись). Не проверяет заново токен — переиспользует request.state, выставленный middleware.

    Пока аутентификация выключена, администраторов ещё нет — доступ определяет require_setup_access."""
    if not getattr(request.state, "auth_enabled", False):
        require_setup_access(request)
        return
    user: Optional[User] = getattr(request.state, "user", None)
    if user is None or user.role != UserRole.ADMIN:
        raise HTTPException(403, "Требуются права администратора.")
