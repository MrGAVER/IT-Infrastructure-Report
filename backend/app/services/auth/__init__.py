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

import hmac
from typing import Optional

from fastapi import HTTPException, Request

from ...config import (
    SETUP_TOKEN,
)
from ...constants import ErrorCode, UserRole
from ...models import User
from ..actor_context import Actor, current_actor
from .sessions import (
    cleanup_expired_sessions,
    create_session,
    list_active_sessions,
    resolve_session,
    revoke_all_sessions,
    revoke_all_sessions_except,
    revoke_session,
    revoke_session_by_id,
    serialize_session,
)
from .settings import get_or_create_auth_settings, reset_auth_enabled_cache, set_auth_enabled
from .users import (
    change_own_password,
    create_user,
    delete_user,
    ensure_not_last_admin,
    find_user_by_username,
    serialize_user,
    update_user,
)
from .gate import (
    PUBLIC_API_PATHS,
    READ_ONLY_POST_PATHS,
    ROLE_CHECK_EXEMPT_PATHS,
    ROLE_CHECK_EXEMPT_PREFIXES,
    WRITE_METHODS,
    auth_gate_middleware,
)
from .login import authenticate
from .passwords import hash_password, validate_password_strength, verify_password

# Публичный интерфейс пакета. До нарезки (код-ревью, BE-06) всё это жило в одном модуле services/auth.py, поэтому прежние
# `from ..services.auth import …` продолжают работать; определения лежат в подмодулях, а здесь только реэкспорт.
# Подменять имена в тестах нужно в подмодуле, который их ЧИТАЕТ (monkeypatch.setattr(auth.sessions, …)): подмена имени на
# самом пакете функции подмодулей не затрагивает.
__all__ = [
    "Actor", "current_actor",  # актор запроса: тесты и роутеры берут его отсюда
    # passwords
    "hash_password", "validate_password_strength", "verify_password",
    # sessions
    "cleanup_expired_sessions", "create_session", "list_active_sessions", "resolve_session", "revoke_all_sessions",
    "revoke_all_sessions_except", "revoke_session", "revoke_session_by_id", "serialize_session",
    # users
    "change_own_password", "create_user", "delete_user", "ensure_not_last_admin", "find_user_by_username", "serialize_user",
    "update_user",
    # login
    "authenticate",
    # gate
    "PUBLIC_API_PATHS", "READ_ONLY_POST_PATHS", "ROLE_CHECK_EXEMPT_PATHS", "ROLE_CHECK_EXEMPT_PREFIXES", "WRITE_METHODS",
    "auth_gate_middleware",
    # settings
    "get_or_create_auth_settings", "reset_auth_enabled_cache", "set_auth_enabled",
]

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


def require_admin_if_auth_enabled(request: Request) -> None:
    """Журнал аудита (имена пользователей, IP-адреса, неудачные попытки входа) — только администратору (A-23).

    В отличие от `require_admin`, при выключенной аутентификации ничего не требует: однопользовательский режим по умолчанию
    открыт, как и весь остальной API (иначе журнал пропал бы у владельца локальной установки)."""
    if not getattr(request.state, "auth_enabled", False):
        return
    user: Optional[User] = getattr(request.state, "user", None)
    if user is None or user.role != UserRole.ADMIN:
        raise HTTPException(403, "Журнал аудита доступен только администратору.")


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
