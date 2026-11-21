"""
Код-ревью main, F-06 (этап 2): тела запросов роутеров отчётов, конструктора шаблонов, портов/подключений и ресурсов описаны
Pydantic-моделями вместо ``payload: dict`` (модели — api/report_schemas.py, port_config_schemas.py, resource_schemas.py).

Проверяется то, ради чего это сделано, и то, что не должно было измениться:
* форма тела видна в OpenAPI, а новый безымянный ``dict`` в теле запроса не появится (защитный тест на весь API);
* тексты ошибок прежние — строка по-русски, а не список объектов Pydantic;
* порядок проверок прежний: где раньше шёл 404, он идёт и теперь (поиск записи — зависимостью, раньше разбора тела);
* два случая, которые раньше давали 500, теперь отклоняются (название шаблона не строка, description не строка).

Запуск: pytest backend/tests/test_request_body_schemas.py -v
"""

from __future__ import annotations

import pytest

from app.main import app
from app.services.connection_query import MAX_SEARCH_LENGTH

MISSING = "нет-такого"  # id, которого нет в БД: по нему видно, что отвечает первым — 404 или проверка тела


def _assert_422(response, message: str) -> None:
    assert response.status_code == 422, response.text
    assert response.json() == {"detail": message}


def _body_schema_names(operation: dict) -> set[str]:
    """Имена компонентов-моделей тела запроса операции (у необязательного тела схема — anyOf [модель, null])."""
    schema = operation["requestBody"]["content"]["application/json"]["schema"]
    variants = schema.get("anyOf", [schema])
    return {v["$ref"].rsplit("/", 1)[-1] for v in variants if "$ref" in v}


# --- Форма тела описана в OpenAPI ---------------------------------------------------------------------------------------------

DOCUMENTED = [
    ("/api/v1/report-builder/preview", "post", "ReportPreviewRequest"),
    ("/api/v1/report-templates", "post", "ReportTemplateWrite"),
    ("/api/v1/report-templates/{template_id}", "put", "ReportTemplateWrite"),
    ("/api/v1/report-templates/{template_id}/generate", "post", "ReportGenerateRequest"),
    ("/api/v1/reports/inventory", "post", "InventoryReportRequest"),
    ("/api/v1/reports/structural-appendix", "post", "StructuralAppendixRequest"),
    ("/api/v1/interfaces/{interface_id}/port-role", "put", "PortRoleUpdate"),
    ("/api/v1/interfaces/{interface_id}/port-config", "put", "PortConfigUpdate"),
    ("/api/v1/interfaces/{interface_id}/vlan-mode-cascade/preview", "post", "CascadePreviewRequest"),
    ("/api/v1/interfaces/{interface_id}/vlan-mode-cascade", "post", "CascadeApplyRequest"),
    ("/api/v1/connections/port-config/approve", "post", "ApprovePortConfigRequest"),
    ("/api/v1/resources/information-systems/{item_id}/details", "put", "InformationSystemDetailsUpdate"),
]


@pytest.mark.parametrize(("path", "method", "schema"), DOCUMENTED)
def test_openapi_describes_the_request_bodies(path, method, schema):
    spec = app.openapi()
    assert schema in _body_schema_names(spec["paths"][path][method])
    assert spec["components"]["schemas"][schema]["properties"]


# Эти два тела — объект произвольных полей: набор колонок зависит от ресурса (см. api/resource_schemas.py), но у них есть описание.
FREE_FORM = {("/api/v1/resources/{resource}", "post"), ("/api/v1/resources/{resource}/{item_id}", "put")}
# Известный пробел, не входивший в отчёт ревью (там считались `payload: dict`, а здесь `payload: Any = Body(...)`): роутер правил
# согласования портов принимает тело как есть, а форму проверяют сервисы port_sync_*. Перевод на модели — отдельная задача: сначала
# нужно описать структуру правила (стороны, условия, действия), а не только обёртку запроса. Когда её сделают — убрать из набора.
NOT_YET_DESCRIBED = {
    ("/api/v1/port-sync/rules", "post"),
    ("/api/v1/port-sync/rules/reorder", "post"),
    ("/api/v1/port-sync/rules/{rule_id}", "put"),
    ("/api/v1/port-sync/preview", "post"),
    ("/api/v1/port-sync/apply", "post"),
}


def _anonymous_bodies(spec: dict) -> set[tuple[str, str]]:
    found = set()
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            body = operation.get("requestBody", {}).get("content", {}).get("application/json")
            if body is not None and not _body_schema_names(operation):
                found.add((path, method))
    return found


def test_no_new_request_body_is_an_anonymous_dict():
    anonymous = _anonymous_bodies(app.openapi())
    assert anonymous == FREE_FORM | NOT_YET_DESCRIBED, "эндпоинт с безымянным телом: опишите его моделью (api/*_schemas.py)"


def test_the_free_form_bodies_are_at_least_described():
    spec = app.openapi()
    for path, method in FREE_FORM:
        assert spec["paths"][path][method]["requestBody"]["content"]["application/json"]["schema"]["description"]


def test_openapi_lists_the_modes_and_the_batch_limit():
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["PortConfigUpdate"]["properties"]["mode"]["anyOf"][0]["enum"] == ["access", "trunk"]
    assert schemas["CascadePreviewRequest"]["properties"]["mode"]["enum"] == ["access", "trunk"]
    assert "500" in schemas["ApprovePortConfigRequest"]["properties"]["connection_ids"]["description"]


# --- Тексты ошибок остались прежними и приходят строкой ------------------------------------------------------------------------

REPORT_ERRORS = [
    # Модель сообщает обо всех ошибках тела сразу (до трёх, через «; »), прежний код — только о первой.
    ("post", "/api/v1/report-templates", {}, "Укажите название шаблона; Поле config должно быть объектом с описанием листов/блоков"),
    ("post", "/api/v1/report-templates", {"name": "   ", "config": {}}, "Укажите название шаблона"),
    ("post", "/api/v1/report-templates", {"name": "Т"}, "Поле config должно быть объектом с описанием листов/блоков"),
    ("post", "/api/v1/report-templates", {"name": "Т", "config": []}, "Поле config должно быть объектом с описанием листов/блоков"),
    ("post", "/api/v1/report-templates", {"name": "Т", "config": {}, "format": 7}, "Неизвестный формат отчёта: '7' (ожидается xlsx или docx)"),
    ("post", "/api/v1/report-builder/preview", {"limit": 0}, "limit должен быть целым числом от 1 до 200"),
    ("post", "/api/v1/report-builder/preview", {"limit": True}, "limit должен быть целым числом от 1 до 200"),
    ("post", "/api/v1/report-builder/preview", {"limit": None}, "limit должен быть целым числом от 1 до 200"),
    ("post", "/api/v1/report-builder/preview", {"config": []}, "config должен быть объектом с описанием листов/блоков"),
    ("post", "/api/v1/reports/inventory", {"structural_unit_ids": "x"}, "structural_unit_ids должен быть списком идентификаторов"),
    ("post", "/api/v1/reports/inventory", {"structural_unit_ids": [""]}, "structural_unit_ids должен быть списком идентификаторов"),
    ("post", "/api/v1/reports/structural-appendix", {"is_name": 5}, "Короткое имя ИС должно быть строкой"),
    ("post", "/api/v1/reports/structural-appendix", {"is_name": None}, "Короткое имя ИС должно быть строкой"),
]


@pytest.mark.parametrize(("method", "path", "body", "message"), REPORT_ERRORS)
def test_report_bodies_keep_the_russian_messages_as_a_plain_string(client, method, path, body, message):
    _assert_422(client.request(method.upper(), path, json=body), message)


PORT_ERRORS = [
    ("put", "port-role", {}, "Поле is_management должно быть true или false; Поле is_data_transfer должно быть true или false"),
    ("put", "port-role", {"is_management": 1, "is_data_transfer": True}, "Поле is_management должно быть true или false"),
    ("put", "port-role", {"is_management": True, "is_data_transfer": "yes"}, "Поле is_data_transfer должно быть true или false"),
    ("put", "port-config", {}, "Укажите role, vlan_ids и/или all_vlans"),
    ("put", "port-config", {"role": "бог"}, "Поле role: допустимые значения — none, management, data, management_data"),
    ("put", "port-config", {"role": "data", "bogus": 1}, "Неизвестные поля: bogus"),
    ("put", "port-config", {"vlan_ids": "10"}, "Поле vlan_ids должно быть массивом идентификаторов VLAN"),
    ("put", "port-config", {"all_vlans": "yes"}, "Поле all_vlans должно быть true или false"),
    ("put", "port-config", {"role": "data", "mode": "bridge"}, "Поле mode должно быть access или trunk"),
    ("post", "vlan-mode-cascade/preview", {}, "Режим порта должен быть 'access' или 'trunk'"),
    ("post", "vlan-mode-cascade/preview", {"mode": "trunk", "edited": []}, "Поле edited должно быть объектом с непустым device_id"),
    ("post", "vlan-mode-cascade", {"mode": "бог"}, "Режим порта должен быть 'access' или 'trunk'"),
    ("post", "vlan-mode-cascade", {"mode": "trunk"}, "Применение требует подтверждения: confirm = true"),
]


@pytest.mark.parametrize(("method", "tail", "body", "message"), PORT_ERRORS)
def test_port_bodies_keep_the_russian_messages_as_a_plain_string(client, method, tail, body, message):
    # Порта с таким id нет: тело проверяется раньше поиска порта, как и до моделей, — поэтому здесь 422, а не 404.
    _assert_422(client.request(method.upper(), f"/api/v1/interfaces/{MISSING}/{tail}", json=body), message)


@pytest.mark.parametrize("confirm", ["true", 1, "yes", False, None])
def test_cascade_apply_does_not_treat_a_lookalike_as_confirmation(client, confirm):
    body = {"mode": "trunk", "confirm": confirm}
    _assert_422(client.post(f"/api/v1/interfaces/{MISSING}/vlan-mode-cascade", json=body), "Применение требует подтверждения: confirm = true")


APPROVE_ERRORS = [
    ({}, "Передайте ровно одно из полей: connection_ids или match"),
    ({"connection_ids": ["a"], "match": {}}, "Передайте ровно одно из полей: connection_ids или match"),
    ({"connection_ids": []}, "Поле connection_ids должно быть непустым массивом идентификаторов подключений"),
    ({"connection_ids": "abc"}, "Поле connection_ids должно быть непустым массивом идентификаторов подключений"),
    ({"connection_ids": ["a", ""]}, "Поле connection_ids должно быть непустым массивом идентификаторов подключений"),
    ({"connection_ids": [str(i) for i in range(501)]}, "За один запрос можно одобрить не более 500 подключений"),
    ({"match": "all"}, "Поле match должно быть объектом с необязательными q и is_active"),
    ({"match": {"q": 5}}, f"Поле match.q должно быть строкой не длиннее {MAX_SEARCH_LENGTH} символов"),
    ({"match": {"is_active": "yes"}}, "Поле match.is_active должно быть true, false или null"),
]


@pytest.mark.parametrize(("body", "message"), APPROVE_ERRORS)
def test_approve_keeps_the_russian_messages_as_a_plain_string(client, body, message):
    _assert_422(client.post("/api/v1/connections/port-config/approve", json=body), message)


@pytest.mark.parametrize("value", ["x", None, {"a": 1}, 5])
@pytest.mark.parametrize("key", ["departments", "protocols", "placement_assets", "sources"])
def test_information_system_details_reject_a_non_list(client, key, value):
    system = client.post("/api/v1/resources/information-systems", json={"name": f"ИС для {key}"}).json()
    _assert_422(client.put(f"/api/v1/resources/information-systems/{system['id']}/details", json={key: value}), f"Поле {key} должно быть массивом")


# --- Порядок проверок не изменился: где был 404 раньше разбора тела, там он и остался ----------------------------------------


def test_an_unknown_template_is_404_before_the_body_is_checked(client):
    assert client.put(f"/api/v1/report-templates/{MISSING}", json={}).status_code == 404
    assert client.post(f"/api/v1/report-templates/{MISSING}/generate", json={"params": "x"}).status_code == 404


def test_an_unknown_information_system_is_404_before_the_body_is_checked(client):
    assert client.put(f"/api/v1/resources/information-systems/{MISSING}/details", json={"departments": "x"}).status_code == 404


def test_the_port_part_of_a_cascade_is_checked_after_the_port_is_found(client):
    response = client.post(f"/api/v1/interfaces/{MISSING}/vlan-mode-cascade/preview", json={"mode": "trunk", "port": {"role": "бог"}})
    assert (response.status_code, response.json()) == (404, {"detail": "Порт не найден"})


# --- То, что раньше давало 500 или принималось молча ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", [5, ["Т"], {"a": 1}, True])
def test_a_template_name_that_is_not_a_string_is_a_422_not_a_500(client, name):
    _assert_422(client.post("/api/v1/report-templates", json={"name": name, "config": {}}), "Укажите название шаблона")


@pytest.mark.parametrize("description", [5, ["x"], {"a": 1}])
def test_a_template_description_must_be_a_string_or_null(client, description):
    _assert_422(client.post("/api/v1/report-templates", json={"name": "Т", "config": {}, "description": description}), "Поле description должно быть строкой или null")


# --- На корректных запросах поведение прежнее -----------------------------------------------------------------------------------


def test_a_valid_preview_still_uses_the_defaults(client):
    # Ни формата, ни limit, ни config: xlsx, 15 строк, пустое описание — его отклоняет предметная проверка шаблона, а не модель.
    response = client.post("/api/v1/report-builder/preview", json={})
    assert response.status_code == 422
    assert "detail" in response.json() and isinstance(response.json()["detail"], str)


def test_information_system_details_without_lists_clear_them_as_before(client):
    system = client.post("/api/v1/resources/information-systems", json={"name": "ИС без списков"}).json()
    response = client.put(f"/api/v1/resources/information-systems/{system['id']}/details", json={})
    assert response.status_code == 200, response.text
    assert response.json()["departments"] == [] and response.json()["protocols"] == []


def test_unknown_fields_in_report_and_resource_bodies_are_still_ignored(client):
    system = client.post("/api/v1/resources/information-systems", json={"name": "ИС лишние поля"}).json()
    response = client.put(f"/api/v1/resources/information-systems/{system['id']}/details", json={"departments": [], "лишнее": [1]})
    assert response.status_code == 200, response.text
