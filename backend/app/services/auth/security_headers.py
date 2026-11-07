"""Заголовки безопасности ответов: базовый набор против MIME-sniffing и кликджекинга и Content-Security-Policy."""
from __future__ import annotations

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


def with_security_headers(response, path: str = ""):
    for header, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    # Content-Security-Policy — второй рубеж после DOMPurify: токен сессии лежит в localStorage, и любая
    # XSS означала бы его кражу. Политику можно заменить или отключить через INFRA_REGISTRY_CSP
    # (см. config.CSP_POLICY) — например, когда её выставляет обратный прокси.
    if CSP_POLICY and path not in _CSP_EXEMPT_PATHS:
        response.headers.setdefault("Content-Security-Policy", CSP_POLICY)
    return response
