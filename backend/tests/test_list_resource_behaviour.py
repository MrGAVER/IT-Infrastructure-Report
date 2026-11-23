"""Тесты, фиксирующие поведение list_resource до и после снижения его сложности (код-ревью, п. 10).

Функция собирает запрос из пяти независимых частей: сортировка, поиск q, фильтры по полям, диапазон дат и выбор
обогащения строк. Тесты написаны на прежнем коде и должны проходить без изменений на коде после рефакторинга.
Запуск: pytest backend/tests/test_list_resource_behaviour.py -v
"""

from __future__ import annotations

from datetime import datetime

import pytest

from app.models import AuditLog, Manufacturer
from app.services.crud import list_resource
from app.services.serialization import enrich_devices, serialize


def _vlan(client, number: int, **extra) -> dict:
    r = client.post("/api/v1/resources/vlans", json={"vlan_id": number, "name": f"v{number}", **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _device(client, serial: str) -> dict:
    categories = client.get("/api/v1/resources/device-categories").json()["items"]
    device_type = client.post("/api/v1/resources/device-types", json={"name": f"Тип {serial}", "category_id": categories[0]["id"]}).json()
    r = client.post("/api/v1/resources/devices", json={"device_type_id": device_type["id"], "serial_number": serial})
    assert r.status_code == 201, r.text
    return r.json()


class TestFilters:
    def test_unknown_filter_field_is_rejected_with_its_name(self, client):
        r = client.get("/api/v1/resources/manufacturers?no_such_field=1")
        assert r.status_code == 422
        assert "no_such_field" in r.text

    def test_equality_filter_matches_exact_value_only(self, client):
        _vlan(client, 10, description="офис")
        _vlan(client, 20, description="офис 2")
        items = client.get("/api/v1/resources/vlans?description=офис").json()["items"]
        assert [v["vlan_id"] for v in items] == [10]

    def test_empty_value_filter_means_is_null(self, client):
        _vlan(client, 10, description="есть")
        _vlan(client, 20)
        items = client.get("/api/v1/resources/vlans?description=").json()["items"]
        assert [v["vlan_id"] for v in items] == [20]

    def test_several_filters_are_combined_with_and(self, client):
        _vlan(client, 10, description="офис")
        _vlan(client, 20, description="офис")
        items = client.get("/api/v1/resources/vlans?description=офис&name=v20").json()["items"]
        assert [v["vlan_id"] for v in items] == [20]

    def test_filter_and_search_are_applied_together_and_total_counts_the_filtered_rows(self, client):
        for number in (10, 11, 12):
            _vlan(client, number, description="офис")
        _vlan(client, 13, description="склад")
        page = client.get("/api/v1/resources/vlans?description=офис&q=v1&limit=2").json()
        assert page["total"] == 3 and len(page["items"]) == 2


class TestDateRange:
    def _seed(self, db_session) -> None:
        for day, entity in ((14, "a"), (15, "b"), (16, "c")):
            db_session.add(
                AuditLog(
                    entity_type="devices", entity_id=entity, action="UPDATE", details=entity, created_at=datetime(2026, 8, day, 12, 0, 0)
                )
            )
        db_session.commit()

    def _ids(self, db_session, **kwargs) -> list[str]:
        return sorted(row["entity_id"] for row in list_resource("audit-log", db_session, offset=0, limit=100, **kwargs)["items"])

    def test_date_from_is_inclusive_from_the_start_of_the_day(self, db_session):
        self._seed(db_session)
        assert self._ids(db_session, date_from="2026-08-15") == ["b", "c"]

    def test_pure_date_to_includes_the_whole_last_day(self, db_session):
        self._seed(db_session)
        assert self._ids(db_session, date_to="2026-08-15") == ["a", "b"]

    def test_full_iso_datetime_is_taken_literally(self, db_session):
        self._seed(db_session)
        assert self._ids(db_session, date_to="2026-08-15T11:59:59") == ["a"]

    def test_range_combines_both_bounds(self, db_session):
        self._seed(db_session)
        assert self._ids(db_session, date_from="2026-08-15", date_to="2026-08-15") == ["b"]

    def test_invalid_date_is_a_422_with_the_value(self, client):
        r = client.get("/api/v1/resources/audit-log?date_from=вчера")
        assert r.status_code == 422 and "вчера" in r.text


class TestRowEnrichment:
    def test_plain_resources_are_just_serialized(self, db_session):
        db_session.add(Manufacturer(name="Plain"))
        db_session.commit()
        rows = db_session.query(Manufacturer).all()
        assert list_resource("manufacturers", db_session)["items"] == [serialize(r) for r in rows]

    def test_devices_are_enriched_not_just_serialized(self, client, db_session):
        _device(client, "ENR-1")
        from app.models import PhysicalDevice

        rows = db_session.query(PhysicalDevice).all()
        listed = list_resource("devices", db_session)["items"]
        assert listed == enrich_devices(rows, db_session)
        assert set(listed[0]) > set(serialize(rows[0]))  # у обогащённой строки есть поля сверх колонок модели

    def test_envelope_reports_total_offset_and_limit(self, db_session):
        for i in range(5):
            db_session.add(Manufacturer(name=f"M{i}"))
        db_session.commit()
        page = list_resource("manufacturers", db_session, offset=2, limit=2)
        assert (page["total"], page["offset"], page["limit"], len(page["items"])) == (5, 2, 2, 2)

    @pytest.mark.parametrize("resource", ["interfaces", "connections", "information-systems", "open-ports", "devices"])
    def test_enriched_resources_list_without_error_on_empty_tables(self, db_session, resource):
        assert list_resource(resource, db_session) == {"items": [], "total": 0, "offset": 0, "limit": 100}


# ---------------------------------------------------------------------------
# update_resource: поведение, которое нельзя потерять при снижении сложности
# ---------------------------------------------------------------------------
class TestUpdateResourceBehaviour:
    def _host(self, client, serial: str, os_id: str | None) -> dict:
        categories = client.get("/api/v1/resources/device-categories").json()["items"]
        device_type = client.post(
            "/api/v1/resources/device-types", json={"name": f"Хост {serial}", "category_id": categories[0]["id"], "allows_vm_hosting": True}
        )
        assert device_type.status_code == 201, device_type.text
        body = {"device_type_id": device_type.json()["id"], "serial_number": serial}
        if os_id:
            body["operating_system_id"] = os_id
        r = client.post("/api/v1/resources/devices", json=body)
        assert r.status_code == 201, r.text
        return r.json()

    def _hypervisor_os(self, client) -> str:
        category = client.post("/api/v1/resources/os-categories", json={"name": "Гипервизоры тест", "is_hypervisor": True}).json()
        return client.post(
            "/api/v1/resources/operating-systems", json={"category_id": category["id"], "name": "HV", "version": "1"}
        ).json()["id"]

    def test_moving_a_vm_to_another_host_updates_its_hypervisor_os(self, client):
        hv = self._hypervisor_os(client)
        with_os = self._host(client, "UPD-HV-1", hv)
        without_os = self._host(client, "UPD-HV-2", None)
        vm = client.post("/api/v1/resources/vms", json={"name": "vm-upd", "physical_device_id": with_os["id"]}).json()
        assert vm["hypervisor_os_id"] == hv
        moved = client.put(f"/api/v1/resources/vms/{vm['id']}", json={"physical_device_id": without_os["id"]})
        assert moved.status_code == 200, moved.text
        assert moved.json()["hypervisor_os_id"] is None  # у нового хоста ОС нет — значение сбрасывается
        back = client.put(f"/api/v1/resources/vms/{vm['id']}", json={"physical_device_id": with_os["id"]}).json()
        assert back["hypervisor_os_id"] == hv

    def test_editing_another_field_of_a_vm_keeps_hypervisor_os(self, client):
        hv = self._hypervisor_os(client)
        host = self._host(client, "UPD-HV-3", hv)
        vm = client.post("/api/v1/resources/vms", json={"name": "vm-keep", "physical_device_id": host["id"]}).json()
        edited = client.put(f"/api/v1/resources/vms/{vm['id']}", json={"description": "новое описание"}).json()
        assert edited["hypervisor_os_id"] == hv and edited["description"] == "новое описание"

    def test_update_of_missing_record_is_404_and_audit_records_the_change(self, client):
        assert client.put("/api/v1/resources/manufacturers/нет-такого", json={"name": "x"}).status_code == 404
        created = client.post("/api/v1/resources/manufacturers", json={"name": "Было"}).json()
        client.put(f"/api/v1/resources/manufacturers/{created['id']}", json={"name": "Стало"})
        entries = client.get("/api/v1/audit-log?entity_id=" + created["id"]).json()["items"]
        assert [e["action"] for e in entries] == ["UPDATE", "CREATE"]
        assert "Было" in entries[0]["details"] and "Стало" in entries[0]["details"]


# ---------------------------------------------------------------------------
# sync_device_vlans: проверки входа и откат (вызов сервиса напрямую — HTTP-схема уже отсекает часть некорректных тел)
# ---------------------------------------------------------------------------
class TestDeviceVlansSyncValidation:
    def _setup(self, client, db_session):
        from app.models import PhysicalDeviceVLAN  # noqa: F401  (проверка, что модель импортируется)

        device = _device(client, "SYNC-V-1")
        first = _vlan(client, 10)
        second = _vlan(client, 20)
        return device, first, second

    def _call(self, db_session, device_id, vlans):
        from fastapi import HTTPException

        from app.services.crud import sync_device_vlans

        with pytest.raises(HTTPException) as exc_info:
            sync_device_vlans(device_id, {"vlans": vlans}, db_session)
        return exc_info.value

    def _assigned(self, db_session, device_id) -> set[str]:
        from sqlalchemy import select

        from app.models import PhysicalDeviceVLAN

        db_session.expire_all()
        return set(db_session.scalars(select(PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id == device_id)).all())

    def test_item_must_be_an_object(self, client, db_session):
        device, first, _ = self._setup(client, db_session)
        error = self._call(db_session, device["id"], [first["id"]])
        assert error.status_code == 422 and "объектом" in error.detail

    def test_item_without_vlan_id_is_rejected(self, client, db_session):
        device, *_ = self._setup(client, db_session)
        error = self._call(db_session, device["id"], [{"description": "без VLAN"}])
        assert error.status_code == 422 and "vlan_id" in error.detail

    def test_same_vlan_twice_is_rejected(self, client, db_session):
        device, first, _ = self._setup(client, db_session)
        error = self._call(db_session, device["id"], [{"vlan_id": first["id"]}, {"vlan_id": first["id"]}])
        assert error.status_code == 422 and "несколько раз" in error.detail

    def test_error_in_the_middle_of_the_list_leaves_the_previous_state(self, client, db_session):
        device, first, second = self._setup(client, db_session)
        assert client.put(f"/api/v1/devices/{device['id']}/vlans", json={"vlans": [{"vlan_id": first["id"]}]}).status_code == 200
        error = self._call(db_session, device["id"], [{"vlan_id": second["id"]}, {"description": "сломанная строка"}])
        assert error.status_code == 422
        assert self._assigned(db_session, device["id"]) == {first["id"]}  # ни добавление второго, ни удаление первого не прошли

    def test_replacing_the_list_adds_updates_and_removes_in_one_call(self, client, db_session):
        device, first, second = self._setup(client, db_session)
        client.put(f"/api/v1/devices/{device['id']}/vlans", json={"vlans": [{"vlan_id": first["id"], "description": "старое"}]})
        r = client.put(f"/api/v1/devices/{device['id']}/vlans", json={"vlans": [{"vlan_id": second["id"]}]})
        assert r.status_code == 200
        assert {row["vlan_id"] for row in r.json()["items"]} == {second["id"]}
        entries = client.get("/api/v1/audit-log?entity_type=device-vlans").json()["items"]
        assert "добавлено 1, изменено 0, удалено 1" in entries[0]["details"]
