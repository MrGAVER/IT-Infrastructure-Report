"""Ограничение размера тела запроса.

Раньше предела не было вовсе: обработчики с ``payload: dict`` и pydantic-модели читают тело целиком, и запрос в сотни мегабайт
FastAPI разбирал бы в память. При выключенной аутентификации (режим по умолчанию) это доступно любому клиенту из разрешённых
сетей, при включённой — любому вошедшему пользователю, в том числе с ролью viewer.

``BodySizeLimitMiddleware`` отвечает 413 ``REQUEST_BODY_TOO_LARGE`` двумя путями:

* заголовок ``Content-Length`` больше предела — ответ сразу, до обработчика: тело не читается вообще;
* заголовка нет (``Transfer-Encoding: chunked``) либо он занижен — байты считаются по мере чтения, и на превышении из
  ``receive`` поднимается ``RequestBodyTooLarge``. Это подкласс ``fastapi.HTTPException``: FastAPI пропускает его без
  изменений (любое другое исключение при чтении тела он подменил бы ответом 400 «error parsing the body»), а
  ``ExceptionMiddleware`` превращает в обычный JSON-ответ 413.

Это возможно потому, что все слои над обработчиком — чистый ASGI (csrf_guard, network_access, security_headers, шлюз доступа
``AuthGateMiddleware``): ``receive`` читается в той же задаче, и исключение доходит до FastAPI как есть. Раньше шлюз был функцией под
``BaseHTTPMiddleware`` — тот читает ``receive`` внутри группы задач anyio, и исключение приходило обёрнутым в ``ExceptionGroup``
(то есть не как ``HTTPException``) и превращалось в 400; от этого здесь был обход с подменой любого ответа приложения на 413. Обход убран. Вернёт ли кто-то ``BaseHTTPMiddleware`` в стек — поймает
tests/test_review_p1_auth_gate_asgi.py.

Предел — ``INFRA_REGISTRY_MAX_REQUEST_BODY_BYTES`` (config.MAX_REQUEST_BODY_BYTES); 0 отключает проверку. Все тела запросов
приложения — JSON (загрузок файлов нет). Самый тяжёлый легитимный запрос — SVG-иконка: её длину ограничивает
``validate_svg_markup`` (``MAX_CUSTOM_ICON_SVG_LENGTH`` — 256 К символов; длиннее иконка бесполезна, экспорт диаграммы её
пропускает). Такая иконка в JSON — до 1,5 МБ даже при экранировании каждого символа как ``\\uXXXX``,
поэтому предел по умолчанию (2 МБ) выше. Размеры остальных тяжёлых запросов
(раскладка на максимум узлов, устройство со стеком портов) измерены в tests/test_body_limit.py.
"""

from __future__ import annotations

from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..constants import ErrorCode

_KIB = 1024
_MIB = 1024 * _KIB


def describe_limit(max_bytes: int) -> str:
    """Предел для сообщения пользователю: «2 МБ», «512 КБ» или «700 байт» — без дробей."""
    if max_bytes >= _MIB and max_bytes % _MIB == 0:
        return f"{max_bytes // _MIB} МБ"
    if max_bytes >= _KIB and max_bytes % _KIB == 0:
        return f"{max_bytes // _KIB} КБ"
    return f"{max_bytes} байт"


def too_large_detail(max_bytes: int) -> dict[str, str]:
    """Тело ошибки в том же виде, что и остальные структурированные ошибки API (``detail.code`` + ``detail.message``)."""
    return {
        "code": ErrorCode.REQUEST_BODY_TOO_LARGE,
        "message": (f"Запрос слишком большой: тело превышает допустимые {describe_limit(max_bytes)}. Уменьшите объём отправляемых данных. Администратор может поднять предел параметром INFRA_REGISTRY_MAX_REQUEST_BODY_BYTES."),
    }


class RequestBodyTooLarge(HTTPException):
    """413 из потока тела: см. описание модуля — именно подкласс ``fastapi.HTTPException``, а не обычное исключение."""

    def __init__(self, max_bytes: int) -> None:
        super().__init__(status_code=413, detail=too_large_detail(max_bytes), headers={"Connection": "close"})


def _declared_length(scope: Scope) -> int | None:
    """Значение ``Content-Length`` или None, если заголовка нет либо он не число (тогда решает подсчёт по потоку)."""
    raw = Headers(scope=scope).get("content-length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


async def _reject(scope: Scope, receive: Receive, send: Send, max_bytes: int) -> None:
    """413 с закрытием соединения: клиент мог уже слать тело, и оставшиеся байты не должны разбираться как следующий запрос."""
    response = JSONResponse(status_code=413, content={"detail": too_large_detail(max_bytes)}, headers={"Connection": "close"})
    await response(scope, receive, send)


def _counting_receive(receive: Receive, max_bytes: int) -> Receive:
    """``receive``, который считает принятые байты тела и на превышении предела поднимает ``RequestBodyTooLarge``."""
    received = 0

    async def counting_receive() -> Message:
        nonlocal received
        message = await receive()
        if message["type"] == "http.request":
            received += len(message.get("body", b""))
            if received > max_bytes:
                raise RequestBodyTooLarge(max_bytes)
        return message

    return counting_receive


class BodySizeLimitMiddleware:
    """Тело запроса больше ``max_bytes`` — 413 ``REQUEST_BODY_TOO_LARGE``. Проверяются запросы любого метода: тело есть не только
    у POST/PUT/PATCH, а список методов, который можно обойти, ничего не стоит. ``max_bytes <= 0`` — проверка выключена."""

    def __init__(self, app: ASGIApp, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self.max_bytes <= 0:
            await self.app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > self.max_bytes:
            await _reject(scope, receive, send, self.max_bytes)
            return
        await self.app(scope, _counting_receive(receive, self.max_bytes), send)
