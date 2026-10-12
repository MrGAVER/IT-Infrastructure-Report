"""Общие настройки VLAN стека (кластера): IP-адрес, префикс и «Управление» для всех устройств стека.

GET/PUT/DELETE /api/v1/device-stacks/{id}/vlans[/{vlan_id}], GET .../members/preview, блокировка правки значений на
устройстве и применение настроек при добавлении участника (services/device_stack_vlans.py,
services/crud/stack_vlan_settings.py).

Запуск:  pytest backend/tests/test_device_stack_vlans.py -v
"""
from __future__ import annotations

from app.models import DeviceInterface, InterfaceVLAN, PhysicalDeviceVLAN


def _device(client, serial: str, **extra) -> dict:
    category_id = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    dt = client.post("/api/v1/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    r = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": serial, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _stack(client, name: str, devices: list[dict]) -> dict:
    stack = client.post("/api/v1/resources/device-stacks", json={"name": name}).json()
    for position, device in enumerate(devices, start=1):
        _add_member(client, stack["id"], device, position)
    return stack


def _add_member(client, stack_id: str, device: dict, position: int = 1):
    r = client.post(f"/api/v1/device-stacks/{stack_id}/members", json={"physical_device_id": device["id"], "position": position})
    assert r.status_code == 200, r.text
    return r.json()


def _vlan(client, number: int, **extra) -> dict:
    r = client.post("/api/v1/resources/vlans", json={"vlan_id": number, "name": f"VLAN {number}", **extra})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _set_device_vlans(client, device_id: str, rows: list[dict]):
    return client.put(f"/api/v1/devices/{device_id}/vlans", json={"vlans": rows})


def _stored(client, device_id: str) -> dict[str, dict]:
    items = client.get("/api/v1/resources/device-vlans", params={"physical_device_id": device_id, "limit": 1000}).json()["items"]
    return {x["vlan_id"]: x for x in items}


def _apply(client, stack_id: str, vlan_id: str, ip, prefix, management: bool = False):
    return client.put(f"/api/v1/device-stacks/{stack_id}/vlans/{vlan_id}", json={"ip_address": ip, "prefix_length": prefix, "is_management": management})


def _state(client, stack_id: str) -> dict:
    r = client.get(f"/api/v1/device-stacks/{stack_id}/vlans")
    assert r.status_code == 200, r.text
    return r.json()


def _item(data: dict, vlan_id: str) -> dict:
    return next(x for x in data["items"] if x["vlan_id"] == vlan_id)


def _triple(link: dict) -> tuple:
    return (link["ip_address"], link["prefix_length"], link["is_management"])


class TestApplySharedSetting:
    def test_writes_same_values_to_every_member_creating_missing_assignments(self, client):
        a, b, c = (_device(client, f"CL-{n}", system_name=f"fw-{n}") for n in "abc")
        stack = _stack(client, "Кластер МЭ", [a, b, c])
        v10 = _vlan(client, 10)
        assert _set_device_vlans(client, a["id"], [{"vlan_id": v10["id"], "ip_address": "10.0.10.2", "prefix_length": 24, "description": "mgmt"}]).status_code == 200

        r = _apply(client, stack["id"], v10["id"], "10.0.10.1", 24, True)

        assert r.status_code == 200, r.text
        for device in (a, b, c):
            assert _triple(_stored(client, device["id"])[v10["id"]]) == ("10.0.10.1", 24, True)
        assert _stored(client, a["id"])[v10["id"]]["description"] == "mgmt"  # описание существующего назначения не затронуто
        row = _item(r.json(), v10["id"])
        assert (row["is_shared"], row["is_uniform"], row["ip_address"], row["prefix_length"], row["is_management"]) == (True, True, "10.0.10.1", 24, True)
        assert (row["assigned_count"], row["member_count"]) == (3, 3)

    def test_management_flag_set_on_one_device_ends_up_on_all(self, client):
        a, b = _device(client, "CL-M-1"), _device(client, "CL-M-2")
        stack = _stack(client, "Флаг управления", [a, b])
        v = _vlan(client, 11)
        assert _set_device_vlans(client, a["id"], [{"vlan_id": v["id"], "is_management": True}]).status_code == 200
        assert _set_device_vlans(client, b["id"], [{"vlan_id": v["id"], "is_management": False}]).status_code == 200

        candidate = next(x for x in _state(client, stack["id"])["available"] if x["vlan_id"] == v["id"])
        assert candidate["is_management"] is True  # подсказка формы: флаг есть хотя бы у одного
        assert _apply(client, stack["id"], v["id"], None, None, candidate["is_management"]).status_code == 200

        assert [_stored(client, d["id"])[v["id"]]["is_management"] for d in (a, b)] == [True, True]

    def test_only_management_without_address_is_allowed(self, client):
        a = _device(client, "CL-O-0")
        stack = _stack(client, "Без адреса", [a])
        v = _vlan(client, 12)
        r = _apply(client, stack["id"], v["id"], None, None, True)
        assert r.status_code == 200, r.text
        assert _triple(_stored(client, a["id"])[v["id"]]) == (None, None, True)

    def test_second_identical_apply_changes_nothing(self, client):
        a, b = _device(client, "CL-I-1"), _device(client, "CL-I-2")
        stack = _stack(client, "Идемпотентность", [a, b])
        v = _vlan(client, 20)
        assert _apply(client, stack["id"], v["id"], "10.0.20.1", 24).status_code == 200
        before = _stored(client, a["id"])[v["id"]]
        assert _apply(client, stack["id"], v["id"], "10.0.20.1", 24).status_code == 200
        after = _stored(client, a["id"])[v["id"]]
        assert (after["id"], after["updated_at"]) == (before["id"], before["updated_at"])
        assert len(client.get("/api/v1/resources/device-stack-vlans").json()["items"]) == 1  # одна настройка, не две

    def test_changing_the_setting_rewrites_all_members(self, client):
        a, b = _device(client, "CL-R-1"), _device(client, "CL-R-2")
        stack = _stack(client, "Смена", [a, b])
        v = _vlan(client, 21)
        assert _apply(client, stack["id"], v["id"], "10.0.21.1", 24).status_code == 200
        assert _apply(client, stack["id"], v["id"], "10.0.21.5", 25, True).status_code == 200
        assert [_triple(_stored(client, d["id"])[v["id"]]) for d in (a, b)] == [("10.0.21.5", 25, True)] * 2

    def test_does_not_touch_devices_outside_the_stack(self, client):
        a, b, outsider = _device(client, "CL-X-1"), _device(client, "CL-X-2"), _device(client, "CL-X-3")
        stack = _stack(client, "Свой стек", [a, b])
        v = _vlan(client, 30)
        assert _set_device_vlans(client, outsider["id"], [{"vlan_id": v["id"], "ip_address": "192.168.0.9", "prefix_length": 16}]).status_code == 200
        assert _apply(client, stack["id"], v["id"], "10.0.30.1", 24).status_code == 200
        assert _triple(_stored(client, outsider["id"])[v["id"]]) == ("192.168.0.9", 16, False)

    def test_reapply_repairs_a_device_that_drifted_from_the_setting(self, client, db_session):
        a, b = _device(client, "CL-D-A"), _device(client, "CL-D-B")
        stack = _stack(client, "Расхождение", [a, b])
        v = _vlan(client, 31)
        assert _apply(client, stack["id"], v["id"], "10.0.31.1", 24).status_code == 200
        # Расхождение, в обход API: например, назначение переписала служебная операция домена.
        link = db_session.query(PhysicalDeviceVLAN).filter_by(physical_device_id=b["id"], vlan_id=v["id"]).one()
        link.ip_address = "10.9.9.9"
        db_session.commit()
        row = _item(_state(client, stack["id"]), v["id"])
        assert (row["is_uniform"], row["ip_address"]) == (False, "10.0.31.1")  # настройка остаётся источником значений
        assert [m["ip_address"] for m in row["members"]] == ["10.0.31.1", "10.9.9.9"]

        assert _apply(client, stack["id"], v["id"], "10.0.31.1", 24).status_code == 200

        assert _item(_state(client, stack["id"]), v["id"])["is_uniform"] is True

    def test_drift_of_only_the_management_flag_is_reported_as_divergence(self, client, db_session):
        a, b = _device(client, "CL-DF-A"), _device(client, "CL-DF-B")
        stack = _stack(client, "Расхождение флага", [a, b])
        v = _vlan(client, 32)
        assert _apply(client, stack["id"], v["id"], "10.0.32.1", 24, True).status_code == 200
        link = db_session.query(PhysicalDeviceVLAN).filter_by(physical_device_id=b["id"], vlan_id=v["id"]).one()
        link.is_management = False
        db_session.commit()
        assert _item(_state(client, stack["id"]), v["id"])["is_uniform"] is False

    def test_audit_entry_names_stack_vlan_and_counts(self, client):
        a, b = _device(client, "CL-A-1"), _device(client, "CL-A-2")
        stack = _stack(client, "Аудит стека", [a, b])
        v = _vlan(client, 50)
        assert _apply(client, stack["id"], v["id"], "10.0.50.1", 24, True).status_code == 200
        audit = client.get("/api/v1/resources/audit-log?entity_type=device-stacks&limit=50").json()["items"]
        details = [x["details"] for x in audit if x["entity_id"] == stack["id"] and "Общая настройка VLAN" in (x.get("details") or "")]
        assert details and "10.0.50.1/24" in details[0] and "«Управление»" in details[0] and "назначено устройствам 2" in details[0]


class TestValidation:
    def test_ip_without_prefix_or_prefix_without_ip_is_rejected(self, client):
        a = _device(client, "CL-V-1")
        stack = _stack(client, "Валидация", [a])
        v = _vlan(client, 60)
        assert _apply(client, stack["id"], v["id"], "10.0.60.1", None).status_code == 422
        assert _apply(client, stack["id"], v["id"], None, 24).status_code == 422
        assert _stored(client, a["id"]) == {} and _state(client, stack["id"])["items"] == []  # ничего не записано

    def test_invalid_ip_and_out_of_range_prefix_are_rejected(self, client):
        a = _device(client, "CL-V-2")
        stack = _stack(client, "Валидация 2", [a])
        v = _vlan(client, 61)
        assert _apply(client, stack["id"], v["id"], "999.1.1.1", 24).status_code == 422
        assert _apply(client, stack["id"], v["id"], "fe80::1", 24).status_code == 422  # IPv6 пока не поддерживается
        assert _apply(client, stack["id"], v["id"], "10.0.61.1", 33).status_code == 422
        assert _apply(client, stack["id"], v["id"], "10.0.61.1", -1).status_code == 422

    def test_unknown_stack_unknown_vlan_and_empty_stack(self, client):
        v = _vlan(client, 62)
        assert _apply(client, "no-such-stack", v["id"], "10.0.62.1", 24).status_code == 404
        empty = _stack(client, "Пустой стек", [])
        assert _apply(client, empty["id"], v["id"], "10.0.62.1", 24).status_code == 409
        stack = _stack(client, "Валидация 3", [_device(client, "CL-V-3")])
        assert _apply(client, stack["id"], "no-such-vlan", "10.0.62.1", 24).status_code == 404

    def test_domain_vlan_is_rejected_atomically_when_a_member_is_outside_the_domain(self, client):
        a, b = _device(client, "CL-DM-1", system_name="in-domain"), _device(client, "CL-DM-2", system_name="outside")
        stack = _stack(client, "Домен", [a, b])
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен ЦОД"}).json()
        assert client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": a["id"]}).status_code in (200, 201)
        v = _vlan(client, 70, domain_id=domain["id"])

        r = _apply(client, stack["id"], v["id"], "10.0.70.1", 24)

        assert r.status_code == 422
        assert "outside" in r.json()["detail"] and "in-domain" not in r.json()["detail"]
        link = _stored(client, a["id"]).get(v["id"])
        assert link is None or link["ip_address"] is None  # входящий в домен участник тоже не изменён
        assert _state(client, stack["id"])["items"] == []  # и настройка не создана


class TestLockedOnDevice:
    def _shared(self, client):
        a, b, outsider = _device(client, "CL-LK-1"), _device(client, "CL-LK-2"), _device(client, "CL-LK-3")
        stack = _stack(client, "Блокировка", [a, b])
        v10, v20 = _vlan(client, 10), _vlan(client, 20)
        assert _apply(client, stack["id"], v10["id"], "10.0.10.1", 24, True).status_code == 200
        return a, b, outsider, stack, v10, v20

    def test_device_form_cannot_change_ip_prefix_or_management_of_shared_vlan(self, client):
        a, _, _, _, v10, _ = self._shared(client)
        same = {"vlan_id": v10["id"], "ip_address": "10.0.10.1", "prefix_length": 24, "is_management": True}
        for field, value in (("ip_address", "10.0.10.9"), ("prefix_length", 25), ("is_management", False)):
            r = _set_device_vlans(client, a["id"], [{**same, field: value}])
            assert r.status_code == 409, (field, r.text)
            assert "стека" in r.json()["detail"]
        assert _triple(_stored(client, a["id"])[v10["id"]]) == ("10.0.10.1", 24, True)

    def test_device_form_saves_unchanged_shared_row_and_edits_other_vlans(self, client):
        a, _, _, _, v10, v20 = self._shared(client)
        r = _set_device_vlans(client, a["id"], [
            {"vlan_id": v10["id"], "ip_address": "10.0.10.1", "prefix_length": 24, "is_management": True, "description": "новое описание"},
            {"vlan_id": v20["id"], "ip_address": "10.0.20.7", "prefix_length": 24},
        ])
        assert r.status_code == 200, r.text
        stored = _stored(client, a["id"])
        assert stored[v10["id"]]["description"] == "новое описание"  # описание не входит в общую настройку
        assert stored[v20["id"]]["ip_address"] == "10.0.20.7"

    def test_shared_vlan_cannot_be_removed_from_a_single_device(self, client):
        a, _, _, _, _, v20 = self._shared(client)
        r = _set_device_vlans(client, a["id"], [{"vlan_id": v20["id"]}])  # общий VLAN 10 в запросе отсутствует
        assert r.status_code == 409 and "снимите общую настройку" in r.json()["detail"]

    def test_generic_device_vlan_update_is_locked_too_but_description_is_not(self, client):
        a, _, _, _, v10, _ = self._shared(client)
        link = _stored(client, a["id"])[v10["id"]]
        assert client.put(f"/api/v1/resources/device-vlans/{link['id']}", json={"ip_address": "10.0.10.99"}).status_code == 409
        assert client.put(f"/api/v1/resources/device-vlans/{link['id']}", json={"description": "ok"}).status_code == 200

    def test_device_outside_the_stack_is_not_locked(self, client):
        _, _, outsider, _, v10, _ = self._shared(client)
        assert _set_device_vlans(client, outsider["id"], [{"vlan_id": v10["id"], "ip_address": "172.16.0.1", "prefix_length": 16}]).status_code == 200

    def test_removing_the_device_from_the_stack_unlocks_it_keeping_values(self, client):
        a, _, _, stack, v10, _ = self._shared(client)
        member = next(m for m in client.get("/api/v1/resources/device-stack-members", params={"limit": 100}).json()["items"] if m["physical_device_id"] == a["id"])
        assert client.delete(f"/api/v1/resources/device-stack-members/{member['id']}").status_code == 200
        assert _triple(_stored(client, a["id"])[v10["id"]]) == ("10.0.10.1", 24, True)  # значения остались
        assert _set_device_vlans(client, a["id"], [{"vlan_id": v10["id"], "ip_address": "10.0.10.50", "prefix_length": 24}]).status_code == 200


class TestListing:
    def test_items_are_only_shared_settings_and_available_carries_a_prefill(self, client):
        a, b = _device(client, "CL-L-1", system_name="sw-a"), _device(client, "CL-L-2", system_name="sw-b")
        stack = _stack(client, "Состояния", [a, b])
        v10, v20, v30 = (_vlan(client, n) for n in (10, 20, 30))
        same = {"ip_address": "10.0.20.1", "prefix_length": 24}
        assert _set_device_vlans(client, a["id"], [{"vlan_id": v20["id"], **same}, {"vlan_id": v30["id"], "ip_address": "10.0.30.1", "prefix_length": 24}]).status_code == 200
        assert _set_device_vlans(client, b["id"], [{"vlan_id": v20["id"], **same}, {"vlan_id": v30["id"], "ip_address": "10.0.30.2", "prefix_length": 24}]).status_code == 200
        assert _apply(client, stack["id"], v10["id"], "10.0.10.1", 24).status_code == 200

        data = _state(client, stack["id"])

        assert [x["vlan_number"] for x in data["items"]] == [10]  # только заданные настройки, VLAN устройств сюда не попадают
        assert (data["stack_name"], data["member_count"]) == ("Состояния", 2)
        by_id = {x["vlan_id"]: x for x in data["available"]}
        assert v10["id"] not in by_id
        assert (by_id[v20["id"]]["ip_address"], by_id[v20["id"]]["prefix_length"], by_id[v20["id"]]["assigned_count"]) == ("10.0.20.1", 24, 2)  # сошлись
        assert (by_id[v30["id"]]["ip_address"], by_id[v30["id"]]["prefix_length"]) == (None, None)  # адреса разные — подсказки нет

    def test_available_excludes_vlans_of_domains_that_do_not_contain_every_member(self, client):
        a, b = _device(client, "CL-AV-1"), _device(client, "CL-AV-2")
        stack = _stack(client, "Доступные", [a, b])
        free = _vlan(client, 90)
        foreign_domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Чужой домен"}).json()
        foreign = _vlan(client, 92, domain_id=foreign_domain["id"])
        available = {x["vlan_id"] for x in _state(client, stack["id"])["available"]}
        assert free["id"] in available and foreign["id"] not in available

    def test_empty_stack_and_unknown_stack(self, client):
        empty = _stack(client, "Пустой для списка", [])
        assert _state(client, empty["id"]) == {"stack_name": "Пустой для списка", "member_count": 0, "items": [], "available": []}
        assert client.get("/api/v1/device-stacks/no-such-stack/vlans").status_code == 404


class TestRemoveSetting:
    def _shared(self, client):
        a, b, outsider = _device(client, "CL-RM-1"), _device(client, "CL-RM-2"), _device(client, "CL-RM-3")
        stack = _stack(client, "Удаление", [a, b])
        v = _vlan(client, 10)
        assert _apply(client, stack["id"], v["id"], "10.0.10.1", 24, True).status_code == 200
        assert _set_device_vlans(client, outsider["id"], [{"vlan_id": v["id"], "ip_address": "172.16.0.1", "prefix_length": 16}]).status_code == 200
        return a, b, outsider, stack, v

    def test_default_removes_only_the_setting_and_keeps_values_editable(self, client):
        a, b, _, stack, v = self._shared(client)
        r = client.delete(f"/api/v1/device-stacks/{stack['id']}/vlans/{v['id']}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["items"] == [] and v["id"] in {x["vlan_id"] for x in data["available"]}
        assert [_triple(_stored(client, d["id"])[v["id"]]) for d in (a, b)] == [("10.0.10.1", 24, True)] * 2
        assert _set_device_vlans(client, a["id"], [{"vlan_id": v["id"], "ip_address": "10.0.10.77", "prefix_length": 24}]).status_code == 200

    def test_remove_from_devices_deletes_the_vlan_on_every_member_only(self, client):
        a, b, outsider, stack, v = self._shared(client)
        r = client.delete(f"/api/v1/device-stacks/{stack['id']}/vlans/{v['id']}", params={"remove_from_devices": "true"})
        assert r.status_code == 200, r.text
        assert v["id"] not in _stored(client, a["id"]) and v["id"] not in _stored(client, b["id"])
        assert v["id"] in _stored(client, outsider["id"])  # устройство вне стека не затронуто
        audit = client.get("/api/v1/resources/audit-log?entity_type=device-stacks&limit=50").json()["items"]
        assert any("Снята общая настройка" in (x.get("details") or "") and "убран у устройств: 2" in x["details"] for x in audit)

    def test_remove_from_devices_is_refused_while_a_port_uses_the_vlan(self, client, db_session):
        a, b, _, stack, v = self._shared(client)
        port = DeviceInterface(physical_device_id=a["id"], name="Gi1/0/1")
        db_session.add(port); db_session.flush()
        db_session.add(InterfaceVLAN(interface_id=port.id, vlan_id=v["id"], mode="trunk")); db_session.commit()

        r = client.delete(f"/api/v1/device-stacks/{stack['id']}/vlans/{v['id']}", params={"remove_from_devices": "true"})

        assert r.status_code == 409 and "Gi1/0/1" not in r.json()["detail"] and "(1)" in r.json()["detail"]
        assert v["id"] in _stored(client, a["id"]) and v["id"] in _stored(client, b["id"])  # ничего не удалено
        assert len(_state(client, stack["id"])["items"]) == 1  # настройка тоже осталась

    def test_unknown_setting_is_404(self, client):
        stack = _stack(client, "Нет настройки", [_device(client, "CL-RM-9")])
        v = _vlan(client, 77)
        assert client.delete(f"/api/v1/device-stacks/{stack['id']}/vlans/{v['id']}").status_code == 404
        assert client.delete(f"/api/v1/device-stacks/no-such/vlans/{v['id']}").status_code == 404


class TestAddingAMember:
    def _stack_with_settings(self, client):
        a = _device(client, "CL-AM-1", system_name="fw-a")
        stack = _stack(client, "Кластер", [a])
        v10, v20 = _vlan(client, 10), _vlan(client, 20)
        assert _apply(client, stack["id"], v10["id"], "10.0.10.1", 24, True).status_code == 200
        assert _apply(client, stack["id"], v20["id"], "10.0.20.1", 24).status_code == 200
        return stack, v10, v20

    def _preview(self, client, stack_id: str, device: dict):
        return client.get(f"/api/v1/device-stacks/{stack_id}/members/preview", params={"physical_device_id": device["id"], "position": 2})

    def test_preview_lists_vlans_to_add_and_values_to_replace(self, client):
        stack, v10, v20 = self._stack_with_settings(client)
        newcomer = _device(client, "CL-AM-2", system_name="fw-b")
        assert _set_device_vlans(client, newcomer["id"], [{"vlan_id": v10["id"], "ip_address": "10.0.10.9", "prefix_length": 24}]).status_code == 200

        data = self._preview(client, stack["id"], newcomer).json()

        assert (data["stack_name"], data["device_name"], data["already_member"], data["unchanged_count"]) == ("Кластер", "fw-b", False, 0)
        by_vlan = {c["vlan_number"]: c for c in data["changes"]}
        assert by_vlan[10]["action"] == "update"
        assert by_vlan[10]["before"] == {"ip_address": "10.0.10.9", "prefix_length": 24, "is_management": False}
        assert by_vlan[10]["after"] == {"ip_address": "10.0.10.1", "prefix_length": 24, "is_management": True}
        assert (by_vlan[20]["action"], by_vlan[20]["before"]) == ("add", None)
        assert _stored(client, newcomer["id"])[v10["id"]]["ip_address"] == "10.0.10.9"  # предпросмотр ничего не записывает

    def test_preview_hides_unchanged_and_is_empty_without_settings(self, client):
        stack, v10, v20 = self._stack_with_settings(client)
        twin = _device(client, "CL-AM-3")
        assert _set_device_vlans(client, twin["id"], [{"vlan_id": v10["id"], "ip_address": "10.0.10.1", "prefix_length": 24, "is_management": True},
                                                      {"vlan_id": v20["id"], "ip_address": "10.0.20.1", "prefix_length": 24}]).status_code == 200
        data = self._preview(client, stack["id"], twin).json()
        assert (data["changes"], data["unchanged_count"]) == ([], 2)
        plain = _stack(client, "Без настроек", [])
        assert self._preview(client, plain["id"], _device(client, "CL-AM-4")).json()["changes"] == []

    def test_preview_reports_already_member_and_conflicts(self, client):
        stack, _, _ = self._stack_with_settings(client)
        member = client.get("/api/v1/resources/devices", params={"limit": 100}).json()["items"][0]
        assert self._preview(client, stack["id"], member).json()["already_member"] is True
        other_stack = _stack(client, "Другой стек", [_device(client, "CL-AM-5")])
        in_other = client.get("/api/v1/resources/devices", params={"limit": 100}).json()["items"][-1]
        r = self._preview(client, stack["id"], in_other)
        assert r.status_code == 409 and other_stack["name"] in r.json()["detail"]
        assert client.get(f"/api/v1/device-stacks/{stack['id']}/members/preview", params={"physical_device_id": "nope"}).status_code == 404

    def test_adding_a_member_applies_the_stack_settings(self, client):
        stack, v10, v20 = self._stack_with_settings(client)
        newcomer = _device(client, "CL-AM-6")
        _add_member(client, stack["id"], newcomer, 2)
        stored = _stored(client, newcomer["id"])
        assert _triple(stored[v10["id"]]) == ("10.0.10.1", 24, True) and _triple(stored[v20["id"]]) == ("10.0.20.1", 24, False)
        assert all(x["is_uniform"] for x in _state(client, stack["id"])["items"])
        audit = client.get("/api/v1/resources/audit-log?entity_type=device-stack-members&limit=50").json()["items"]
        assert any("назначено 2, заменено 0" in (x.get("details") or "") for x in audit)

    def test_adding_through_the_generic_resource_applies_them_too(self, client):
        stack, v10, _ = self._stack_with_settings(client)
        newcomer = _device(client, "CL-AM-7")
        r = client.post("/api/v1/resources/device-stack-members", json={"stack_id": stack["id"], "physical_device_id": newcomer["id"], "position": 2})
        assert r.status_code == 201, r.text
        assert _triple(_stored(client, newcomer["id"])[v10["id"]]) == ("10.0.10.1", 24, True)

    def test_member_outside_the_vlan_domain_is_refused_and_not_added(self, client):
        a = _device(client, "CL-AM-8", system_name="in-domain")
        stack = _stack(client, "Домен стека", [a])
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен 1"}).json()
        assert client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": a["id"]}).status_code in (200, 201)
        v = _vlan(client, 70, domain_id=domain["id"])
        assert _apply(client, stack["id"], v["id"], "10.0.70.1", 24).status_code == 200
        newcomer = _device(client, "CL-AM-9", system_name="outsider")

        assert self._preview(client, stack["id"], newcomer).status_code == 422
        r = client.post(f"/api/v1/device-stacks/{stack['id']}/members", json={"physical_device_id": newcomer["id"], "position": 2})

        assert r.status_code == 422 and "outsider" in r.json()["detail"]
        assert _state(client, stack["id"])["member_count"] == 1  # участник не создан


class TestReferentialProtection:
    def test_generic_crud_is_read_only_for_shared_settings(self, client):
        stack = _stack(client, "Только чтение", [_device(client, "CL-RO-1")])
        v = _vlan(client, 10)
        assert client.post("/api/v1/resources/device-stack-vlans", json={"stack_id": stack["id"], "vlan_id": v["id"]}).status_code == 403

    def test_vlan_with_a_shared_setting_cannot_be_deleted_until_it_is_removed(self, client):
        stack = _stack(client, "Защита VLAN", [_device(client, "CL-RF-1")])
        v = _vlan(client, 10)
        assert _apply(client, stack["id"], v["id"], "10.0.10.1", 24).status_code == 200
        r = client.delete(f"/api/v1/resources/vlans/{v['id']}")
        assert r.status_code == 409 and "Общие VLAN стеков" in r.text
        assert client.delete(f"/api/v1/device-stacks/{stack['id']}/vlans/{v['id']}", params={"remove_from_devices": "true"}).status_code == 200
        assert client.delete(f"/api/v1/resources/vlans/{v['id']}").status_code == 200
