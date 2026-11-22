"""«Все VLAN» порта и группы портов — сохраняемый признак, а не вычисление из числа выбранных VLAN
(device_interfaces.all_vlans / interface_groups.all_vlans, services/port_vlans.py).

Что проверяется:
  * признак хранится в БД; порт (группа) с признаком НЕ хранит связей interface_vlans / interface_group_vlans,
    а набор VLAN вычисляется из VLAN устройства (VLAN типа ∪ VLAN самого устройства) и следует за ним;
  * вручную выбранный полный набор — не признак (ничего не выводится из числа VLAN);
  * форма читает VLAN портов запросом по устройству (GET /devices/{id}/interface-vlans): общий список связей
    реестра с потолком в 1000 записей отрезал новые связи, и порт открывался с 0 VLAN;
  * правка порта с дашборда, каскад смены режима и сверка подключений понимают признак.

Запуск: pytest backend/tests/test_all_vlans_flag.py -v
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from app.models import DeviceInterface, DeviceTypeVLAN, InterfaceGroupVLAN, InterfaceVLAN, PhysicalDevice, PhysicalDeviceVLAN, VLAN
from app.services.connection_query import _vlan_fingerprint_sql
from app.services.port_config import vlan_fingerprint

API = "/api/v1"


class Lab:
    """Устройства с VLAN типа и собственными VLAN плюс обращения к эндпоинтам формы."""

    def __init__(self, client, db_session) -> None:
        self.client, self.db = client, db_session
        self.category = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
        self.vlans: dict[int, VLAN] = {}

    def vlan(self, number: int) -> VLAN:
        if number not in self.vlans:
            row = VLAN(vlan_id=number, name=f"vlan{number}")
            self.db.add(row)
            self.db.commit()
            self.vlans[number] = row
        return self.vlans[number]

    def device(self, serial: str, *, type_vlans: tuple[int, ...] = (), own_vlans: tuple[int, ...] = ()) -> str:
        device_type = self.client.post(
            f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": self.category}
        ).json()["id"]
        for number in type_vlans:
            self.db.add(DeviceTypeVLAN(device_type_id=device_type, vlan_id=self.vlan(number).id))
        self.db.commit()
        device = self.client.post(f"{API}/resources/devices", json={"device_type_id": device_type, "serial_number": serial}).json()["id"]
        for number in own_vlans:
            self.db.add(PhysicalDeviceVLAN(physical_device_id=device, vlan_id=self.vlan(number).id))
        self.db.commit()
        return device

    def put(self, device_id: str, interfaces: list[dict], groups: list[dict] | None = None):
        body: dict = {"interfaces": interfaces}
        if groups is not None:
            body["groups"] = groups
        return self.client.put(f"{API}/devices/{device_id}/interfaces", json=body)

    def save(self, device_id: str, interfaces: list[dict], groups: list[dict] | None = None) -> dict:
        response = self.put(device_id, interfaces, groups)
        assert response.status_code == 200, response.text
        return response.json()

    def form(self, device_id: str) -> dict[str, dict]:
        """GET /devices/{id}/interface-vlans: {id порта: {all_vlans, vlan_ids}}."""
        response = self.client.get(f"{API}/devices/{device_id}/interface-vlans")
        assert response.status_code == 200, response.text
        return {item["interface_id"]: item for item in response.json()["items"]}

    def ids(self, *numbers: int) -> list[str]:
        return [self.vlan(n).id for n in numbers]

    def stored_links(self, interface_id: str) -> int:
        self.db.expire_all()
        return self.db.scalar(select(func.count()).select_from(InterfaceVLAN).where(InterfaceVLAN.interface_id == interface_id))

    def flag(self, interface_id: str) -> bool:
        self.db.expire_all()
        return self.db.get(DeviceInterface, interface_id).all_vlans


@pytest.fixture()
def lab(client, db_session) -> Lab:
    return Lab(client, db_session)


def _trunk(name: str = "Gi0/1", **extra) -> dict:
    return {"name": name, "vlan_mode": "trunk", **extra}


# --- Признак порта ----------------------------------------------------------------------------------


def test_flag_is_stored_without_links_and_the_form_reads_the_devices_vlans(lab):
    device = lab.device("AV-1", type_vlans=(10,), own_vlans=(20,))

    saved = lab.save(device, [_trunk(all_vlans=True)])

    (port,) = saved["items"]
    assert port["all_vlans"] is True and port["vlan_mode"] == "trunk"
    assert lab.stored_links(port["id"]) == 0  # хранится только признак
    assert lab.form(device)[port["id"]] == {"interface_id": port["id"], "all_vlans": True, "vlan_ids": lab.ids(10, 20)}


def test_the_flagged_port_follows_the_vlans_added_to_and_removed_from_the_device(lab):
    device = lab.device("AV-2", type_vlans=(10,), own_vlans=(20,))
    (port,) = lab.save(device, [_trunk(all_vlans=True)])["items"]

    lab.db.add(DeviceTypeVLAN(device_type_id=lab.db.get(PhysicalDevice, device).device_type_id, vlan_id=lab.vlan(30).id))
    lab.db.commit()
    assert lab.form(device)[port["id"]]["vlan_ids"] == lab.ids(10, 20, 30)  # добавленный позже VLAN появился сам

    lab.db.query(PhysicalDeviceVLAN).filter_by(physical_device_id=device).delete()
    lab.db.commit()
    assert lab.form(device)[port["id"]]["vlan_ids"] == lab.ids(10, 30)  # снятый — пропал
    assert lab.stored_links(port["id"]) == 0


def test_all_vlans_chosen_by_hand_is_not_the_flag(lab):
    device = lab.device("AV-3", type_vlans=(10, 20))

    (port,) = lab.save(device, [_trunk(vlan_ids=lab.ids(10, 20))])["items"]

    assert port["all_vlans"] is False  # полный набор вручную ≠ «Все VLAN»
    assert lab.stored_links(port["id"]) == 2
    assert lab.form(device)[port["id"]] == {"interface_id": port["id"], "all_vlans": False, "vlan_ids": lab.ids(10, 20)}


def test_resaving_without_the_key_drops_the_flag_and_stores_the_chosen_vlans(lab):
    device = lab.device("AV-4", type_vlans=(10, 20))
    (port,) = lab.save(device, [_trunk(all_vlans=True)])["items"]

    (again,) = lab.save(device, [_trunk(id=port["id"], vlan_ids=lab.ids(10))])["items"]

    assert again["id"] == port["id"] and again["all_vlans"] is False
    assert lab.stored_links(port["id"]) == 1
    assert lab.form(device)[port["id"]]["vlan_ids"] == lab.ids(10)


def test_vlan_ids_sent_with_the_flag_are_ignored(lab):
    device = lab.device("AV-5", type_vlans=(10,))
    foreign = lab.vlan(99)  # не доступен устройству: без флага это 422, с флагом набор не используется

    (port,) = lab.save(device, [_trunk(all_vlans=True, vlan_ids=[foreign.id])])["items"]

    assert lab.stored_links(port["id"]) == 0
    assert lab.form(device)[port["id"]]["vlan_ids"] == lab.ids(10)


def test_all_vlans_is_rejected_in_access_mode_and_for_a_non_boolean(lab):
    device = lab.device("AV-6", type_vlans=(10,))

    access = lab.put(device, [{"name": "Gi0/1", "vlan_mode": "access", "all_vlans": True}])
    garbage = lab.put(device, [_trunk(all_vlans="yes")])

    assert access.status_code == 422 and "trunk" in access.text
    assert garbage.status_code == 422 and "all_vlans" in garbage.text


def test_the_flag_is_dropped_when_the_port_becomes_access(lab):
    device = lab.device("AV-7", type_vlans=(10, 20))
    (port,) = lab.save(device, [_trunk(all_vlans=True)])["items"]

    (again,) = lab.save(device, [{"id": port["id"], "name": "Gi0/1", "vlan_mode": "access", "vlan_ids": lab.ids(10)}])["items"]

    assert again["all_vlans"] is False and again["vlan_mode"] == "access"
    assert lab.form(device)[port["id"]] == {"interface_id": port["id"], "all_vlans": False, "vlan_ids": lab.ids(10)}


# --- Корень бага: форма не должна зависеть от размера реестра ---------------------------------------


def test_the_form_still_sees_vlans_when_the_registry_has_more_than_1000_links(lab):
    """Раньше форма брала ВСЕ связи реестра одним запросом с limit=1000 (oldest-first) и фильтровала по порту у
    себя: когда в реестре больше 1000 связей, связи свежих портов отрезались — порт открывался с 0 VLAN, а
    повторное сохранение их удаляло. Эндпоинт устройства читает только порты этого устройства."""
    busy = lab.device("AV-BUSY", type_vlans=(10,))
    vlan = lab.vlan(10)
    ports = [DeviceInterface(physical_device_id=busy, name=f"p{i}", vlan_mode="trunk") for i in range(1001)]
    lab.db.add_all(ports)
    lab.db.flush()
    lab.db.add_all(InterfaceVLAN(interface_id=p.id, vlan_id=vlan.id, mode="trunk") for p in ports)
    lab.db.commit()
    assert lab.db.scalar(select(func.count()).select_from(InterfaceVLAN)) > 1000

    device = lab.device("AV-LATE", type_vlans=(10, 20))
    (port,) = lab.save(device, [_trunk(vlan_ids=lab.ids(10, 20))])["items"]

    assert lab.form(device)[port["id"]]["vlan_ids"] == lab.ids(10, 20)
    assert len(lab.form(busy)) == 1001


def test_interface_vlans_endpoint_404_for_an_unknown_device(client):
    assert client.get(f"{API}/devices/no-such-device/interface-vlans").status_code == 404


# --- Группы портов -----------------------------------------------------------------------------------


def test_group_flag_is_stored_without_links_and_marks_the_member_ports(lab):
    device = lab.device("AV-G1", type_vlans=(10,), own_vlans=(20,))
    groups = [{"key": "g", "name": "Магистрали", "vlan_mode": "trunk", "all_vlans": True}]

    saved = lab.save(device, [_trunk("Gi0/1", group_key="g"), _trunk("Gi0/2", group_key="g"), _trunk("Gi0/3")], groups)

    (group,) = saved["groups"]
    assert group["all_vlans"] is True and sorted(group["vlan_ids"]) == sorted(lab.ids(10, 20))
    assert lab.db.scalar(select(func.count()).select_from(InterfaceGroupVLAN)) == 0
    by_name = {p["name"]: p for p in saved["items"]}
    for name in ("Gi0/1", "Gi0/2"):
        assert by_name[name]["all_vlans"] is True and lab.stored_links(by_name[name]["id"]) == 0
        assert lab.form(device)[by_name[name]["id"]]["vlan_ids"] == lab.ids(10, 20)
    assert by_name["Gi0/3"]["all_vlans"] is False


def test_group_with_an_explicit_set_clears_the_flag_of_its_ports(lab):
    device = lab.device("AV-G2", type_vlans=(10, 20))
    saved = lab.save(device, [_trunk("Gi0/1", group_key="g")], [{"key": "g", "name": "Г", "vlan_mode": "trunk", "all_vlans": True}])
    (group,) = saved["groups"]
    (port,) = saved["items"]

    again = lab.save(
        device,
        [_trunk("Gi0/1", id=port["id"], group_key=group["id"])],
        [{"key": group["id"], "id": group["id"], "name": "Г", "vlan_mode": "trunk", "vlan_ids": lab.ids(10)}],
    )

    assert again["groups"][0]["all_vlans"] is False and again["items"][0]["all_vlans"] is False
    assert lab.form(device)[port["id"]]["vlan_ids"] == lab.ids(10)


def test_group_all_vlans_needs_trunk_mode(lab):
    device = lab.device("AV-G3", type_vlans=(10,))

    response = lab.put(device, [], [{"key": "g", "name": "Г", "vlan_mode": "access", "all_vlans": True}])

    assert response.status_code == 422 and "trunk" in response.text


# --- Правка порта с дашборда подключений -------------------------------------------------------------


def test_port_config_edit_sets_and_clears_the_flag(lab, client):
    device = lab.device("AV-E1", type_vlans=(10, 20))
    (port,) = lab.save(device, [_trunk(vlan_ids=lab.ids(10))])["items"]

    flagged = client.put(f"{API}/interfaces/{port['id']}/port-config", json={"all_vlans": True})
    assert flagged.status_code == 200, flagged.text
    assert lab.flag(port["id"]) is True and lab.stored_links(port["id"]) == 0
    assert lab.form(device)[port["id"]]["vlan_ids"] == lab.ids(10, 20)

    explicit = client.put(f"{API}/interfaces/{port['id']}/port-config", json={"vlan_ids": lab.ids(10)})
    assert explicit.status_code == 200, explicit.text
    assert lab.flag(port["id"]) is False and lab.stored_links(port["id"]) == 1


def test_port_config_edit_rejects_the_flag_in_access_mode(lab, client):
    device = lab.device("AV-E2", type_vlans=(10,))
    (port,) = lab.save(device, [{"name": "Gi0/1", "vlan_mode": "access", "vlan_ids": lab.ids(10)}])["items"]

    response = client.put(f"{API}/interfaces/{port['id']}/port-config", json={"all_vlans": True})

    assert response.status_code == 422 and "trunk" in response.text
    assert lab.flag(port["id"]) is False


# --- Каскад смены режима -----------------------------------------------------------------------------


def test_cascade_to_access_drops_the_flag_and_keeps_at_most_one_vlan(lab, client):
    device = lab.device("AV-C1", type_vlans=(10, 20))
    (port,) = lab.save(device, [_trunk(all_vlans=True)])["items"]
    plan = client.post(f"{API}/interfaces/{port['id']}/vlan-mode-cascade/preview", json={"mode": "access"}).json()

    response = client.post(
        f"{API}/interfaces/{port['id']}/vlan-mode-cascade", json={"mode": "access", "plan_hash": plan["hash"], "confirm": True}
    )

    assert response.status_code == 200, response.text
    assert lab.flag(port["id"]) is False
    assert len(lab.form(device)[port["id"]]["vlan_ids"]) <= 1
    assert lab.db.get(DeviceInterface, port["id"]).vlan_mode == "access"


# --- Сверка подключений: SQL-отпечаток порта с «Все VLAN» --------------------------------------------


def _fingerprint(lab: Lab, interface_id: str) -> int:
    iface = aliased(DeviceInterface)
    return lab.db.scalar(select(_vlan_fingerprint_sql(iface)).select_from(iface).where(iface.id == interface_id))


def test_sql_fingerprint_of_a_flagged_port_is_its_own_devices_vlans_only(lab):
    """Подзапросы «VLAN устройства» ссылаются на порт через два уровня SELECT: без явной корреляции порт
    перемножался со всеми портами реестра, и у любого порта отпечаток был одинаковым."""
    narrow = lab.device("AV-F1", type_vlans=(10,))
    wide = lab.device("AV-F2", type_vlans=(10,), own_vlans=(20, 30))
    plain = lab.device("AV-F3", type_vlans=(10, 20))
    (a,) = lab.save(narrow, [_trunk(all_vlans=True)])["items"]
    (b,) = lab.save(wide, [_trunk(all_vlans=True)])["items"]
    (c,) = lab.save(plain, [_trunk(vlan_ids=lab.ids(10, 20))])["items"]

    assert _fingerprint(lab, a["id"]) == vlan_fingerprint([10])
    assert _fingerprint(lab, b["id"]) == vlan_fingerprint([10, 20, 30])
    assert _fingerprint(lab, c["id"]) == vlan_fingerprint([10, 20])  # порт без признака — по своим связям
