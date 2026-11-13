"""
Код-ревью, BE-02: схема OpenAPI описывает ошибки так, как их отдаёт приложение.

Раньше ``HTTPValidationError.detail`` в схеме был списком объектов (умолчание FastAPI), хотя обработчик 422 отдаёт строку
(services/request_errors.py), а ответ 413 о слишком большом теле не был описан вовсе. Тесты сверяют схему с настоящими ответами —
не только друг с другом, — чтобы описание не разошлось с поведением снова.

Запуск: pytest backend/tests/test_openapi_errors.py -v
"""
from __future__ import annotations

import copy

import pytest

from app.config import MAX_REQUEST_BODY_BYTES
from app.constants import ErrorCode
from app.main import app
from app.services.openapi_errors import TOO_LARGE_SCHEMA, VALIDATION_ERROR_SCHEMA, apply_error_formats

API = "/api/v1/diagrams"
REF_PREFIX = "#/components/schemas/"


def _collect_refs(node: object) -> set[str]:
    if isinstance(node, dict):
        found = {node["$ref"]} if isinstance(node.get("$ref"), str) else set()
        return found.union(*(_collect_refs(value) for value in node.values()))
    if isinstance(node, list):
        return set().union(*(_collect_refs(item) for item in node))
    return set()


def _body_operations(spec: dict) -> list[tuple[str, str, dict]]:
    return [(path, method, op) for path, item in spec["paths"].items() for method, op in item.items() if "requestBody" in op]


# --- 422 ------------------------------------------------------------------------------------------------------------------

def test_the_422_schema_describes_a_plain_string_detail():
    schema = app.openapi()["components"]["schemas"][VALIDATION_ERROR_SCHEMA]
    assert schema["properties"]["detail"]["type"] == "string"
    assert "items" not in schema["properties"]["detail"]


def test_a_real_422_answer_matches_the_schema(client):
    # Контроль в обратную сторону: описание верно не «по замыслу», а по настоящему ответу обработчика.
    response = client.post(API, json={})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    broken_json = client.post(API, content="{oops", headers={"content-type": "application/json"})
    assert broken_json.status_code == 422 and isinstance(broken_json.json()["detail"], str)


def test_every_reference_in_the_schema_resolves():
    # Замена схемы ошибки не должна оставлять «висячих» ссылок (ни на удалённый ValidationError, ни на несозданный RequestBodyTooLarge).
    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    missing = {ref for ref in _collect_refs(spec) if ref.startswith(REF_PREFIX) and ref[len(REF_PREFIX):] not in schemas}
    assert not missing
    assert "ValidationError" not in schemas  # на него больше никто не ссылается


# --- 413 ------------------------------------------------------------------------------------------------------------------

def test_413_is_described_for_every_operation_with_a_request_body_and_only_for_them():
    spec = app.openapi()
    with_body = _body_operations(spec)
    assert with_body, "в приложении есть операции с телом запроса"
    for path, method, operation in with_body:
        ref = operation["responses"]["413"]["content"]["application/json"]["schema"]["$ref"]
        assert ref == REF_PREFIX + TOO_LARGE_SCHEMA, f"{method.upper()} {path}"
    for path, item in spec["paths"].items():
        for method, operation in item.items():
            if "requestBody" not in operation:
                assert "413" not in operation["responses"], f"{method.upper()} {path}: у запроса без тела 413 не бывает"


def test_a_real_413_answer_matches_the_schema(client):
    schema = app.openapi()["components"]["schemas"][TOO_LARGE_SCHEMA]
    response = client.post(API, content=b"x" * (MAX_REQUEST_BODY_BYTES + 1), headers={"content-type": "application/json"})
    assert response.status_code == 413
    detail = response.json()["detail"]
    assert set(detail) == set(schema["properties"]["detail"]["properties"])
    assert detail["code"] == ErrorCode.REQUEST_BODY_TOO_LARGE
    assert detail["code"] in schema["properties"]["detail"]["properties"]["code"]["enum"]
    assert isinstance(detail["message"], str)


# --- Сборка схемы ---------------------------------------------------------------------------------------------------------

def test_the_schema_is_built_once_and_rebuilds_identically():
    first = app.openapi()
    assert app.openapi() is first  # кэш FastAPI (app.openapi_schema) работает
    snapshot = copy.deepcopy(first)
    app.openapi_schema = None  # сброс кэша: схема собирается заново и правится заново — результат тот же, ничего не задвоилось
    try:
        assert app.openapi() == snapshot
    finally:
        app.openapi_schema = None  # не оставляем после теста объект, отличный от того, что видели другие тесты


def test_applying_the_formats_twice_changes_nothing():
    base = {
        "paths": {"/x": {"post": {"requestBody": {}, "responses": {"422": {"$ref": REF_PREFIX + VALIDATION_ERROR_SCHEMA}}}}},
        "components": {"schemas": {VALIDATION_ERROR_SCHEMA: {"type": "object", "properties": {"detail": {"type": "array"}}}, "ValidationError": {}}},
    }
    once = apply_error_formats(copy.deepcopy(base), max_body_bytes=2048)
    twice = apply_error_formats(copy.deepcopy(once), max_body_bytes=2048)
    assert once == twice
    assert "2 КБ" in once["paths"]["/x"]["post"]["responses"]["413"]["description"]


def test_413_is_not_described_when_the_limit_is_switched_off():
    spec = {"paths": {"/x": {"post": {"requestBody": {}, "responses": {}}}}, "components": {"schemas": {}}}
    apply_error_formats(spec, max_body_bytes=0)  # 0 — проверка размера выключена (config.MAX_REQUEST_BODY_BYTES)
    assert "413" not in spec["paths"]["/x"]["post"]["responses"]
    assert TOO_LARGE_SCHEMA not in spec["components"]["schemas"]


def test_an_existing_413_description_is_kept():
    own = {"description": "своё описание"}
    spec = {"paths": {"/x": {"put": {"requestBody": {}, "responses": {"413": own}}}}, "components": {"schemas": {}}}
    apply_error_formats(spec, max_body_bytes=1024)
    assert spec["paths"]["/x"]["put"]["responses"]["413"] is own


@pytest.mark.parametrize("schemas", [{}, {"Other": {}}])
def test_a_schema_without_the_validation_error_is_left_without_it(schemas):
    # Если ни одна операция не может ответить 422, FastAPI не создаёт HTTPValidationError — и мы его не придумываем.
    spec = {"paths": {}, "components": {"schemas": dict(schemas)}}
    apply_error_formats(spec, max_body_bytes=1024)
    assert VALIDATION_ERROR_SCHEMA not in spec["components"]["schemas"]
