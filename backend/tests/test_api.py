"""
Интеграционные тесты HTTP-слоя: fastapi.testclient.TestClient поверх реальной SQLAlchemy-сессии
на in-memory SQLite (см. conftest.py). Раньше этот слой (api/*.py + services/crud.py) не был
покрыт тестами вовсе — существовавшие тесты проверяли только форматирование Excel-отчёта на
облегчённом моке ORM (mock_sqlalchemy.py), без реальных запросов, FK-констрейнтов, конфликтов
409 и т.п.

Запуск:  pip install -r backend/requirements-dev.txt && pytest backend/tests/test_api.py -v
"""
from __future__ import annotations

from app.config import REPORT_DIR


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


class TestNPlusOneRegressions:
    """Закрепляет количество SQL-запросов к конкретным таблицам там, где раньше был N+1 (см.
    историю коммита e068add) — если кто-то случайно вернёт запрос внутрь цикла, эти тесты упадут
    сразу на маленьком наборе данных, а не когда это станет заметно на реальном объёме."""

    def test_sync_interfaces_allowed_vlan_lookup_does_not_scale_with_port_count(self, client, sql_log):
        dt = client.post("/api/v1/resources/device-types", json={"name": "Тип для подсчёта запросов"}).json()
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "QC-1"}).json()

        sql_log.clear()
        payload = {"interfaces": [{"name": f"eth{i}"} for i in range(10)]}
        r = client.put(f"/api/v1/devices/{dev['id']}/interfaces", json=payload)
        assert r.status_code == 200, r.text

        vlan_lookup_queries = [s for s in sql_log if "device_type_vlans" in s or "physical_device_vlans" in s]
        # Раньше — 2 запроса НА КАЖДЫЙ интерфейс (было бы 20 для 10 портов); теперь — 2 на весь вызов.
        assert len(vlan_lookup_queries) <= 2, f"Ожидалось <=2 запроса к allowed-VLAN, получено {len(vlan_lookup_queries)}"

    def test_sync_vlan_domain_does_not_query_per_device_per_vlan_pair(self, client, sql_log):
        dt = client.post("/api/v1/resources/device-types", json={"name": "Тип для домена подсчёта"}).json()
        source = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "QC-SRC"}).json()
        members = [
            client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": f"QC-M{i}"}).json()
            for i in range(5)
        ]
        domain = client.post(
            "/api/v1/resources/vlan-domains", json={"name": "Домен подсчёта", "source_device_id": source["id"]}
        ).json()
        for dev in [source, *members]:
            r = client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": dev["id"]})
            assert r.status_code == 200, r.text
        vlans = [
            client.post("/api/v1/resources/vlans", json={"vlan_id": 900 + i, "name": f"Домен-{i}"}).json()
            for i in range(3)
        ]
        for vlan in vlans:
            r = client.post(
                "/api/v1/resources/device-vlans", json={"physical_device_id": source["id"], "vlan_id": vlan["id"]}
            )
            assert r.status_code == 201, r.text

        sql_log.clear()
        r = client.post(f"/api/v1/vlan-domains/{domain['id']}/sync")
        assert r.status_code == 200, r.text

        vlan_select_queries = [s for s in sql_log if s.strip().upper().startswith("SELECT") and "vlans" in s.lower()]
        # 5 участников x 3 VLAN = 15 пар устройство/VLAN; раньше на каждую пару был отдельный
        # SELECT (было бы >=15). Теперь домен-локальные VLAN и назначения участников загружаются
        # пакетно один раз каждое — независимо от числа пар.
        assert len(vlan_select_queries) < 15, f"Ожидалось < 15 SELECT к VLAN-таблицам, получено {len(vlan_select_queries)}"


class TestBulkVlanAssign:
    def _setup(self, client, n_devices=3):
        dt = client.post("/api/v1/resources/device-types", json={"name": "Тип для bulk-VLAN"}).json()
        devices = [
            client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": f"BULK-{i}"}).json()
            for i in range(n_devices)
        ]
        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 88, "name": "Bulk"}).json()
        return devices, vlan

    def test_assigns_vlan_to_every_listed_device(self, client):
        devices, vlan = self._setup(client)
        r = client.post(
            "/api/v1/device-vlans/bulk-assign",
            json={"physical_device_ids": [d["id"] for d in devices], "vlan_id": vlan["id"], "description": "Тест"},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "ok", "assigned": 3, "skipped_existing": 0}
        for d in devices:
            r = client.get(f"/api/v1/resources/device-vlans?physical_device_id={d['id']}")
            assert any(x["vlan_id"] == vlan["id"] for x in r.json()["items"])

    def test_skips_devices_already_assigned_and_is_idempotent(self, client):
        devices, vlan = self._setup(client, n_devices=2)
        client.post(
            "/api/v1/resources/device-vlans",
            json={"physical_device_id": devices[0]["id"], "vlan_id": vlan["id"]},
        )
        r = client.post(
            "/api/v1/device-vlans/bulk-assign",
            json={"physical_device_ids": [d["id"] for d in devices], "vlan_id": vlan["id"]},
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "ok", "assigned": 1, "skipped_existing": 1}

        # Повторный вызов с теми же устройствами больше ничего не добавляет.
        r2 = client.post(
            "/api/v1/device-vlans/bulk-assign",
            json={"physical_device_ids": [d["id"] for d in devices], "vlan_id": vlan["id"]},
        )
        assert r2.json() == {"status": "ok", "assigned": 0, "skipped_existing": 2}

    def test_rejects_empty_device_list(self, client):
        _, vlan = self._setup(client, n_devices=0)
        r = client.post("/api/v1/device-vlans/bulk-assign", json={"physical_device_ids": [], "vlan_id": vlan["id"]})
        assert r.status_code == 422

    def test_rejects_unknown_vlan(self, client):
        devices, _ = self._setup(client, n_devices=1)
        r = client.post(
            "/api/v1/device-vlans/bulk-assign",
            json={"physical_device_ids": [devices[0]["id"]], "vlan_id": "не-существует"},
        )
        assert r.status_code == 404

    def test_rejects_unknown_device(self, client):
        _, vlan = self._setup(client, n_devices=0)
        r = client.post(
            "/api/v1/device-vlans/bulk-assign",
            json={"physical_device_ids": ["не-существует"], "vlan_id": vlan["id"]},
        )
        assert r.status_code == 404


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


class TestGlobalSearchTextIndex:
    """globalSearch() во фронтенде опирается на то, что q= находит IP-адрес в этих 4 таблицах
    (is-ips/is-sources/device-vlans/open-ports) — до этого сквозной поиск их не покрывал вовсе,
    IP из этих таблиц приходилось искать вручную по разделам."""

    def test_is_ip_searchable_by_address(self, client):
        is_ = client.post("/api/v1/resources/information-systems", json={"name": "ИС для поиска IP"}).json()
        r = client.post(
            "/api/v1/resources/is-ips",
            json={"information_system_id": is_["id"], "ip_address": "10.20.30.40"},
        )
        assert r.status_code == 201, r.text
        r = client.get("/api/v1/resources/is-ips?q=10.20.30.40")
        assert r.status_code == 200
        assert any(x["ip_address"] == "10.20.30.40" for x in r.json()["items"])

    def test_is_source_searchable_by_address(self, client):
        is_ = client.post("/api/v1/resources/information-systems", json={"name": "ИС-источник для поиска"}).json()
        r = client.post(
            "/api/v1/resources/is-sources",
            json={"information_system_id": is_["id"], "source_type": "manual", "ip_address": "10.20.30.41"},
        )
        assert r.status_code == 201, r.text
        r = client.get("/api/v1/resources/is-sources?q=10.20.30.41")
        assert r.status_code == 200
        assert any(x["ip_address"] == "10.20.30.41" for x in r.json()["items"])

    def test_device_vlan_ip_searchable_by_address(self, client):
        dt = client.post("/api/v1/resources/device-types", json={"name": "Тип для поиска VLAN-IP"}).json()
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SRCH-1"}).json()
        vlan = client.post("/api/v1/resources/vlans", json={"vlan_id": 77, "name": "Поиск"}).json()
        r = client.post(
            "/api/v1/resources/device-vlans",
            json={"physical_device_id": dev["id"], "vlan_id": vlan["id"], "ip_address": "10.20.30.42"},
        )
        assert r.status_code == 201, r.text
        r = client.get("/api/v1/resources/device-vlans?q=10.20.30.42")
        assert r.status_code == 200
        assert any(x["ip_address"] == "10.20.30.42" for x in r.json()["items"])

    def test_open_port_ip_searchable_by_address(self, client):
        dt = client.post("/api/v1/resources/device-types", json={"name": "Тип для поиска порта"}).json()
        dev = client.post("/api/v1/resources/devices", json={"device_type_id": dt["id"], "serial_number": "SRCH-2"}).json()
        r = client.post(
            "/api/v1/resources/open-ports",
            json={"owner_type": "physical_device", "owner_id": dev["id"], "port": 443, "ip_address": "10.20.30.43"},
        )
        assert r.status_code == 201, r.text
        r = client.get("/api/v1/resources/open-ports?q=10.20.30.43")
        assert r.status_code == 200
        assert any(x["ip_address"] == "10.20.30.43" for x in r.json()["items"])


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

    def test_audit_log_filters_by_entity_type_and_date_range(self, client):
        r = client.post("/api/v1/resources/manufacturers", json={"name": "Фильтр-тест"})
        assert r.status_code == 201, r.text

        # entity_type — уже работающий generic equality-фильтр (не новый код), но здесь
        # это регрессия для комбинации с date_from/date_to.
        r = client.get("/api/v1/resources/audit-log?entity_type=manufacturers&limit=300")
        assert r.status_code == 200
        assert all(x["entity_type"] == "manufacturers" for x in r.json()["items"])

        far_future = "2999-01-01"
        r = client.get(f"/api/v1/resources/audit-log?date_from={far_future}")
        assert r.status_code == 200
        assert r.json()["items"] == []

        far_past = "1970-01-01"
        r = client.get(f"/api/v1/resources/audit-log?date_from={far_past}&date_to={far_future}")
        assert r.status_code == 200
        assert len(r.json()["items"]) >= 1

        # date_to без времени должен включать весь день (до 23:59:59), а не исключать его целиком.
        today = client.get("/api/v1/resources/audit-log?limit=1").json()["items"][0]["created_at"][:10]
        r = client.get(f"/api/v1/resources/audit-log?date_from={today}&date_to={today}")
        assert r.status_code == 200
        assert len(r.json()["items"]) >= 1

    def test_audit_log_rejects_invalid_date(self, client):
        r = client.get("/api/v1/resources/audit-log?date_from=не-дата")
        assert r.status_code == 422


class TestReportTemplateVersions:
    VALID_CONFIG = {"sheets": [{
        "title": "Лист1", "root_entity": "information-systems",
        "columns": [{"header": "Наименование", "source": "field", "path": "name"}],
    }]}

    def _create(self, client, name="Шаблон версий"):
        r = client.post("/api/v1/report-templates", json={"name": name, "config": self.VALID_CONFIG})
        assert r.status_code == 201, r.text
        return r.json()

    def test_new_template_has_no_version_history(self, client):
        t = self._create(client)
        r = client.get(f"/api/v1/report-templates/{t['id']}/versions")
        assert r.status_code == 200
        assert r.json() == []

    def test_update_snapshots_previous_state_before_overwriting(self, client):
        t = self._create(client, "Шаблон А")
        r = client.put(
            f"/api/v1/report-templates/{t['id']}",
            json={"name": "Шаблон А (переименован)", "config": self.VALID_CONFIG},
        )
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Шаблон А (переименован)"

        r = client.get(f"/api/v1/report-templates/{t['id']}/versions")
        assert r.status_code == 200
        versions = r.json()
        assert len(versions) == 1
        assert versions[0]["version_number"] == 1
        assert versions[0]["name"] == "Шаблон А"  # снимок ДО переименования, не после

    def test_multiple_updates_number_versions_sequentially(self, client):
        t = self._create(client, "Версия 0")
        for name in ("Версия 1", "Версия 2", "Версия 3"):
            r = client.put(f"/api/v1/report-templates/{t['id']}", json={"name": name, "config": self.VALID_CONFIG})
            assert r.status_code == 200, r.text
        versions = client.get(f"/api/v1/report-templates/{t['id']}/versions").json()
        assert [v["version_number"] for v in versions] == [3, 2, 1]  # новые сверху
        assert [v["name"] for v in versions] == ["Версия 2", "Версия 1", "Версия 0"]

    def test_restore_reverts_config_and_is_itself_reversible(self, client):
        t = self._create(client, "Оригинал")
        client.put(f"/api/v1/report-templates/{t['id']}", json={"name": "Изменено", "config": self.VALID_CONFIG})
        versions = client.get(f"/api/v1/report-templates/{t['id']}/versions").json()
        original_version_id = versions[0]["id"]  # снимок "Оригинал"

        r = client.post(f"/api/v1/report-templates/{t['id']}/versions/{original_version_id}/restore")
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "Оригинал"

        # Восстановление тоже создаёт снимок — состояние "Изменено" не потеряно безвозвратно.
        versions_after = client.get(f"/api/v1/report-templates/{t['id']}/versions").json()
        assert len(versions_after) == 2
        assert versions_after[0]["name"] == "Изменено"

    def test_restore_rejects_name_collision_with_another_template(self, client):
        t = self._create(client, "Шаблон Б исходное имя")
        client.put(f"/api/v1/report-templates/{t['id']}", json={"name": "Шаблон Б", "config": self.VALID_CONFIG})
        version_id = client.get(f"/api/v1/report-templates/{t['id']}/versions").json()[0]["id"]
        self._create(client, "Шаблон Б исходное имя")  # занимает старое имя другим шаблоном

        r = client.post(f"/api/v1/report-templates/{t['id']}/versions/{version_id}/restore")
        assert r.status_code == 409

    def test_delete_template_cascades_version_history(self, client):
        t = self._create(client, "На удаление")
        client.put(f"/api/v1/report-templates/{t['id']}", json={"name": "На удаление v2", "config": self.VALID_CONFIG})
        assert len(client.get(f"/api/v1/report-templates/{t['id']}/versions").json()) == 1

        r = client.delete(f"/api/v1/report-templates/{t['id']}")
        assert r.status_code == 200, r.text
        assert client.get(f"/api/v1/report-templates/{t['id']}/versions").status_code == 404


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

    def test_generate_and_download_audit_log_report(self, client):
        client.post("/api/v1/resources/manufacturers", json={"name": "Для экспорта аудита"})

        r = client.post("/api/v1/reports/audit-log")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["file_name"].endswith(".xlsx")

        r2 = client.get(body["download_url"])
        assert r2.status_code == 200
        assert r2.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    def test_audit_log_report_respects_filters(self, client):
        client.post("/api/v1/resources/manufacturers", json={"name": "Останется за пределами фильтра"})

        r = client.post("/api/v1/reports/audit-log", params={"date_from": "2999-01-01"})
        assert r.status_code == 200, r.text

        import openpyxl
        path = REPORT_DIR / r.json()["file_name"]
        wb = openpyxl.load_workbook(path)
        ws = wb.active
        # Только заголовок — ни одна запись не попадает в диапазон дат из будущего.
        assert ws.max_row == 1
