"""Единый формат 422 при ошибке разбора запроса.

FastAPI по умолчанию отвечает на неверное тело, параметр запроса или пути списком объектов
``{"detail": [{"type", "loc", "msg", "input"}, …]}``. Фронтенд (api/client.ts) ждёт ``detail`` строкой или объектом
``{code, message}``, поэтому список показывался пользователю сырым JSON. Кроме того, ``input`` в таком ответе — это значение,
которое прислал клиент: для эндпоинтов с паролями оно эхом возвращалось в ответе.

Обработчик отдаёт тот же формат, что и остальные 422 приложения, — ``{"detail": "<сообщение по-русски>"}``:
* сообщения валидаторов моделей (``ValueError`` с русским текстом) передаются как есть;
* типовые ошибки Pydantic (нет поля, не тот тип, выход за границы, битый JSON) переведены;
* всё остальное — имя поля и исходный текст Pydantic: лучше английская подсказка, чем её отсутствие;
* значение, которое прислал клиент, в ответ не попадает.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Столько сообщений показываем клиенту: остальные — шум, исправив первые, пользователь увидит их при повторной отправке.
MAX_REPORTED_ERRORS = 3
_PREFIXES = {"query": "Параметр запроса", "path": "Параметр пути", "header": "Заголовок", "cookie": "Cookie"}

Formatter = Callable[[str, Mapping[str, Any]], str]


def _field_path(loc: Sequence[Any]) -> tuple[str, str]:
    """(откуда, путь до поля): ("body", "node_positions.x") — для body, ("query", "limit") — для параметров."""
    where = str(loc[0]) if loc else "body"
    return where, ".".join(str(part) for part in loc[1:])


def _label(where: str, field: str) -> str:
    if where == "body":
        return f"Поле «{field}»" if field else "Тело запроса"
    return f"{_PREFIXES.get(where, where)} «{field}»"


def _limit(ctx: Mapping[str, Any], key: str) -> str:
    return str(ctx.get(key, ""))


def _plural(count: object, one: str, few: str, many: str) -> str:
    """«1 символ», «2 символа», «5 символов» — число и слово в правильной форме."""
    if not isinstance(count, int):
        return f"{count} {many}"
    last_two, last = count % 100, count % 10
    if last == 1 and last_two != 11:
        word = one
    elif 2 <= last <= 4 and not 12 <= last_two <= 14:
        word = few
    else:
        word = many
    return f"{count} {word}"


def _chars(count: object) -> str:
    return _plural(count, "символ", "символа", "символов")


def _items(count: object) -> str:
    return _plural(count, "элемент", "элемента", "элементов")


def _too_short(label: str, ctx: Mapping[str, Any]) -> str:
    minimum = ctx.get("min_length")
    return f"{label}: значение не должно быть пустым" if minimum == 1 else f"{label}: минимальная длина — {_chars(minimum)}"


def _too_few_items(label: str, ctx: Mapping[str, Any]) -> str:
    minimum = ctx.get("min_length")
    return f"{label}: значение не должно быть пустым" if minimum == 1 else f"{label}: минимальное количество — {_items(minimum)}"


def _literal_error(label: str, ctx: Mapping[str, Any]) -> str:
    """Допустимые значения берутся из схемы (``ctx["expected"]``: «'a', 'b' or 'c'»), а не из ввода клиента."""
    expected = str(ctx.get("expected") or "").replace(" or ", " или ")
    return f"{label}: допустимые значения — {expected}" if expected else f"{label}: недопустимое значение"


def _expected(noun: str) -> Formatter:
    return lambda label, ctx: f"{label}: ожидается {noun}"


def _bound(phrase: str, key: str) -> Formatter:
    return lambda label, ctx: f"{label}: значение должно быть {phrase} {_limit(ctx, key)}"


# Подписи построены без согласования по роду («Поле», «Параметр», «Тело»): «<подпись>: ожидается …», «<подпись>: значение …».
_BY_TYPE: dict[str, Formatter] = {
    "missing": lambda label, ctx: f"{label}: значение обязательно",
    "json_invalid": lambda label, ctx: "Тело запроса не является корректным JSON",
    "model_attributes_type": _expected("объект"),
    "model_type": _expected("объект"),
    "dict_type": _expected("объект"),
    "extra_forbidden": lambda label, ctx: f"{label}: не предусмотрено",
    "list_type": _expected("список"),
    "string_type": _expected("строка"),
    "bool_type": _expected("true или false"),
    "bool_parsing": _expected("true или false"),
    "int_type": _expected("целое число"),
    "int_parsing": _expected("целое число"),
    "int_from_float": _expected("целое число"),
    "float_type": _expected("число"),
    "float_parsing": _expected("число"),
    "finite_number": _expected("конечное число"),
    "greater_than_equal": _bound("не меньше", "ge"),
    "greater_than": _bound("больше", "gt"),
    "less_than_equal": _bound("не больше", "le"),
    "less_than": _bound("меньше", "lt"),
    "string_too_long": lambda label, ctx: f"{label}: максимальная длина — {_chars(ctx.get('max_length'))}",
    "string_too_short": _too_short,
    "too_long": lambda label, ctx: f"{label}: максимальное количество — {_items(ctx.get('max_length'))}",
    "too_short": _too_few_items,
    "literal_error": _literal_error,
}


def describe_error(error: Mapping[str, Any]) -> str:
    """Сообщение об одной ошибке разбора запроса (элемент RequestValidationError.errors())."""
    ctx = error.get("ctx") or {}
    if error.get("type") == "value_error" and ctx.get("error") is not None:
        return str(ctx["error"])  # текст ValueError из валидатора модели — уже по-русски и уже называет поле
    where, field = _field_path(error.get("loc") or ())
    label = _label(where, field)
    formatter = _BY_TYPE.get(str(error.get("type")))
    if formatter is not None:
        return formatter(label, ctx)
    return f"{label}: {error.get('msg', 'некорректное значение')}"


def describe_errors(errors: Sequence[Mapping[str, Any]]) -> str:
    """Не более MAX_REPORTED_ERRORS различных сообщений через «; »."""
    messages: list[str] = []
    for error in errors:
        message = describe_error(error)
        if message not in messages:
            messages.append(message)
        if len(messages) == MAX_REPORTED_ERRORS:
            break
    return "; ".join(messages) or "Некорректный запрос"


async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    logger.info("Ошибка разбора запроса %s %s: %d", request.method, request.url.path, len(exc.errors()))
    return JSONResponse(status_code=422, content={"detail": describe_errors(exc.errors())})
