"""Подинтерфейсы портов устройства: PUT /devices/{id}/interfaces с ключом subinterfaces у порта и
GET /devices/{id}/subinterfaces (services/crud/subinterfaces.py).

Главные инварианты: подинтерфейс — НЕ физический порт (не попадает в ресурс interfaces), его IP и
открытые порты хранятся с owner_type=device_subinterface, ключ subinterfaces — полный список (без
ключа подинтерфейсы не трогаются), а удаление порта/подинтерфейса не оставляет «висячих» IP и портов.
"""
from __future__ import annotations

API = "/api/v1"


def _catalog_entry(client, port: int, protocol_type: str) -> dict:
    existing = client.get(f"{API}/resources/protocol-port-catalog", params={"limit": 1000}).json()["items"]
    match = next((e for e in existing if e["port"] == port and e["protocol_type"] == protocol_type), None)
    return match or client.post(f"{API}/resources/protocol-port-catalog", json={"port": port, "protocol_type": protocol_type}).json()


def _vlan(client, number: int) -> dict:
    r = client.post(f"{API}/resources/vlans", json={"vlan_id": number, "name": f"VLAN {number}"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _device(client, serial: str = "RTR-1", vlans: tuple[dict, ...] = ()) -> dict:
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    dt = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    for v in vlans:
        client.post(f"{API}/resources/device-type-vlans", json={"device_type_id": dt["id"], "vlan_id": v["id"]})
    return client.post(f"{API}/resources/devices", json={"device_type_id": dt["id"], "serial_number": serial}).json()


def _sync(client, device_id: str, interfaces: list[dict]):
    return client.put(f"{API}/devices/{device_id}/interfaces", json={"interfaces": interfaces})


def _sub(name: str, vlan: dict | None, **extra) -> dict:
    return {"name": name, "vlan_id": vlan["id"] if vlan else None, **extra}


def _port(name: str, **extra) -> dict:
    return {"name": name, **extra}


def _by_name(items: list[dict]) -> dict[str, dict]:
    return {x["name"]: x for x in items}


def _poly(client, resource: str, owner_type: str) -> list[dict]:
    return client.get(f"{API}/resources/{resource}", params={"owner_type": owner_type, "limit": 1000}).json()["items"]


def test_port_with_subinterfaces_is_saved_with_ips_ports_and_flags(client):
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    dev = _device(client, vlans=(v10, v20))
    ssh = _catalog_entry(client, 22, "SSH")

    r = _sync(client, dev["id"], [_port("Gi0/0", subinterfaces=[
        _sub("Gi0/0.10", v10, is_management=True, description="управление", ips=[{"ip_address": "10.0.10.1", "prefix_length": 24, "purpose": "шлюз"}],
             open_ports=[{"protocol_catalog_id": ssh["id"], "transport_protocol": "TCP", "description": "админ"}]),
        _sub("Gi0/0.20", v20, is_data_transfer=True, ips=[{"ip_address": "10.0.20.1", "prefix_length": 24}]),
    ])])

    assert r.status_code == 200, r.text
    (port,) = r.json()["items"]
    subs = _by_name(port["subinterfaces"])
    assert set(subs) == {"Gi0/0.10", "Gi0/0.20"}
    mgmt = subs["Gi0/0.10"]
    assert (mgmt["vlan_id"], mgmt["is_management"], mgmt["is_data_transfer"], mgmt["description"]) == (v10["id"], True, False, "управление")
    assert [(i["ip_address"], i["prefix_length"], i["purpose"], i["is_management"]) for i in mgmt["ips"]] == [("10.0.10.1", 24, "шлюз", True)]
    assert [(p["protocol_catalog_id"], p["port"], p["description"]) for p in mgmt["open_ports"]] == [(ssh["id"], 22, "админ")]
    assert subs["Gi0/0.20"]["is_data_transfer"] is True and subs["Gi0/0.20"]["ips"][0]["is_management"] is False
    # порядок подинтерфейсов порта — по номеру VLAN
    assert [s["name"] for s in port["subinterfaces"]] == ["Gi0/0.10", "Gi0/0.20"]

    listed = client.get(f"{API}/devices/{dev['id']}/subinterfaces").json()["items"]
    assert {s["id"] for s in listed} == {s["id"] for s in port["subinterfaces"]}
    assert all(s["parent_interface_id"] == port["id"] for s in listed)


def test_subinterface_is_not_a_physical_port_and_uses_its_own_owner_type(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    r = _sync(client, dev["id"], [_port("Gi0/0", subinterfaces=[_sub("Gi0/0.10", v10, ips=[{"ip_address": "10.0.10.1", "prefix_length": 24}])])])
    assert r.status_code == 200, r.text

    ports = client.get(f"{API}/resources/interfaces", params={"physical_device_id": dev["id"], "limit": 1000}).json()["items"]
    assert [p["name"] for p in ports] == ["Gi0/0"]
    assert _poly(client, "ip-addresses", "device_interface") == []
    assert [i["ip_address"] for i in _poly(client, "ip-addresses", "device_subinterface")] == ["10.0.10.1"]


def test_resync_updates_in_place_adds_and_removes_without_orphans(client):
    v10, v20, v30 = _vlan(client, 10), _vlan(client, 20), _vlan(client, 30)
    dev = _device(client, vlans=(v10, v20, v30))
    ssh = _catalog_entry(client, 22, "SSH")
    first = _sync(client, dev["id"], [_port("Gi0/0", subinterfaces=[
        _sub("Gi0/0.10", v10, ips=[{"ip_address": "10.0.10.1", "prefix_length": 24}], open_ports=[{"protocol_catalog_id": ssh["id"]}]),
        _sub("Gi0/0.20", v20, ips=[{"ip_address": "10.0.20.1", "prefix_length": 24}]),
    ])]).json()["items"][0]
    keep = _by_name(first["subinterfaces"])["Gi0/0.10"]

    r = _sync(client, dev["id"], [_port("Gi0/0", id=first["id"], subinterfaces=[
        {**_sub("Gi0/0.100", v10), "id": keep["id"], "ips": [{"id": keep["ips"][0]["id"], "ip_address": "10.0.10.254", "prefix_length": 24}], "open_ports": []},
        _sub("Gi0/0.30", v30),
    ])])

    assert r.status_code == 200, r.text
    subs = _by_name(r.json()["items"][0]["subinterfaces"])
    assert set(subs) == {"Gi0/0.100", "Gi0/0.30"}
    assert subs["Gi0/0.100"]["id"] == keep["id"]
    assert [(i["id"], i["ip_address"]) for i in subs["Gi0/0.100"]["ips"]] == [(keep["ips"][0]["id"], "10.0.10.254")]
    assert subs["Gi0/0.100"]["open_ports"] == []
    # IP удалённого Gi0/0.20 и порт SSH не остались в БД
    assert [i["ip_address"] for i in _poly(client, "ip-addresses", "device_subinterface")] == ["10.0.10.254"]
    assert _poly(client, "open-ports", "device_subinterface") == []


def test_missing_subinterfaces_key_leaves_them_untouched_and_empty_list_removes_all(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    port = _sync(client, dev["id"], [_port("Gi0/0", subinterfaces=[_sub("Gi0/0.10", v10, ips=[{"ip_address": "10.0.10.1", "prefix_length": 24}])])]).json()["items"][0]

    kept = _sync(client, dev["id"], [_port("Gi0/0", id=port["id"], description="uplink")]).json()["items"][0]
    assert [s["name"] for s in kept["subinterfaces"]] == ["Gi0/0.10"]
    assert len(_poly(client, "ip-addresses", "device_subinterface")) == 1

    cleared = _sync(client, dev["id"], [_port("Gi0/0", id=port["id"], subinterfaces=[])]).json()["items"][0]
    assert cleared["subinterfaces"] == []
    assert _poly(client, "ip-addresses", "device_subinterface") == []
    assert client.get(f"{API}/devices/{dev['id']}/subinterfaces").json()["items"] == []


def test_vlans_and_names_can_be_swapped_in_one_request(client):
    """Обмен VLAN между двумя подинтерфейсами одним PUT — законная правка, ограничения БД её бы отвергли."""
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    dev = _device(client, vlans=(v10, v20))
    port = _sync(client, dev["id"], [_port("Gi0/0", subinterfaces=[_sub("a", v10), _sub("b", v20)])]).json()["items"][0]
    subs = _by_name(port["subinterfaces"])

    r = _sync(client, dev["id"], [_port("Gi0/0", id=port["id"], subinterfaces=[
        {**_sub("b", v10), "id": subs["a"]["id"]},
        {**_sub("a", v20), "id": subs["b"]["id"]},
    ])])

    assert r.status_code == 200, r.text
    after = _by_name(r.json()["items"][0]["subinterfaces"])
    assert (after["a"]["id"], after["a"]["vlan_id"]) == (subs["b"]["id"], v20["id"])
    assert (after["b"]["id"], after["b"]["vlan_id"]) == (subs["a"]["id"], v10["id"])


def test_validation_rejects_bad_subinterfaces_and_saves_nothing(client):
    v10, v20, foreign = _vlan(client, 10), _vlan(client, 20), _vlan(client, 99)
    dev = _device(client, vlans=(v10, v20))
    other = _device(client, serial="RTR-2", vlans=(v10,))
    other_sub = _sync(client, other["id"], [_port("Gi0/0", subinterfaces=[_sub("x", v10)])]).json()["items"][0]["subinterfaces"][0]

    bad_payloads = {
        "без имени": [_port("Gi0/0", subinterfaces=[_sub(" ", v10)])],
        "без VLAN": [_port("Gi0/0", subinterfaces=[_sub("Gi0/0.10", None)])],
        "VLAN вне разрешённых": [_port("Gi0/0", subinterfaces=[_sub("Gi0/0.99", foreign)])],
        "два на одном VLAN у порта": [_port("Gi0/0", subinterfaces=[_sub("a", v10), _sub("b", v10)])],
        "одно имя на двух портах": [_port("Gi0/0", subinterfaces=[_sub("dup", v10)]), _port("Gi0/1", subinterfaces=[_sub("DUP", v20)])],
        "имя как у порта": [_port("Gi0/0", subinterfaces=[_sub("Gi0/1", v10)]), _port("Gi0/1")],
        "чужой id подинтерфейса": [_port("Gi0/0", subinterfaces=[{**_sub("z", v10), "id": other_sub["id"]}])],
        "некорректный IP": [_port("Gi0/0", subinterfaces=[_sub("a", v10, ips=[{"ip_address": "не-ip"}])])],
        "ips не массив": [_port("Gi0/0", subinterfaces=[_sub("a", v10, ips="10.0.0.1")])],
        "subinterfaces не массив": [_port("Gi0/0", subinterfaces={"name": "a"})],
    }
    for label, interfaces in bad_payloads.items():
        r = _sync(client, dev["id"], interfaces)
        assert r.status_code == 422, f"{label}: {r.status_code} {r.text}"

    # ни порт, ни подинтерфейсы не сохранились (откат всей транзакции)
    assert client.get(f"{API}/resources/interfaces", params={"physical_device_id": dev["id"], "limit": 1000}).json()["items"] == []
    assert client.get(f"{API}/devices/{dev['id']}/subinterfaces").json()["items"] == []


def test_error_messages_name_the_offending_subinterface(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    r = _sync(client, dev["id"], [_port("Gi0/0", subinterfaces=[_sub("Gi0/0.10", v10, ips=[{"ip_address": "не-ip"}])])])
    assert r.status_code == 422 and "Gi0/0.10" in r.json()["detail"]

    r = _sync(client, dev["id"], [_port("Gi0/0", subinterfaces=[_sub("a", v10), _sub("b", v10)])])
    assert r.status_code == 422 and "Gi0/0" in r.json()["detail"] and "10" in r.json()["detail"]


def test_removing_a_port_removes_its_subinterfaces_ips_and_open_ports(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    ssh = _catalog_entry(client, 22, "SSH")
    port = _sync(client, dev["id"], [_port("Gi0/0", subinterfaces=[
        _sub("Gi0/0.10", v10, ips=[{"ip_address": "10.0.10.1", "prefix_length": 24}], open_ports=[{"protocol_catalog_id": ssh["id"]}]),
    ]), _port("Gi0/1")]).json()["items"][0]

    r = _sync(client, dev["id"], [_port("Gi0/1")])

    assert r.status_code == 200, r.text
    assert client.get(f"{API}/devices/{dev['id']}/subinterfaces").json()["items"] == []
    assert _poly(client, "ip-addresses", "device_subinterface") == []
    assert _poly(client, "open-ports", "device_subinterface") == []
    assert port["id"] not in {i["id"] for i in r.json()["items"]}
    assert client.get(f"{API}/integrity").json()["orphans"] == []


def test_generic_delete_of_a_port_removes_its_subinterfaces(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    port = _sync(client, dev["id"], [_port("Gi0/0", subinterfaces=[_sub("Gi0/0.10", v10, ips=[{"ip_address": "10.0.10.1", "prefix_length": 24}])])]).json()["items"][0]

    r = client.delete(f"{API}/resources/interfaces/{port['id']}")

    assert r.status_code == 200, r.text
    assert client.get(f"{API}/devices/{dev['id']}/subinterfaces").json()["items"] == []
    assert _poly(client, "ip-addresses", "device_subinterface") == []


def test_vlan_used_by_a_subinterface_cannot_be_deleted(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    port = _sync(client, dev["id"], [_port("Gi0/0", subinterfaces=[_sub("Gi0/0.10", v10)])]).json()["items"][0]

    r = client.delete(f"{API}/resources/vlans/{v10['id']}")
    assert r.status_code == 409 and "Подинтерфейсы" in str(r.json()["detail"])

    # после снятия подинтерфейса «Подинтерфейсы» из причин отказа исчезают (остаётся лишь привязка VLAN к типу устройства)
    _sync(client, dev["id"], [_port("Gi0/0", id=port["id"], subinterfaces=[])])
    r = client.delete(f"{API}/resources/vlans/{v10['id']}")
    assert "Подинтерфейсы" not in str(r.json())


def test_subinterfaces_of_unknown_device_return_404(client):
    assert client.get(f"{API}/devices/no-such-device/subinterfaces").status_code == 404


def test_subinterface_has_no_incoming_foreign_keys():
    """Основание для прямого удаления подинтерфейсов (см. ALLOWED_DELETIONS в test_deletion_guards.py): на
    таблицу device_subinterfaces не ссылается ни один внешний ключ — входящие ссылки только полиморфные
    (ip_addresses / open_ports с owner_type=device_subinterface), и их удаляет та же функция. Появится
    FK — удаление должно пойти через crud.assert_deletable(), а не напрямую."""
    from app.models import Base

    referencing = sorted(
        f"{table.name}.{fk.parent.name}"
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.name == "device_subinterfaces"
    )
    assert referencing == []
