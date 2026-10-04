"""Атомарная синхронизация ПО физического устройства: PUT /api/v1/devices/{id}/deployed-software.

Как и у ВМ (см. test_vm_nested_lists_sync.py): форма устройства раньше при каждом сохранении удаляла всё
ПО устройства и создавала его заново. Теперь сервер сравнивает присланный список с БД по id
(services/crud.py:_sync_owned_rows) — id и дата создания сохраняются, любая ошибка откатывает весь
запрос, а в журнал аудита попадает только реальное изменение.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog

API = "/api/v1"


def _device(client, serial: str = "SN-SW-1") -> dict:
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    device_type = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    r = client.post(f"{API}/resources/devices", json={"device_type_id": device_type["id"], "serial_number": serial})
    assert r.status_code == 201, r.text
    return r.json()


def _asset(client, name: str) -> dict:
    r = client.post(f"{API}/resources/software-assets", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _sync(client, device_id: str, rows: list[dict] | None):
    return client.put(f"{API}/devices/{device_id}/deployed-software", json={} if rows is None else {"deployed_software": rows})


def _sw(asset: dict, **extra) -> dict:
    return {"software_asset_id": asset["id"], "version": None, **extra}


def _stored(client, owner_type: str, owner_id: str) -> list[dict]:
    return client.get(f"{API}/resources/deployed-software", params={"owner_type": owner_type, "owner_id": owner_id, "limit": 1000}).json()["items"]


class TestSyncDeviceDeployedSoftware:
    def test_creates_edits_in_place_and_deletes_missing(self, client):
        device = _device(client)
        one_c, nginx, ad = _asset(client, "1С:Предприятие"), _asset(client, "nginx"), _asset(client, "Active Directory")
        first = {i["software_asset_id"]: i for i in _sync(client, device["id"], [_sw(one_c, version="8.3.20"), _sw(nginx)]).json()["items"]}
        assert len(first) == 2

        r = _sync(client, device["id"], [_sw(one_c, id=first[one_c["id"]]["id"], version="8.3.24"), _sw(ad)])

        assert r.status_code == 200, r.text
        by_asset = {i["software_asset_id"]: i for i in r.json()["items"]}
        assert sorted(by_asset) == sorted([one_c["id"], ad["id"]])
        assert by_asset[one_c["id"]]["id"] == first[one_c["id"]]["id"]
        assert by_asset[one_c["id"]]["version"] == "8.3.24"
        assert all(i["owner_type"] == "physical_device" and i["owner_id"] == device["id"] for i in by_asset.values())
        assert first[nginx["id"]]["id"] not in {i["id"] for i in _stored(client, "physical_device", device["id"])}

    def test_resave_keeps_ids_and_creation_time(self, client):
        device = _device(client)
        one_c = _asset(client, "1С:Предприятие")
        first = _sync(client, device["id"], [_sw(one_c, version="8.3.20")]).json()["items"][0]

        again = _sync(client, device["id"], [_sw(one_c, id=first["id"], version="8.3.20")]).json()["items"][0]

        assert (again["id"], again["created_at"]) == (first["id"], first["created_at"])

    def test_blank_rows_are_skipped_and_empty_list_clears(self, client):
        device = _device(client)
        one_c = _asset(client, "1С:Предприятие")

        r = _sync(client, device["id"], [_sw(one_c), {"software_asset_id": "", "version": "8.3"}])
        assert len(r.json()["items"]) == 1

        assert _sync(client, device["id"], []).json()["items"] == []
        assert _stored(client, "physical_device", device["id"]) == []

    def test_software_of_another_device_and_of_vm_is_not_touched(self, client):
        device, other = _device(client, "SN-SW-A"), _device(client, "SN-SW-B")
        vm = client.post(f"{API}/resources/vms", json={"name": "vm-sw"}).json()
        nginx = _asset(client, "nginx")
        _sync(client, other["id"], [_sw(nginx)])
        client.put(f"{API}/vms/{vm['id']}/deployed-software", json={"deployed_software": [_sw(nginx)]})

        _sync(client, device["id"], [_sw(nginx)])
        _sync(client, device["id"], [])

        assert len(_stored(client, "physical_device", other["id"])) == 1
        assert len(_stored(client, "virtual_machine", vm["id"])) == 1


class TestSyncDeviceDeployedSoftwareValidation:
    def test_unknown_asset_is_a_422_and_nothing_changes(self, client):
        device = _device(client)
        one_c = _asset(client, "1С:Предприятие")
        _sync(client, device["id"], [_sw(one_c)])

        r = _sync(client, device["id"], [{"software_asset_id": "нет-такого-актива", "version": None}])

        assert r.status_code == 422, r.text
        assert [i["software_asset_id"] for i in _stored(client, "physical_device", device["id"])] == [one_c["id"]]

    def test_too_long_version_is_rejected(self, client):
        device = _device(client)
        one_c = _asset(client, "1С:Предприятие")

        assert _sync(client, device["id"], [_sw(one_c, version="9" * 101)]).status_code == 422
        assert _stored(client, "physical_device", device["id"]) == []

    def test_foreign_id_rolls_back_and_missing_key_or_device_are_errors(self, client):
        device, other = _device(client, "SN-SW-A"), _device(client, "SN-SW-B")
        one_c, nginx = _asset(client, "1С:Предприятие"), _asset(client, "nginx")
        foreign = _sync(client, other["id"], [_sw(one_c)]).json()["items"][0]

        r = _sync(client, device["id"], [_sw(nginx), _sw(one_c, id=foreign["id"])])

        assert r.status_code == 422, r.text
        assert _stored(client, "physical_device", device["id"]) == []  # откат: nginx не создан
        assert [i["id"] for i in _stored(client, "physical_device", other["id"])] == [foreign["id"]]
        assert _sync(client, device["id"], None).status_code == 422  # не молчаливое удаление всего ПО
        assert _sync(client, "нет-такого-устройства", []).status_code == 404


class TestSyncDeviceDeployedSoftwareAudit:
    def test_audit_records_only_real_changes_under_devices_entity(self, client, db_session):
        device = _device(client)
        one_c = _asset(client, "1С:Предприятие")
        item = _sync(client, device["id"], [_sw(one_c)]).json()["items"][0]

        def entries() -> list[str]:
            rows = db_session.scalars(select(AuditLog).where(AuditLog.entity_type == "devices", AuditLog.entity_id == device["id"], AuditLog.details.like("Программные активы:%"))).all()
            return [r.details for r in rows]

        assert entries() == ["Программные активы: добавлено 1, изменено 0, удалено 0"]
        _sync(client, device["id"], [_sw(one_c, id=item["id"])])  # без правок
        assert len(entries()) == 1
        _sync(client, device["id"], [])
        assert entries()[-1] == "Программные активы: добавлено 0, изменено 0, удалено 1"
