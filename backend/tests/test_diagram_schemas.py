"""
Код-ревью main, F-06 (этап 2): тела запросов роутера диаграмм описаны Pydantic-моделями вместо ``payload: dict``.

Проверяется то, ради чего это сделано: текст ошибок остался прежним (русским и строкой), форма тела видна в OpenAPI, а три
случая, которые ручные проверки пропускали, теперь отклоняются (булево значение из строки, нестрока в description, огромное
целое в координатах — раньше OverflowError и 500).

Запуск: pytest backend/tests/test_diagram_schemas.py -v
"""

from __future__ import annotations

import json

import pytest

from app.api.diagram_schemas import MAX_COLLAPSE_THRESHOLD, MAX_DIAGRAM_NAME_LENGTH, checked_viewport
from app.api.diagrams import _parse_viewport
from app.main import app
from app.models import DiagramGroupState, DiagramLayout, SavedDiagram

API = "/api/v1/diagrams"
HUGE_INT = 10**400  # JSON позволяет сколько угодно цифр; в float такое число не помещается


def _create(client, name: str, **extra) -> dict:
    response = client.post(API, json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return response.json()


def _assert_422(response, message: str) -> None:
    assert response.status_code == 422, response.text
    assert response.json() == {"detail": message}


# --- Сообщения не изменились -------------------------------------------------------------------------------------------

CREATE_ERRORS = [
    ({}, "Укажите название диаграммы"),
    ({"name": "   "}, "Укажите название диаграммы"),
    ({"name": 123}, "Укажите название диаграммы"),
    ({"name": "x" * (MAX_DIAGRAM_NAME_LENGTH + 1)}, f"Название диаграммы не должно быть длиннее {MAX_DIAGRAM_NAME_LENGTH} символов"),
    ({"name": "d", "group_by": "color"}, "group_by должен быть одним из: structural_unit, vlan, building, device_category"),
    ({"name": "d", "group_by": None}, "group_by должен быть одним из: structural_unit, vlan, building, device_category"),
    ({"name": "d", "scope_filter": [1]}, "scope_filter должен быть объектом-фильтром охвата"),
    ({"name": "d", "collapse_threshold": 0}, "collapse_threshold должен быть положительным целым числом"),
    ({"name": "d", "collapse_threshold": True}, "collapse_threshold должен быть положительным целым числом"),
    ({"name": "d", "collapse_threshold": "5"}, "collapse_threshold должен быть положительным целым числом"),
    ({"name": "d", "collapse_threshold": -1}, "collapse_threshold должен быть положительным целым числом"),
    ({"name": "d", "collapse_threshold": 1.5}, "collapse_threshold должен быть положительным целым числом"),
    ({"name": "d", "collapse_threshold": None}, "collapse_threshold должен быть положительным целым числом"),
]


@pytest.mark.parametrize(("body", "message"), CREATE_ERRORS)
def test_create_keeps_the_russian_messages_as_a_plain_string(client, body, message):
    _assert_422(client.post(API, json=body), message)


def test_rename_keeps_the_russian_messages(client):
    diagram = _create(client, "Модели переименование")
    _assert_422(client.put(f"{API}/{diagram['id']}/rename", json={}), "Укажите название диаграммы")
    _assert_422(
        client.put(f"{API}/{diagram['id']}/rename", json={"name": "x" * 300}),
        f"Название диаграммы не должно быть длиннее {MAX_DIAGRAM_NAME_LENGTH} символов",
    )


LAYOUT_ERRORS = [
    ({}, "node_positions должен быть объектом {id: {x, y}} (не более 5000 узлов)"),
    ({"node_positions": [1]}, "node_positions должен быть объектом {id: {x, y}} (не более 5000 узлов)"),
    ({"node_positions": {"n1": {"x": "a", "y": 1}}}, "Некорректная позиция узла «n1»: ожидается {x: число, y: число}"),
    ({"node_positions": {}, "viewport": "wide"}, "viewport должен быть объектом с числовыми полями pan_x, pan_y, x, y, zoom или null"),
    ({"node_positions": {}, "viewport": {"zoom": "2"}}, "viewport должен быть объектом с числовыми полями pan_x, pan_y, x, y, zoom или null"),
    ({"node_positions": {}, "viewport": {"foo": 1}}, "viewport должен быть объектом с числовыми полями pan_x, pan_y, x, y, zoom или null"),
]


@pytest.mark.parametrize(("body", "message"), LAYOUT_ERRORS)
def test_layout_keeps_the_russian_messages(client, body, message):
    diagram = _create(client, "Модели раскладка")
    _assert_422(client.put(f"{API}/{diagram['id']}/layout", json=body), message)


GROUP_ERRORS = [
    ({"custom_threshold": 0}, "custom_threshold должен быть положительным целым числом или null"),
    ({"custom_threshold": "7"}, "custom_threshold должен быть положительным целым числом или null"),
    ({"custom_threshold": True}, "custom_threshold должен быть положительным целым числом или null"),
    ({"custom_threshold": -1}, "custom_threshold должен быть положительным целым числом или null"),
    ({"custom_threshold": 1.5}, "custom_threshold должен быть положительным целым числом или null"),
]


@pytest.mark.parametrize(("body", "message"), GROUP_ERRORS)
def test_group_state_keeps_the_russian_messages(client, body, message):
    diagram = _create(client, "Модели группа")
    _assert_422(client.put(f"{API}/{diagram['id']}/groups/g1", json=body), message)


def test_a_body_that_is_not_an_object_or_not_json_gets_a_readable_message(client):
    _assert_422(client.post(API, json=[1, 2]), "Тело запроса: ожидается объект")
    response = client.post(API, content="{oops", headers={"content-type": "application/json"})
    _assert_422(response, "Тело запроса не является корректным JSON")


# --- OpenAPI описывает тела -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "method", "schema"),
    [
        ("/api/v1/diagrams", "post", "DiagramCreate"),
        ("/api/v1/diagrams/{diagram_id}/rename", "put", "DiagramRename"),
        ("/api/v1/diagrams/{diagram_id}/layout", "put", "DiagramLayoutUpdate"),
        ("/api/v1/diagrams/{diagram_id}/groups/{group_key}", "put", "DiagramGroupStateUpdate"),
    ],
)
def test_openapi_describes_the_request_bodies(path, method, schema):
    spec = app.openapi()
    body_ref = spec["paths"][path][method]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert body_ref.endswith(f"/{schema}")
    assert spec["components"]["schemas"][schema]["properties"]


def test_openapi_lists_the_grouping_dimensions_and_the_threshold_minimum():
    props = app.openapi()["components"]["schemas"]["DiagramCreate"]["properties"]
    assert props["group_by"]["enum"] == ["structural_unit", "vlan", "building", "device_category"]
    assert props["collapse_threshold"]["minimum"] == 1


def test_openapi_lists_the_threshold_maximum_for_both_threshold_fields():
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["DiagramCreate"]["properties"]["collapse_threshold"]["maximum"] == MAX_COLLAPSE_THRESHOLD
    # custom_threshold допускает null, поэтому границы лежат в ветке anyOf с типом integer
    custom = schemas["DiagramGroupStateUpdate"]["properties"]["custom_threshold"]["anyOf"]
    integer = next(branch for branch in custom if branch.get("type") == "integer")
    assert (integer["minimum"], integer["maximum"]) == (1, MAX_COLLAPSE_THRESHOLD)


# --- Поведение на корректных запросах не изменилось -----------------------------------------------------------------------


def test_create_applies_defaults_and_ignores_unknown_fields(client):
    created = _create(client, "  Модели  умолчания ", id="forged", created_at="1999-01-01", unknown=[1])
    assert created["name"] == "Модели умолчания"
    assert created["group_by"] == "structural_unit"
    assert created["collapse_threshold"] == 20
    assert created["scope_filter"] == {}
    assert created["id"] != "forged"


def test_null_scope_filter_means_no_filter(client):
    assert _create(client, "Модели null-фильтр", scope_filter=None)["scope_filter"] == {}


def test_description_must_be_a_string_or_null(client):
    assert _create(client, "Модели описание", description="текст")["description"] == "текст"
    assert _create(client, "Модели описание null", description=None)["description"] is None
    response = client.post(API, json={"name": "Модели описание число", "description": 5})
    assert response.status_code == 422


def test_layout_keeps_integers_as_integers(client, db_session):
    diagram = _create(client, "Модели целые")
    response = client.put(f"{API}/{diagram['id']}/layout", json={"node_positions": {"n": {"x": 1, "y": 2.5}}, "viewport": {"zoom": 2, "pan_x": 0}})
    assert response.status_code == 200
    db_session.expire_all()
    stored = db_session.query(DiagramLayout).filter_by(saved_diagram_id=diagram["id"]).one()
    assert stored.node_positions.startswith('{"n": {"x": 1, "y": 2.5}}'), stored.node_positions
    assert json.loads(stored.viewport) == {"zoom": 2, "pan_x": 0}
    assert '"zoom": 2,' in stored.viewport  # не 2.0


def test_group_state_applies_only_what_was_sent(client, db_session):
    diagram = _create(client, "Модели состояние группы")
    url = f"{API}/{diagram['id']}/groups/net-1"
    assert client.put(url, json={"is_collapsed": True, "custom_threshold": 7}).json()["custom_threshold"] == 7
    only_flag = client.put(url, json={"is_collapsed": False}).json()
    assert only_flag["is_collapsed"] is False and only_flag["custom_threshold"] == 7  # порог не тронут
    reset = client.put(url, json={"custom_threshold": None}).json()
    assert reset["custom_threshold"] is None and reset["is_collapsed"] is False  # null сбрасывает порог
    untouched = client.put(url, json={}).json()
    assert untouched["custom_threshold"] is None
    assert db_session.query(DiagramGroupState).filter_by(saved_diagram_id=diagram["id"]).count() == 1


def test_group_key_longer_than_the_limit_is_still_rejected_after_the_lookup(client):
    diagram = _create(client, "Модели длинный ключ")
    response = client.put(f"{API}/{diagram['id']}/groups/{'k' * 201}", json={"is_collapsed": True})
    _assert_422(response, "group_key не должен быть длиннее 200 символов")


# --- Что стало строже --------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["false", "0", "", 1, None])
def test_is_collapsed_must_be_a_real_boolean(client, db_session, value):
    # Раньше bool("false") был True: строка «false» сворачивала группу.
    diagram = _create(client, "Модели булево")
    response = client.put(f"{API}/{diagram['id']}/groups/g", json={"is_collapsed": value})
    assert response.status_code == 422
    assert db_session.query(DiagramGroupState).filter_by(saved_diagram_id=diagram["id"]).count() == 0


@pytest.mark.parametrize(
    "body",
    [
        {"node_positions": {"n": {"x": HUGE_INT, "y": 1}}},
        {"node_positions": {}, "viewport": {"zoom": HUGE_INT}},
    ],
)
def test_an_integer_too_large_for_a_float_is_a_422_not_a_500(client, body):
    # math.isfinite(10**400) бросает OverflowError: раньше такой запрос заканчивался 500.
    diagram = _create(client, "Модели переполнение")
    response = client.put(f"{API}/{diagram['id']}/layout", content=json.dumps(body), headers={"content-type": "application/json"})
    assert response.status_code == 422


def test_a_stored_viewport_with_an_overflowing_number_reads_as_absent():
    assert checked_viewport({"zoom": 1}) == {"zoom": 1}
    with pytest.raises(ValueError):
        checked_viewport({"zoom": HUGE_INT})
    assert _parse_viewport(json.dumps({"zoom": HUGE_INT})) is None


def test_invalid_body_is_checked_before_the_diagram_is_looked_up(client):
    # Порядок проверок изменился: тело проверяется до обработчика, поэтому неверное тело к несуществующей диаграмме — 422, а не 404.
    missing = f"{API}/no-such-diagram"
    assert client.put(f"{missing}/rename", json={}).status_code == 422
    assert client.put(f"{missing}/rename", json={"name": "Корректное"}).status_code == 404
    assert client.put(f"{missing}/layout", json={"node_positions": {}}).status_code == 404


def test_rejected_requests_change_nothing(client, db_session):
    before = db_session.query(SavedDiagram).count()
    assert client.post(API, json={"name": "Не создастся", "collapse_threshold": -1}).status_code == 422
    assert db_session.query(SavedDiagram).count() == before


# --- Верхняя граница порогов (код-ревью, BE-01) ---------------------------------------------------------------------------
# Раньше 10**30 доходило до драйвера БД: OverflowError → 500 на SQLite, а 2**31 не помещалось в INTEGER PostgreSQL.

OUT_OF_RANGE_THRESHOLDS = [
    pytest.param(10**30, id="10**30"),
    pytest.param(10**400, id="10**400"),
    pytest.param(2**31, id="2**31"),
    pytest.param(MAX_COLLAPSE_THRESHOLD + 1, id="max+1"),
]


@pytest.mark.parametrize("value", OUT_OF_RANGE_THRESHOLDS)
def test_create_rejects_a_collapse_threshold_above_the_maximum(client, db_session, value):
    before = db_session.query(SavedDiagram).count()
    response = client.post(API, content=json.dumps({"name": "Порог выше границы", "collapse_threshold": value}), headers={"content-type": "application/json"})
    _assert_422(response, f"collapse_threshold не должен превышать {MAX_COLLAPSE_THRESHOLD}")
    assert db_session.query(SavedDiagram).count() == before


@pytest.mark.parametrize("value", OUT_OF_RANGE_THRESHOLDS)
def test_group_state_rejects_a_custom_threshold_above_the_maximum(client, db_session, value):
    diagram = _create(client, "Порог группы выше границы")
    response = client.put(f"{API}/{diagram['id']}/groups/g1", content=json.dumps({"custom_threshold": value}), headers={"content-type": "application/json"})
    _assert_422(response, f"custom_threshold не должен превышать {MAX_COLLAPSE_THRESHOLD}")
    assert db_session.query(DiagramGroupState).filter_by(saved_diagram_id=diagram["id"]).count() == 0


def test_the_maximum_threshold_itself_is_accepted_by_both_endpoints(client):
    created = _create(client, "Порог на границе", collapse_threshold=MAX_COLLAPSE_THRESHOLD)
    assert created["collapse_threshold"] == MAX_COLLAPSE_THRESHOLD
    response = client.put(f"{API}/{created['id']}/groups/g1", json={"custom_threshold": MAX_COLLAPSE_THRESHOLD})
    assert response.status_code == 200, response.text
    assert response.json()["custom_threshold"] == MAX_COLLAPSE_THRESHOLD
