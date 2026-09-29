"""PUT /api/v1/devices/{id}/vlans — атомарная diff-синхронизация блока «VLAN устройства»
(services/crud.py:sync_device_vlans). Заменяет клиентскую схему «удалить всё и создать заново»
(до этого DeviceFormModal.vue делал десятки отдельных запросов без транзакции)."""
from __future__ import annotations

import pytest


def _device(client, serial: str = "SW-VLAN") -> dict:
    category_id = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    dt = client.post("/api/v1/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    return client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": serial}).json()


def _vlan(client, number: int, **extra) -> dict:
    r = client.post("/api/v1/resources/vlans", json={"vlan_id": number, "name": f"VLAN {number}", **extra})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _sync(client, device_id: str, rows: list[dict]):
    return client.put(f"/api/v1/devices/{device_id}/vlans", json={"vlans": rows})


def _stored(client, device_id: str) -> dict[str, dict]:
    items = client.get("/api/v1/resources/device-vlans", params={"physical_device_id": device_id, "limit": 1000}).json()["items"]
    return {x["vlan_id"]: x for x in items}


def test_creates_rows_with_normalized_values(client):
    dev, v10 = _device(client), None
    v10 = _vlan(client, 10)
    r = _sync(client, dev["id"], [{"vlan_id": v10["id"], "ip_address": "10.0.10.1", "prefix_length": "24", "is_management": True, "description": ""}])
    assert r.status_code == 200, r.text
    (item,) = r.json()["items"]
    assert (item["ip_address"], item["prefix_length"], item["is_management"], item["description"]) == ("10.0.10.1", 24, True, None)


def test_diff_keeps_unchanged_rows_and_only_touches_changed_added_removed(client):
    dev = _device(client)
    v10, v20, v30, v40 = (_vlan(client, n) for n in (10, 20, 30, 40))
    assert _sync(client, dev["id"], [{"vlan_id": v["id"]} for v in (v10, v20, v30)]).status_code == 200
    before = _stored(client, dev["id"])

    r = _sync(client, dev["id"], [
        {"vlan_id": v10["id"]},                                  # не менялся
        {"vlan_id": v20["id"], "ip_address": "10.0.20.1", "prefix_length": 24},  # изменён
        {"vlan_id": v40["id"]},                                  # добавлен; v30 убран
    ])
    assert r.status_code == 200, r.text
    after = _stored(client, dev["id"])

    assert set(after) == {v10["id"], v20["id"], v40["id"]}
    assert after[v10["id"]]["id"] == before[v10["id"]]["id"]
    assert after[v10["id"]]["updated_at"] == before[v10["id"]]["updated_at"]  # нет лишнего UPDATE
    assert after[v20["id"]]["id"] == before[v20["id"]]["id"]  # обновлена на месте, не пересоздана
    assert after[v20["id"]]["ip_address"] == "10.0.20.1"
    audit = client.get("/api/v1/resources/audit-log?entity_type=device-vlans&limit=50").json()["items"]
    assert any("добавлено 1, изменено 1, удалено 1" in (a.get("details") or "") for a in audit)


def test_invalid_row_rolls_back_everything(client):
    """Раньше ошибка на середине delete+create оставляла устройство без части VLAN."""
    dev = _device(client)
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    assert _sync(client, dev["id"], [{"vlan_id": v10["id"], "ip_address": "10.0.10.1"}]).status_code == 200

    r = _sync(client, dev["id"], [{"vlan_id": v20["id"]}, {"vlan_id": v10["id"], "ip_address": "999.1.1.1"}])
    assert r.status_code == 422
    stored = _stored(client, dev["id"])
    assert set(stored) == {v10["id"]}
    assert stored[v10["id"]]["ip_address"] == "10.0.10.1"


def test_replacing_vlan_in_row_and_swapping_do_not_violate_unique_constraint(client):
    dev = _device(client)
    v10, v20, v30 = (_vlan(client, n) for n in (10, 20, 30))
    assert _sync(client, dev["id"], [{"vlan_id": v10["id"]}, {"vlan_id": v20["id"]}]).status_code == 200
    assert _sync(client, dev["id"], [{"vlan_id": v20["id"]}, {"vlan_id": v10["id"]}]).status_code == 200  # перестановка
    assert _sync(client, dev["id"], [{"vlan_id": v30["id"]}, {"vlan_id": v20["id"]}]).status_code == 200  # 10 -> 30
    assert set(_stored(client, dev["id"])) == {v20["id"], v30["id"]}


@pytest.mark.parametrize(
    ("rows", "status"),
    [
        ([{"ip_address": "10.0.0.1"}], 422),  # нет vlan_id
        ([{"vlan_id": "no-such-vlan"}], 422),
        (["не объект"], 422),
        ([{"vlan_id": "X", "prefix_length": 33}], 422),
    ],
)
def test_rejects_malformed_rows(client, rows, status):
    dev = _device(client)
    if rows and isinstance(rows[0], dict) and rows[0].get("vlan_id") == "X":
        rows[0]["vlan_id"] = _vlan(client, 10)["id"]
    assert _sync(client, dev["id"], rows).status_code == status


def test_rejects_duplicate_vlan_unknown_device_and_non_array(client):
    dev = _device(client)
    v10 = _vlan(client, 10)
    assert _sync(client, dev["id"], [{"vlan_id": v10["id"]}, {"vlan_id": v10["id"]}]).status_code == 422
    assert _sync(client, "does-not-exist", []).status_code == 404
    assert client.put(f"/api/v1/devices/{dev['id']}/vlans", json={"vlans": "x"}).status_code == 422


def test_domain_vlan_requires_membership_and_auto_assigned_rows_survive_sync(client):
    source, dev = _device(client, "SW-SRC"), _device(client, "SW-MEMBER")
    domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен sync", "source_device_id": source["id"]}).json()
    v10, v20 = (_vlan(client, n, domain_id=domain["id"]) for n in (10, 20))

    assert _sync(client, dev["id"], [{"vlan_id": v10["id"]}]).status_code == 422  # ещё не член домена

    assert client.post("/api/v1/resources/vlan-domain-devices", json={"physical_device_id": dev["id"], "domain_id": domain["id"]}).status_code in (200, 201)
    auto = _stored(client, dev["id"])  # членство само назначило VLAN домена
    assert set(auto) == {v10["id"], v20["id"]}

    r = _sync(client, dev["id"], [{"vlan_id": v10["id"]}, {"vlan_id": v20["id"], "ip_address": "10.0.20.5", "prefix_length": 24}])
    assert r.status_code == 200, r.text
    after = _stored(client, dev["id"])
    assert after[v10["id"]]["id"] == auto[v10["id"]]["id"] and after[v20["id"]]["id"] == auto[v20["id"]]["id"]
    assert after[v20["id"]]["ip_address"] == "10.0.20.5"
