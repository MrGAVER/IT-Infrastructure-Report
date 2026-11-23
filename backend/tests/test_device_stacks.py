"""
Тесты на две доработки "Инвентаризации физических устройств", связанные со стеками:

1) enrich_devices() (services/serialization.py) отдаёт stack_id/stack_name/stack_position для
   каждого устройства — на этом строится группировка строк в таблице на фронтенде
   (stores/devices.ts:groupedFiltered).
2) duplicate_system_name() (services/validation.py) не требует подтверждения дубля системного
   имени, если совпадение найдено у другого участника ТОГО ЖЕ стека (нормальная ситуация для
   стекируемого сетевого оборудования — общий hostname на весь стек).

Запуск:  pytest backend/tests/test_device_stacks.py -v
"""

from __future__ import annotations


def _create_device_type(client, name: str, **extra):
    category_id = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    return client.post("/api/v1/resources/device-types", json={"name": name, "category_id": category_id, **extra}).json()


def _create_device(client, serial_number: str, **extra):
    device_type = _create_device_type(client, f"Тип для {serial_number}")
    payload = {"device_type_id": device_type["id"], "serial_number": serial_number, **extra}
    r = client.post("/api/v1/resources/devices", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _create_stack(client, name: str):
    r = client.post("/api/v1/resources/device-stacks", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _add_stack_member(client, stack_id: str, device_id: str, position: int):
    r = client.post(f"/api/v1/device-stacks/{stack_id}/members", json={"physical_device_id": device_id, "position": position})
    assert r.status_code == 200, r.text
    return r.json()


class TestEnrichDevicesStackFields:
    def test_device_outside_any_stack_has_null_stack_fields(self, client):
        device = _create_device(client, "STK-LONE-1", system_name="lone-1")
        r = client.get("/api/v1/devices")
        assert r.status_code == 200
        item = next(d for d in r.json()["items"] if d["id"] == device["id"])
        assert item["stack_id"] is None
        assert item["stack_name"] is None
        assert item["stack_position"] is None

    def test_stack_members_carry_stack_id_name_and_position(self, client):
        stack = _create_stack(client, "Стек ядра сети")
        member_a = _create_device(client, "STK-A-1", system_name="core-sw-1")
        member_b = _create_device(client, "STK-A-2", system_name="core-sw-2")
        _add_stack_member(client, stack["id"], member_a["id"], position=1)
        _add_stack_member(client, stack["id"], member_b["id"], position=2)

        items = {d["id"]: d for d in client.get("/api/v1/devices").json()["items"]}
        assert items[member_a["id"]]["stack_id"] == stack["id"]
        assert items[member_a["id"]]["stack_name"] == "Стек ядра сети"
        assert items[member_a["id"]]["stack_position"] == 1
        assert items[member_b["id"]]["stack_position"] == 2

        # Тот же generic-листинг ресурса (используется, например, отчётами) — enrich_devices()
        # общая для обоих эндпоинтов, см. services/crud/generic.py:list_resource.
        via_resources = {d["id"]: d for d in client.get("/api/v1/resources/devices", params={"limit": 1000}).json()["items"]}
        assert via_resources[member_a["id"]]["stack_id"] == stack["id"]


class TestDuplicateSystemNameSkippedWithinStack:
    def test_same_system_name_within_same_stack_does_not_require_confirmation(self, client):
        stack = _create_stack(client, "Стек коммутаторов")
        member_a = _create_device(client, "STK-B-1", system_name="stack-sw")
        member_b = _create_device(client, "STK-B-2", system_name="stack-sw-old")
        _add_stack_member(client, stack["id"], member_a["id"], position=1)
        _add_stack_member(client, stack["id"], member_b["id"], position=2)

        # member_b переименовывается в то же системное имя, что уже носит member_a — оба состоят
        # в ОДНОМ стеке, подтверждение дубля не требуется.
        r = client.put(f"/api/v1/resources/devices/{member_b['id']}", json={"system_name": "stack-sw"})
        assert r.status_code == 200, r.text
        assert r.json()["system_name"] == "stack-sw"

    def test_same_system_name_outside_the_stack_still_requires_confirmation(self, client):
        stack = _create_stack(client, "Стек периферии")
        member = _create_device(client, "STK-C-1", system_name="edge-sw")
        _add_stack_member(client, stack["id"], member["id"], position=1)
        outsider = _create_device(client, "STK-C-OUTSIDE", system_name="edge-sw-other")

        # outsider НЕ состоит в стеке member'а — совпадение с его именем должно требовать
        # подтверждения, как для любых двух обычных устройств.
        r = client.put(f"/api/v1/resources/devices/{outsider['id']}", json={"system_name": "edge-sw"})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "DUPLICATE_SYSTEM_NAME"

    def test_same_system_name_between_two_different_stacks_still_requires_confirmation(self, client):
        stack_a = _create_stack(client, "Стек А")
        stack_b = _create_stack(client, "Стек Б")
        member_a = _create_device(client, "STK-D-1", system_name="sw-a")
        member_b = _create_device(client, "STK-D-2", system_name="sw-b")
        _add_stack_member(client, stack_a["id"], member_a["id"], position=1)
        _add_stack_member(client, stack_b["id"], member_b["id"], position=1)

        r = client.put(f"/api/v1/resources/devices/{member_b['id']}", json={"system_name": "sw-a"})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "DUPLICATE_SYSTEM_NAME"
