"""
Код-ревью main, F-06 (этап 2): общий формат 422 при ошибке разбора запроса (services/request_errors.py).

По умолчанию FastAPI отвечает списком объектов с полем ``input`` — значением, которое прислал клиент. Фронтенд показывал
этот список сырым JSON, а пароль из неверного запроса эхом возвращался в ответе. Теперь ``detail`` — строка по-русски,
как у остальных 422 приложения.

Запуск: pytest backend/tests/test_request_errors.py -v
"""

from __future__ import annotations

import pytest

from app.services.request_errors import MAX_REPORTED_ERRORS, describe_error, describe_errors


def _error(type_: str, loc: tuple, msg: str = "english text", **ctx) -> dict:
    return {"type": type_, "loc": loc, "msg": msg, "input": "секрет", "ctx": ctx}


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (_error("missing", ("body", "name")), "Поле «name»: значение обязательно"),
        (_error("string_type", ("body", "name")), "Поле «name»: ожидается строка"),
        (_error("int_parsing", ("query", "limit")), "Параметр запроса «limit»: ожидается целое число"),
        (_error("bool_parsing", ("body", "flag")), "Поле «flag»: ожидается true или false"),
        (_error("less_than_equal", ("query", "limit"), le=1000), "Параметр запроса «limit»: значение должно быть не больше 1000"),
        (_error("greater_than_equal", ("query", "offset"), ge=0), "Параметр запроса «offset»: значение должно быть не меньше 0"),
        (_error("string_too_short", ("body", "username"), min_length=1), "Поле «username»: значение не должно быть пустым"),
        (_error("string_too_short", ("body", "name"), min_length=3), "Поле «name»: минимальная длина — 3 символа"),
        (_error("string_too_long", ("body", "username"), max_length=150), "Поле «username»: максимальная длина — 150 символов"),
        (_error("string_too_long", ("body", "code"), max_length=1), "Поле «code»: максимальная длина — 1 символ"),
        (_error("model_attributes_type", ("body",)), "Тело запроса: ожидается объект"),
        (_error("model_type", ("body", "child")), "Поле «child»: ожидается объект"),
        (_error("extra_forbidden", ("body", "typo")), "Поле «typo»: не предусмотрено"),
        (_error("too_long", ("body", "ids"), max_length=500), "Поле «ids»: максимальное количество — 500 элементов"),
        (_error("too_long", ("body", "ids"), max_length=1), "Поле «ids»: максимальное количество — 1 элемент"),
        (_error("too_short", ("body", "ids"), min_length=1), "Поле «ids»: значение не должно быть пустым"),
        (_error("too_short", ("body", "ids"), min_length=2), "Поле «ids»: минимальное количество — 2 элемента"),
        (_error("literal_error", ("body", "mode"), expected="'access' or 'trunk'"), "Поле «mode»: допустимые значения — 'access' или 'trunk'"),
        (_error("literal_error", ("body", "mode")), "Поле «mode»: недопустимое значение"),
        (_error("json_invalid", ("body", 1)), "Тело запроса не является корректным JSON"),
        (_error("missing", ("body", "items", 2, "id")), "Поле «items.2.id»: значение обязательно"),
        (_error("missing", ("header", "x-token")), "Заголовок «x-token»: значение обязательно"),
    ],
)
def test_common_pydantic_errors_are_translated(error, expected):
    assert describe_error(error) == expected


def test_a_validator_message_passes_through_unchanged():
    error = _error("value_error", ("body", "name"), msg="Value error, Укажите название диаграммы", error=ValueError("Укажите название диаграммы"))
    assert describe_error(error) == "Укажите название диаграммы"


def test_an_unknown_error_type_keeps_the_field_and_the_pydantic_text():
    assert describe_error(_error("url_scheme", ("body", "site"), msg="URL scheme should be 'http'")) == "Поле «site»: URL scheme should be 'http'"


@pytest.mark.parametrize(("count", "word"), [(1, "символ"), (2, "символа"), (4, "символа"), (5, "символов"), (11, "символов"), (12, "символов"), (21, "символ"), (22, "символа")])
def test_character_count_uses_the_right_word_form(count, word):
    assert describe_error(_error("string_too_long", ("body", "f"), max_length=count)).endswith(f"{count} {word}")


def test_messages_are_deduplicated_and_capped():
    errors = [_error("missing", ("body", f"f{i}")) for i in range(10)] + [_error("missing", ("body", "f0"))]
    message = describe_errors(errors)
    assert message.count("; ") == MAX_REPORTED_ERRORS - 1
    assert message.startswith("Поле «f0»: значение обязательно; Поле «f1»")
    assert describe_errors([_error("missing", ("body", "a")), _error("missing", ("body", "a"))]) == "Поле «a»: значение обязательно"
    assert describe_errors([]) == "Некорректный запрос"


# --- Через настоящее приложение: другие эндпоинты с моделями и параметрами запроса ------------------------------------


def test_login_validation_error_does_not_echo_the_submitted_value(client):
    secret = "секрет-пароль-123"
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": [secret]})
    assert response.status_code == 422
    assert response.json() == {"detail": "Поле «password»: ожидается строка"}
    assert secret not in response.text


def test_query_parameter_errors_are_plain_russian_strings(client):
    response = client.get("/api/v1/resources/interfaces", params={"limit": 5000})
    assert response.status_code == 422
    assert response.json() == {"detail": "Параметр запроса «limit»: значение должно быть не больше 1000"}
    response = client.get("/api/v1/resources/interfaces", params={"offset": "abc"})
    assert response.json() == {"detail": "Параметр запроса «offset»: ожидается целое число"}


def test_several_errors_are_joined_into_one_message(client):
    response = client.post("/api/v1/auth/login", json={})
    assert response.status_code == 422
    assert response.json() == {"detail": "Поле «username»: значение обязательно; Поле «password»: значение обязательно"}
