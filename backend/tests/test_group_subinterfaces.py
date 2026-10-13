"""Подинтерфейсы групп портов: payload['groups'][i]['subinterfaces'] + manage_subinterfaces
(services/crud/interface_group_subinterfaces.py).

Главный инвариант — как у остальных параметров группы: шаблон МАТЕРИАЛИЗУЕТСЯ в порты группы обычными подинтерфейсами
`<порт>.<номер VLAN>` (models.DeviceSubinterface со своими IP и открытыми портами), поэтому отчёты и схемы читают итоговые
подинтерфейсы портов и о группах ничего не знают. Группа без manage_subinterfaces подинтерфейсы своих портов не трогает.
"""
from __future__ import annotations

import pytest

API = "/api/v1"


def _catalog_entry(client, port: int, protocol_type: str) -> dict:
    existing = client.get(f"{API}/resources/protocol-port-catalog", params={"limit": 1000}).json()["items"]
    match = next((e for e in existing if e["port"] == port and e["protocol_type"] == protocol_type), None)
    return match or client.post(f"{API}/resources/protocol-port-catalog", json={"port": port, "protocol_type": protocol_type}).json()


def _vlan(client, number: int) -> dict:
    r = client.post(f"{API}/resources/vlans", json={"vlan_id": number, "name": f"VLAN {number}"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _device(client, serial: str = "SW-GS", vlans: tuple[dict, ...] = ()) -> dict:
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    dt = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    for v in vlans:
        client.post(f"{API}/resources/device-type-vlans", json={"device_type_id": dt["id"], "vlan_id": v["id"]})
    return client.post(f"{API}/resources/devices", json={"device_type_id": dt["id"], "serial_number": serial}).json()


def _sync(client, device_id: str, interfaces: list[dict], groups: list[dict] | None):
    body: dict = {"interfaces": interfaces}
    if groups is not None:
        body["groups"] = groups
    return client.put(f"{API}/devices/{device_id}/interfaces", json=body)


def _group(vlans: list[dict], subinterfaces: list[dict] | None, key: str = "g1", **extra) -> dict:
    """Группа trunk с заданными VLAN; subinterfaces=None — группа подинтерфейсами не управляет."""
    body = {"key": key, "name": "Группа", "vlan_mode": "trunk", "vlan_ids": [v["id"] for v in vlans], **extra}
    if subinterfaces is not None:
        body.update({"manage_subinterfaces": True, "subinterfaces": subinterfaces})
    return body


def _tpl(vlan: dict, **extra) -> dict:
    return {"vlan_id": vlan["id"], **extra}


def _port(name: str, group_key: str | None = "g1", **extra) -> dict:
    return {"name": name, "group_key": group_key, **extra}


def _subs(sync_response: dict, port_name: str) -> dict[str, dict]:
    port = next(p for p in sync_response["items"] if p["name"] == port_name)
    return {s["name"]: s for s in port["subinterfaces"]}


def test_group_template_is_written_into_every_member_port(client):
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    dev = _device(client, vlans=(v10, v20))
    ssh = _catalog_entry(client, 22, "SSH")
    group = _group([v10, v20], [
        _tpl(v10, is_management=True, description="управление", ips=[{"ip_address": "10.0.10.1", "prefix_length": 24, "purpose": "шлюз"}],
             open_ports=[{"protocol_catalog_id": ssh["id"], "transport_protocol": "TCP", "description": "админ"}]),
        _tpl(v20, is_data_transfer=True),
    ])

    r = _sync(client, dev["id"], [_port("Gi0/0"), _port("Gi0/1"), _port("Gi0/2", group_key=None)], [group])

    assert r.status_code == 200, r.text
    body = r.json()
    for port in ("Gi0/0", "Gi0/1"):
        subs = _subs(body, port)
        assert set(subs) == {f"{port}.10", f"{port}.20"}
        mgmt = subs[f"{port}.10"]
        assert (mgmt["vlan_id"], mgmt["is_management"], mgmt["description"]) == (v10["id"], True, "управление")
        assert [(i["ip_address"], i["prefix_length"], i["purpose"], i["is_management"]) for i in mgmt["ips"]] == [("10.0.10.1", 24, "шлюз", True)]
        assert [(p["protocol_catalog_id"], p["description"]) for p in mgmt["open_ports"]] == [(ssh["id"], "админ")]
        assert subs[f"{port}.20"]["is_data_transfer"] is True
    assert _subs(body, "Gi0/2") == {}  # порт вне группы подинтерфейсов не получил


def test_group_templates_are_returned_with_ips_and_open_ports(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    ssh = _catalog_entry(client, 22, "SSH")
    group = _group([v10], [_tpl(v10, ips=[{"ip_address": "10.0.10.1", "prefix_length": 24}], open_ports=[{"protocol_catalog_id": ssh["id"]}])])
    assert _sync(client, dev["id"], [_port("Gi0/0")], [group]).status_code == 200

    (loaded,) = client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"]

    assert loaded["manage_subinterfaces"] is True
    (tpl,) = loaded["subinterfaces"]
    assert tpl["vlan_id"] == v10["id"]
    assert [(i["ip_address"], i["prefix_length"]) for i in tpl["ips"]] == [("10.0.10.1", 24)]
    assert [(p["protocol_catalog_id"], p["transport_protocol"]) for p in tpl["open_ports"]] == [(ssh["id"], "TCP")]


def test_repeated_sync_keeps_ids_and_template_edit_updates_in_place(client):
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    dev = _device(client, vlans=(v10, v20))
    ssh = _catalog_entry(client, 22, "SSH")
    first = _sync(client, dev["id"], [_port("Gi0/0")], [_group([v10, v20], [_tpl(v10, ips=[{"ip_address": "10.0.10.1", "prefix_length": 24}], open_ports=[{"protocol_catalog_id": ssh["id"]}])])]).json()
    sub = _subs(first, "Gi0/0")["Gi0/0.10"]
    stored_group = client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"][0]

    # Повторное сохранение: порт и группа приходят с id, шаблон меняет адрес и описание.
    tpl = stored_group["subinterfaces"][0]
    edited = {**stored_group, "key": stored_group["id"], "subinterfaces": [{**tpl, "description": "новое", "ips": [{**tpl["ips"][0], "ip_address": "10.0.10.2"}]}]}
    port_id = first["items"][0]["id"]
    second = _sync(client, dev["id"], [_port("Gi0/0", group_key=stored_group["id"], id=port_id)], [edited])

    assert second.status_code == 200, second.text
    again = _subs(second.json(), "Gi0/0")["Gi0/0.10"]
    assert again["id"] == sub["id"]  # подинтерфейс порта обновлён на месте
    assert again["description"] == "новое"
    assert [(i["id"], i["ip_address"]) for i in again["ips"]] == [(sub["ips"][0]["id"], "10.0.10.2")]  # IP тоже на месте
    assert [p["id"] for p in again["open_ports"]] == [sub["open_ports"][0]["id"]]


def test_group_replaces_ports_own_subinterfaces_with_its_full_list(client):
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    dev = _device(client, vlans=(v10, v20))
    own = {"name": "wan-uplink", "vlan_id": v20["id"], "ips": [{"ip_address": "192.168.0.1", "prefix_length": 24}]}

    r = _sync(client, dev["id"], [_port("Gi0/0", subinterfaces=[own])], [_group([v10, v20], [_tpl(v10)])])

    assert r.status_code == 200, r.text
    assert set(_subs(r.json(), "Gi0/0")) == {"Gi0/0.10"}  # «wan-uplink» на VLAN вне шаблона удалён
    leftovers = client.get(f"{API}/resources/ip-addresses", params={"owner_type": "device_subinterface", "limit": 1000}).json()["items"]
    assert leftovers == []  # и его IP не осиротел


def test_group_without_manage_subinterfaces_leaves_port_subinterfaces_alone(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    own = {"name": "mgmt", "vlan_id": v10["id"]}

    r = _sync(client, dev["id"], [_port("Gi0/0", subinterfaces=[own])], [_group([v10], None)])

    assert r.status_code == 200, r.text
    assert set(_subs(r.json(), "Gi0/0")) == {"mgmt"}


def test_removing_a_template_removes_its_subinterface_from_ports(client):
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    dev = _device(client, vlans=(v10, v20))
    first = _sync(client, dev["id"], [_port("Gi0/0")], [_group([v10, v20], [_tpl(v10), _tpl(v20, ips=[{"ip_address": "10.0.20.1", "prefix_length": 24}])])]).json()
    stored = client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"][0]
    keep = next(t for t in stored["subinterfaces"] if t["vlan_id"] == v10["id"])

    r = _sync(client, dev["id"], [_port("Gi0/0", group_key=stored["id"], id=first["items"][0]["id"])], [{**stored, "key": stored["id"], "subinterfaces": [keep]}])

    assert set(_subs(r.json(), "Gi0/0")) == {"Gi0/0.10"}
    assert client.get(f"{API}/resources/ip-addresses", params={"owner_type": "device_subinterface", "limit": 1000}).json()["items"] == []
    assert len(client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"][0]["subinterfaces"]) == 1


def test_all_vlans_group_accepts_any_device_vlan(client):
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    dev = _device(client, vlans=(v10, v20))
    group = {"key": "g1", "name": "Все", "vlan_mode": "trunk", "all_vlans": True, "manage_subinterfaces": True, "subinterfaces": [_tpl(v20)]}

    r = _sync(client, dev["id"], [_port("Gi0/0")], [group])

    assert r.status_code == 200, r.text
    assert set(_subs(r.json(), "Gi0/0")) == {"Gi0/0.20"}


@pytest.mark.parametrize(
    ("build", "expected"),
    [
        (lambda v10, v20: _group([v10], [_tpl(v20)]), "не входит в VLAN группы"),
        (lambda v10, v20: _group([v10], [_tpl(v10), _tpl(v10)]), "несколько подинтерфейсов на VLAN 10"),
        (lambda v10, v20: _group([v10], [{"vlan_id": None}]), "не выбран VLAN"),
        (lambda v10, v20: {"key": "g1", "name": "Группа", "manage_subinterfaces": True, "subinterfaces": [_tpl(v10)]}, "только вместе с режимом порта"),
        (lambda v10, v20: _group([v10], [_tpl(v10, ips=[{"ip_address": "не-ip"}])]), "IP-адрес"),
        (lambda v10, v20: _group([v10], [_tpl(v10, ips=[{"ip_address": "10.0.0.1", "prefix_length": 99}])]), "префикс"),
        (lambda v10, v20: _group([v10], [_tpl(v10, open_ports=[{"protocol_catalog_id": "нет-такого"}])]), "справочника"),
        (lambda v10, v20: _group([v10], "не-массив"), "должно быть массивом"),
    ],
)
def test_invalid_group_subinterfaces_are_rejected_and_nothing_is_saved(client, build, expected):
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    dev = _device(client, vlans=(v10, v20))

    r = _sync(client, dev["id"], [_port("Gi0/0")], [build(v10, v20)])

    assert r.status_code == 422, r.text
    assert expected.lower() in r.text.lower()
    assert client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"] == []


def test_templates_are_dropped_when_group_stops_managing_subinterfaces(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    first = _sync(client, dev["id"], [_port("Gi0/0")], [_group([v10], [_tpl(v10)])]).json()
    stored = client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"][0]

    r = _sync(client, dev["id"], [_port("Gi0/0", group_key=stored["id"], id=first["items"][0]["id"])], [{**stored, "key": stored["id"], "manage_subinterfaces": False}])

    assert r.status_code == 200, r.text
    (after,) = client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"]
    assert (after["manage_subinterfaces"], after["subinterfaces"]) == (False, [])
    assert set(_subs(r.json(), "Gi0/0")) == {"Gi0/0.10"}  # уже записанные подинтерфейсы остаются данными порта


def test_deleting_group_removes_templates_but_keeps_port_subinterfaces(client, db_session):
    from app.models import InterfaceGroupSubinterface, InterfaceGroupSubinterfaceIP, InterfaceGroupSubinterfaceOpenPort

    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    ssh = _catalog_entry(client, 22, "SSH")
    first = _sync(client, dev["id"], [_port("Gi0/0")], [_group([v10], [_tpl(v10, ips=[{"ip_address": "10.0.10.1", "prefix_length": 24}], open_ports=[{"protocol_catalog_id": ssh["id"]}])])]).json()

    r = _sync(client, dev["id"], [_port("Gi0/0", group_key=None, id=first["items"][0]["id"])], [])

    assert r.status_code == 200, r.text
    for model in (InterfaceGroupSubinterface, InterfaceGroupSubinterfaceIP, InterfaceGroupSubinterfaceOpenPort):
        assert db_session.query(model).count() == 0
    assert set(_subs(r.json(), "Gi0/0")) == {"Gi0/0.10"}


def test_name_clash_with_another_ports_own_subinterface_is_reported(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    # у Gi0/1 вручную задан подинтерфейс с именем, которое группа даст подинтерфейсу порта Gi0/0
    clash = {"name": "Gi0/0.10", "vlan_id": v10["id"]}

    r = _sync(client, dev["id"], [_port("Gi0/0"), _port("Gi0/1", group_key=None, subinterfaces=[clash])], [_group([v10], [_tpl(v10)])])

    assert r.status_code == 422, r.text
    assert "повторяется" in r.text


def test_vlan_used_by_group_subinterface_cannot_be_deleted(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    assert _sync(client, dev["id"], [], [_group([v10], [_tpl(v10)])]).status_code == 200

    r = client.delete(f"{API}/resources/vlans/{v10['id']}")

    assert r.status_code == 409, r.text
    assert "Подинтерфейсы групп портов" in r.text
