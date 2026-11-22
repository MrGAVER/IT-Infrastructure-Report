"""A-09: типы и длины полей generic CRUD проверяются по колонкам модели.

Pydantic-схемы есть только у devices / information-systems / vlans, остальные ~40 ресурсов шли «сырым dict» в `model(**data)`:
`{"name": {"a": 1}}` давал 500, `{"name": 12345}` сохранялся как текст, строка в 100 000 символов принималась (на PostgreSQL она
падала DataError, который не перехватывался). Теперь `validate_column_types` отвечает 422 с названием поля, а DataError,
дошедший до драйвера, превращается в 422 без текста драйвера.

Запуск: pytest backend/tests/test_column_types_validation.py -v
На PostgreSQL: INFRA_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/infra_test pytest backend/tests/test_column_types_validation.py
"""

from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Boolean, Date, DateTime, Integer, String
from sqlalchemy.exc import DataError
from sqlalchemy.inspection import inspect

import app.main as main_module
from app.registry import MODEL_MAP, READONLY_RESOURCES
from app.schemas import RESOURCE_SCHEMAS
from app.services.crud.columns import allowed_columns
from app.services.crud.payload import _column_rules, validate_column_types
from fastapi import HTTPException

API = "/api/v1/resources"
WRITABLE = sorted(set(MODEL_MAP) - READONLY_RESOURCES)
WITHOUT_SCHEMA = [r for r in WRITABLE if r not in RESOURCE_SCHEMAS]


def _columns(resource: str, column_type) -> list:
    model = MODEL_MAP[resource]
    allowed = allowed_columns(model)
    return [c for c in inspect(model).columns if c.key in allowed and isinstance(c.type, column_type)]


def _string_column(resource: str):
    """Строковая колонка с ограничением длины — на ней проверяем мусорные типы и длину."""
    columns = [c for c in _columns(resource, String) if getattr(c.type, "length", None)]
    assert columns, f"у ресурса {resource} нет строковой колонки с длиной — тест нужно дополнить"
    return columns[0]


def _total(client, resource: str) -> int:
    response = client.get(f"{API}/{resource}", params={"limit": 1})
    assert response.status_code == 200, response.text
    return response.json()["total"]


def _assert_validation_error(response, *fragments: str):
    assert response.status_code == 422, f"{response.status_code}: {response.text[:300]}"
    detail = response.json()["detail"]
    assert isinstance(detail, str) and detail.startswith("Ошибка валидации"), detail
    for fragment in fragments:
        assert fragment in detail, f"{fragment!r} не найдено в {detail!r}"


# ---------------------------------------------------------------------------------------------------------------------
# Все ресурсы: мусорный тип и слишком длинная строка → 422, а не 500
# ---------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("resource", WRITABLE)
@pytest.mark.parametrize("garbage", [{"a": 1}, ["x"]], ids=["dict", "list"])
def test_container_instead_of_string_is_422_for_every_resource(client, resource, garbage):
    column = _string_column(resource)
    before = _total(client, resource)
    response = client.post(f"{API}/{resource}", json={column.key: garbage})
    assert response.status_code == 422, f"{resource}.{column.key}: {response.status_code} {response.text[:200]}"
    assert _total(client, resource) == before, "запись не должна создаваться"


@pytest.mark.parametrize("resource", WITHOUT_SCHEMA)
@pytest.mark.parametrize("garbage", [12345, True, 1.5], ids=["int", "bool", "float"])
def test_scalar_of_wrong_type_instead_of_string_is_422(client, resource, garbage):
    """Число раньше сохранялось в строковое поле как есть (у ресурсов с Pydantic-схемой это отвергает сама схема)."""
    column = _string_column(resource)
    response = client.post(f"{API}/{resource}", json={column.key: garbage})
    _assert_validation_error(response, column.key, "ожидается строка")


@pytest.mark.parametrize("resource", WRITABLE)
def test_too_long_string_is_422_for_every_resource(client, resource):
    column = _string_column(resource)
    limit = column.type.length
    before = _total(client, resource)
    response = client.post(f"{API}/{resource}", json={column.key: "я" * (limit + 1)})
    assert response.status_code == 422, f"{resource}.{column.key}: {response.status_code} {response.text[:200]}"
    assert column.key in response.text and f"не более {limit} символов" in response.text or resource in RESOURCE_SCHEMAS
    assert _total(client, resource) == before


def test_string_of_exactly_the_limit_is_accepted(client):
    limit = _string_column("manufacturers").type.length
    created = client.post(f"{API}/manufacturers", json={"name": "я" * limit})
    assert created.status_code == 201, created.text
    assert len(created.json()["name"]) == limit


def test_huge_string_does_not_reach_the_database(client):
    response = client.post(f"{API}/manufacturers", json={"name": "x" * 100_000})
    _assert_validation_error(response, "name", "не более")


# ---------------------------------------------------------------------------------------------------------------------
# Остальные типы колонок
# ---------------------------------------------------------------------------------------------------------------------
BOOLEAN_COLUMNS = [(r, c.key) for r in WITHOUT_SCHEMA for c in _columns(r, Boolean)]
INTEGER_COLUMNS = [(r, c.key) for r in WITHOUT_SCHEMA for c in _columns(r, Integer)]


@pytest.mark.parametrize(("resource", "column"), BOOLEAN_COLUMNS)
@pytest.mark.parametrize("value", ["true", 1, 0, {"a": 1}], ids=["str", "one", "zero", "dict"])
def test_non_boolean_in_boolean_column_is_422(client, resource, column, value):
    _assert_validation_error(client.post(f"{API}/{resource}", json={column: value}), column, "true/false")


@pytest.mark.parametrize(("resource", "column"), INTEGER_COLUMNS)
@pytest.mark.parametrize("value", ["5", "", 1.5, True, [1], {"a": 1}], ids=["numeric-str", "empty-str", "float", "bool", "list", "dict"])
def test_non_integer_in_integer_column_is_422(client, resource, column, value):
    _assert_validation_error(client.post(f"{API}/{resource}", json={column: value}), column, "ожидается целое число")


@pytest.mark.parametrize(("resource", "column"), INTEGER_COLUMNS)
@pytest.mark.parametrize("value", [2**31, -(2**31) - 1, 10**30], ids=["int32-max+1", "int32-min-1", "huge"])
def test_integer_outside_database_range_is_422_not_500(client, resource, column, value):
    """SQLite падала OverflowError на числе больше 64 бит, PostgreSQL — DataError «integer out of range»."""
    _assert_validation_error(client.post(f"{API}/{resource}", json={column: value}), column, "число должно быть от")


def test_every_column_type_in_the_registry_has_a_validation_rule():
    """Новая колонка нового типа (JSON, Numeric, …) не должна остаться без проверки молча — тест напомнит дополнить правила."""
    unchecked = []
    for resource, model in MODEL_MAP.items():
        rules = _column_rules(model)
        unchecked += [f"{resource}.{c.key}: {type(c.type).__name__}" for c in inspect(model).columns if c.key not in rules]
    assert unchecked == []


# ---------------------------------------------------------------------------------------------------------------------
# Правка: PUT проверяется так же, запись остаётся прежней
# ---------------------------------------------------------------------------------------------------------------------
class TestUpdate:
    def test_garbage_on_put_is_422_and_record_is_unchanged(self, client):
        created = client.post(f"{API}/manufacturers", json={"name": "Исходное имя"}).json()
        for garbage in ({"a": 1}, ["x"], 12345, True):
            response = client.put(f"{API}/manufacturers/{created['id']}", json={"name": garbage})
            _assert_validation_error(response, "name")
        too_long = client.put(f"{API}/manufacturers/{created['id']}", json={"name": "я" * 5000})
        _assert_validation_error(too_long, "name", "не более")
        assert client.get(f"{API}/manufacturers/{created['id']}").json()["name"] == "Исходное имя"

    def test_valid_put_still_works_and_null_clears_optional_text(self, client):
        building = client.post(f"{API}/buildings", json={"name": "Корпус А-09", "address": "ул. Тестовая"}).json()
        updated = client.put(f"{API}/buildings/{building['id']}", json={"name": "Корпус А-09б", "address": None})
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "Корпус А-09б" and updated.json()["address"] is None

    def test_integer_column_on_put(self, client):
        building = client.post(f"{API}/buildings", json={"name": "Корпус стоек А-09"}).json()
        room = client.post(f"{API}/rooms", json={"name": "Зал", "building_id": building["id"]}).json()
        rack = client.post(f"{API}/racks", json={"name": "Стойка", "room_id": room["id"], "height_u": 42})
        assert rack.status_code == 201, rack.text
        bad = client.put(f"{API}/racks/{rack.json()['id']}", json={"height_u": "42"})
        _assert_validation_error(bad, "height_u", "ожидается целое число")
        assert client.put(f"{API}/racks/{rack.json()['id']}", json={"height_u": 45}).json()["height_u"] == 45

    def test_echoed_record_can_be_sent_back_unchanged(self, client):
        """Цикл «прочитал запись — поправил — отправил обратно» не ломается: id, created_at, updated_at отбрасываются
        до проверки, а прочие поля (в том числе None) остаются допустимыми."""
        created = client.post(f"{API}/manufacturers", json={"name": "Эхо-производитель"}).json()
        echoed = {**created, "name": "Эхо-производитель 2"}
        assert {"id", "created_at", "updated_at"} <= set(echoed)
        response = client.put(f"{API}/manufacturers/{created['id']}", json=echoed)
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Эхо-производитель 2"

    def test_echo_fields_with_odd_values_are_ignored_on_create(self, client):
        response = client.post(f"{API}/manufacturers", json={"name": "С эхом", "id": {"x": 1}, "created_at": 5, "updated_at": []})
        assert response.status_code == 201, response.text


# ---------------------------------------------------------------------------------------------------------------------
# Ресурсы со схемой Pydantic по-прежнему отвечают своей схемой, а дата — ISO-строкой
# ---------------------------------------------------------------------------------------------------------------------
class TestSchemaResources:
    def test_schema_resources_still_reject_garbage(self, client):
        for resource, column in (("devices", "serial_number"), ("information-systems", "name"), ("vlans", "name")):
            assert client.post(f"{API}/{resource}", json={column: {"a": 1}}).status_code == 422

    def test_device_with_valid_date_is_accepted_after_pydantic_conversion(self, client):
        category = client.get(f"{API}/device-categories").json()["items"][0]
        device_type = client.post(f"{API}/device-types", json={"name": "Тип А-09 дата", "category_id": category["id"]}).json()
        created = client.post(
            f"{API}/devices", json={"device_type_id": device_type["id"], "serial_number": "A09-D1", "oac_certificate_registry_date": "2026-10-19"}
        )
        assert created.status_code == 201, created.text
        assert created.json()["oac_certificate_registry_date"] == "2026-10-19"

    @pytest.mark.parametrize("value", ["не дата", "2026-13-45", 5, {"a": 1}])
    def test_device_with_bad_date_is_422(self, client, value):
        category = client.get(f"{API}/device-categories").json()["items"][0]
        device_type = client.post(f"{API}/device-types", json={"name": "Тип А-09 дата 2", "category_id": category["id"]}).json()
        response = client.post(f"{API}/devices", json={"device_type_id": device_type["id"], "serial_number": "A09-D2", "oac_certificate_registry_date": value})
        assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------------------------------------------------
# validate_column_types: unit
# ---------------------------------------------------------------------------------------------------------------------
class TestValidateColumnTypes:
    @staticmethod
    def _errors(model_key: str, data: dict) -> str | None:
        try:
            validate_column_types(MODEL_MAP[model_key], data)
        except HTTPException as exc:
            assert exc.status_code == 422
            return exc.detail
        return None

    def test_valid_values_and_none_pass(self):
        assert self._errors("racks", {"name": "Стойка", "height_u": 42, "room_id": None}) is None
        assert self._errors("racks", {"height_u": None}) is None
        assert self._errors("manufacturers", {}) is None

    def test_all_errors_are_reported_together_with_field_names(self):
        message = self._errors("racks", {"name": {"a": 1}, "height_u": "42", "room_id": 7})
        assert message.startswith("Ошибка валидации: ")
        assert all(fragment in message for fragment in ("name: ожидается строка", "height_u: ожидается целое число", "room_id: ожидается строка"))
        assert message.count(";") == 2

    def test_keys_that_are_not_columns_are_ignored(self):
        assert self._errors("manufacturers", {"name": "x", "not_a_column": {"a": 1}, "confirm_system_name_duplicate": True}) is None

    def test_nul_character_and_lone_surrogate_are_rejected(self):
        assert "нулевой символ" in self._errors("manufacturers", {"name": "a\x00b"})
        assert "недопустимые символы" in self._errors("manufacturers", {"name": "\ud800"})

    def test_bool_is_not_an_integer_and_int_is_not_a_boolean(self):
        assert "ожидается целое число" in self._errors("racks", {"height_u": True})
        assert "true/false" in self._errors("vlans", {"is_active": 1}) if "is_active" in _column_rules(MODEL_MAP["vlans"]) else True

    def test_date_and_datetime_rules(self):
        from sqlalchemy import Column
        from sqlalchemy.orm import declarative_base

        Base = declarative_base()

        class Sample(Base):
            __tablename__ = "a09_sample"
            id = Column(Integer, primary_key=True)
            day = Column(Date)
            moment = Column(DateTime)

        def check(data):
            try:
                validate_column_types(Sample, data)
            except HTTPException as exc:
                return exc.detail
            return None

        assert check({"day": "2026-10-19", "moment": "2026-10-19T18:00:00+00:00"}) is None
        assert check({"day": date(2026, 10, 19), "moment": datetime(2026, 10, 19, 18, 0)}) is None
        assert check({"day": "2026-10-19T18:00:00"}) is not None, "в колонку Date — только дата"
        assert "ГГГГ-ММ-ДД" in check({"day": "19.10.2026"})
        assert "ISO 8601" in check({"moment": "вчера"})
        assert check({"day": 20261019, "moment": 5}) is not None

    def test_rules_are_cached_per_model(self):
        assert _column_rules(MODEL_MAP["racks"]) is _column_rules(MODEL_MAP["racks"])


# ---------------------------------------------------------------------------------------------------------------------
# Обработчик DataError
# ---------------------------------------------------------------------------------------------------------------------
class TestDataErrorHandler:
    def test_handler_returns_422_without_driver_text(self):
        app = FastAPI()
        app.add_exception_handler(DataError, main_module.data_error_handler)

        @app.post("/boom")
        def boom():
            raise DataError("INSERT INTO secret_table …", {"p": "secret value"}, Exception("value too long for type character varying(255) secret_table"))

        response = TestClient(app).post("/boom")
        assert response.status_code == 422
        assert response.json() == {"detail": "Ошибка валидации: значение не подходит по типу или размеру."}
        assert "secret" not in response.text and "INSERT" not in response.text

    def test_handler_is_registered_in_the_real_application(self):
        assert main_module.app.exception_handlers[DataError] is main_module.data_error_handler

    def test_data_error_inside_create_resource_is_422_on_the_real_application(self, client, monkeypatch):
        import app.services.crud.generic as generic

        def failing_audit(*args, **kwargs):
            raise DataError("INSERT …", {}, Exception("value too long"))

        with monkeypatch.context() as patch:  # undo() целиком откатил бы и подмену БД из фикстуры client
            patch.setattr(generic, "audit", failing_audit)
            response = client.post(f"{API}/manufacturers", json={"name": "Падающий аудит"})
        assert response.status_code == 422
        assert "value too long" not in response.text
        names = [m["name"] for m in client.get(f"{API}/manufacturers", params={"limit": 500}).json()["items"]]
        assert "Падающий аудит" not in names, "транзакция откатана"

    def test_data_error_inside_update_resource_is_422_and_record_is_unchanged(self, client, monkeypatch):
        import app.services.crud.generic as generic

        created = client.post(f"{API}/manufacturers", json={"name": "До правки"}).json()

        def failing_audit(*args, **kwargs):
            raise DataError("UPDATE …", {}, Exception("value too long"))

        with monkeypatch.context() as patch:
            patch.setattr(generic, "audit", failing_audit)
            response = client.put(f"{API}/manufacturers/{created['id']}", json={"name": "После правки"})
        assert response.status_code == 422
        assert "value too long" not in response.text
        assert client.get(f"{API}/manufacturers/{created['id']}").json()["name"] == "До правки"

    @pytest.mark.postgres_only
    def test_postgres_data_error_from_the_driver_is_422(self, client, monkeypatch):
        """Проверка типов отключена: до PostgreSQL доходит строка длиннее VARCHAR(255) — DataError → 422, не 500."""
        import app.services.crud.generic as generic

        monkeypatch.setattr(generic, "validate_column_types", lambda model, data: None)
        response = client.post(f"{API}/manufacturers", json={"name": "я" * 300})
        assert response.status_code == 422, response.text
        assert response.json()["detail"].startswith("Ошибка валидации")
