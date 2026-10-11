"""Универсальный CRUD (`/resources/interfaces`, `/resources/interface-vlans`) соблюдает инварианты «Все VLAN».

Основной путь записи портов — PUT /devices/{id}/interfaces (sync_interfaces) — проверяет, что «Все VLAN»
(device_interfaces.all_vlans) возможно только в режиме trunk и что у такого порта нет выбранных VLAN (набор вычисляется
из VLAN устройства). Generic-ресурсы раньше принимали `all_vlans` и `vlan_mode` как есть и могли породить состояния,
которых sync_interfaces не допускает: access-порт с признаком, признак не-булева типа, порт с признаком и со связями.

Запуск: pytest backend/tests/test_generic_all_vlans_rules.py -v
"""
from __future__ import annotations

import pytest

from app.models import PhysicalDeviceVLAN, VLAN

API = "/api/v1"


class Lab:
    """Устройство с VLAN и порты: обычный trunk (id в `plain`) и trunk с признаком «Все VLAN» (id в `flagged`)."""

    def __init__(self, client, db_session) -> None:
        self.client, self.db = client, db_session
        category = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
        device_type = client.post(f"{API}/resources/device-types", json={"name": "Тип коммутатора", "category_id": category}).json()["id"]
        self.device = client.post(f"{API}/resources/devices", json={"device_type_id": device_type, "serial_number": "SW-GENERIC-1"}).json()["id"]
        self.vlan = VLAN(vlan_id=10, name="vlan10")
        self.db.add(self.vlan)
        self.db.commit()
        self.db.add(PhysicalDeviceVLAN(physical_device_id=self.device, vlan_id=self.vlan.id))
        self.db.commit()
        ports = self.save([
            {"name": "plain", "vlan_mode": "trunk", "vlan_ids": []},
            {"name": "flagged", "vlan_mode": "trunk", "all_vlans": True},
            {"name": "access", "vlan_mode": "access", "vlan_ids": [self.vlan.id]},
        ])
        self.plain, self.flagged, self.access = ports["plain"], ports["flagged"], ports["access"]

    def save(self, interfaces: list[dict]) -> dict[str, str]:
        response = self.client.put(f"{API}/devices/{self.device}/interfaces", json={"interfaces": interfaces})
        assert response.status_code == 200, response.text
        return {item["name"]: item["id"] for item in response.json()["items"]}

    def update(self, port_id: str, **fields):
        return self.client.put(f"{API}/resources/interfaces/{port_id}", json=fields)

    def create(self, **fields):
        return self.client.post(f"{API}/resources/interfaces", json={"physical_device_id": self.device, "name": "new", **fields})

    def stored(self, port_id: str) -> dict:
        return self.client.get(f"{API}/resources/interfaces/{port_id}").json()


@pytest.fixture()
def lab(client, db_session) -> Lab:
    return Lab(client, db_session)


def test_all_vlans_is_rejected_for_access_mode_on_update_and_create(lab):
    response = lab.update(lab.access, all_vlans=True)
    assert response.status_code == 422 and "trunk" in response.json()["detail"]
    assert lab.stored(lab.access)["all_vlans"] is False

    response = lab.create(vlan_mode="access", all_vlans=True)
    assert response.status_code == 422 and "trunk" in response.json()["detail"]


def test_switching_a_flagged_port_to_access_requires_dropping_the_flag_in_the_same_request(lab):
    response = lab.update(lab.flagged, vlan_mode="access")

    assert response.status_code == 422
    assert lab.stored(lab.flagged)["vlan_mode"] == "trunk" and lab.stored(lab.flagged)["all_vlans"] is True

    response = lab.update(lab.flagged, vlan_mode="access", all_vlans=False)
    assert response.status_code == 200, response.text
    assert lab.stored(lab.flagged)["vlan_mode"] == "access" and lab.stored(lab.flagged)["all_vlans"] is False


def test_flag_can_be_set_on_a_trunk_port_without_links_and_is_read_back_from_the_device(lab):
    created = lab.create(vlan_mode="trunk", all_vlans=True)
    assert created.status_code in (200, 201), created.text
    assert created.json()["all_vlans"] is True

    response = lab.update(lab.plain, all_vlans=True)
    assert response.status_code == 200, response.text

    form = {item["interface_id"]: item for item in lab.client.get(f"{API}/devices/{lab.device}/interface-vlans").json()["items"]}
    assert form[lab.plain] == {"interface_id": lab.plain, "all_vlans": True, "vlan_ids": [lab.vlan.id]}
    assert form[created.json()["id"]]["all_vlans"] is True


@pytest.mark.parametrize("value", ["yes", 1, 0, None, "true"])
def test_all_vlans_must_be_a_boolean(lab, value):
    assert lab.update(lab.plain, all_vlans=value).status_code == 422
    assert lab.create(all_vlans=value).status_code == 422
    assert lab.stored(lab.plain)["all_vlans"] is False


def test_unknown_vlan_mode_is_rejected(lab):
    assert lab.update(lab.plain, vlan_mode="hybrid").status_code == 422
    assert lab.create(vlan_mode="hybrid").status_code == 422
    assert lab.stored(lab.plain)["vlan_mode"] == "trunk"


def test_flag_is_rejected_for_a_port_that_still_has_selected_vlans(lab):
    """У порта с признаком связей нет: «Все VLAN» поверх выбранных вручную VLAN оставило бы их мёртвым грузом,
    который вернулся бы при снятии признака."""
    manual = lab.create(name="manual", vlan_mode="trunk").json()["id"]
    link = lab.client.post(f"{API}/resources/interface-vlans", json={"interface_id": manual, "vlan_id": lab.vlan.id, "mode": "trunk"})
    assert link.status_code in (200, 201), link.text

    response = lab.update(manual, all_vlans=True)

    assert response.status_code == 422 and "VLAN" in response.json()["detail"]
    assert lab.stored(manual)["all_vlans"] is False


def test_vlan_link_cannot_be_added_to_a_port_with_the_flag(lab):
    response = lab.client.post(f"{API}/resources/interface-vlans", json={"interface_id": lab.flagged, "vlan_id": lab.vlan.id, "mode": "trunk"})
    assert response.status_code == 422, response.text

    ok = lab.client.post(f"{API}/resources/interface-vlans", json={"interface_id": lab.plain, "vlan_id": lab.vlan.id, "mode": "trunk"})
    assert ok.status_code in (200, 201), ok.text


def test_ordinary_edits_of_a_flagged_port_still_work(lab):
    """Правка других полей (как writeFlagsToNeighbor на дашборде) валидацию признака не задевает."""
    response = lab.update(lab.flagged, is_management=True, description="uplink")

    assert response.status_code == 200, response.text
    stored = lab.stored(lab.flagged)
    assert stored["is_management"] is True and stored["description"] == "uplink" and stored["all_vlans"] is True
