"""Код-ревью F-03: защита от потерянных обновлений охватывает и вложенные коллекции записи.

`expected_updated_at` сверяется с `updated_at` самой записи, а формы устройства, ВМ и ИС сохраняют порты, VLAN, IP и ПО отдельными PUT с
семантикой полной замены, которые версию родителя не двигали: вкладка со старым токеном проходила проверку и затирала чужую правку.
Теперь реальная правка вложенного списка сдвигает версию родителя (services/crud/versioning.py), а повторное сохранение без правок — нет.

Запуск: pytest backend/tests/test_review_p3_nested_collection_version.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.constants import ErrorCode
from app.models import Manufacturer
from app.services.crud import versioning
from app.services.crud.versioning import touch_parent, track_nested_changes

API = "/api/v1"


def _device(client, serial: str = "NV-1") -> dict:
    categories = client.get(f"{API}/resources/device-categories").json()["items"]
    device_type = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": categories[0]["id"]}).json()
    response = client.post(f"{API}/resources/devices", json={"device_type_id": device_type["id"], "serial_number": serial})
    assert response.status_code == 201, response.text
    return response.json()


def _vm(client, name: str = "ВМ версии") -> dict:
    response = client.post(f"{API}/resources/vms", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _information_system(client, name: str = "ИС версии") -> dict:
    response = client.post(f"{API}/resources/information-systems", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _version(client, resource: str, item_id: str) -> str:
    response = client.get(f"{API}/resources/{resource}/{item_id}")
    assert response.status_code == 200, response.text
    return response.json()["updated_at"]


def _put_with_token(client, resource: str, item_id: str, token: str, body: dict):
    return client.put(f"{API}/resources/{resource}/{item_id}", json={**body, "expected_updated_at": token})


def _assert_stale(response) -> None:
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == ErrorCode.STALE_RECORD


# --- touch_parent ---------------------------------------------------------------------------------------------------------------


def test_touch_parent_moves_the_version_forward_by_at_least_a_millisecond(monkeypatch):
    """Сверка токена идёт с точностью до миллисекунды: правка в ту же миллисекунду не должна оставить прежнюю версию."""
    before = datetime(2026, 11, 22, 12, 0, 0, 123_400)
    parent = SimpleNamespace(updated_at=before)
    monkeypatch.setattr(versioning, "utcnow_naive", lambda: before)  # «сейчас» совпало с прежней версией
    touch_parent(parent)
    assert parent.updated_at >= before + timedelta(milliseconds=1)
    assert parent.updated_at.replace(microsecond=parent.updated_at.microsecond // 1000 * 1000) != before.replace(microsecond=123_000)


def test_touch_parent_survives_a_clock_that_went_backwards(monkeypatch):
    before = datetime(2026, 11, 22, 12, 0, 0)
    parent = SimpleNamespace(updated_at=before)
    monkeypatch.setattr(versioning, "utcnow_naive", lambda: before - timedelta(hours=1))
    touch_parent(parent)
    assert parent.updated_at > before


def test_touch_parent_uses_the_current_time_when_it_is_later(monkeypatch):
    now = datetime(2026, 11, 22, 12, 30, 0)
    parent = SimpleNamespace(updated_at=datetime(2026, 11, 22, 12, 0, 0))
    monkeypatch.setattr(versioning, "utcnow_naive", lambda: now)
    touch_parent(parent)
    assert parent.updated_at == now


def test_touch_parent_sets_the_version_of_a_record_that_has_none(monkeypatch):
    now = datetime(2026, 11, 22, 12, 30, 0)
    parent = SimpleNamespace(updated_at=None)
    monkeypatch.setattr(versioning, "utcnow_naive", lambda: now)
    touch_parent(parent)
    assert parent.updated_at == now


# --- track_nested_changes -------------------------------------------------------------------------------------------------------


@pytest.fixture()
def saved_manufacturer(db_session) -> Manufacturer:
    row = Manufacturer(name="Исходное имя")
    db_session.add(row)
    db_session.commit()
    return row


def test_tracker_ignores_assigning_the_same_value(db_session, saved_manufacturer):
    with track_nested_changes(db_session) as nested:
        saved_manufacturer.name = "Исходное имя"
    assert nested.changed is False


def test_tracker_sees_a_changed_value(db_session, saved_manufacturer):
    with track_nested_changes(db_session) as nested:
        saved_manufacturer.name = "Новое имя"
    assert nested.changed is True


def test_tracker_sees_created_and_deleted_rows(db_session, saved_manufacturer):
    with track_nested_changes(db_session) as created:
        db_session.add(Manufacturer(name="Добавленный"))
    assert created.changed is True
    with track_nested_changes(db_session) as deleted:
        db_session.delete(saved_manufacturer)
    assert deleted.changed is True


def test_tracker_does_not_count_the_parent_itself(db_session, saved_manufacturer):
    with track_nested_changes(db_session, ignore=saved_manufacturer) as nested:
        saved_manufacturer.name = "Правка самого родителя"
    assert nested.changed is False


def test_tracker_detaches_its_listener_even_after_an_error(db_session):
    listeners_before = len(db_session.dispatch.after_flush)
    with pytest.raises(RuntimeError):
        with track_nested_changes(db_session):
            assert len(db_session.dispatch.after_flush) == listeners_before + 1
            raise RuntimeError("сбой внутри блока")
    assert len(db_session.dispatch.after_flush) == listeners_before, "обработчик остался на сессии после сбоя"


# --- порты устройства -------------------------------------------------------------------------------------------------------------


def test_syncing_ports_moves_the_device_version_and_a_stale_form_gets_409(client):
    device = _device(client)
    token = _version(client, "devices", device["id"])  # форма Б открыта до правки портов формой А

    assert client.put(f"{API}/devices/{device['id']}/interfaces", json={"interfaces": [{"name": "Gi0/1"}]}).status_code == 200
    assert _version(client, "devices", device["id"]) != token, "правка портов сдвигает версию устройства"

    _assert_stale(_put_with_token(client, "devices", device["id"], token, {"system_name": "Правка Б"}))


def _as_the_form_resends(items: list[dict]) -> dict:
    """Тело повторного «Сохранить»: форма шлёт id существующих портов и IP (строка без id — новая запись, то есть настоящая правка)."""
    return {
        "interfaces": [
            {
                "id": item["id"],
                "name": item["name"],
                "ips": [
                    {"id": ip["id"], "ip_address": ip["ip_address"], "prefix_length": ip["prefix_length"]} for ip in item.get("ips", [])
                ],
            }
            for item in items
        ]
    }


def test_resaving_unchanged_ports_keeps_the_version(client):
    """Форма шлёт полное состояние при каждом «Сохранить»: без правок другая вкладка не должна получать ложный конфликт."""
    device = _device(client)
    body = {"interfaces": [{"name": "Gi0/1", "ips": [{"ip_address": "10.0.0.1", "prefix_length": 24}]}, {"name": "Gi0/2"}]}
    saved_items = client.put(f"{API}/devices/{device['id']}/interfaces", json=body).json()["items"]
    saved = _version(client, "devices", device["id"])

    again = client.put(f"{API}/devices/{device['id']}/interfaces", json=_as_the_form_resends(saved_items))
    assert again.status_code == 200, again.text
    assert _version(client, "devices", device["id"]) == saved


def test_changing_a_nested_ip_moves_the_device_version(client):
    device = _device(client)
    body = {"interfaces": [{"name": "Gi0/1", "ips": [{"ip_address": "10.0.0.1", "prefix_length": 24}]}]}
    saved_items = client.put(f"{API}/devices/{device['id']}/interfaces", json=body).json()["items"]
    saved = _version(client, "devices", device["id"])

    edited = _as_the_form_resends(saved_items)
    edited["interfaces"][0]["ips"][0]["ip_address"] = "10.0.0.2"
    assert client.put(f"{API}/devices/{device['id']}/interfaces", json=edited).status_code == 200
    assert _version(client, "devices", device["id"]) != saved


def test_adding_a_port_to_the_saved_state_moves_the_device_version(client):
    device = _device(client)
    saved_items = client.put(f"{API}/devices/{device['id']}/interfaces", json={"interfaces": [{"name": "Gi0/1"}]}).json()["items"]
    saved = _version(client, "devices", device["id"])

    grown = _as_the_form_resends(saved_items)
    grown["interfaces"].append({"name": "Gi0/2"})
    assert client.put(f"{API}/devices/{device['id']}/interfaces", json=grown).status_code == 200
    assert _version(client, "devices", device["id"]) != saved


def test_a_rejected_ports_sync_leaves_the_version_alone(client):
    device = _device(client)
    saved = _version(client, "devices", device["id"])
    rejected = client.put(
        f"{API}/devices/{device['id']}/interfaces", json={"interfaces": [{"name": "Gi0/1", "ips": [{"ip_address": "999.1.1.1"}]}]}
    )
    assert rejected.status_code == 422
    assert _version(client, "devices", device["id"]) == saved


def test_the_editor_who_refreshes_the_token_after_nested_steps_can_save_again(client):
    """Цепочка формы: сохранить запись → синхронизировать порты → перечитать токен → повторное сохранение проходит."""
    device = _device(client)
    token = _version(client, "devices", device["id"])
    assert _put_with_token(client, "devices", device["id"], token, {"system_name": "SW-A"}).status_code == 200
    assert client.put(f"{API}/devices/{device['id']}/interfaces", json={"interfaces": [{"name": "Gi0/1"}]}).status_code == 200

    stale_own_token = token
    _assert_stale(_put_with_token(client, "devices", device["id"], stale_own_token, {"system_name": "SW-B"}))
    fresh = _version(client, "devices", device["id"])
    assert _put_with_token(client, "devices", device["id"], fresh, {"system_name": "SW-B"}).status_code == 200


# --- VLAN устройства --------------------------------------------------------------------------------------------------------------


def test_syncing_device_vlans_moves_the_device_version(client):
    device = _device(client, "NV-VLAN")
    vlan = client.post(f"{API}/resources/vlans", json={"vlan_id": 10, "name": "vlan-10"}).json()
    token = _version(client, "devices", device["id"])

    assert client.put(f"{API}/devices/{device['id']}/vlans", json={"vlans": [{"vlan_id": vlan["id"]}]}).status_code == 200
    assert _version(client, "devices", device["id"]) != token
    _assert_stale(_put_with_token(client, "devices", device["id"], token, {"system_name": "Правка Б"}))


def test_resaving_the_same_device_vlans_keeps_the_version(client):
    device = _device(client, "NV-VLAN2")
    vlan = client.post(f"{API}/resources/vlans", json={"vlan_id": 20, "name": "vlan-20"}).json()
    body = {"vlans": [{"vlan_id": vlan["id"], "ip_address": "10.0.20.1", "prefix_length": 24}]}
    assert client.put(f"{API}/devices/{device['id']}/vlans", json=body).status_code == 200
    saved = _version(client, "devices", device["id"])

    assert client.put(f"{API}/devices/{device['id']}/vlans", json=body).status_code == 200
    assert _version(client, "devices", device["id"]) == saved


# --- списки ВМ ------------------------------------------------------------------------------------------------------------------


def test_syncing_vm_ip_addresses_moves_the_vm_version(client):
    vm = _vm(client)
    token = _version(client, "vms", vm["id"])

    body = {"ip_addresses": [{"ip_address": "10.1.0.5", "prefix_length": 24}]}
    response = client.put(f"{API}/vms/{vm['id']}/ip-addresses", json=body)
    assert response.status_code == 200, response.text
    assert _version(client, "vms", vm["id"]) != token
    _assert_stale(_put_with_token(client, "vms", vm["id"], token, {"name": vm["name"], "description": "Правка Б"}))


def test_resaving_the_same_vm_ip_addresses_keeps_the_version(client):
    vm = _vm(client, "ВМ без правок")
    body = {"ip_addresses": [{"ip_address": "10.1.0.6", "prefix_length": 24}]}
    saved_items = client.put(f"{API}/vms/{vm['id']}/ip-addresses", json=body).json()["items"]
    saved = _version(client, "vms", vm["id"])

    same = {"ip_addresses": [{"id": saved_items[0]["id"], "ip_address": "10.1.0.6", "prefix_length": 24}]}
    assert client.put(f"{API}/vms/{vm['id']}/ip-addresses", json=same).status_code == 200
    assert _version(client, "vms", vm["id"]) == saved


def test_removing_the_last_vm_row_moves_the_vm_version(client):
    vm = _vm(client, "ВМ с удалением")
    client.put(f"{API}/vms/{vm['id']}/ip-addresses", json={"ip_addresses": [{"ip_address": "10.1.0.7", "prefix_length": 24}]})
    saved = _version(client, "vms", vm["id"])

    assert client.put(f"{API}/vms/{vm['id']}/ip-addresses", json={"ip_addresses": []}).status_code == 200
    assert _version(client, "vms", vm["id"]) != saved


# --- детали ИС --------------------------------------------------------------------------------------------------------------------


def test_syncing_information_system_details_moves_the_system_version(client):
    system = _information_system(client)
    department = client.post(f"{API}/resources/departments", json={"name": "Отдел версий"}).json()
    token = _version(client, "information-systems", system["id"])

    response = client.put(
        f"{API}/resources/information-systems/{system['id']}/details", json={"departments": [{"department_id": department["id"]}]}
    )
    assert response.status_code == 200, response.text
    assert _version(client, "information-systems", system["id"]) != token
    _assert_stale(_put_with_token(client, "information-systems", system["id"], token, {"name": system["name"], "description": "Правка Б"}))


def test_resaving_unchanged_information_system_details_keeps_the_version(client):
    system = _information_system(client, "ИС без правок")
    department = client.post(f"{API}/resources/departments", json={"name": "Отдел без правок"}).json()
    first = client.put(
        f"{API}/resources/information-systems/{system['id']}/details", json={"departments": [{"department_id": department["id"]}]}
    ).json()
    saved = _version(client, "information-systems", system["id"])

    same = {"departments": [{"id": first["departments"][0]["id"], "department_id": department["id"]}]}
    assert client.put(f"{API}/resources/information-systems/{system['id']}/details", json=same).status_code == 200
    assert _version(client, "information-systems", system["id"]) == saved
