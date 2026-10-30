"""Группы портов устройства (правка формы устройства, п.4): PUT /devices/{id}/interfaces с
payload['groups'] и GET /devices/{id}/interface-groups (services/crud/interfaces.py:sync_interfaces и
_sync_interface_groups/_apply_group_to_interface).

Главный инвариант: параметры группы (режим порта + VLAN, общий IP, открытые порты)
МАТЕРИАЛИЗУЮТСЯ в порты группы — VLAN-связи, IPAddress и OpenPort самого порта, поэтому отчёты и
диаграммы читают итоговые значения порта и о группах ничего не знают.
"""
from __future__ import annotations

import pytest

API = "/api/v1"


def _catalog_entry(client, port: int, protocol_type: str) -> dict:
    """Запись справочника «Протоколы и порты» (часть «хрестоматийных» уже засеяна по умолчанию —
    ищем существующую, а не создаём вслепую, иначе UNIQUE по паре port+protocol_type даст 409)."""
    existing = client.get(f"{API}/resources/protocol-port-catalog", params={"limit": 1000}).json()["items"]
    match = next((e for e in existing if e["port"] == port and e["protocol_type"] == protocol_type), None)
    return match or client.post(f"{API}/resources/protocol-port-catalog", json={"port": port, "protocol_type": protocol_type}).json()


def _device(client, serial: str = "SW-GRP", vlans: tuple[dict, ...] = ()) -> dict:
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    dt = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    for v in vlans:
        client.post(f"{API}/resources/device-type-vlans", json={"device_type_id": dt["id"], "vlan_id": v["id"]})
    return client.post(f"{API}/resources/devices", json={"device_type_id": dt["id"], "serial_number": serial}).json()


def _vlan(client, number: int) -> dict:
    r = client.post(f"{API}/resources/vlans", json={"vlan_id": number, "name": f"VLAN {number}"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _sync(client, device_id: str, interfaces: list[dict], groups: list[dict] | None):
    body: dict = {"interfaces": interfaces}
    if groups is not None:
        body["groups"] = groups
    return client.put(f"{API}/devices/{device_id}/interfaces", json=body)


def _stored_interfaces(client, device_id: str) -> dict[str, dict]:
    items = client.get(f"{API}/resources/interfaces", params={"physical_device_id": device_id, "limit": 1000}).json()["items"]
    return {x["name"]: x for x in items}


def _ips(client, iface_id: str) -> list[dict]:
    items = client.get(f"{API}/resources/ip-addresses", params={"owner_type": "device_interface", "limit": 1000}).json()["items"]
    return [x for x in items if x["owner_id"] == iface_id]


def _open_ports(client, iface_id: str) -> list[dict]:
    items = client.get(f"{API}/resources/open-ports", params={"owner_type": "device_interface", "limit": 1000}).json()["items"]
    return [x for x in items if x["owner_id"] == iface_id]


def _links(client, iface_id: str) -> list[dict]:
    items = client.get(f"{API}/resources/interface-vlans", params={"limit": 1000}).json()["items"]
    return [x for x in items if x["interface_id"] == iface_id]


def _port(name: str, group_key: str | None = None, **extra) -> dict:
    return {"name": name, "group_key": group_key, **extra}


def test_group_values_are_written_into_every_member_port(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    ssh = _catalog_entry(client, 22, "SSH")
    groups = [{"key": "g1", "name": "Серверные", "vlan_mode": "access", "vlan_ids": [v10["id"]], "ips": [{"ip_address": "10.0.0.5", "prefix_length": 24}], "manage_open_ports": True, "open_ports": [{"protocol_catalog_id": ssh["id"], "transport_protocol": "TCP", "description": "админ"}]}]

    r = _sync(client, dev["id"], [_port("Gi0/1", "g1"), _port("Gi0/2", "g1"), _port("Gi0/3")], groups)

    assert r.status_code == 200, r.text
    stored = _stored_interfaces(client, dev["id"])
    (group,) = r.json()["groups"]
    assert group["name"] == "Серверные" and group["vlan_ids"] == [v10["id"]] and [i["ip_address"] for i in group["ips"]] == ["10.0.0.5"]
    assert [p["protocol_catalog_id"] for p in group["open_ports"]] == [ssh["id"]]
    for name in ("Gi0/1", "Gi0/2"):
        iface = stored[name]
        assert iface["group_id"] == group["id"] and iface["vlan_mode"] == "access"
        assert [l["vlan_id"] for l in _links(client, iface["id"])] == [v10["id"]]
        assert [(i["ip_address"], i["prefix_length"]) for i in _ips(client, iface["id"])] == [("10.0.0.5", 24)]
        assert [(p["protocol_catalog_id"], p["description"]) for p in _open_ports(client, iface["id"])] == [(ssh["id"], "админ")]
    outsider = stored["Gi0/3"]
    assert outsider["group_id"] is None and _ips(client, outsider["id"]) == [] and _open_ports(client, outsider["id"]) == []

    listed = client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"]
    assert [g["id"] for g in listed] == [group["id"]]


def test_group_overrides_client_values_for_managed_fields_only(client):
    """Группа — источник истины для заданных ею параметров, что бы ни прислал клиент; параметры,
    которых группа не задаёт (здесь — IP и открытые порты), порт хранит свои."""
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    dev = _device(client, vlans=(v10, v20))
    groups = [{"key": "g1", "name": "Access", "vlan_mode": "access", "vlan_ids": [v10["id"]]}]
    own_ip = [{"ip_address": "192.168.1.9", "prefix_length": 24}]

    r = _sync(client, dev["id"], [_port("Gi0/1", "g1", vlan_mode="trunk", vlan_ids=[v20["id"]], ips=own_ip)], groups)

    assert r.status_code == 200, r.text
    iface = _stored_interfaces(client, dev["id"])["Gi0/1"]
    assert iface["vlan_mode"] == "access"
    assert [l["vlan_id"] for l in _links(client, iface["id"])] == [v10["id"]]
    assert [i["ip_address"] for i in _ips(client, iface["id"])] == ["192.168.1.9"]


def _as_loaded(client, iface: dict, group_key: str | None) -> dict:
    """Порт в том виде, в каком его снова отправляет форма после загрузки: с id и со всеми
    значениями (VLAN, режим, IP и открытые порты с их id)."""
    return {
        "id": iface["id"], "name": iface["name"], "group_key": group_key, "vlan_mode": iface["vlan_mode"],
        "vlan_ids": [l["vlan_id"] for l in _links(client, iface["id"])],
        "ips": [{"id": i["id"], "ip_address": i["ip_address"], "prefix_length": i["prefix_length"]} for i in _ips(client, iface["id"])],
        "open_ports": [{"id": p["id"], "protocol_catalog_id": p["protocol_catalog_id"], "transport_protocol": p["transport_protocol"]} for p in _open_ports(client, iface["id"])],
    }


def test_repeated_sync_updates_in_place_without_recreating_rows(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    ssh, http = _catalog_entry(client, 22, "SSH"), _catalog_entry(client, 80, "HTTP")
    group = {"key": "g1", "name": "Группа", "ips": [{"ip_address": "10.0.0.5", "prefix_length": 24}], "manage_open_ports": True, "open_ports": [{"protocol_catalog_id": ssh["id"]}, {"protocol_catalog_id": http["id"]}]}
    _sync(client, dev["id"], [_port("Gi0/1", "g1")], [group])
    iface = _stored_interfaces(client, dev["id"])["Gi0/1"]
    ip_id = _ips(client, iface["id"])[0]["id"]
    port_ids = {p["id"] for p in _open_ports(client, iface["id"])}
    saved_group = client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"][0]

    # Меняем только IP группы и убираем HTTP: строка IP и порт SSH обновляются на месте.
    group2 = {**group, "key": saved_group["id"], "id": saved_group["id"], "ips": [{**saved_group["ips"][0], "ip_address": "10.0.0.6"}],
              "open_ports": [next(p for p in saved_group["open_ports"] if p["protocol_catalog_id"] == ssh["id"])]}
    r = _sync(client, dev["id"], [_as_loaded(client, iface, saved_group["id"])], [group2])

    assert r.status_code == 200, r.text
    (ip,) = _ips(client, iface["id"])
    assert ip["id"] == ip_id and ip["ip_address"] == "10.0.0.6"
    remaining = _open_ports(client, iface["id"])
    assert [p["protocol_catalog_id"] for p in remaining] == [ssh["id"]] and remaining[0]["id"] in port_ids


def test_group_membership_without_changes_is_idempotent(client):
    """Повторное сохранение без правок не пересоздаёт IP и открытые порты и не меняет набор VLAN.
    (Строки interface_vlans пересоздаёт уже существующая синхронизация самого порта, к группам это
    не относится, поэтому для VLAN сравнивается набор, а не id строк.)"""
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    ssh = _catalog_entry(client, 22, "SSH")
    group = {"key": "g1", "name": "Группа", "vlan_mode": "access", "vlan_ids": [v10["id"]], "ips": [{"ip_address": "10.0.0.5"}], "manage_open_ports": True, "open_ports": [{"protocol_catalog_id": ssh["id"]}]}
    _sync(client, dev["id"], [_port("Gi0/1", "g1")], [group])
    iface = _stored_interfaces(client, dev["id"])["Gi0/1"]
    saved_group = client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"][0]
    ips_before, ports_before = _ips(client, iface["id"]), _open_ports(client, iface["id"])

    r = _sync(client, dev["id"], [_as_loaded(client, iface, saved_group["id"])], [{**saved_group, "key": saved_group["id"]}])

    assert r.status_code == 200, r.text
    assert [i["id"] for i in _ips(client, iface["id"])] == [i["id"] for i in ips_before]
    assert [p["id"] for p in _open_ports(client, iface["id"])] == [p["id"] for p in ports_before]
    assert [l["vlan_id"] for l in _links(client, iface["id"])] == [v10["id"]]


def test_removing_group_keeps_values_in_ports_and_cleans_group_rows(client, db_session):
    from app.models import InterfaceGroup, InterfaceGroupOpenPort, InterfaceGroupVLAN

    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    ssh = _catalog_entry(client, 22, "SSH")
    group = {"key": "g1", "name": "Временная", "vlan_mode": "access", "vlan_ids": [v10["id"]], "ips": [{"ip_address": "10.0.0.5"}], "manage_open_ports": True, "open_ports": [{"protocol_catalog_id": ssh["id"]}]}
    _sync(client, dev["id"], [_port("Gi0/1", "g1")], [group])
    iface = _stored_interfaces(client, dev["id"])["Gi0/1"]

    # Группа исчезла из payload, порт остался без group_key и прислан со своими значениями,
    # ранее записанными из группы («оставить значения» в диалоге удаления группы).
    r = _sync(client, dev["id"], [_as_loaded(client, iface, None)], [])

    assert r.status_code == 200, r.text
    assert r.json()["groups"] == []
    after = _stored_interfaces(client, dev["id"])["Gi0/1"]
    assert after["group_id"] is None and after["vlan_mode"] == "access"
    assert [l["vlan_id"] for l in _links(client, iface["id"])] == [v10["id"]]
    assert [i["ip_address"] for i in _ips(client, iface["id"])] == ["10.0.0.5"]
    assert len(_open_ports(client, iface["id"])) == 1
    db_session.expire_all()
    assert db_session.query(InterfaceGroup).count() == 0
    assert db_session.query(InterfaceGroupVLAN).count() == 0 and db_session.query(InterfaceGroupOpenPort).count() == 0


def test_client_can_erase_values_when_dropping_group(client):
    """«Стереть значения» при удалении группы — это явные пустые значения порта в том же PUT: бэкенд
    сам ничего не стирает, а сохраняет то, что прислал клиент."""
    dev = _device(client)
    _sync(client, dev["id"], [_port("Gi0/1", "g1")], [{"key": "g1", "name": "Г", "ips": [{"ip_address": "10.0.0.5"}]}])
    iface = _stored_interfaces(client, dev["id"])["Gi0/1"]
    assert len(_ips(client, iface["id"])) == 1

    r = _sync(client, dev["id"], [_port("Gi0/1", id=iface["id"], ips=[])], [])

    assert r.status_code == 200, r.text
    assert _ips(client, iface["id"]) == []


def test_sync_without_groups_key_leaves_groups_and_membership_untouched(client):
    """Старый клиент API (не знает про группы) не должен ни удалять группы, ни отвязывать порты."""
    dev = _device(client)
    _sync(client, dev["id"], [_port("Gi0/1", "g1")], [{"key": "g1", "name": "Г", "ips": [{"ip_address": "10.0.0.5"}]}])
    iface = _stored_interfaces(client, dev["id"])["Gi0/1"]

    r = _sync(client, dev["id"], [{"id": iface["id"], "name": "Gi0/1"}], None)

    assert r.status_code == 200, r.text
    assert _stored_interfaces(client, dev["id"])["Gi0/1"]["group_id"] == iface["group_id"] is not None
    assert len(client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"]) == 1


@pytest.mark.parametrize(
    "group, expected",
    [
        ({"key": "g", "name": "  "}, "наименование"),
        ({"key": "g", "name": "Г", "vlan_mode": "half-duplex"}, "vlan_mode"),
        ({"key": "g", "name": "Г", "ips": [{"ip_address": "999.1.1.1"}]}, "IP-адрес"),
        ({"key": "g", "name": "Г", "ips": [{"ip_address": "10.0.0.1", "prefix_length": 40}]}, "префикс"),
        ({"name": "Г"}, "key"),
    ],
)
def test_invalid_group_is_rejected(client, group, expected):
    dev = _device(client)
    r = _sync(client, dev["id"], [_port("Gi0/1")], [group])
    assert r.status_code == 422
    assert expected.lower() in r.text.lower()
    assert _stored_interfaces(client, dev["id"]) == {}


def test_vlan_rules_for_groups(client):
    v10, v20, foreign = _vlan(client, 10), _vlan(client, 20), _vlan(client, 30)
    dev = _device(client, vlans=(v10, v20))
    base = {"key": "g", "name": "Г"}

    def attempt(**extra):
        return _sync(client, dev["id"], [_port("Gi0/1")], [{**base, **extra}])

    assert attempt(vlan_mode="access", vlan_ids=[v10["id"], v20["id"]]).status_code == 422   # access — не более одного
    assert attempt(vlan_ids=[v10["id"]]).status_code == 422                                    # VLAN без режима
    assert attempt(vlan_mode="trunk", vlan_ids=[foreign["id"]]).status_code == 422             # VLAN не разрешён устройству
    assert attempt(vlan_mode="trunk", vlan_ids=[v10["id"], v20["id"]]).status_code == 200


def test_duplicate_names_keys_and_unknown_group_key_are_rejected(client):
    dev = _device(client)
    assert _sync(client, dev["id"], [], [{"key": "a", "name": "Одна"}, {"key": "b", "name": "одна"}]).status_code == 422
    assert _sync(client, dev["id"], [], [{"key": "a", "name": "Одна"}, {"key": "a", "name": "Другая"}]).status_code == 422
    assert _sync(client, dev["id"], [_port("Gi0/1", "нет-такой")], [{"key": "a", "name": "Одна"}]).status_code == 422
    assert client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"] == []


def test_group_of_another_device_cannot_be_referenced(client):
    dev_a, dev_b = _device(client, "SW-A"), _device(client, "SW-B")
    _sync(client, dev_a["id"], [], [{"key": "a", "name": "Чужая"}])
    foreign_id = client.get(f"{API}/devices/{dev_a['id']}/interface-groups").json()["items"][0]["id"]

    r = _sync(client, dev_b["id"], [], [{"key": foreign_id, "id": foreign_id, "name": "Чужая"}])

    assert r.status_code == 422


def test_error_rolls_back_the_whole_sync(client):
    """Ошибка на порту откатывает и уже созданные в этом запросе группы."""
    dev = _device(client)
    r = _sync(client, dev["id"], [_port("Gi0/1", "g1"), {"name": "Gi0/2", "vlan_mode": "bogus"}], [{"key": "g1", "name": "Г"}])
    assert r.status_code == 422
    assert client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"] == []
    assert _stored_interfaces(client, dev["id"]) == {}


def test_device_without_interfaces_can_be_deleted_together_with_its_groups(client, db_session):
    from app.models import InterfaceGroup

    dev = _device(client)
    _sync(client, dev["id"], [], [{"key": "g", "name": "Пустая группа", "ips": [{"ip_address": "10.0.0.5"}]}])

    r = client.delete(f"{API}/resources/devices/{dev['id']}")

    assert r.status_code == 200, r.text
    db_session.expire_all()
    assert db_session.query(InterfaceGroup).count() == 0


def test_group_vlan_definition_disappears_with_deleted_vlan(client):
    v10 = _vlan(client, 10)
    dev = _device(client, vlans=(v10,))
    _sync(client, dev["id"], [], [{"key": "g", "name": "Г", "vlan_mode": "trunk", "vlan_ids": [v10["id"]]}])
    client.delete(f"{API}/resources/device-type-vlans/{client.get(f'{API}/resources/device-type-vlans').json()['items'][0]['id']}")

    r = client.delete(f"{API}/resources/vlans/{v10['id']}")

    assert r.status_code == 200, r.text
    assert client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"][0]["vlan_ids"] == []


# --- Назначение общего IP-адреса в группе (поле «Назначение» рядом с «IP-адрес» и «Префикс») ------------


def _ip_group(key: str = "g1", name: str = "Серверные", ip_purpose: str | None = "Доступ администраторов", **extra) -> dict:
    return {"key": key, "name": name, "ips": [{"ip_address": "10.0.0.5", "prefix_length": 24, "purpose": ip_purpose}], **extra}


def test_group_ip_purpose_is_written_into_ip_of_every_member_port(client):
    dev = _device(client, serial="SW-IP-PURPOSE")

    r = _sync(client, dev["id"], [_port("Gi0/1", "g1"), _port("Gi0/2", "g1"), _port("Gi0/3")], [_ip_group()])

    assert r.status_code == 200, r.text
    (group,) = r.json()["groups"]
    assert [(i["ip_address"], i["purpose"]) for i in group["ips"]] == [("10.0.0.5", "Доступ администраторов")]
    stored = _stored_interfaces(client, dev["id"])
    for name in ("Gi0/1", "Gi0/2"):
        assert [(i["ip_address"], i["prefix_length"], i["purpose"]) for i in _ips(client, stored[name]["id"])] == [("10.0.0.5", 24, "Доступ администраторов")]
    assert _ips(client, stored["Gi0/3"]["id"]) == []  # порт вне группы не затронут


def test_group_ip_purpose_overrides_client_purpose_of_member_port(client):
    """Назначение заданного группой IP — источник истины группа, что бы ни прислал клиент."""
    dev = _device(client, serial="SW-IP-PURPOSE-OVR")
    own_ip = [{"ip_address": "192.168.1.9", "prefix_length": 24, "purpose": "Своё назначение"}]

    r = _sync(client, dev["id"], [_port("Gi0/1", "g1", ips=own_ip)], [_ip_group()])

    assert r.status_code == 200, r.text
    iface = _stored_interfaces(client, dev["id"])["Gi0/1"]
    assert [(i["ip_address"], i["purpose"]) for i in _ips(client, iface["id"])] == [("10.0.0.5", "Доступ администраторов")]


def test_group_with_empty_ip_purpose_clears_purpose_of_member_ports(client):
    """Назначение — часть общего IP, как адрес и префикс: группа записывает его безусловно, поэтому
    пустое назначение группы очищает назначение, которое стояло у порта."""
    dev = _device(client, serial="SW-IP-NO-PURPOSE")
    own_ip = [{"ip_address": "192.168.1.9", "prefix_length": 24, "purpose": "Своё назначение"}]

    r = _sync(client, dev["id"], [_port("Gi0/1", "g1", ips=own_ip), _port("Gi0/2", "g1")], [_ip_group(ip_purpose=None)])

    assert r.status_code == 200, r.text
    stored = _stored_interfaces(client, dev["id"])
    for name in ("Gi0/1", "Gi0/2"):
        assert [(i["ip_address"], i["purpose"]) for i in _ips(client, stored[name]["id"])] == [("10.0.0.5", None)]


def test_group_without_ip_does_not_touch_purpose_of_member_port_ip(client):
    """Пока группа общего IP не задаёт, IP порта (и его назначение) остаются как есть."""
    dev = _device(client, serial="SW-NO-GROUP-IP")
    own_ip = [{"ip_address": "192.168.1.9", "prefix_length": 24, "purpose": "Своё назначение"}]

    r = _sync(client, dev["id"], [_port("Gi0/1", "g1", ips=own_ip)], [{"key": "g1", "name": "Без IP"}])

    assert r.status_code == 200, r.text
    iface = _stored_interfaces(client, dev["id"])["Gi0/1"]
    assert [(i["ip_address"], i["purpose"]) for i in _ips(client, iface["id"])] == [("192.168.1.9", "Своё назначение")]


def test_group_ip_purpose_is_trimmed_and_blank_means_not_set(client):
    dev = _device(client, serial="SW-IP-PURPOSE-TRIM")

    r = _sync(client, dev["id"], [_port("Gi0/1", "g1")], [_ip_group(ip_purpose="  Управление  ")])
    assert r.status_code == 200, r.text
    (group,) = r.json()["groups"]
    assert group["ips"][0]["purpose"] == "Управление"

    # Повторное сохранение ссылается на уже существующую группу по её id.
    r = _sync(client, dev["id"], [_port("Gi0/1", group["id"])], [_ip_group(key=group["id"], id=group["id"], ip_purpose="   ")])
    assert r.status_code == 200, r.text
    assert r.json()["groups"][0]["ips"][0]["purpose"] is None


def test_group_ip_purpose_is_not_stored_without_ip_address(client):
    dev = _device(client, serial="SW-IP-PURPOSE-NOIP")

    r = _sync(client, dev["id"], [_port("Gi0/1", "g1")], [{"key": "g1", "name": "Без IP", "ips": [{"purpose": "Управление"}]}])  # назначение без адреса — плейсхолдер

    assert r.status_code == 200, r.text
    assert r.json()["groups"][0]["ips"] == []
    iface = _stored_interfaces(client, dev["id"])["Gi0/1"]
    assert _ips(client, iface["id"]) == []


def test_group_ip_purpose_longer_than_column_is_rejected(client):
    dev = _device(client, serial="SW-IP-PURPOSE-LONG")

    r = _sync(client, dev["id"], [_port("Gi0/1", "g1")], [_ip_group(ip_purpose="я" * 256)])

    assert r.status_code == 422
    assert "255" in r.json()["detail"]


def test_group_ip_purpose_is_applied_to_existing_ip_in_place(client):
    """Повторное сохранение с новым назначением обновляет ту же запись IP, а не пересоздаёт её."""
    dev = _device(client, serial="SW-IP-PURPOSE-UPD")
    _sync(client, dev["id"], [_port("Gi0/1", "g1")], [_ip_group()])
    iface = _stored_interfaces(client, dev["id"])["Gi0/1"]
    (ip_before,) = _ips(client, iface["id"])
    group_id = client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"][0]["id"]

    r = _sync(
        client,
        dev["id"],
        [{"id": iface["id"], "name": "Gi0/1", "group_key": group_id, "ips": [{"id": ip_before["id"], "ip_address": "10.0.0.5", "prefix_length": 24, "purpose": ip_before["purpose"]}]}],
        [_ip_group(key=group_id, id=group_id, ip_purpose="Резервный канал")],
    )

    assert r.status_code == 200, r.text
    (ip_after,) = _ips(client, iface["id"])
    assert (ip_after["id"], ip_after["purpose"]) == (ip_before["id"], "Резервный канал")
