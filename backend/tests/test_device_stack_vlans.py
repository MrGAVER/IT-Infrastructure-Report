"""Общие IP-адрес и маска VLAN для всех устройств стека (кластера):
GET/PUT /api/v1/device-stacks/{id}/vlans (services/device_stack_vlans.py).

Запуск:  pytest backend/tests/test_device_stack_vlans.py -v
"""
from __future__ import annotations


def _device(client, serial: str, **extra) -> dict:
    category_id = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    dt = client.post("/api/v1/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    r = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": serial, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _stack(client, name: str, devices: list[dict]) -> dict:
    stack = client.post("/api/v1/resources/device-stacks", json={"name": name}).json()
    for position, device in enumerate(devices, start=1):
        r = client.post(f"/api/v1/device-stacks/{stack['id']}/members", json={"physical_device_id": device["id"], "position": position})
        assert r.status_code == 200, r.text
    return stack


def _vlan(client, number: int, **extra) -> dict:
    r = client.post("/api/v1/resources/vlans", json={"vlan_id": number, "name": f"VLAN {number}", **extra})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _set_device_vlans(client, device_id: str, rows: list[dict]) -> None:
    r = client.put(f"/api/v1/devices/{device_id}/vlans", json={"vlans": rows})
    assert r.status_code == 200, r.text


def _stored(client, device_id: str) -> dict[str, dict]:
    items = client.get("/api/v1/resources/device-vlans", params={"physical_device_id": device_id, "limit": 1000}).json()["items"]
    return {x["vlan_id"]: x for x in items}


def _apply(client, stack_id: str, vlan_id: str, ip, prefix):
    return client.put(f"/api/v1/device-stacks/{stack_id}/vlans/{vlan_id}", json={"ip_address": ip, "prefix_length": prefix})


def _item(data: dict, vlan_id: str) -> dict:
    return next(x for x in data["items"] if x["vlan_id"] == vlan_id)


class TestApplySharedIp:
    def test_sets_same_ip_and_prefix_on_every_member_and_creates_missing_assignments(self, client):
        a, b, c = (_device(client, f"CL-{n}", system_name=f"fw-{n}") for n in "abc")
        stack = _stack(client, "Кластер МЭ", [a, b, c])
        v10 = _vlan(client, 10)
        # У a VLAN уже назначен (с управляющим флагом и описанием), у b и c — нет.
        _set_device_vlans(client, a["id"], [{"vlan_id": v10["id"], "ip_address": "10.0.10.2", "prefix_length": 24, "is_management": True, "description": "mgmt"}])

        r = _apply(client, stack["id"], v10["id"], "10.0.10.1", 24)

        assert r.status_code == 200, r.text
        for device in (a, b, c):
            link = _stored(client, device["id"])[v10["id"]]
            assert (link["ip_address"], link["prefix_length"]) == ("10.0.10.1", 24)
        # Флаг «Управление» и описание существующего назначения не затронуты.
        link_a = _stored(client, a["id"])[v10["id"]]
        assert (link_a["is_management"], link_a["description"]) == (True, "mgmt")
        row = _item(r.json(), v10["id"])
        assert (row["is_uniform"], row["ip_address"], row["prefix_length"], row["assigned_count"], row["member_count"]) == (True, "10.0.10.1", 24, 3, 3)

    def test_second_identical_apply_changes_nothing(self, client):
        a, b = _device(client, "CL-I-1"), _device(client, "CL-I-2")
        stack = _stack(client, "Идемпотентность", [a, b])
        v20 = _vlan(client, 20)
        assert _apply(client, stack["id"], v20["id"], "10.0.20.1", 24).status_code == 200
        before = _stored(client, a["id"])[v20["id"]]

        assert _apply(client, stack["id"], v20["id"], "10.0.20.1", 24).status_code == 200

        after = _stored(client, a["id"])[v20["id"]]
        assert (after["id"], after["updated_at"]) == (before["id"], before["updated_at"])  # нет лишнего UPDATE

    def test_does_not_touch_devices_outside_the_stack(self, client):
        a, b, outsider = _device(client, "CL-O-1"), _device(client, "CL-O-2"), _device(client, "CL-O-3")
        stack = _stack(client, "Свой стек", [a, b])
        v30 = _vlan(client, 30)
        _set_device_vlans(client, outsider["id"], [{"vlan_id": v30["id"], "ip_address": "192.168.0.9", "prefix_length": 16}])

        assert _apply(client, stack["id"], v30["id"], "10.0.30.1", 24).status_code == 200

        link = _stored(client, outsider["id"])[v30["id"]]
        assert (link["ip_address"], link["prefix_length"]) == ("192.168.0.9", 16)

    def test_empty_ip_and_prefix_clear_address_but_keep_assignments(self, client):
        a, b = _device(client, "CL-C-1"), _device(client, "CL-C-2")
        stack = _stack(client, "Очистка", [a, b])
        v40 = _vlan(client, 40)
        assert _apply(client, stack["id"], v40["id"], "10.0.40.1", 24).status_code == 200

        r = _apply(client, stack["id"], v40["id"], None, None)

        assert r.status_code == 200, r.text
        for device in (a, b):
            link = _stored(client, device["id"])[v40["id"]]
            assert (link["ip_address"], link["prefix_length"]) == (None, None)
        assert _item(r.json(), v40["id"])["is_uniform"] is True  # у обоих VLAN есть, адрес одинаково пуст

    def test_audit_entry_names_stack_vlan_and_counts(self, client):
        a, b = _device(client, "CL-A-1"), _device(client, "CL-A-2")
        stack = _stack(client, "Аудит стека", [a, b])
        v50 = _vlan(client, 50)
        assert _apply(client, stack["id"], v50["id"], "10.0.50.1", 24).status_code == 200

        audit = client.get("/api/v1/resources/audit-log?entity_type=device-stacks&limit=50").json()["items"]
        details = [x["details"] for x in audit if x["entity_id"] == stack["id"] and "Общий IP VLAN" in (x.get("details") or "")]
        assert details and "10.0.50.1/24" in details[0] and "назначено устройствам 2" in details[0]


class TestValidation:
    def test_ip_without_prefix_or_prefix_without_ip_is_rejected(self, client):
        a = _device(client, "CL-V-1")
        stack = _stack(client, "Валидация", [a])
        v = _vlan(client, 60)
        assert _apply(client, stack["id"], v["id"], "10.0.60.1", None).status_code == 422
        assert _apply(client, stack["id"], v["id"], None, 24).status_code == 422
        assert _stored(client, a["id"]) == {}  # ничего не записано

    def test_invalid_ip_and_out_of_range_prefix_are_rejected(self, client):
        a = _device(client, "CL-V-2")
        stack = _stack(client, "Валидация 2", [a])
        v = _vlan(client, 61)
        assert _apply(client, stack["id"], v["id"], "999.1.1.1", 24).status_code == 422
        assert _apply(client, stack["id"], v["id"], "10.0.61.1", 33).status_code == 422
        assert _apply(client, stack["id"], v["id"], "10.0.61.1", -1).status_code == 422

    def test_unknown_stack_unknown_vlan_and_empty_stack(self, client):
        v = _vlan(client, 62)
        assert _apply(client, "no-such-stack", v["id"], "10.0.62.1", 24).status_code == 404
        empty = _stack(client, "Пустой стек", [])
        assert _apply(client, empty["id"], v["id"], "10.0.62.1", 24).status_code == 409
        a = _device(client, "CL-V-3")
        stack = _stack(client, "Валидация 3", [a])
        assert _apply(client, stack["id"], "no-such-vlan", "10.0.62.1", 24).status_code == 404

    def test_domain_vlan_is_rejected_atomically_when_a_member_is_outside_the_domain(self, client):
        a, b = _device(client, "CL-D-1", system_name="in-domain"), _device(client, "CL-D-2", system_name="outside")
        stack = _stack(client, "Домен", [a, b])
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен ЦОД"}).json()
        assert client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": a["id"]}).status_code in (200, 201)
        v = _vlan(client, 70, domain_id=domain["id"])

        r = _apply(client, stack["id"], v["id"], "10.0.70.1", 24)

        assert r.status_code == 422
        assert "outside" in r.json()["detail"] and "in-domain" not in r.json()["detail"]
        # Атомарность: участник, входящий в домен, тоже не изменён (VLAN у него остался с пустым адресом).
        link = _stored(client, a["id"]).get(v["id"])
        assert link is None or link["ip_address"] is None


class TestListing:
    def test_reports_uniform_and_diverging_states_per_vlan(self, client):
        a, b, c = (_device(client, f"CL-L-{n}", system_name=f"sw-{n}") for n in "abc")
        stack = _stack(client, "Состояния", [a, b, c])
        v10, v20, v30 = (_vlan(client, n) for n in (10, 20, 30))
        same = {"ip_address": "10.0.10.1", "prefix_length": 24}
        # v10 — одинаковый адрес у всех; v20 — у a и b разные адреса, у c нет; v30 — у a адрес, у c без адреса, у b нет.
        _set_device_vlans(client, a["id"], [{"vlan_id": v10["id"], **same}, {"vlan_id": v20["id"], "ip_address": "10.0.20.1", "prefix_length": 24},
                                            {"vlan_id": v30["id"], "ip_address": "10.0.30.1", "prefix_length": 24}])
        _set_device_vlans(client, b["id"], [{"vlan_id": v10["id"], **same}, {"vlan_id": v20["id"], "ip_address": "10.0.20.2", "prefix_length": 24}])
        _set_device_vlans(client, c["id"], [{"vlan_id": v10["id"], **same}, {"vlan_id": v30["id"]}])

        data = client.get(f"/api/v1/device-stacks/{stack['id']}/vlans").json()

        assert [x["vlan_number"] for x in data["items"]] == [10, 20, 30]  # по номеру VLAN
        uniform, differing, partial = (_item(data, v["id"]) for v in (v10, v20, v30))
        assert (uniform["is_uniform"], uniform["ip_address"], uniform["prefix_length"]) == (True, "10.0.10.1", 24)
        assert (differing["is_uniform"], differing["ip_address"], differing["prefix_length"], differing["assigned_count"]) == (False, None, None, 2)
        assert [m["assigned"] for m in differing["members"]] == [True, True, False]
        assert [m["device_name"] for m in differing["members"]] == ["sw-a", "sw-b", "sw-c"]
        assert (partial["is_uniform"], partial["ip_address"], partial["assigned_count"], partial["member_count"]) == (False, None, 2, 3)

    def test_partial_state_with_agreed_value_prefills_it_for_completing_the_rest(self, client):
        a, b = _device(client, "CL-P-1"), _device(client, "CL-P-2")
        stack = _stack(client, "Частично", [a, b])
        v = _vlan(client, 80)
        _set_device_vlans(client, a["id"], [{"vlan_id": v["id"], "ip_address": "10.0.80.1", "prefix_length": 24}])

        row = _item(client.get(f"/api/v1/device-stacks/{stack['id']}/vlans").json(), v["id"])

        assert (row["is_uniform"], row["ip_address"], row["prefix_length"], row["assigned_count"]) == (False, "10.0.80.1", 24, 1)

    def test_available_lists_unassigned_vlans_assignable_to_every_member(self, client):
        a, b = _device(client, "CL-AV-1"), _device(client, "CL-AV-2")
        stack = _stack(client, "Доступные", [a, b])
        free = _vlan(client, 90)
        taken = _vlan(client, 91)
        foreign_domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Чужой домен"}).json()
        foreign = _vlan(client, 92, domain_id=foreign_domain["id"])  # в домене нет участников стека
        _set_device_vlans(client, a["id"], [{"vlan_id": taken["id"]}])

        data = client.get(f"/api/v1/device-stacks/{stack['id']}/vlans").json()

        available = {x["vlan_id"] for x in data["available"]}
        assert free["id"] in available
        assert taken["id"] not in available and foreign["id"] not in available

    def test_empty_stack_and_unknown_stack(self, client):
        empty = _stack(client, "Пустой для списка", [])
        assert client.get(f"/api/v1/device-stacks/{empty['id']}/vlans").json() == {"items": [], "available": []}
        assert client.get("/api/v1/device-stacks/no-such-stack/vlans").status_code == 404
