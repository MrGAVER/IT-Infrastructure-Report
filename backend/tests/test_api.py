"""
Интеграционные тесты HTTP-слоя: fastapi.testclient.TestClient поверх реальной SQLAlchemy-сессии
на in-memory SQLite (см. conftest.py). Раньше этот слой (api/*.py + services/crud.py) не был
покрыт тестами вовсе — существовавшие тесты проверяли только форматирование Excel-отчёта на
облегчённом моке ORM (mock_sqlalchemy.py), без реальных запросов, FK-констрейнтов, конфликтов
409 и т.п.

Запуск:  pip install -r backend/requirements-dev.txt && pytest backend/tests/test_api.py -v
"""
from __future__ import annotations


def test_health(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_dashboard_counts_are_zero_on_empty_db(client):
    r = client.get("/api/v1/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert data["physical_devices"] == 0
    assert data["information_systems"] == 0


def test_resources_list_excludes_audit_log(client):
    r = client.get("/api/v1/resources")
    assert r.status_code == 200
    keys = {item["key"] for item in r.json()}
    assert "audit-log" not in keys
    assert "devices" in keys
    assert "information-systems" in keys


class TestCrudBasics:
    def test_create_get_update_delete_manufacturer(self, client):
        r = client.post("/api/v1/resources/manufacturers", json={"name": "Тест-Производитель"})
        assert r.status_code == 201, r.text
        obj = r.json()
        assert obj["name"] == "Тест-Производитель"
        item_id = obj["id"]

        r = client.get(f"/api/v1/resources/manufacturers/{item_id}")
        assert r.status_code == 200
        assert r.json()["id"] == item_id

        r = client.put(f"/api/v1/resources/manufacturers/{item_id}", json={"name": "Переименовано"})
        assert r.status_code == 200
        assert r.json()["name"] == "Переименовано"

        r = client.delete(f"/api/v1/resources/manufacturers/{item_id}")
        assert r.status_code == 200
        assert r.json()["status"] == "deleted"

        r = client.get(f"/api/v1/resources/manufacturers/{item_id}")
        assert r.status_code == 404

    def test_get_missing_resource_returns_404(self, client):
        r = client.get("/api/v1/resources/manufacturers/does-not-exist")
        assert r.status_code == 404

    def test_unknown_resource_key_returns_404(self, client):
        r = client.get("/api/v1/resources/not-a-real-resource")
        assert r.status_code == 404

    def test_list_pagination_fields_present(self, client):
        before = client.get("/api/v1/resources/manufacturers").json()["total"]
        client.post("/api/v1/resources/manufacturers", json={"name": "Тестовый производитель A"})
        client.post("/api/v1/resources/manufacturers", json={"name": "Тестовый производитель B"})
        r = client.get("/api/v1/resources/manufacturers?limit=1&offset=0")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == before + 2
        assert len(data["items"]) == 1
        assert data["limit"] == 1 and data["offset"] == 0


class TestReferentialIntegrity:
    def test_cannot_delete_device_type_referenced_by_device(self, client):
        dt = client.post("/api/v1/resources/device-types", json={"name": "Тестовый сервер А"}).json()
        dev = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": dt["id"], "serial_number": "SN-001"},
        )
        assert dev.status_code == 201, dev.text

        r = client.delete(f"/api/v1/resources/device-types/{dt['id']}")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "REFERENCED_BY_OTHER_RECORDS"

    def test_unreferenced_device_type_can_be_deleted(self, client):
        dt = client.post("/api/v1/resources/device-types", json={"name": "Неиспользуемый тип"}).json()
        r = client.delete(f"/api/v1/resources/device-types/{dt['id']}")
        assert r.status_code == 200

    def test_duplicate_system_name_requires_confirmation(self, client):
        dt = client.post("/api/v1/resources/device-types", json={"name": "Тестовый сервер А"}).json()
        first = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": dt["id"], "serial_number": "SN-100", "system_name": "srv-01"},
        )
        assert first.status_code == 201

        conflict = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": dt["id"], "serial_number": "SN-101", "system_name": "srv-01"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "DUPLICATE_SYSTEM_NAME"

        confirmed = client.post(
            "/api/v1/resources/devices",
            json={
                "device_type_id": dt["id"],
                "serial_number": "SN-101",
                "system_name": "srv-01",
                "confirm_system_name_duplicate": True,
            },
        )
        assert confirmed.status_code == 201, confirmed.text

    def test_rack_position_conflict_requires_confirmation(self, client):
        dt = client.post("/api/v1/resources/device-types", json={"name": "Тестовый сервер А"}).json()
        building = client.post("/api/v1/resources/buildings", json={"name": "Тестовый ЦОД"}).json()
        room = client.post("/api/v1/resources/rooms", json={"building_id": building["id"], "name": "Серверная"}).json()
        rack = client.post("/api/v1/resources/racks", json={"room_id": room["id"], "name": "R01"}).json()

        first = client.post(
            "/api/v1/resources/devices",
            json={
                "device_type_id": dt["id"], "serial_number": "SN-200",
                "room_id": room["id"], "rack_id": rack["id"], "rack_position": "10U",
            },
        )
        assert first.status_code == 201, first.text

        conflict = client.post(
            "/api/v1/resources/devices",
            json={
                "device_type_id": dt["id"], "serial_number": "SN-201",
                "room_id": room["id"], "rack_id": rack["id"], "rack_position": "10U",
            },
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "RACK_POSITION_OCCUPIED"


class TestInterfacesSync:
    def test_sync_interfaces_creates_and_lists_ips(self, client):
        dt = client.post("/api/v1/resources/device-types", json={"name": "Коммутатор"}).json()
        dev = client.post(
            "/api/v1/resources/devices",
            json={"device_type_id": dt["id"], "serial_number": "SW-01"},
        ).json()

        payload = {
            "interfaces": [
                {
                    "name": "Gi0/1",
                    "is_management": True,
                    "ips": [{"ip_address": "10.0.0.1", "prefix_length": 24}],
                }
            ]
        }
        r = client.put(f"/api/v1/devices/{dev['id']}/interfaces", json=payload)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "Gi0/1"
        assert items[0]["ips"][0]["ip_address"] == "10.0.0.1"

    def test_sync_interfaces_unknown_device_returns_404(self, client):
        r = client.put("/api/v1/devices/does-not-exist/interfaces", json={"interfaces": []})
        assert r.status_code == 404


class TestInformationSystemDetails:
    def test_get_details_for_missing_is_returns_404(self, client):
        r = client.get("/api/v1/resources/information-systems/does-not-exist/details")
        assert r.status_code == 404

    def test_sync_and_read_back_departments(self, client):
        info = client.post("/api/v1/resources/information-systems", json={"name": "ИС 1"}).json()
        dept = client.post("/api/v1/resources/departments", json={"name": "ИТ-отдел"}).json()

        r = client.put(
            f"/api/v1/resources/information-systems/{info['id']}/details",
            json={"departments": [{"department_id": dept["id"]}]},
        )
        assert r.status_code == 200, r.text
        assert len(r.json()["departments"]) == 1

        r = client.get(f"/api/v1/resources/information-systems/{info['id']}/details")
        assert r.status_code == 200
        assert r.json()["departments"][0]["department_id"] == dept["id"]


class TestVlanDomainSync:
    def test_sync_creates_definitions_and_assigns_to_members(self, client):
        """POST /vlan-domains/{id}/sync must propagate every source-device VLAN to every other
        member device exactly once — regression test for the N+1 refactor in api/system.py."""
        dt = client.post("/api/v1/resources/device-types", json={"name": "Коммутатор VLAN-домена"}).json()
        source = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "VD-SRC"}).json()
        member1 = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "VD-M1"}).json()
        member2 = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "VD-M2"}).json()

        domain = client.post(
            "/api/v1/resources/vlan-domains",
            json={"name": "Домен-тест", "source_device_id": source["id"]},
        ).json()
        for dev in (source, member1, member2):
            r = client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": dev["id"]})
            assert r.status_code == 200, r.text

        vlan10 = client.post("/api/v1/resources/vlans", json={"vlan_id": 10, "name": "Данные"}).json()
        vlan20 = client.post("/api/v1/resources/vlans", json={"vlan_id": 20, "name": "Управление"}).json()
        for vlan in (vlan10, vlan20):
            r = client.post(
                "/api/v1/resources/device-vlans",
                json={"physical_device_id": source["id"], "vlan_id": vlan["id"]},
            )
            assert r.status_code == 201, r.text

        r = client.post(f"/api/v1/vlan-domains/{domain['id']}/sync")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["created_definitions"] == 2  # два домен-локальных определения (VLAN 10 и 20)
        assert body["assigned"] == 4  # 2 участника (member1, member2) × 2 VLAN

        for member in (member1, member2):
            r = client.get(f"/api/v1/resources/device-vlans?physical_device_id={member['id']}")
            assert r.status_code == 200
            assigned_numbers = sorted(client.get(f"/api/v1/resources/vlans/{row['vlan_id']}").json()["vlan_id"] for row in r.json()["items"])
            assert assigned_numbers == [10, 20]

        # Re-running sync must not create duplicate definitions or duplicate assignments.
        r2 = client.post(f"/api/v1/vlan-domains/{domain['id']}/sync")
        assert r2.status_code == 200
        assert r2.json() == {"status": "ok", "created_definitions": 0, "assigned": 0}


class TestAuditLog:
    def test_audit_log_lists_most_recent_action_first(self, client):
        """GET /resources/audit-log?limit=N must return the N most recent entries (newest
        first), not the first N by insertion order — see services/crud.list_resource."""
        ids = []
        for name in ("Аудит-А", "Аудит-Б", "Аудит-В"):
            r = client.post("/api/v1/resources/manufacturers", json={"name": name})
            assert r.status_code == 201, r.text
            ids.append(r.json()["id"])

        r = client.get("/api/v1/resources/audit-log?limit=300")
        assert r.status_code == 200
        rows = r.json()["items"]
        positions = {x["entity_id"]: i for i, x in enumerate(rows) if x["entity_id"] in ids}
        assert len(positions) == 3
        # Most recently created manufacturer (last id) must appear before the earliest one.
        assert positions[ids[-1]] < positions[ids[0]]


class TestReports:
    def test_seed_endpoint_populates_catalogs(self, client):
        r = client.post("/api/v1/seed")
        assert r.status_code == 200
        assert r.json()["status"] == "seeded"

    def test_generate_and_download_inventory_report(self, client):
        r = client.post("/api/v1/reports/inventory")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["file_name"].endswith(".xlsx")

        r2 = client.get(body["download_url"])
        assert r2.status_code == 200
        assert r2.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    def test_download_report_rejects_path_traversal(self, client):
        r = client.get("/api/v1/reports/download/..%2F..%2Fetc%2Fpasswd")
        assert r.status_code in (404, 400)
