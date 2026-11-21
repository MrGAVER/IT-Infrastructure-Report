"""Код-ревью (раздел 5, backend, п. 3): контракт единого формата 422 — каждый тип ошибки Pydantic даёт русский текст без эха значения.

``services/request_errors.py`` превращает ошибки разбора тела (``RequestValidationError``) в одну строку ``detail`` на русском. Два свойства
этого формата нельзя проверять выборочно, иначе они ломаются незаметно:

1. **Русский текст.** Тип ошибки, которого нет в таблице ``_BY_TYPE``, падает в запасной вариант с английским ``msg`` Pydantic
   («Input should be a valid …»). Первая же новая модель с ограничением нового вида (длина списка, допустимое значение) привела бы
   к английской фразе в интерфейсе.
2. **Без эха ввода.** Значение клиента в ответ не попадает: в ``msg`` и ``ctx`` Pydantic оно иногда есть, и достаточно одного
   форматтера, который его подставит, чтобы ответ вернул клиенту произвольную строку (логин-форма, поле пароля).
   Исключение по замыслу модуля — тексты ``ValueError`` из валидаторов моделей (тип ``value_error``): они передаются как есть и
   сами решают, что назвать («Неизвестный формат отчёта: '…'»). Их формулировки закреплены ``test_request_body_schemas.py``.

Тест устроен в два слоя:

* **таблица** — для каждого ключа ``_BY_TYPE`` пробная модель вызывает настоящую ошибку Pydantic, ``describe_error`` форматирует её;
  набор проверенных типов обязан совпадать с таблицей (новая строка таблицы без случая здесь ломает тест);
* **API** — в каждое поле каждой записывающей операции подставляются значения «не того» типа с уникальной меткой и значения,
  нарушающие границы схемы (``maxItems``, ``maxLength``, ``minimum`` …). Любой ответ 422 — строка с русским текстом, без английских
  фраз Pydantic, а сообщения форматтеров таблицы — без метки. Так находятся типы, которых в таблице ещё нет.

Запуск: pytest backend/tests/test_request_errors_contract.py -v
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any, Literal

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient
from openapi_walk import fill_path, operations, seed_path_values, send, variants
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.main import app
from app.services import request_errors
from app.services.request_errors import _BY_TYPE, describe_error

SENTINEL = "zq7echo9x"  # метка: латиница без пробелов, в сообщениях приложения не встречается
CYRILLIC = re.compile("[а-яА-ЯёЁ]")
# Фразы Pydantic, по которым узнаётся запасной английский текст (``msg``).
ENGLISH_PYDANTIC = re.compile(
    r"Input should|Field required|should be|should have|Value error|Extra inputs|valid (dictionary|string|integer|number|list|boolean|"
    r"object|decimal|date)|Assertion failed|unable to parse|Input is not|Input must|None is not"
)


# --- слой «таблица» --------------------------------------------------------------------------------------------------------


class _Child(BaseModel):
    a: int


class _Probe(BaseModel):
    """По одному полю на каждый вид ошибки; ``VALID`` — тело без ошибок, случаи портят ровно одно поле."""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")

    required: str
    text: str
    flag: bool
    count: int
    ratio: float
    items: list[str]
    mapping: dict[str, int]
    child: _Child
    at_least: int = Field(ge=1)
    above: int = Field(gt=0)
    at_most: int = Field(le=5)
    below: int = Field(lt=5)
    long: str = Field(max_length=3)
    short: str = Field(min_length=2)
    many: list[int] = Field(max_length=1)
    few: list[int] = Field(min_length=2)
    choice: Literal["a", "b"]


VALID: dict[str, Any] = {
    "required": "r",
    "text": "t",
    "flag": True,
    "count": 1,
    "ratio": 1.5,
    "items": ["i"],
    "mapping": {"k": 1},
    "child": {"a": 1},
    "at_least": 1,
    "above": 1,
    "at_most": 5,
    "below": 4,
    "long": "abc",
    "short": "ab",
    "many": [1],
    "few": [1, 2],
    "choice": "a",
}

# ожидаемый тип ошибки → (что испортить, значение; None — убрать поле). Значения с меткой проверяют, что она не попадёт в текст.
TABLE_CASES: dict[str, tuple[str, Any]] = {
    "missing": ("required", None),
    "extra_forbidden": ("unexpected", 1),
    "string_type": ("text", [SENTINEL]),
    "bool_type": ("flag", [SENTINEL]),
    "bool_parsing": ("flag", SENTINEL),
    "int_type": ("count", [SENTINEL]),
    "int_parsing": ("count", SENTINEL),
    "int_from_float": ("count", 1.5),
    "float_type": ("ratio", [SENTINEL]),
    "float_parsing": ("ratio", SENTINEL),
    "finite_number": ("ratio", float("nan")),
    "list_type": ("items", SENTINEL),
    "dict_type": ("mapping", SENTINEL),
    "greater_than_equal": ("at_least", 0),
    "greater_than": ("above", 0),
    "less_than_equal": ("at_most", 6),
    "less_than": ("below", 5),
    "string_too_long": ("long", SENTINEL),
    "string_too_short": ("short", "x"),
    "too_long": ("many", [1, 2]),
    "too_short": ("few", [1]),
    "literal_error": ("choice", SENTINEL),
    "model_type": ("child", SENTINEL),
}


def _error_of_type(error_type: str) -> dict[str, Any]:
    field, value = TABLE_CASES[error_type]
    payload = {key: item for key, item in VALID.items() if key != field}
    if value is not None:
        payload[field] = value
    with pytest.raises(ValidationError) as caught:
        _Probe.model_validate(payload)
    matching = [error for error in caught.value.errors() if error["type"] == error_type]
    assert matching, f"случай для {error_type!r} дал ошибки другого вида: {[e['type'] for e in caught.value.errors()]}"
    return matching[0]


class TestFormatterTable:
    def test_every_row_of_the_table_has_a_case_and_every_case_has_a_row(self):
        covered = set(TABLE_CASES) | {"json_invalid", "model_attributes_type"}  # последние два — отдельными тестами ниже
        assert covered == set(_BY_TYPE), f"таблица и случаи расходятся: {sorted(covered ^ set(_BY_TYPE))}"

    @pytest.mark.parametrize("error_type", sorted(TABLE_CASES))
    def test_message_is_russian_and_does_not_echo_the_value(self, error_type):
        message = describe_error(_error_of_type(error_type))
        assert CYRILLIC.search(message), f"{error_type}: нет русского текста: {message!r}"
        assert not ENGLISH_PYDANTIC.search(message), f"{error_type}: английская фраза Pydantic: {message!r}"
        assert SENTINEL not in message, f"{error_type}: в тексте значение клиента: {message!r}"

    def test_body_that_is_not_an_object(self):
        with pytest.raises(ValidationError) as caught:
            _Probe.model_validate(SENTINEL, from_attributes=True)  # так FastAPI разбирает тело модели
        error = next(e for e in caught.value.errors() if e["type"] == "model_attributes_type")
        message = describe_error(error)
        assert CYRILLIC.search(message) and SENTINEL not in message

    def test_broken_json(self, client):
        response = client.post("/api/v1/auth/login", content=b'{"username": ' + SENTINEL.encode(), headers={"content-type": "application/json"})
        assert response.status_code == 422
        assert response.json()["detail"] == "Тело запроса не является корректным JSON"

    def test_unknown_type_falls_back_to_the_pydantic_text_without_the_value(self):
        # Запасной путь: для типа вне таблицы показывается msg Pydantic. Значения клиента в нём быть не должно — проверяем, на чём
        # держится этот вывод: msg описывает ожидание, а не ввод. Если Pydantic когда-нибудь начнёт вставлять input в msg, тест скажет.
        error = {"type": "brand_new_type", "loc": ("body", "field"), "msg": "Input should be something", "input": SENTINEL, "ctx": {}}
        assert SENTINEL not in describe_error(error)


# --- слой «API» ------------------------------------------------------------------------------------------------------------

WRONG_VALUES: tuple[Any, ...] = (SENTINEL, {"k": SENTINEL}, [SENTINEL], 12345, 1.5, True, None, -1, 10**30, [], {})
_ITEM_FILLERS: dict[str, Any] = {"string": "a", "integer": 1, "number": 1.0, "boolean": True}


@pytest.fixture
def described(monkeypatch) -> list[tuple[str, str]]:
    """(тип ошибки, сообщение) по каждой ошибке, которую обработчик 422 превратил в текст."""
    seen: list[tuple[str, str]] = []

    def spy(error):
        message = describe_error(error)
        seen.append((str(error.get("type")), message))
        return message

    monkeypatch.setattr(request_errors, "describe_error", spy)
    return seen


def _top_level_properties(spec: dict, schema: dict) -> dict[str, dict]:
    options = variants(spec, schema)
    return dict((options[0].get("properties") or {})) if options else {}


def _violations(prop: dict) -> Iterator[Any]:
    """Значения, нарушающие границы поля из схемы: Pydantic отвечает на них типами too_long, string_too_long, greater_than …"""
    for option in prop.get("anyOf") or [prop]:
        if "maxItems" in option:
            filler = _ITEM_FILLERS.get((option.get("items") or {}).get("type"), {})
            yield [filler] * (option["maxItems"] + 1)
        if option.get("minItems"):
            yield []
        if "maxLength" in option:
            yield "x" * (option["maxLength"] + 1)
        if option.get("minLength"):
            yield ""
        for key, shift in (("minimum", -1), ("maximum", 1)):
            if key in option:
                yield option[key] + shift
        for key in ("exclusiveMinimum", "exclusiveMaximum"):
            if key in option:
                yield option[key]


def _bodies(spec: dict, schema: dict) -> Iterator[Any]:
    yield from WRONG_VALUES  # тело целиком «не того» типа
    for name, prop in _top_level_properties(spec, schema).items():
        for value in (*WRONG_VALUES, *_violations(prop)):
            yield {name: value}


@pytest.mark.parametrize(("method", "path", "schema"), operations())
def test_every_422_is_russian_and_formatters_do_not_echo_the_value(client, db_session, described, method, path, schema):
    spec = app.openapi()
    url = fill_path(path, seed_path_values(client))
    problems = []
    for body in _bodies(spec, schema):
        described.clear()
        status, text = send(client, db_session, method, url, body)
        if status != 422:
            continue
        label = json.dumps(body, ensure_ascii=False)[:80]
        try:
            detail = json.loads(text)["detail"]
        except (ValueError, KeyError, TypeError):
            problems.append(f"{label} → не JSON с detail: {text[:120]}")
            continue
        if isinstance(detail, dict):  # допустимый вид ответа приложения: {"code": …, "message": …} (api/client.ts)
            detail = detail.get("message")
        if not isinstance(detail, str):
            problems.append(f"{label} → detail не строка и не {{code, message}}: {text[:120]}")
            continue
        if not CYRILLIC.search(detail):
            problems.append(f"{label} → нет русского текста: {detail[:160]}")
        if ENGLISH_PYDANTIC.search(detail):
            problems.append(f"{label} → английский текст Pydantic: {detail[:160]}")
        problems += [f"{label} → эхо значения в {kind}: {message[:160]}" for kind, message in described if kind != "value_error" and SENTINEL in message]
    assert not problems, f"{method.upper()} {path}:\n" + "\n".join(dict.fromkeys(problems))


class _Limited(BaseModel):  # на уровне модуля: при ``from __future__ import annotations`` FastAPI не видит локальные классы
    ids: list[str] = Field(max_length=2)


def test_a_list_over_the_limit_goes_through_the_real_handler():
    # Охрана самого теста: нарушение границы списка доходит до форматтера too_long. На настоящих эндпоинтах его часто опережает
    # «before»-проверка модели (value_error), поэтому здесь — минимальное приложение с тем же обработчиком.
    mini = FastAPI()
    mini.add_exception_handler(RequestValidationError, request_errors.request_validation_handler)

    @mini.post("/x")
    def endpoint(body: _Limited) -> dict:
        return {"count": len(body.ids)}

    response = TestClient(mini).post("/x", json={"ids": ["a", "b", "c"]})
    assert response.status_code == 422
    assert response.json() == {"detail": "Поле «ids»: максимальное количество — 2 элемента"}


def test_violations_are_generated_from_the_schema():
    schema = {"anyOf": [{"type": "array", "items": {"type": "string"}, "maxItems": 3, "minItems": 1}, {"type": "null"}]}
    assert list(_violations(schema)) == [["a"] * 4, []]
    assert list(_violations({"type": "integer", "minimum": 1, "maximum": 5})) == [0, 6]
    assert list(_violations({"type": "string", "maxLength": 2, "minLength": 1})) == ["xxx", ""]
