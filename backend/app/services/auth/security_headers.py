"""Заголовки безопасности ответов: базовый набор против MIME-sniffing и кликджекинга и Content-Security-Policy.

Ставит их один слой — SecurityHeadersMiddleware, САМЫЙ внешний в приложении (main.py): заголовки получает любой ответ, в том числе
сформированный внутренними слоями — 400 проверки Host, 403 проверки клиента и origin, 413 предела тела запроса, 401/403 шлюза
доступа. Раньше их дополнительно ставил сам шлюз (with_security_headers) — дублирование убрано вместе с переходом шлюза на
чистый ASGI (код-ревью С-5, Н-8).

apply_security_headers пишет через ``setdefault``: заголовок, уже выставленный обработчиком или обратным прокси,
не перезаписывается и не дублируется.

Пример: ``app.add_middleware(SecurityHeadersMiddleware)`` — после install_http_security(...): последний добавленный слой
в Starlette самый внешний.
"""
from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ...config import CSP_POLICY

_SECURITY_HEADERS = {
    # Базовый набор против MIME-sniffing и кликджекинга для встроенного Vue-интерфейса.
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
}

# Swagger UI/ReDoc подгружают скрипты и стили со сторонних CDN — строгая политика сломала бы
# страницы документации, а данных реестра на них нет.
_CSP_EXEMPT_PATHS = frozenset({"/docs", "/redoc", "/docs/oauth2-redirect", "/openapi.json"})

# Ответы API несут данные реестра; статические файлы интерфейса (/assets/…) кэшируются как обычно.
_NO_STORE_PREFIX = "/api/"


def apply_security_headers(headers: MutableHeaders, path: str = "") -> None:
    """Дописывает недостающие заголовки безопасности; уже стоящие не трогает (регистр имени не важен)."""
    for header, value in _SECURITY_HEADERS.items():
        headers.setdefault(header, value)
    # Content-Security-Policy — второй рубеж после DOMPurify: токен сессии лежит в localStorage, и любая
    # XSS означала бы его кражу. Политику можно заменить или отключить через INFRA_REGISTRY_CSP
    # (см. config.CSP_POLICY) — например, когда её выставляет обратный прокси.
    if CSP_POLICY and path not in _CSP_EXEMPT_PATHS:
        headers.setdefault("Content-Security-Policy", CSP_POLICY)
    # Данные реестра не должны оседать в кэше браузера и промежуточных прокси — на общем компьютере их потом откроет следующий
    # пользователь (код-ревью Н-2). setdefault: ответ, у которого обработчик сам задал Cache-Control, остаётся как есть.
    if path.startswith(_NO_STORE_PREFIX):
        headers.setdefault("Cache-Control", "no-store")


class SecurityHeadersMiddleware:
    """Самый внешний слой: заголовки получают и ответы, сформированные внутренними middleware (400/401/403/413)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":  # lifespan и websocket заголовков ответа не имеют
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])  # по ASGI заголовки в начале ответа необязательны
                apply_security_headers(MutableHeaders(scope=message), path)
            await send(message)

        await self.app(scope, receive, send_with_headers)
