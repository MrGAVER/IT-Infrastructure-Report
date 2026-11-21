"""Шлюз доступа: ASGI-middleware, единая точка контроля доступа к /api/* (регистрируется в main.py).

Решает по пути и методу запроса, не заглядывая в конкретный роутер. Пути и роли, на которые распространяются исключения
(публичные пути, действия любой роли, POST без записи), перечислены здесь же. Причины выбора middleware вместо Depends()
на каждом роутере — в докстринге пакета (services/auth/__init__.py)."""
from __future__ import annotations

import re
from typing import NamedTuple, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.types import ASGIApp, Receive, Scope, Send

from ... import db as db_module
from ...constants import UserRole
from ...models import User
from ..actor_context import Actor, current_actor
from ._common import extract_bearer, request_client_ip
from .proxy_headers import warn_once_if_proxy_untrusted
from .sessions import resolve_session
from .settings import auth_enabled_cached

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

        token = extract_bearer(authorization)
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


class AuthGateMiddleware:
    """Единая точка контроля доступа к /api/*: чистый ASGI-middleware (код-ревью С-5).

    Раньше шлюз был функцией под ``BaseHTTPMiddleware``: тот запускает приложение в отдельной задаче anyio и читает ``receive``
    внутри группы задач, из-за чего исключение предела тела запроса приходило в FastAPI обёрнутым в ``ExceptionGroup`` и
    превращалось в 400 (обход жил в body_limit.py). Теперь шлюз вызывает приложение прямо, как остальные слои
    (csrf_guard, body_limit, network_access, security_headers).

    Раздача Vue-оболочки (`/`, `/assets/*`, SPA-фоллбэк в main.py) проверку доступа не проходит: статика отдаётся всегда, экран
    логина рисует сам Vue-роутер на клиенте (frontend-vue/src/router/index.ts). Контроль — только над `/api/*`, и только над
    данными, а не над тем, загрузится ли интерфейс. Заголовки безопасности ставит SecurityHeadersMiddleware — самый внешний
    слой, поэтому они есть и на отказах 401/403 отсюда.

    Для любого запроса к /api/* (в том числе публичному) в ``scope["state"]`` кладутся ``auth_enabled`` и ``user``:
    ``request.state`` в Starlette читает именно этот словарь, и api/auth.py берёт оттуда результат проверки, а не ходит в БД
    повторно. На время запроса выставляется ``current_actor`` (адрес клиента, а после проверки токена — ещё и пользователь):
    из него crud.audit() берёт автора действия для журнала аудита.

    Пример: ``app.add_middleware(AuthGateMiddleware)`` — внутри CORS, проверки Host и origin и предела тела запроса (main.py)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        path = request.url.path
        if not path.startswith("/api/"):
            await self.app(scope, receive, send)
            return

        warn_once_if_proxy_untrusted(request)
        client_ip = request_client_ip(request)
        actor_token = current_actor.set(Actor(ip=client_ip))
        try:
            decision = await run_in_threadpool(_authorize, request.method, path, request.headers.get("authorization"))
            scope.setdefault("state", {}).update(auth_enabled=decision.auth_enabled, user=decision.user)
            if decision.user is not None:
                current_actor.set(Actor(decision.user.id, decision.user.username, client_ip))
            if decision.deny_status is not None:
                response = JSONResponse({"detail": decision.deny_detail}, status_code=decision.deny_status)
                await response(scope, receive, send)
                return
            await self.app(scope, receive, send)
        finally:
            current_actor.reset(actor_token)
