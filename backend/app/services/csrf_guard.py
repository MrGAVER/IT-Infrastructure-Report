"""Защита от межсайтовых запросов (CSRF): запрос, меняющий данные, должен прийти с того же origin, что и приложение.

Пока аутентификация выключена (режим по умолчанию), реестр не требует токена, а CORS выключен. CORS защищает от
ЧТЕНИЯ ответа чужой страницей, но не от самого запроса: браузер отправляет «простой» POST без preflight, если нет
нестандартных заголовков, а тело отсутствует или это `text/plain`. Поэтому вредоносная страница в браузере владельца
могла вслепую вызвать любой POST без тела (`/api/v1/seed`, `/diagrams/{id}/duplicate`, `/reports/inventory`,
синхронизацию VLAN-доменов). Проверка заголовка Host от этого не спасает: Host у такого запроса — свой, локальный.

``SameOriginGuardMiddleware`` отклоняет такие запросы ответом 403 ``CROSS_ORIGIN_BLOCKED`` до выполнения обработчика
(и до проверки аутентификации). Решение принимается по заголовкам, которые браузер ставит сам и которые страница
подделать не может:

* ``Origin`` — есть у любого межсайтового POST/PUT/PATCH/DELETE; сравнивается с ``Host`` запроса. Значение ``null``
  (изолированный iframe, ``file://``) и любое несовпадение — чужой origin.
* ``Sec-Fetch-Site: cross-site`` — отдельный сигнал браузера; блокируется, даже если ``Origin`` не прислан.

Не-браузерные клиенты (curl, скрипты, Excel Power Query) этих заголовков не шлют и проходят как раньше: CSRF — атака
через браузер жертвы, а клиент со своим HTTP-стеком и так может отправить что угодно. Безопасные методы (GET, HEAD,
OPTIONS) не проверяются: они ничего не меняют, а чтение чужой страницей закрывает CORS.

Исключения:

* Origin из ``INFRA_REGISTRY_CORS_ORIGINS`` — администратор явно доверил этот сайт (dev-сервер Vite на отдельном порту
  и прокси с ``changeOrigin``: браузер шлёт ``Origin: http://localhost:5173``, а ``Host`` прокси переписывает).
  Запись ``*`` означает «доверять любому origin»: CORS в таком режиме и так отдаёт API любой странице, защищать нечего.
* За обратным прокси, который заменяет ``Host`` на внутренний адрес, ``Origin`` не совпадёт с ``Host``. Если
  ``FORWARDED_ALLOW_IPS`` перечисляет прокси не из loopback (значит, uvicorn работает за настоящим прокси), учитывается
  и первый адрес из ``X-Forwarded-Host``. Страница заголовок ``X-Forwarded-Host`` выставить не может (это нестандартный
  заголовок: кросс-сайтовый запрос с ним потребовал бы preflight, а CORS его не разрешает), поэтому доверие к нему
  не открывает путь для CSRF; без настройки заголовок игнорируется.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Iterable
from functools import lru_cache
from urllib.parse import urlsplit

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ..constants import ErrorCode

logger = logging.getLogger(__name__)

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
PROTECTED_PREFIX = "/api/"
_DEFAULT_PORTS = {"http": "80", "https": "443"}
_MAX_LOGGED_ORIGIN_LENGTH = 200


def normalize_origin(value: str) -> str:
    """Origin для сравнения со списком: без пробелов и завершающего «/», в нижнем регистре."""
    return value.strip().rstrip("/").lower()


def forwarded_host_trusted(forwarded_allow_ips: Iterable[str] | None) -> bool:
    """Работает ли приложение за прокси, которому доверяет uvicorn (``FORWARDED_ALLOW_IPS``).

    Истина, если в списке есть ``*`` либо адрес или подсеть не из loopback. Значение по умолчанию (``127.0.0.1``,
    ``::1``) — прокси на этом же компьютере, обычно сохраняющий исходный ``Host``; для него ``X-Forwarded-Host``
    не учитывается, и администратор при необходимости добавляет origin в ``INFRA_REGISTRY_CORS_ORIGINS``.
    Запись, не являющаяся адресом, игнорируется (как «литерал» в uvicorn: сокеты и т. п.)."""
    for entry in forwarded_allow_ips or ():
        entry = entry.strip()
        if entry == "*":
            return True
        try:
            network = ipaddress.ip_network(entry, strict=False)
        except ValueError:
            continue
        if not network.is_loopback:
            return True
    return False


def _split_origin(origin: str) -> tuple[str, str]:
    """(схема, netloc) из значения Origin; пустой netloc — значение не является origin (``null``, мусор)."""
    try:
        parts = urlsplit(origin)
    except ValueError:  # например, незакрытая «[» в IPv6-адресе
        return "", ""
    return parts.scheme.lower(), parts.netloc.lower()


def _without_default_port(netloc: str, scheme: str) -> str:
    """``example.com:443`` → ``example.com`` для https: браузер опускает стандартный порт в Origin, а прокси
    иногда оставляют его в Host."""
    default = _DEFAULT_PORTS.get(scheme)
    if default and netloc.endswith(f":{default}"):  # и для «[::1]:443»: адрес в скобках остаётся
        return netloc[: -(len(default) + 1)]
    return netloc


def _request_hosts(headers: Headers, *, trust_forwarded_host: bool) -> set[str]:
    hosts = {headers.get("host", "").strip().lower()}
    if trust_forwarded_host:
        forwarded = headers.get("x-forwarded-host", "").split(",")[0].strip().lower()  # первый — исходный клиентский
        hosts.add(forwarded)
    hosts.discard("")
    return hosts


def is_cross_origin_request(
    headers: Headers,
    *,
    trusted_origins: frozenset[str] = frozenset(),
    allow_any_origin: bool = False,
    trust_forwarded_host: bool = False,
) -> bool:
    """Пришёл ли запрос со стороннего origin (см. описание модуля)."""
    fetch_site = headers.get("sec-fetch-site", "").strip().lower()
    origin = headers.get("origin")
    if origin is None:
        return fetch_site == "cross-site"  # curl и скрипты: ни Origin, ни Sec-Fetch-Site
    if allow_any_origin or normalize_origin(origin) in trusted_origins:
        return False
    if fetch_site == "cross-site":
        return True
    scheme, netloc = _split_origin(origin.strip())
    if not netloc:
        return True  # «null» и всё, что не похоже на origin
    own_hosts = {_without_default_port(host, scheme) for host in _request_hosts(headers, trust_forwarded_host=trust_forwarded_host)}
    return _without_default_port(netloc, scheme) not in own_hosts


@lru_cache(maxsize=256)
def _log_blocked_origin(origin: str) -> None:
    """Одна запись в журнале на каждый отвергнутый origin: чаще всего это не атака, а прокси, подменяющий Host,
    и по записи администратор видит, что добавить в ``INFRA_REGISTRY_CORS_ORIGINS``."""
    logger.warning(
        "Отклонён запрос, меняющий данные, с origin %r: он не совпадает с Host приложения. Если это адрес самого "
        "реестра за обратным прокси, передавайте исходный Host либо добавьте origin в INFRA_REGISTRY_CORS_ORIGINS.",
        origin,
    )


class SameOriginGuardMiddleware:
    """Чистый ASGI-middleware: ``POST``/``PUT``/``PATCH``/``DELETE`` на ``/api/`` с чужого origin получают 403
    ``CROSS_ORIGIN_BLOCKED``. Остальные запросы проходят без изменений."""

    def __init__(self, app: ASGIApp, *, extra_origins: Iterable[str] = (), trust_forwarded_host: bool = False) -> None:
        self.app = app
        normalized = {normalize_origin(origin) for origin in extra_origins if origin and origin.strip()}
        self.allow_any_origin = "*" in normalized
        self.trusted_origins = frozenset(normalized - {"*"})
        self.trust_forwarded_host = trust_forwarded_host

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in UNSAFE_METHODS and scope["path"].startswith(PROTECTED_PREFIX):
            headers = Headers(scope=scope)
            if is_cross_origin_request(
                headers,
                trusted_origins=self.trusted_origins,
                allow_any_origin=self.allow_any_origin,
                trust_forwarded_host=self.trust_forwarded_host,
            ):
                _log_blocked_origin((headers.get("origin") or f"Sec-Fetch-Site: {headers.get('sec-fetch-site', '')}")[:_MAX_LOGGED_ORIGIN_LENGTH])
                response = JSONResponse(
                    status_code=403,
                    content={
                        "detail": {
                            "code": ErrorCode.CROSS_ORIGIN_BLOCKED,
                            "message": (
                                "Запрос с другого сайта отклонён: адрес страницы не совпадает с адресом приложения. Если реестр работает за "
                                "обратным прокси, см. раздел «Безопасность» в README."
                            ),
                        }
                    },
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
