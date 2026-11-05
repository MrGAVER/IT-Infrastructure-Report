"""Ограничение размера тела запроса (код-ревью main, F-06, этап 1).

Раньше предела не было вовсе: обработчики с ``payload: dict`` и pydantic-модели читают тело целиком, и запрос в сотни мегабайт
FastAPI разбирал бы в память. При выключенной аутентификации (режим по умолчанию) это доступно любому клиенту из разрешённых
сетей, при включённой — любому вошедшему пользователю, в том числе с ролью viewer.

``BodySizeLimitMiddleware`` отвечает 413 ``REQUEST_BODY_TOO_LARGE`` двумя путями:

* заголовок ``Content-Length`` больше предела — ответ сразу, до обработчика: тело не читается вообще;
* заголовка нет (``Transfer-Encoding: chunked``) либо он занижен — байты считаются по мере чтения, и на превышении из
  ``receive`` поднимается ``RequestBodyTooLarge``. Это подкласс ``fastapi.HTTPException``: FastAPI пропускает его без
  изменений (любое другое исключение при чтении тела он подменил бы ответом 400 «error parsing the body»), а
  ``ExceptionMiddleware`` превращает в обычный JSON-ответ 413.

Одного исключения мало: между этим слоем и обработчиком стоит ``auth_gate_middleware`` (``BaseHTTPMiddleware``), а тот читает
``receive`` внутри группы задач anyio, и исключение приходит в FastAPI уже обёрнутым в ``ExceptionGroup`` — то есть не как
``HTTPException`` — и превращается в 400. Поэтому после обнаружения превышения любой ответ приложения подменяется на 413
(``_GuardedRequest.send``), а исключение, дошедшее до этого слоя, гасится: оно вызвано самим превышением, и если приложение упало, не
успев ответить, 413 отправляется отсюда. Так результат не зависит от того, какие обёртки над ``receive`` появятся ниже по стеку.

Чистый ASGI-middleware, а не ``BaseHTTPMiddleware``: тот не даёт подменить ``receive`` для приложения под ним.

Предел — ``INFRA_REGISTRY_MAX_REQUEST_BODY_BYTES`` (config.MAX_REQUEST_BODY_BYTES); 0 отключает проверку. Все тела запросов
приложения — JSON (загрузок файлов нет). Самый тяжёлый легитимный запрос — SVG-иконка: при записи её длина не ограничена, но
длиннее ``MAX_CUSTOM_ICON_SVG_LENGTH`` (256 К символов) иконку пропускает экспорт диаграммы, то есть она бесполезна. Такая иконка
в JSON — до 1,5 МБ даже при экранировании каждого символа как ``\\uXXXX``, поэтому предел по умолчанию (2 МБ) выше. Размеры
остальных тяжёлых запросов (раскладка на максимум узлов, устройство со стеком портов) измерены в tests/test_body_limit.py.
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
        "message": (
            f"Запрос слишком большой: тело превышает допустимые {describe_limit(max_bytes)}. Уменьшите объём отправляемых данных. "
            "Администратор может поднять предел параметром INFRA_REGISTRY_MAX_REQUEST_BODY_BYTES."
        ),
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


class _GuardedRequest:
    """Состояние одного запроса без заголовка Content-Length (или с недостоверным): подсчёт принятых байт и подмена ответа."""

    def __init__(self, app: ASGIApp, scope: Scope, receive: Receive, send: Send, max_bytes: int) -> None:
        self.app, self.scope, self.original_receive, self.original_send, self.max_bytes = app, scope, receive, send, max_bytes
        self.received = 0
        self.exceeded = False  # тело превысило предел
        self.response_started = False  # ответ приложения уже пошёл клиенту: заменять поздно
        self.replaced = False  # вместо ответа приложения клиенту уже ушёл 413

    async def receive(self) -> Message:
        message = await self.original_receive()
        if message["type"] == "http.request":
            self.received += len(message.get("body", b""))
            if self.received > self.max_bytes:
                self.exceeded = True
                raise RequestBodyTooLarge(self.max_bytes)
        return message

    async def send(self, message: Message) -> None:
        if self.replaced:
            return  # остаток ответа приложения (тело 400/500) клиенту не нужен
        if message["type"] == "http.response.start":
            if self.exceeded and not self.response_started:
                self.replaced = True
                await _reject(self.scope, self.original_receive, self.original_send, self.max_bytes)
                return
            self.response_started = True
        await self.original_send(message)

    async def run(self) -> None:
        try:
            await self.app(self.scope, self.receive, self.send)
        except Exception:
            # Исключение вызвано самим превышением: ответ уже подменён на 413 либо приложение упало, не успев ответить (например,
            # ExceptionGroup от BaseHTTPMiddleware дошла сюда мимо ExceptionMiddleware) — тогда 413 отправляем сами. Ошибку выше
            # не пробрасываем: иначе сервер залогировал бы «Exception in ASGI application» на обычное превышение предела.
            # Если приложение уже начало отвечать (потоковый ответ), заменять поздно — ошибка идёт дальше как обычно.
            if not self.exceeded or self.response_started:
                raise
            if not self.replaced:
                await _reject(self.scope, self.original_receive, self.original_send, self.max_bytes)


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
        await _GuardedRequest(self.app, scope, receive, send, self.max_bytes).run()
