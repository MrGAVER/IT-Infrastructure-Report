"""Аутентификация/авторизация: хеширование паролей, непрозрачные токены сессий, блокировка после
серии неудачных попыток входа, и единая точка контроля доступа — ASGI-middleware auth_gate_middleware
(регистрируется в main.py).

Архитектурные решения:
- Токен сессии — случайная строка (secrets.token_urlsafe), а не JWT. В БД хранится только её
  sha256-хеш (AuthSession.token_hash), сам токен виден клиенту ровно один раз — в ответе на
  /api/v1/auth/login. Это делает logout/принудительный сброс сессий тривиальным (удалить строку),
  не требует секретного ключа подписи и не хранит в БД ничего, что само по себе годится для входа —
  в отличие от JWT, кража дампа БД (например, той самой стухшей infra_registry.db из репозитория,
  см. память проекта) не даёт готовых к использованию токенов.
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
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import db as db_module
from ..config import (
    AUTH_LOCKOUT_MINUTES,
    AUTH_MAX_FAILED_ATTEMPTS,
    AUTH_MIN_PASSWORD_LENGTH,
    AUTH_SESSION_TTL_HOURS,
)
from ..constants import AuditAction, ErrorCode, UserRole
from ..models import AuthSession, AuthSettings, User
from .crud import audit

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
PBKDF2_ITERATIONS = 260_000  # ориентир OWASP (2023) для PBKDF2-HMAC-SHA256
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


def count_active_admins(session: Session, *, exclude_user_id: Optional[str] = None) -> int:
    stmt = select(func.count()).select_from(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True))
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return session.scalar(stmt) or 0


def ensure_not_last_admin(session: Session, user: User) -> None:
    """Запрещает удалить/деактивировать/понизить в правах единственную оставшуюся активную
    учётную запись администратора — иначе при включённой аутентификации администрировать её
    (в т.ч. снова выключить переключатель) стало бы физически некому, включая того, кто совершает
    это действие."""
    if user.role == UserRole.ADMIN and user.is_active and count_active_admins(session, exclude_user_id=user.id) == 0:
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
    if enabled and not settings_row.enabled and count_active_admins(session) == 0:
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


def list_active_sessions(session: Session, user_id: str) -> list[AuthSession]:
    return list(session.scalars(
        select(AuthSession).where(AuthSession.user_id == user_id, AuthSession.expires_at >= _now())
        .order_by(AuthSession.created_at.desc())
    ).all())


# ---------------------------------------------------------------------------
# Вход: блокировка после серии неудачных попыток
# ---------------------------------------------------------------------------
_INVALID_CREDENTIALS = HTTPException(401, "Неверное имя пользователя или пароль.")


def authenticate(session: Session, username: str, password: str, *, request: Optional[Request] = None) -> tuple[User, str]:
    """Возвращает (пользователь, токен сессии) либо кидает HTTPException. Намеренно не различает
    в тексте ошибки «нет такого пользователя» и «неверный пароль» (защита от перебора логинов) —
    но блокировка (423) неизбежно подтверждает существование аккаунта, это осознанный компромисс
    между защитой от перебора паролей и полной анонимностью логинов."""
    user = find_user_by_username(session, username)
    if user is None or not user.is_active:
        # Тратим примерно то же время, что и на реальную проверку пароля — чтобы «нет такого
        # пользователя» не отвечал заметно быстрее «пароль неверный» (ещё один timing-сигнал).
        hash_password(password)
        raise _INVALID_CREDENTIALS

    now = _now()
    if user.locked_until and user.locked_until > now:
        remaining_minutes = max(1, int((user.locked_until - now).total_seconds() // 60) + 1)
        raise HTTPException(423, {
            "message": f"Учётная запись временно заблокирована после серии неудачных попыток входа. "
                       f"Повторите попытку через {remaining_minutes} мин.",
            "code": ErrorCode.ACCOUNT_LOCKED,
        })

    if not verify_password(password, user.password_hash):
        user.failed_attempts += 1
        locked_now = user.failed_attempts >= AUTH_MAX_FAILED_ATTEMPTS
        if locked_now:
            user.locked_until = now + timedelta(minutes=AUTH_LOCKOUT_MINUTES)
            user.failed_attempts = 0
        session.commit()
        audit(session, "auth", user.id, AuditAction.LOGIN_FAILED,
              f"Неудачная попытка входа «{user.username}»" + (" — учётная запись заблокирована" if locked_now else ""))
        session.commit()
        raise _INVALID_CREDENTIALS

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    if _needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    session.commit()

    token = create_session(session, user, request=request)
    audit(session, "auth", user.id, AuditAction.LOGIN, f"Вход «{user.username}»")
    session.commit()
    return user, token


# ---------------------------------------------------------------------------
# Middleware: единая точка применения доступа для /api/*
# ---------------------------------------------------------------------------
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Публичны всегда, независимо от AuthSettings.enabled — без них не работает ни health-check,
# ни сама форма логина, ни виджет "включена ли аутентификация" на экране входа.
PUBLIC_API_PATHS = frozenset({"/api/v1/health", "/api/v1/auth/status", "/api/v1/auth/login"})

# Единственное исключение из проверки роли на запись: выход должен быть доступен любой
# аутентифицированной роли, включая viewer, которому обычно запрещены методы записи.
ROLE_CHECK_EXEMPT_PATHS = frozenset({"/api/v1/auth/logout"})


def _extract_bearer_token(header_value: Optional[str]) -> Optional[str]:
    if not header_value or not header_value.startswith("Bearer "):
        return None
    token = header_value[len("Bearer "):].strip()
    return token or None


_SECURITY_HEADERS = {
    # Минимальный, не требующий настройки набор — снижает риск MIME-sniffing и кликджекинга для
    # встроенного Vue-интерфейса. Не включает Content-Security-Policy/HSTS: они специфичны для
    # окружения развёртывания (dev-сервер Vite, self-signed TLS в локальной сети и т.п.) и здесь
    # были бы либо бесполезны, либо ломали бы dev-режим — их место в обвязке при деплое, а не тут.
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}


def _with_security_headers(response):
    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


async def auth_gate_middleware(request: Request, call_next):
    """Раздача Vue-оболочки (`/`, `/assets/*`, SPA-фоллбэк в main.py) не проходит проверку
    доступа — статика всегда отдаётся, экран логина рисует сам Vue-роутер на клиенте (см.
    frontend-vue/src/router/index.ts). Контроль — только над `/api/*`, и только над данными, а не
    над тем, загрузится ли вообще интерфейс. Базовые security-заголовки (см. _SECURITY_HEADERS)
    добавляются на ВСЕ ответы, включая статику и короткое замыкание на 401/403.

    request.state.user / request.state.auth_enabled выставляются здесь для ЛЮБОГО запроса к
    /api/* (в т.ч. публичных) — api/auth.py читает их напрямую вместо повторного похода в БД."""
    path = request.url.path
    if not path.startswith("/api/"):
        return _with_security_headers(await call_next(request))

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
            return _with_security_headers(await call_next(request))

        token = _extract_bearer_token(request.headers.get("authorization"))
        user = resolve_session(db_session, token) if token else None
        if user is None:
            return _with_security_headers(JSONResponse({"detail": "Требуется аутентификация."}, status_code=401))
        request.state.user = user

        if user.role != UserRole.ADMIN and request.method in WRITE_METHODS and path not in ROLE_CHECK_EXEMPT_PATHS:
            return _with_security_headers(JSONResponse({"detail": "Недостаточно прав: требуется роль администратора."}, status_code=403))
    finally:
        db_session.close()

    return _with_security_headers(await call_next(request))


def require_admin(request: Request) -> None:
    """Явная проверка внутри конкретных эндпоинтов управления пользователями/настройками —
    вторым слоем поверх middleware (которое пропускает viewer'а на безопасные GET-методы; здесь
    же список пользователей и переключатель должны быть недоступны viewer'у ни на чтение, ни на
    запись). Не проверяет заново токен — переиспользует request.state, выставленный middleware."""
    if not getattr(request.state, "auth_enabled", False):
        return
    user: Optional[User] = getattr(request.state, "user", None)
    if user is None or user.role != UserRole.ADMIN:
        raise HTTPException(403, "Требуются права администратора.")
