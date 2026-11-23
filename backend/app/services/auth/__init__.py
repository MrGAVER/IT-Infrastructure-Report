"""Аутентификация/авторизация: хеширование паролей, непрозрачные токены сессий, блокировка после
серии неудачных попыток входа, и единая точка контроля доступа — ASGI-middleware AuthGateMiddleware
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

Состав пакета (раньше всё это было одним модулем services/auth.py на ~970 строк). Зависимости идут
сверху вниз, циклов нет:
  passwords          — хеширование и проверка паролей, правила стойкости
  sessions           — токены сессий: выпуск, проверка, отзыв
  lockout            — блокировка учётной записи после неверных паролей
  users              — учётные записи, смена собственного пароля, защита последнего администратора
  settings           — переключатель «аутентификация включена» и кэш этого флага
  login              — authenticate, троттлинг по адресу и логину, ограничение параллельных проверок пароля
  security_headers   — заголовки безопасности ответов (в том числе CSP)
  proxy_headers      — предупреждение о прокси, которому не доверяет uvicorn
  gate               — ASGI-шлюз доступа к /api/*
  guards             — зависимости эндпоинтов: первичная настройка, права администратора
  _common            — текущее время и адрес клиента

Здесь только реэкспорт: прежние `from ..services.auth import …` работают как раньше. Определения лежат в подмодулях, поэтому
подменять имена в тестах нужно в том подмодуле, который их ЧИТАЕТ (monkeypatch.setattr(login, "login_throttle", …)): подмена
имени на самом пакете функции подмодулей не затрагивает.
"""

from __future__ import annotations

from ..actor_context import Actor, current_actor
from ._common import extract_bearer
from .gate import (
    PUBLIC_API_PATHS,
    READ_ONLY_POST_PATHS,
    ROLE_CHECK_EXEMPT_PATHS,
    ROLE_CHECK_EXEMPT_PREFIXES,
    WRITE_METHODS,
    AuthGateMiddleware,
)
from .guards import require_admin, require_admin_if_auth_enabled, require_setup_access
from .login import authenticate
from .passwords import hash_password, validate_password_strength, verify_password
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

__all__ = [
    "Actor",
    "current_actor",  # актор запроса: тесты и роутеры берут его отсюда
    # passwords
    "hash_password",
    "validate_password_strength",
    "verify_password",
    # sessions
    "cleanup_expired_sessions",
    "create_session",
    "list_active_sessions",
    "resolve_session",
    "revoke_all_sessions",
    "revoke_all_sessions_except",
    "revoke_session",
    "revoke_session_by_id",
    "serialize_session",
    # users
    "change_own_password",
    "create_user",
    "delete_user",
    "ensure_not_last_admin",
    "find_user_by_username",
    "serialize_user",
    "update_user",
    # settings
    "get_or_create_auth_settings",
    "reset_auth_enabled_cache",
    "set_auth_enabled",
    # login
    "authenticate",
    # gate
    "PUBLIC_API_PATHS",
    "READ_ONLY_POST_PATHS",
    "ROLE_CHECK_EXEMPT_PATHS",
    "ROLE_CHECK_EXEMPT_PREFIXES",
    "WRITE_METHODS",
    "AuthGateMiddleware",
    # guards
    "require_admin",
    "require_admin_if_auth_enabled",
    "require_setup_access",
    # _common
    "extract_bearer",
]
