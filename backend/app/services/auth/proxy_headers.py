"""Предупреждение о заголовках обратного прокси, которому не доверяет uvicorn (код-ревью 2.158.0, П-3)."""
from __future__ import annotations

import ipaddress
import logging
from typing import Optional

from fastapi import Request

from ...config import FORWARDED_ALLOW_IPS

# Имя логгера прежнее — «app.services.auth», как до нарезки модуля на пакет (код-ревью, BE-06): настройки журнала и фильтры
# по этому имени продолжают работать. Логгер подмодуля с именем по умолчанию назывался бы «app.services.auth.proxy_headers».
logger = logging.getLogger("app.services.auth")

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


def warn_once_if_proxy_untrusted(request: Request) -> None:
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
