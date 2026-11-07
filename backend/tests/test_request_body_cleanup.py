"""
Код-ревью, BE-05: шероховатости в моделях тел запросов.

* обязательные поля моделей объявлены без значения по умолчанию (раньше ``Field(default=None, validate_default=True)`` с
  ``# type: ignore[assignment]``): в OpenAPI они попадают в ``required``, а текст ошибки при отсутствии поля прежний;
* у диаграмм общая основа тел с остальными роутерами (``schema_base.RequestBody``), а не собственная копия;
* разбор каскада режимов — публичные функции, а не алиасы на приватные;
* разбор тела одобрения возвращает явный вариант (``ApproveByIds`` | ``ApproveByMatch``), а в ``approve_port_config`` нет ``assert``,
  который при запуске с ``python -O`` исчезает.

Запуск: pytest backend/tests/test_request_body_cleanup.py -v
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import diagram_schemas, port_config_schemas
from app.api.schema_base import RequestBody, absent_as_null
from app.main import app
from app.services import connection_review, vlan_mode_cascade
from app.services.connection_review import MAX_APPROVE_BATCH, ApproveByIds, ApproveByMatch, parse_approve_request

API_DIR = Path(diagram_schemas.__file__).parent
MISSING = "нет-такого"


def _assert_422(response, message: str) -> None:
    assert response.status_code == 422, response.text
    assert response.json() == {"detail": message}


# --- Обязательные поля без подавления типов ------------------------------------------------------------------------------------

def test_api_schemas_have_no_type_ignore():
    offenders = [path.name for path in sorted(API_DIR.glob("*_schemas.py")) if "type: ignore" in path.read_text(encoding="utf-8")]
    assert offenders == []


@pytest.mark.parametrize(
    ("schema", "field"),
    [
        ("PortRoleUpdate", "is_management"),
        ("PortRoleUpdate", "is_data_transfer"),
        ("CascadePreviewRequest", "mode"),
        ("CascadeApplyRequest", "mode"),
        ("ReportTemplateWrite", "config"),
        ("DiagramLayoutUpdate", "node_positions"),
    ],
)
def test_the_field_is_required_in_openapi(schema, field):
    # Сервер отвергает тело без этого поля, поэтому схема обязана так и говорить (раньше поле выглядело необязательным, default: null).
    assert field in app.openapi()["components"]["schemas"][schema]["required"]


@pytest.mark.parametrize(
    ("method", "path", "body", "message"),
    [
        ("put", f"/api/v1/interfaces/{MISSING}/port-role", {}, "Поле is_management должно быть true или false; Поле is_data_transfer должно быть true или false"),
        ("put", f"/api/v1/interfaces/{MISSING}/port-role", {"is_management": True}, "Поле is_data_transfer должно быть true или false"),
        ("post", f"/api/v1/interfaces/{MISSING}/vlan-mode-cascade/preview", {}, "Режим порта должен быть 'access' или 'trunk'"),
        ("post", "/api/v1/report-templates", {"name": "Шаблон"}, "Поле config должно быть объектом с описанием листов/блоков"),
        # Ошибки отсутствующего и неверного поля собираются вместе, как и раньше (а не обрываются на первой).
        ("post", "/api/v1/report-templates", {}, "Укажите название шаблона; Поле config должно быть объектом с описанием листов/блоков"),
    ],
)
def test_an_absent_required_field_keeps_the_message_of_an_invalid_value(client, method, path, body, message):
    _assert_422(getattr(client, method)(path, json=body), message)


def test_an_absent_layout_is_rejected_with_the_same_message_as_a_wrong_one(client):
    created = client.post("/api/v1/diagrams", json={"name": "Раскладка без позиций"}).json()
    absent = client.put(f"/api/v1/diagrams/{created['id']}/layout", json={})
    wrong = client.put(f"/api/v1/diagrams/{created['id']}/layout", json={"node_positions": [1]})
    assert absent.status_code == wrong.status_code == 422
    assert absent.json() == wrong.json()


@pytest.mark.parametrize("path", [f"/api/v1/interfaces/{MISSING}/port-role", "/api/v1/report-templates"])
def test_a_body_that_is_not_an_object_still_gets_the_object_message(client, path):
    # Подстановка null вместо отсутствующих полей касается только объектов: «ожидается объект» по-прежнему даёт Pydantic.
    response = client.put(path, json=[1]) if "port-role" in path else client.post(path, json=[1])
    _assert_422(response, "Тело запроса: ожидается объект")


def test_absent_as_null_fills_only_the_missing_names_and_keeps_the_input_intact():
    raw = {"a": 1, "b": None}
    assert absent_as_null(raw, "a", "b", "c") == {"a": 1, "b": None, "c": None}
    assert raw == {"a": 1, "b": None}  # входной словарь не меняется
    assert absent_as_null(raw, "a", "b") is raw  # нечего подставлять — тот же объект
    assert absent_as_null([1], "a") == [1]  # не объект — как есть


# --- Общая основа и публичные имена -----------------------------------------------------------------------------------------

def test_diagram_bodies_share_the_common_request_body_base():
    assert not hasattr(diagram_schemas, "_Body")
    for model in (diagram_schemas.DiagramCreate, diagram_schemas.DiagramRename, diagram_schemas.DiagramLayoutUpdate, diagram_schemas.DiagramGroupStateUpdate):
        assert issubclass(model, RequestBody)
    assert diagram_schemas.DiagramCreate.model_config["extra"] == "ignore"  # лишние поля по-прежнему игнорируются


def test_cascade_parsers_are_plain_public_functions_not_aliases():
    assert vlan_mode_cascade.parse_cascade_mode.__name__ == "parse_cascade_mode"
    assert vlan_mode_cascade.parse_cascade_edited.__name__ == "parse_cascade_edited"
    assert not hasattr(vlan_mode_cascade, "_parse_mode") and not hasattr(vlan_mode_cascade, "_parse_edited")
    assert port_config_schemas.parse_cascade_mode is vlan_mode_cascade.parse_cascade_mode


# --- Разбор тела одобрения --------------------------------------------------------------------------------------------------

def test_approve_request_by_ids_is_deduplicated_in_arrival_order():
    selection = parse_approve_request({"connection_ids": ["b", "a", "b"]})
    assert selection == ApproveByIds(["b", "a"])


def test_approve_request_by_match_carries_the_query_with_the_mismatch_status():
    selection = parse_approve_request({"match": {"q": "srv", "is_active": True}})
    assert isinstance(selection, ApproveByMatch)
    assert (selection.query.q, selection.query.is_active) == ("srv", True)
    assert selection.query.status is not None  # статус всегда «расхождение»: клиент его не передаёт


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({}, "Передайте ровно одно из полей: connection_ids или match"),
        ({"connection_ids": ["a"], "match": {}}, "Передайте ровно одно из полей: connection_ids или match"),
        ({"connection_ids": []}, "Поле connection_ids должно быть непустым массивом идентификаторов подключений"),
        ({"connection_ids": [str(i) for i in range(MAX_APPROVE_BATCH + 1)]}, f"За один запрос можно одобрить не более {MAX_APPROVE_BATCH} подключений"),
        ([], "Тело запроса должно быть объектом"),
    ],
)
def test_approve_request_keeps_its_messages(payload, message):
    with pytest.raises(HTTPException) as caught:
        parse_approve_request(payload)
    assert (caught.value.status_code, caught.value.detail) == (422, message)


def test_approve_port_config_has_no_assert():
    # assert исчезает при запуске с `python -O`: проверка варианта должна быть обычным кодом.
    tree = ast.parse(inspect.getsource(connection_review.approve_port_config).lstrip())
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]


def test_approve_port_config_handles_both_variants(client):
    by_ids = client.post("/api/v1/connections/port-config/approve", json={"connection_ids": [MISSING]})
    assert by_ids.status_code == 404  # неизвестный id — 404 без изменений (ветка ApproveByIds)
    by_match = client.post("/api/v1/connections/port-config/approve", json={"match": {}})
    assert by_match.status_code == 200 and by_match.json() == {"items": [], "skipped_ids": [], "approved_count": 0}  # ветка ApproveByMatch
