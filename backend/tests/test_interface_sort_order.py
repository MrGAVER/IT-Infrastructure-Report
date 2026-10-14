"""Порядок портов устройства: device_interfaces.sort_order.

Пользователь переставляет порты в форме устройства стрелками вверх/вниз; порядок элементов в PUT /devices/{id}/interfaces
записывается в sort_order, а чтение (результат PUT и GET /resources/interfaces) отдаёт порты в этом порядке — а не по имени
и не по времени создания.

Запуск: pytest backend/tests/test_interface_sort_order.py -v
"""
from __future__ import annotations

API = "/api/v1"


def _device(client, serial: str = "SW-1") -> dict:
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    dt = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    return client.post(f"{API}/resources/devices", json={"device_type_id": dt["id"], "serial_number": serial}).json()


def _sync(client, device_id: str, names_or_rows: list) -> list[dict]:
    rows = [{"name": x} if isinstance(x, str) else x for x in names_or_rows]
    r = client.put(f"{API}/devices/{device_id}/interfaces", json={"interfaces": rows})
    assert r.status_code == 200, r.text
    return r.json()["items"] if isinstance(r.json(), dict) and "items" in r.json() else r.json()


def _listed(client, device_id: str) -> list[dict]:
    return client.get(f"{API}/resources/interfaces", params={"physical_device_id": device_id, "limit": 1000}).json()["items"]


def test_order_from_payload_is_saved_and_not_alphabetical(client):
    dev = _device(client)

    result = _sync(client, dev["id"], ["Gi0/3", "Gi0/1", "Gi0/2"])

    assert [p["name"] for p in result] == ["Gi0/3", "Gi0/1", "Gi0/2"]
    assert [p["name"] for p in _listed(client, dev["id"])] == ["Gi0/3", "Gi0/1", "Gi0/2"]
    assert [p["sort_order"] for p in _listed(client, dev["id"])] == [0, 1, 2]


def test_reordering_existing_ports_by_id_persists_after_reload(client):
    dev = _device(client)
    created = _sync(client, dev["id"], ["Gi0/1", "Gi0/2", "Gi0/3"])
    by_name = {p["name"]: p for p in created}

    # Пользователь поднял Gi0/3 на первое место; порты приходят с id, как их отдаёт форма.
    reordered = [{"id": by_name[n]["id"], "name": n} for n in ("Gi0/3", "Gi0/1", "Gi0/2")]
    _sync(client, dev["id"], reordered)

    listed = _listed(client, dev["id"])
    assert [p["name"] for p in listed] == ["Gi0/3", "Gi0/1", "Gi0/2"]
    # Порты те же самые (не пересозданы): id сохранились.
    assert {p["name"]: p["id"] for p in listed} == {n: p["id"] for n, p in by_name.items()}


def test_new_port_appended_by_payload_goes_to_its_position(client):
    dev = _device(client)
    created = _sync(client, dev["id"], ["Gi0/1", "Gi0/2"])
    ids = {p["name"]: p["id"] for p in created}

    _sync(client, dev["id"], [{"id": ids["Gi0/1"], "name": "Gi0/1"}, {"name": "Gi0/9"}, {"id": ids["Gi0/2"], "name": "Gi0/2"}])

    assert [p["name"] for p in _listed(client, dev["id"])] == ["Gi0/1", "Gi0/9", "Gi0/2"]


def test_port_created_outside_the_form_goes_to_the_end(client):
    dev = _device(client)
    _sync(client, dev["id"], ["Gi0/2", "Gi0/1"])

    r = client.post(f"{API}/resources/interfaces", json={"physical_device_id": dev["id"], "name": "Mgmt0"})
    assert r.status_code in (200, 201), r.text

    assert [p["name"] for p in _listed(client, dev["id"])] == ["Gi0/2", "Gi0/1", "Mgmt0"]


def test_order_is_per_device(client):
    first, second = _device(client, "SW-A"), _device(client, "SW-B")

    _sync(client, first["id"], ["B", "A"])
    _sync(client, second["id"], ["Y", "X", "Z"])

    assert [p["name"] for p in _listed(client, first["id"])] == ["B", "A"]
    assert [p["name"] for p in _listed(client, second["id"])] == ["Y", "X", "Z"]
