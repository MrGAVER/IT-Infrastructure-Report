"""Диагностика «подинтерфейсы на недоступном VLAN»: GET /api/v1/integrity/stale-subinterfaces
и services/integrity.py:find_stale_subinterfaces (тот же поиск строит перечень для журнала аудита при переносе VLAN),
find_off_port_subinterfaces (VLAN разрешён устройству, но не выбран на порту) и find_stale_group_subinterfaces (шаблоны
подинтерфейсов групп портов на VLAN, которого у группы больше нет).

VLAN разрешён устройству, если он назначен ему (PhysicalDeviceVLAN) ИЛИ разрешён его типом (DeviceTypeVLAN);
подинтерфейс на любом другом VLAN — «устаревший»: система его не удаляет, а диагностика показывает.
"""

from __future__ import annotations

from sqlalchemy import delete

from app.models import InterfaceGroupVLAN, InterfaceVLAN
from app.services.integrity import find_off_port_subinterfaces, find_stale_group_subinterfaces, find_stale_subinterfaces

API = "/api/v1"
REPORT = f"{API}/integrity/stale-subinterfaces"


def _vlan(client, number: int) -> dict:
    r = client.post(f"{API}/resources/vlans", json={"vlan_id": number, "name": f"VLAN {number}"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _device(client, serial: str, vlans: tuple[dict, ...] = ()) -> dict:
    """Устройство нового типа; vlans разрешены типом (каталог «VLAN типа устройства»)."""
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    dt = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    for v in vlans:
        assert client.post(f"{API}/resources/device-type-vlans", json={"device_type_id": dt["id"], "vlan_id": v["id"]}).status_code in (
            200,
            201,
        )
    return client.post(f"{API}/resources/devices", json={"device_type_id": dt["id"], "serial_number": serial}).json()


def _add_subinterface(client, device: dict, port: str, name: str, vlan: dict) -> dict:
    r = client.put(
        f"{API}/devices/{device['id']}/interfaces",
        json={
            "interfaces": [
                {"name": port, "vlan_mode": "trunk", "all_vlans": True, "subinterfaces": [{"name": name, "vlan_id": vlan["id"]}]}
            ]
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["items"][0]["subinterfaces"][0]


def _drop_type_vlan(client, device: dict, vlan: dict) -> None:
    links = client.get(f"{API}/resources/device-type-vlans", params={"device_type_id": device["device_type_id"], "limit": 1000}).json()[
        "items"
    ]
    (link,) = [x for x in links if x["vlan_id"] == vlan["id"]]
    assert client.delete(f"{API}/resources/device-type-vlans/{link['id']}").status_code in (200, 204)


def test_empty_registry_is_ok(client):
    assert client.get(REPORT).json() == {"ok": True, "total": 0, "subinterfaces": [], "group_subinterfaces": []}


def test_subinterface_on_an_allowed_vlan_is_not_reported(client):
    v10 = _vlan(client, 10)
    dev = _device(client, "RTR-OK", (v10,))
    _add_subinterface(client, dev, "Gi0/0", "Gi0/0.10", v10)

    assert client.get(REPORT).json()["ok"] is True


def test_vlan_removed_from_the_device_type_makes_the_subinterface_reported_with_details(client):
    v10 = _vlan(client, 10)
    dev = _device(client, "RTR-STALE", (v10,))
    sub = _add_subinterface(client, dev, "Gi0/0", "Gi0/0.10", v10)

    _drop_type_vlan(client, dev, v10)

    body = client.get(REPORT).json()
    assert (body["ok"], body["total"]) == (False, 1)
    (item,) = body["subinterfaces"]
    assert item == {
        "subinterface_id": sub["id"],
        "subinterface_name": "Gi0/0.10",
        "port_id": sub["parent_interface_id"],
        "port_name": "Gi0/0",
        "device_id": dev["id"],
        "device_name": "RTR-STALE",
        "vlan_id": v10["id"],
        "vlan_number": 10,
        "vlan_name": "VLAN 10",
        "reason": "device",
    }
    # диагностика только читает: подинтерфейс на месте
    assert [s["id"] for s in client.get(f"{API}/devices/{dev['id']}/subinterfaces").json()["items"]] == [sub["id"]]


def test_vlan_assigned_to_the_device_itself_keeps_the_subinterface_allowed(client):
    v10 = _vlan(client, 10)
    dev = _device(client, "RTR-OWN", (v10,))
    _add_subinterface(client, dev, "Gi0/0", "Gi0/0.10", v10)
    assert client.post(f"{API}/resources/device-vlans", json={"physical_device_id": dev["id"], "vlan_id": v10["id"]}).status_code in (
        200,
        201,
    )

    _drop_type_vlan(client, dev, v10)
    assert client.get(REPORT).json()["ok"] is True  # VLAN остался назначенным самому устройству


def test_only_stale_subinterfaces_are_listed_in_device_port_name_order_and_vlan_filter_narrows_the_search(client, db_session):
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    b_dev = _device(client, "B-RTR", (v10, v20))
    a_dev = _device(client, "A-FW", (v10,))
    r = client.put(
        f"{API}/devices/{b_dev['id']}/interfaces",
        json={
            "interfaces": [
                {"name": "Gi0/1", "vlan_mode": "trunk", "all_vlans": True, "subinterfaces": [{"name": "Gi0/1.20", "vlan_id": v20["id"]}]},
                {"name": "Gi0/0", "vlan_mode": "trunk", "all_vlans": True, "subinterfaces": [{"name": "Gi0/0.10", "vlan_id": v10["id"]}]},
            ]
        },
    )
    assert r.status_code == 200, r.text
    _add_subinterface(client, a_dev, "eth0", "eth0.10", v10)
    _drop_type_vlan(client, b_dev, v10)
    _drop_type_vlan(client, b_dev, v20)
    _drop_type_vlan(client, a_dev, v10)

    names = [(i["device_name"], i["port_name"], i["subinterface_name"]) for i in client.get(REPORT).json()["subinterfaces"]]
    assert names == [("A-FW", "eth0", "eth0.10"), ("B-RTR", "Gi0/0", "Gi0/0.10"), ("B-RTR", "Gi0/1", "Gi0/1.20")]

    only_v20 = find_stale_subinterfaces(db_session, vlan_id=v20["id"])
    assert [(i["device_name"], i["subinterface_name"]) for i in only_v20] == [("B-RTR", "Gi0/1.20")]


# --- подинтерфейс на VLAN, который не выбран на порту ---------------------------------------------------------------


def _drop_port_vlans(db_session, port_id: str) -> None:
    """Снимает VLAN с порта в обход формы (окно порта, согласование портов, каскад режима правят VLAN порта отдельно от подинтерфейсов)."""
    db_session.execute(delete(InterfaceVLAN).where(InterfaceVLAN.interface_id == port_id))
    db_session.commit()


def _port_with_vlan(client, device: dict, port: str, name: str, vlan: dict) -> dict:
    r = client.put(
        f"{API}/devices/{device['id']}/interfaces",
        json={
            "interfaces": [
                {"name": port, "vlan_mode": "trunk", "vlan_ids": [vlan["id"]], "subinterfaces": [{"name": name, "vlan_id": vlan["id"]}]}
            ]
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["items"][0]


def test_vlan_removed_from_the_port_only_makes_the_subinterface_off_port_not_stale(client, db_session):
    v10 = _vlan(client, 10)
    dev = _device(client, "RTR-OFFPORT", (v10,))
    port = _port_with_vlan(client, dev, "Gi0/0", "Gi0/0.10", v10)
    assert client.get(REPORT).json()["ok"] is True  # VLAN на порту — всё в порядке

    _drop_port_vlans(db_session, port["id"])

    assert find_stale_subinterfaces(db_session) == []  # устройству VLAN по-прежнему разрешён
    (item,) = find_off_port_subinterfaces(db_session)
    assert item == {
        "subinterface_id": port["subinterfaces"][0]["id"],
        "subinterface_name": "Gi0/0.10",
        "port_id": port["id"],
        "port_name": "Gi0/0",
        "device_id": dev["id"],
        "device_name": "RTR-OFFPORT",
        "vlan_id": v10["id"],
        "vlan_number": 10,
        "vlan_name": "VLAN 10",
    }
    body = client.get(REPORT).json()
    assert (body["ok"], body["total"]) == (False, 1)
    assert [(i["subinterface_name"], i["reason"]) for i in body["subinterfaces"]] == [("Gi0/0.10", "port")]


def test_subinterface_is_listed_once_when_the_vlan_is_gone_from_the_device_too(client, db_session):
    v10 = _vlan(client, 10)
    dev = _device(client, "RTR-BOTH", (v10,))
    port = _port_with_vlan(client, dev, "Gi0/0", "Gi0/0.10", v10)
    _drop_port_vlans(db_session, port["id"])
    _drop_type_vlan(client, dev, v10)

    body = client.get(REPORT).json()

    assert body["total"] == 1
    assert [(i["subinterface_name"], i["reason"]) for i in body["subinterfaces"]] == [
        ("Gi0/0.10", "device")
    ]  # причина «устройство» важнее, без дубля
    assert find_off_port_subinterfaces(db_session) == []


def test_all_vlans_port_never_reports_off_port(client, db_session):
    v10 = _vlan(client, 10)
    dev = _device(client, "RTR-ALL", (v10,))
    _add_subinterface(client, dev, "Gi0/0", "Gi0/0.10", v10)  # порт «Все VLAN»

    assert find_off_port_subinterfaces(db_session) == []


# --- шаблоны подинтерфейсов групп портов -----------------------------------------------------------------------------


def _group_with_template(client, device: dict, vlans: tuple[dict, ...], template_vlan: dict, name: str = "Группа") -> dict:
    r = client.put(
        f"{API}/devices/{device['id']}/interfaces",
        json={
            "interfaces": [{"name": "Gi0/0", "group_key": "g1"}],
            "groups": [
                {
                    "key": "g1",
                    "name": name,
                    "vlan_mode": "trunk",
                    "vlan_ids": [v["id"] for v in vlans],
                    "manage_subinterfaces": True,
                    "subinterfaces": [{"vlan_id": template_vlan["id"]}],
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    return r.json()["groups"][0]


def test_group_template_on_a_vlan_the_group_still_has_is_not_reported(client, db_session):
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    dev = _device(client, "RTR-GRP-OK", (v10, v20))
    _group_with_template(client, dev, (v10, v20), v10)

    assert find_stale_group_subinterfaces(db_session) == []
    assert client.get(REPORT).json()["group_subinterfaces"] == []


def test_group_template_left_without_its_vlan_is_reported_with_details_and_not_removed(client, db_session):
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    dev = _device(client, "RTR-GRP-STALE", (v10, v20))
    group = _group_with_template(client, dev, (v10, v20), v10)
    # связи VLAN с группой снимает перенос VLAN в другой домен; шаблон при этом остаётся
    db_session.execute(
        delete(InterfaceGroupVLAN).where(InterfaceGroupVLAN.group_id == group["id"], InterfaceGroupVLAN.vlan_id == v10["id"])
    )
    db_session.commit()

    (item,) = find_stale_group_subinterfaces(db_session)
    assert item == {
        "subinterface_id": group["subinterfaces"][0]["id"],
        "group_id": group["id"],
        "group_name": "Группа",
        "device_id": dev["id"],
        "device_name": "RTR-GRP-STALE",
        "vlan_id": v10["id"],
        "vlan_number": 10,
        "vlan_name": "VLAN 10",
    }
    body = client.get(REPORT).json()
    assert (body["ok"], body["total"], body["subinterfaces"]) == (False, 1, [])
    assert body["group_subinterfaces"] == [item]
    assert (
        len(client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"][0]["subinterfaces"]) == 1
    )  # диагностика только читает
    assert [i["subinterface_id"] for i in find_stale_group_subinterfaces(db_session, vlan_id=v10["id"])] == [item["subinterface_id"]]
    assert find_stale_group_subinterfaces(db_session, vlan_id=v20["id"]) == []


def test_all_vlans_group_template_follows_the_device_vlans(client, db_session):
    v10 = _vlan(client, 10)
    dev = _device(client, "RTR-GRP-ALL", (v10,))
    r = client.put(
        f"{API}/devices/{dev['id']}/interfaces",
        json={
            "interfaces": [{"name": "Gi0/0", "group_key": "g1"}],
            "groups": [
                {
                    "key": "g1",
                    "name": "Все",
                    "vlan_mode": "trunk",
                    "all_vlans": True,
                    "manage_subinterfaces": True,
                    "subinterfaces": [{"vlan_id": v10["id"]}],
                }
            ],
        },
    )
    assert r.status_code == 200, r.text
    assert find_stale_group_subinterfaces(db_session) == []

    _drop_type_vlan(client, dev, v10)  # VLAN пропал у устройства — вместе с ним из набора группы «Все VLAN»

    assert [i["vlan_number"] for i in find_stale_group_subinterfaces(db_session)] == [10]
