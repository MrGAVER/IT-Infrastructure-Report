"""Правка порта с дашборда «Подключения»: PUT /api/v1/interfaces/{id}/port-config — роль и набор VLAN
одной операцией (app/services/port_edit.py).

Запуск: pytest backend/tests/test_port_edit_api.py -v
"""
from __future__ import annotations

import pytest

from app.models import AuditLog, DeviceInterface, InterfaceGroup, InterfaceVLAN, IPAddress, PhysicalDeviceVLAN, VLAN


class Lab:
    """Устройство с портом, VLAN устройства и обращения к эндпоинту."""

    def __init__(self, client, db_session) -> None:
        self.client, self.db = client, db_session
        category = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
        self.device_type = client.post("/api/v1/resources/device-types", json={"name": "Тип для правки порта", "category_id": category}).json()["id"]
        self.vlans: dict[int, VLAN] = {}

    def vlan(self, number: int) -> VLAN:
        if number not in self.vlans:
            row = VLAN(vlan_id=number, name=f"vlan{number}")
            self.db.add(row)
            self.db.flush()
            self.vlans[number] = row
        return self.vlans[number]

    def port(self, serial: str = "EDIT-1", *, allowed: tuple[int, ...] = (10, 20, 30), mode: str = "trunk", role: tuple[bool, bool] = (False, True), ip: str | None = None) -> str:
        device = self.client.post("/api/v1/resources/devices", json={"device_type_id": self.device_type, "serial_number": serial}).json()
        for number in allowed:
            self.db.add(PhysicalDeviceVLAN(physical_device_id=device["id"], vlan_id=self.vlan(number).id))
        self.db.commit()
        item: dict = {"name": "Gi0/1", "is_management": role[0], "is_data_transfer": role[1], "vlan_mode": mode}
        if ip:
            item["ips"] = [{"ip_address": ip}]
        response = self.client.put(f"/api/v1/devices/{device['id']}/interfaces", json={"interfaces": [item]})
        assert response.status_code == 200, response.text
        return response.json()["items"][0]["id"]

    def edit(self, interface_id: str, body: dict):
        return self.client.put(f"/api/v1/interfaces/{interface_id}/port-config", json=body)

    def state(self, interface_id: str) -> dict:
        self.db.expire_all()
        iface = self.db.get(DeviceInterface, interface_id)
        links = self.db.query(InterfaceVLAN).filter_by(interface_id=interface_id).all()
        return {
            "role": (iface.is_management, iface.is_data_transfer),
            "mode": iface.vlan_mode,
            "vlans": sorted(self.db.get(VLAN, link.vlan_id).vlan_id for link in links),
            "link_modes": {link.mode for link in links},
        }

    def audit(self, *needles: str) -> list[str]:
        self.db.expire_all()
        return [e.details for e in self.db.query(AuditLog).all() if all(n in (e.details or "") for n in needles)]


@pytest.fixture()
def lab(client, db_session) -> Lab:
    return Lab(client, db_session)


def test_changes_role_and_vlans_in_one_request(lab):
    port = lab.port()

    response = lab.edit(port, {"role": "management_data", "vlan_ids": [lab.vlan(10).id, lab.vlan(20).id], "mode": "trunk"})

    assert response.status_code == 200, response.text
    assert response.json()["id"] == port and response.json()["is_management"] is True and response.json()["is_data_transfer"] is True
    assert lab.state(port) == {"role": (True, True), "mode": "trunk", "vlans": [10, 20], "link_modes": {"trunk"}}
    (entry,) = lab.audit("Правка порта", "Gi0/1")
    assert "роль Передача данных → Передача данных и управление активами" in entry and "VLAN нет → 10, 20" in entry


def test_vlans_replace_the_whole_set_and_keep_the_mode(lab):
    port = lab.port(mode="trunk")
    assert lab.edit(port, {"vlan_ids": [lab.vlan(10).id, lab.vlan(20).id]}).status_code == 200

    assert lab.edit(port, {"vlan_ids": [lab.vlan(20).id, lab.vlan(30).id]}).status_code == 200

    assert lab.state(port)["vlans"] == [20, 30] and lab.state(port)["mode"] == "trunk"
    assert lab.edit(port, {"vlan_ids": []}).status_code == 200 and lab.state(port)["vlans"] == []  # снять все VLAN можно


def test_role_only_does_not_touch_vlans_and_mirrors_the_flag_to_ips(lab):
    port = lab.port(ip="10.0.0.5")
    assert lab.edit(port, {"vlan_ids": [lab.vlan(10).id]}).status_code == 200

    assert lab.edit(port, {"role": "management"}).status_code == 200

    assert lab.state(port)["role"] == (True, False) and lab.state(port)["vlans"] == [10]
    lab.db.expire_all()
    assert lab.db.query(IPAddress).filter_by(owner_id=port).one().is_management is True


def test_access_port_takes_at_most_one_vlan(lab):
    port = lab.port(mode="access")

    too_many = lab.edit(port, {"vlan_ids": [lab.vlan(10).id, lab.vlan(20).id]})
    one = lab.edit(port, {"vlan_ids": [lab.vlan(10).id]})

    assert too_many.status_code == 422 and "access" in too_many.json()["detail"]
    assert one.status_code == 200 and lab.state(port) == {"role": (False, True), "mode": "access", "vlans": [10], "link_modes": {"access"}}


def test_a_vlan_the_device_does_not_have_is_rejected_and_nothing_is_written(lab):
    port = lab.port(allowed=(10,))

    response = lab.edit(port, {"role": "management", "vlan_ids": [lab.vlan(10).id, lab.vlan(99).id]})

    assert response.status_code == 422 and "не разрешены" in response.json()["detail"]
    assert lab.state(port) == {"role": (False, True), "mode": "trunk", "vlans": [], "link_modes": set()}  # роль тоже не записана
    assert lab.audit("Правка порта") == []


def test_a_port_in_a_group_that_sets_mode_and_vlans_keeps_its_vlans_but_may_change_role(lab):
    port = lab.port()
    iface = lab.db.get(DeviceInterface, port)
    group = InterfaceGroup(physical_device_id=iface.physical_device_id, name="Магистрали", vlan_mode="trunk")
    lab.db.add(group)
    lab.db.flush()
    iface.group_id = group.id
    lab.db.commit()

    blocked = lab.edit(port, {"vlan_ids": [lab.vlan(10).id]})
    role = lab.edit(port, {"role": "management"})

    assert blocked.status_code == 409 and "Магистрали" in blocked.json()["detail"] and "группу" in blocked.json()["detail"]
    assert role.status_code == 200 and lab.state(port)["role"] == (True, False)


def test_an_unchanged_set_in_a_group_port_is_not_an_error(lab):
    port = lab.port()
    iface = lab.db.get(DeviceInterface, port)
    group = InterfaceGroup(physical_device_id=iface.physical_device_id, name="Только режим", vlan_mode="trunk")
    lab.db.add(group)
    lab.db.flush()
    iface.group_id = group.id
    lab.db.commit()

    assert lab.edit(port, {"vlan_ids": []}).status_code == 200  # набор тот же — править нечего


def test_mode_in_the_request_is_a_check_not_a_command(lab):
    port = lab.port(mode="access")

    response = lab.edit(port, {"mode": "trunk", "vlan_ids": [lab.vlan(10).id, lab.vlan(20).id]})

    assert response.status_code == 409 and "изменился" in response.json()["detail"]
    assert lab.state(port)["mode"] == "access" and lab.state(port)["vlans"] == []


def test_nothing_changed_writes_nothing_and_leaves_no_audit_entry(lab):
    port = lab.port()

    response = lab.edit(port, {"role": "data", "vlan_ids": []})

    assert response.status_code == 200 and lab.audit("Правка порта") == []


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ({}, "role и/или vlan_ids"),
        ({"role": "boss"}, "role"),
        ({"role": 5}, "role"),
        ({"vlan_ids": "10"}, "vlan_ids"),
        ({"vlan_ids": [1]}, "vlan_ids"),
        ({"vlan_ids": [""]}, "vlan_ids"),
        ({"mode": "hybrid", "role": "data"}, "mode"),
        ({"role": "data", "extra": 1}, "Неизвестные поля"),
    ],
)
def test_malformed_requests_are_rejected(lab, body, fragment):
    port = lab.port()

    response = lab.edit(port, body)

    assert response.status_code == 422 and fragment in response.json()["detail"]


def test_unknown_port_is_404_and_a_non_object_body_is_422(lab, client):
    assert lab.edit("no-such-port", {"role": "data"}).status_code == 404
    assert client.put("/api/v1/interfaces/x/port-config", json=[1]).status_code == 422


def test_duplicate_vlan_ids_are_collapsed(lab):
    port = lab.port()
    vlan = lab.vlan(10).id

    assert lab.edit(port, {"vlan_ids": [vlan, vlan]}).status_code == 200

    assert lab.state(port)["vlans"] == [10]
