"""Тесты проверки неизвестных ключей generic CRUD для devices / information-systems / vlans (код-ревью, п. 8).

Раньше ключ вне колонок модели отбрасывался молча: опечатка `serial_numbr` давала «успех» без значения,
а правка с опечаткой ничего не меняла. Запуск: pytest backend/tests/test_code_review_strict_payload.py -v
"""
from __future__ import annotations


def _device_type(client) -> str:
    categories = client.get("/api/v1/resources/device-categories").json()["items"]
    r = client.post("/api/v1/resources/device-types", json={"name": "Тип для строгих тел", "category_id": categories[0]["id"]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _device(client, serial: str = "STRICT-1", **extra) -> dict:
    r = client.post("/api/v1/resources/devices", json={"device_type_id": _device_type_for(client), "serial_number": serial, **extra})
    assert r.status_code == 201, r.text
    return r.json()


_cache: dict[int, str] = {}


def _device_type_for(client) -> str:
    """Тип устройства для тестов файла — один на клиента. Ключ id(client) ненадёжен: адрес уничтоженного клиента
    может достаться новому (с чистой БД), поэтому запомненный id проверяется на существование в текущей БД."""
    key = id(client)
    cached = _cache.get(key)
    if cached is None or client.get(f"/api/v1/resources/device-types/{cached}").status_code != 200:
        _cache[key] = _device_type(client)
    return _cache[key]


def test_type_id_remembered_for_another_database_is_not_reused(client):
    """Регрессия нестабильного теста: кэш ключуется по id(client), а адрес уничтоженного клиента может достаться
    новому клиенту с другой, чистой БД. Тогда кэш отдавал id типа из прошлой БД и создание устройства падало на
    внешнем ключе — но только в полном прогоне, зависимо от раскладки памяти. Эмулируем такое совпадение."""
    _cache[id(client)] = "id-типа-из-прошлой-БД"
    assert _device(client, "T-STALE")["serial_number"] == "T-STALE"


class TestDevices:
    def test_typo_on_create_is_rejected_with_a_hint_and_nothing_is_created(self, client):
        type_id = _device_type_for(client)
        r = client.post("/api/v1/resources/devices", json={"device_type_id": type_id, "serial_number": "T-1", "system_nam": "sw-1"})
        assert r.status_code == 422
        assert "system_nam" in r.text and "system_name" in r.text  # имя опечатки и подсказка
        assert client.get("/api/v1/resources/devices?q=T-1").json()["items"] == []

    def test_typo_on_update_is_rejected_and_the_record_is_unchanged(self, client):
        device = _device(client, "T-2", description="было")
        r = client.put(f"/api/v1/resources/devices/{device['id']}", json={"descripton": "стало"})
        assert r.status_code == 422 and "description" in r.text
        assert client.get(f"/api/v1/resources/devices/{device['id']}").json()["description"] == "было"

    def test_all_unknown_keys_are_listed_at_once(self, client):
        device = _device(client, "T-3")
        r = client.put(f"/api/v1/resources/devices/{device['id']}", json={"foo_bar": 1, "baz_qux": 2})
        assert r.status_code == 422 and "foo_bar" in r.text and "baz_qux" in r.text

    def test_columns_missing_from_the_pydantic_schema_are_still_accepted(self, client):
        # diagram_icon_id — колонка модели, которой нет в PhysicalDeviceCreate; форма устройства её отправляет.
        icon = client.post("/api/v1/resources/diagram-icons", json={"name": "Иконка", "mode": "custom", "svg_markup": "<rect/>"})
        device = _device(client, "T-4", diagram_icon_id=icon.json()["id"] if icon.status_code == 201 else None)
        assert device["serial_number"] == "T-4"

    def test_service_flags_are_accepted(self, client):
        device = _device(client, "T-5")
        r = client.put(f"/api/v1/resources/devices/{device['id']}", json={"description": "x", "confirm_system_name_duplicate": True, "confirm_rack_position_reassign": False})
        assert r.status_code == 200, r.text

    def test_echoing_a_fetched_record_back_still_works(self, client):
        device = _device(client, "T-6")
        fetched = client.get(f"/api/v1/resources/devices/{device['id']}").json()
        body = {k: fetched[k] for k in ("id", "created_at", "updated_at", "serial_number", "description")}
        assert client.put(f"/api/v1/resources/devices/{device['id']}", json=body).status_code == 200


class TestInformationSystemsAndVlans:
    def test_information_system_typo_is_rejected(self, client):
        r = client.post("/api/v1/resources/information-systems", json={"name": "ИС-1", "purpse": "учёт"})
        assert r.status_code == 422 and "purpse" in r.text and "purpose" in r.text
        ok = client.post("/api/v1/resources/information-systems", json={"name": "ИС-1", "purpose": "учёт"})
        assert ok.status_code == 201

    def test_information_system_number_echo_is_ignored_not_rejected(self, client):
        system = client.post("/api/v1/resources/information-systems", json={"name": "ИС-2"}).json()
        r = client.put(f"/api/v1/resources/information-systems/{system['id']}", json={"name": "ИС-2 новое", "number": 999})
        assert r.status_code == 200 and r.json()["number"] == system["number"]

    def test_vlan_typo_is_rejected(self, client):
        assert client.post("/api/v1/resources/vlans", json={"vlan_id": 10, "name": "v10", "descripton": "x"}).status_code == 422
        assert client.post("/api/v1/resources/vlans", json={"vlan_id": 10, "name": "v10", "description": "x"}).status_code == 201


def test_resources_without_a_schema_keep_the_lenient_behaviour(client):
    # Сознательно инкрементальное покрытие: для остальных ресурсов ключи вне колонок по-прежнему отбрасываются.
    r = client.post("/api/v1/resources/manufacturers", json={"name": "Лояльный", "ignored_key": 1})
    assert r.status_code == 201
