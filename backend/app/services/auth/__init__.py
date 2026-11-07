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
import ipaddress
import logging
import re
from typing import NamedTuple, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ... import db as db_module
from ...config import (
    FORWARDED_ALLOW_IPS,
    SETUP_TOKEN,
)
from ...constants import ErrorCode, UserRole
from ...models import User
from ..actor_context import Actor, current_actor
from ._common import request_client_ip as _client_ip
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
from .security_headers import with_security_headers
from .settings import auth_enabled_cached, get_or_create_auth_settings, reset_auth_enabled_cache, set_auth_enabled
from .users import (
    change_own_password,
    create_user,
    delete_user,
    ensure_not_last_admin,
    find_user_by_username,
    serialize_user,
    update_user,
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
    # settings
    "get_or_create_auth_settings", "reset_auth_enabled_cache", "set_auth_enabled",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Пароли
# ---------------------------------------------------------------------------
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
ROLE_CHECK_EXEMPT_PATHS = frozenset({"/api/v1/auth/logout", "/api/v1/auth/me/password", "/api/v1/preferences/user"})
ROLE_CHECK_EXEMPT_PREFIXES = ("/api/v1/auth/sessions/",)


def _is_role_check_exempt(path: str) -> bool:
    return path in ROLE_CHECK_EXEMPT_PATHS or path.startswith(ROLE_CHECK_EXEMPT_PREFIXES)


# POST-запросы, которые данных реестра не меняют: они только формируют файл отчёта или предпросмотр, а
# метод POST выбран из-за тела запроса (параметры, выбор структурных единиц). Роль viewer («только чтение»)
# должна уметь формировать отчёты — иначе просмотр без выгрузки теряет смысл. Допускаются точные пути:
# создание, правка, удаление и дублирование шаблонов, как и /seed, остаются только для администратора.
READ_ONLY_POST_PATHS = frozenset({
    "/api/v1/reports/inventory",
    "/api/v1/report-builder/preview",
    "/api/v1/reports/structural-appendix",  # формирует Word-файл, реестр не меняет (A-23)
    "/api/v1/port-sync/preview",            # «план согласования портов — ничего не записывает» (api/port_sync.py, A-23)
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


# ---------------------------------------------------------------------------
# Прокси, которому не доверяет uvicorn (ревью 2.158.0, П-3)
# ---------------------------------------------------------------------------
# uvicorn подставляет адрес клиента из X-Forwarded-For только тогда, когда TCP-соединение пришло с адреса из
# FORWARDED_ALLOW_IPS. Если прокси там не перечислен, у всех клиентов за ним один адрес — прокси: троттлинг входа
# (пара «адрес + логин» и счётчик адреса) становится общим, и неверные пароли нападающего задерживают вход настоящего
# администратора, а «знакомым» (см. _is_known_client) оказывается любой. Программно это не запретить — только заметить.
_proxy_headers_warned = False  # один раз на процесс: сообщение о конфигурации, а не журнал каждого запроса


def _normalize_host(value: str) -> str:
    """Адрес без порта и скобок — так запись X-Forwarded-For разбирает uvicorn: «1.2.3.4:80» → «1.2.3.4», «[::1]:80» → «::1»."""
    value = value.strip()
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end != -1 else value
    if value.count(":") == 1:
        return value.rsplit(":", 1)[0]
    return value


def _same_host(left: str, right: str) -> bool:
    try:
        return ipaddress.ip_address(left) == ipaddress.ip_address(right)
    except ValueError:
        return left.casefold() == right.casefold()


def _untrusted_proxy_header(request: Request) -> Optional[str]:
    """Имя прокси-заголовка, пришедшего от адреса, которому uvicorn НЕ доверяет, иначе None.

    К моменту работы middleware uvicorn уже мог заменить request.client на адрес из X-Forwarded-For (если соединение пришло
    с доверенного прокси), поэтому сравнивать client.host со списком FORWARDED_ALLOW_IPS нельзя: за правильно настроенным
    прокси адрес клиента там никогда не бывает, и предупреждение срабатывало бы на каждый запрос. Признак другой: при подмене
    адрес клиента — одна из записей самого заголовка; если заголовок пришёл, а адреса соединения среди его записей нет, значит
    uvicorn его не разбирал. Заголовок Forwarded (RFC 7239) uvicorn не разбирает вообще, поэтому за ним адрес клиента — всегда
    адрес прокси. Значение заголовка (его присылает кто угодно) наружу не отдаётся."""
    client = request.client
    if client is None:
        return None
    entries = (_normalize_host(part) for value in request.headers.getlist("x-forwarded-for") for part in value.split(","))
    seen_entry = False
    for entry in entries:
        if not entry:
            continue
        seen_entry = True
        if _same_host(client.host, entry):
            return None
    if seen_entry:
        return "X-Forwarded-For"
    return "Forwarded" if "forwarded" in request.headers else None


def _warn_once_if_proxy_untrusted(request: Request) -> None:
    """Однократное (на процесс) предупреждение в журнал сервера: пришёл заголовок обратного прокси от адреса, которого нет в
    FORWARDED_ALLOW_IPS. Запрос не блокируется и не меняется — это подсказка администратору, не защита."""
    global _proxy_headers_warned
    if _proxy_headers_warned:
        return
    header = _untrusted_proxy_header(request)
    if header is None:
        return
    _proxy_headers_warned = True
    hint = " Заголовок Forwarded uvicorn не разбирает — настройте прокси на X-Forwarded-For." if header == "Forwarded" else ""
    logger.warning(
        "Запрос пришёл с заголовком %s от адреса %s, которому uvicorn не доверяет (FORWARDED_ALLOW_IPS: %s): адрес клиента "
        "остаётся адресом этого узла. Если это обратный прокси, у всех клиентов за ним один адрес — троттлинг входа (в том "
        "числе для настоящего администратора) и «знакомые» адреса считают их одним клиентом, а в журнале аудита и списке "
        "сессий будет адрес прокси. Перечислите адрес прокси в FORWARDED_ALLOW_IPS (README, «Аутентификация и авторизация»).%s "
        "Сообщение выводится один раз за процесс.",
        header, request.client.host if request.client else "—",
        ", ".join(FORWARDED_ALLOW_IPS) if FORWARDED_ALLOW_IPS else "не задана, по умолчанию 127.0.0.1", hint,
    )


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
        return with_security_headers(await call_next(request), path)

    _warn_once_if_proxy_untrusted(request)
    actor_token = current_actor.set(Actor(ip=_client_ip(request)))
    try:
        response = await _gate_api_request(request, call_next)
    finally:
        current_actor.reset(actor_token)
    return with_security_headers(response, path)


class _GateDecision(NamedTuple):
    """Итог проверки доступа: кто пришёл и, если запрос надо отклонить, чем именно ответить."""

    auth_enabled: bool
    user: Optional[User]
    deny_status: Optional[int] = None
    deny_detail: str = ""


def _authorize(method: str, path: str, authorization: Optional[str]) -> _GateDecision:
    """Решение о доступе к /api/*: синхронная работа с БД, которую вызывают из пула потоков.

    Сессия БД открывается и ГАРАНТИРОВАННО закрывается здесь же, до того как запрос уйдёт дальше по
    цепочке: раньше при выключенной аутентификации (значение по умолчанию) `return await call_next()`
    выполнялся внутри `try`, и соединение middleware висело в пуле весь запрос — вместе с соединением
    обработчика (Depends(get_db)) каждый запрос занимал два соединения из пула в 15, и при ≥16
    параллельных запросах половина получала 500. Синхронные вызовы БД в `async`-мидлвари к тому же
    блокировали цикл событий, пока пул пуст.

    db_module.SessionLocal, а не `from ..db import SessionLocal` в заголовке файла: это мидлварь, а не
    FastAPI Depends — тесты (backend/tests/conftest.py:client) подменяют SessionLocal через
    monkeypatch.setattr(app.db, "SessionLocal", ...) на своё in-memory StaticPool-соединение, а
    `from X import Y` создал бы отдельную, непропатчиваемую ссылку."""
    db_session = db_module.SessionLocal()
    try:
        auth_enabled = auth_enabled_cached(db_session)
        if not auth_enabled or path in PUBLIC_API_PATHS:
            return _GateDecision(auth_enabled, None)

        token = _extract_bearer_token(authorization)
        user = resolve_session(db_session, token) if token else None
        if user is None:
            return _GateDecision(True, None, 401, "Требуется аутентификация.")
        if (
            user.role != UserRole.ADMIN
            and method in WRITE_METHODS
            and not _is_role_check_exempt(path)
            and not _is_read_only_post(method, path)
        ):
            return _GateDecision(True, user, 403, "Недостаточно прав: требуется роль администратора.")
        return _GateDecision(True, user)
    finally:
        db_session.close()


async def _gate_api_request(request: Request, call_next):
    decision = await run_in_threadpool(_authorize, request.method, request.url.path, request.headers.get("authorization"))
    request.state.auth_enabled = decision.auth_enabled
    request.state.user = decision.user
    if decision.user is not None:
        current_actor.set(Actor(decision.user.id, decision.user.username, _client_ip(request)))
    if decision.deny_status is not None:
        return JSONResponse({"detail": decision.deny_detail}, status_code=decision.deny_status)
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
