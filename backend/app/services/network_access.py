"""Сетевой доступ к приложению: список разрешённых клиентов и проверка заголовка Host.

Два независимых слоя защиты HTTP, которые подключает ``main.install_http_security``:

* ``ClientAccessMiddleware`` — пускает только клиентов, чей IP-адрес входит в список адресов и подсетей
  (``INFRA_REGISTRY_ALLOWED_CLIENTS``). Остальные получают 403 до любой другой обработки (в том числе до
  проверки аутентификации). Пустой список не создаёт middleware вовсе — поведение «пускать всех» (Docker,
  запуск из исходников) не меняется.
* ``IpLiteralTrustedHostMiddleware`` — ``TrustedHostMiddleware``, который дополнительно принимает Host в виде
  IP-адреса. Защита от DNS-rebinding требует отвергать чужие ИМЕНА: страница злоумышленника всегда приходит
  с Host вида ``evil.example``, а адрес-литерал перенацелить через DNS нельзя. Поэтому для сетевого режима
  EXE достаточно перечислить имена компьютера, а обращение по ``http://192.168.1.10:8000`` работает само.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Iterable, Sequence
from functools import lru_cache
from typing import Union

from starlette.datastructures import Headers
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ..constants import ErrorCode

logger = logging.getLogger(__name__)

IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

# Код закрытия WebSocket «нарушение политики»: приложение WebSocket не использует, но закрывать такое
# соединение нужно тем же правилом, а не пропускать мимо проверки.
_WS_POLICY_VIOLATION = 1008


def parse_client_networks(entries: Iterable[str]) -> list[IPNetwork]:
    """Список IP-адресов и подсетей из строк: ``192.168.1.15`` (один адрес) или ``192.168.1.0/24`` (подсеть).

    Биты хоста в маске не ошибка (``192.168.1.5/24`` означает подсеть ``192.168.1.0/24``). Некорректная
    запись — ``ValueError`` с понятным текстом: молча пропущенный адрес выглядел бы как «доступ не открылся»,
    а молча принятый мусор — как «доступ открыт всем»."""
    networks: list[IPNetwork] = []
    for entry in entries:
        try:
            networks.append(ipaddress.ip_network(entry.strip(), strict=False))
        except ValueError as exc:
            raise ValueError(
                f"Некорректный IP-адрес или подсеть: {entry!r}. Ожидается адрес (192.168.1.15) или подсеть в формате CIDR (192.168.1.0/24)."
            ) from exc
    return networks


def _normalize_address(value: str) -> IPAddress | None:
    """IP-адрес клиента из строки; IPv4-адрес в IPv6-записи (::ffff:192.168.1.5) приводится к IPv4,
    иначе клиент из разрешённой IPv4-подсети не прошёл бы проверку при двойном стеке."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None  # не IP (например, имя «testclient» у тестового клиента или unix-сокет)
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def is_client_allowed(host: str | None, networks: Sequence[IPNetwork]) -> bool:
    """Входит ли адрес клиента хотя бы в одну из подсетей. Клиент без адреса или с адресом не в виде IP — нет."""
    if not host:
        return False
    address = _normalize_address(host)
    if address is None:
        return False
    return any(address.version == network.version and address in network for network in networks)


def has_remote_clients(networks: Iterable[IPNetwork]) -> bool:
    """Есть ли в списке что-то кроме петли (127.0.0.0/8, ::1): то есть доступно ли приложение по сети."""
    return any(not network.is_loopback for network in networks)


@lru_cache(maxsize=1024)
def _log_rejected_client(host: str) -> None:
    """Одна запись в журнале на каждый отвергнутый адрес (кэш по адресу): иначе сканирование сети
    заполнило бы консоль EXE. Для администратора этого достаточно, чтобы понять, какой адрес добавить."""
    logger.warning(
        "Отклонено подключение с адреса %s: он не входит в список разрешённых клиентов (allowed_clients в файле настроек / INFRA_REGISTRY_ALLOWED_CLIENTS).",
        host,
    )


class ClientAccessMiddleware:
    """Чистый ASGI-middleware: пропускает запрос, только если адрес клиента входит в разрешённые подсети.

    Адрес берётся из ``scope['client']`` — то есть из TCP-соединения (или из X-Forwarded-For, если uvicorn
    доверяет прокси по FORWARDED_ALLOW_IPS). Заголовки запроса сами по себе адрес не подменяют."""

    def __init__(self, app: ASGIApp, networks: Sequence[IPNetwork]) -> None:
        self.app = app
        self.networks = tuple(networks)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):  # lifespan и прочее — не клиентские запросы
            await self.app(scope, receive, send)
            return
        client = scope.get("client")
        host = client[0] if client else None
        if is_client_allowed(host, self.networks):
            await self.app(scope, receive, send)
            return
        _log_rejected_client(host or "<неизвестен>")
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": _WS_POLICY_VIOLATION})
            return
        response = JSONResponse(
            status_code=403,
            content={
                "detail": {
                    "code": ErrorCode.CLIENT_NOT_ALLOWED,
                    "message": "Доступ с этого адреса запрещён настройками приложения. Администратор должен добавить адрес в список разрешённых клиентов.",
                }
            },
        )
        await response(scope, receive, send)


def _host_without_port(header: str) -> str:
    """Host из значения заголовка без порта: ``10.0.0.5:8000`` → ``10.0.0.5``, ``[::1]:8000`` → ``::1``."""
    header = header.strip()
    if header.startswith("["):
        return header[1 : header.find("]")] if "]" in header else ""
    if header.count(":") == 1:
        return header.split(":", 1)[0]
    return header  # без порта, либо «голый» IPv6 (в Host он бывает только в скобках)


def is_ip_literal_host(header: str) -> bool:
    """Заголовок Host — это IP-адрес (с портом или без), а не имя."""
    try:
        ipaddress.ip_address(_host_without_port(header))
    except ValueError:
        return False
    return True


class IpLiteralTrustedHostMiddleware(TrustedHostMiddleware):
    """``TrustedHostMiddleware`` + любой Host в виде IP-адреса. Имена по-прежнему проверяются по списку
    ``allowed_hosts`` (в том числе ``*.corp.local`` и ``*``)."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and is_ip_literal_host(Headers(scope=scope).get("host", "")):
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)
