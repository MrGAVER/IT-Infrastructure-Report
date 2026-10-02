"""Уникальность номеров открытых портов у одного владельца (ВМ, порт устройства, группа портов).

Правило то же, что в форме на фронтенде (frontend-vue/src/utils/openPorts.ts): повтор определяется по
НОМЕРУ порта из справочника «Протоколы и порты», а не по записи справочника — 80/HTTP и 80/HTTP-Proxy,
как и TCP 53 с UDP 53, считаются повтором (для обоих транспортов выбирается «TCP/UDP»). Проверка
серверная, чтобы запрос мимо формы (прямой вызов API, интеграция) не записал дубликаты.

Плюс диагностика уже существующих дублей: GET /api/v1/integrity/open-port-duplicates (только чтение).
"""
from __future__ import annotations

API = "/api/v1"


def _catalog(client, port: int, protocol_type: str) -> dict:
    """Запись справочника «Протоколы и порты» (часть уже засеяна по умолчанию — ищем, не создаём вслепую)."""
    existing = client.get(f"{API}/resources/protocol-port-catalog", params={"limit": 1000}).json()["items"]
    match = next((e for e in existing if e["port"] == port and e["protocol_type"] == protocol_type), None)
    if match:
        return match
    r = client.post(f"{API}/resources/protocol-port-catalog", json={"port": port, "protocol_type": protocol_type})
    assert r.status_code == 201, r.text
    return r.json()


def _device(client, serial: str = "SW-UNIQ") -> dict:
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    dt = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    return client.post(f"{API}/resources/devices", json={"device_type_id": dt["id"], "serial_number": serial}).json()


def _vm_port(client, owner_id: str, catalog_id: str, **extra):
    return client.post(
        f"{API}/resources/open-ports",
        json={"owner_type": "virtual_machine", "owner_id": owner_id, "protocol_catalog_id": catalog_id, **extra},
    )


def _put_interfaces(client, device_id: str, interfaces: list[dict], groups: list[dict] | None = None):
    body: dict = {"interfaces": interfaces}
    if groups is not None:
        body["groups"] = groups
    return client.put(f"{API}/devices/{device_id}/interfaces", json=body)


def _stored_open_ports(client, owner_type: str) -> list[dict]:
    return client.get(f"{API}/resources/open-ports", params={"owner_type": owner_type, "limit": 1000}).json()["items"]


class TestGenericOpenPorts:
    def test_second_port_with_same_number_is_rejected_even_for_another_catalog_entry(self, client):
        http = _catalog(client, 80, "HTTP")
        proxy = _catalog(client, 80, "HTTP-Proxy-Test")
        assert _vm_port(client, "vm-1", http["id"]).status_code == 201

        r = _vm_port(client, "vm-1", proxy["id"])

        assert r.status_code == 422, r.text
        assert "80" in r.json()["detail"]
        assert len(_stored_open_ports(client, "virtual_machine")) == 1

    def test_same_number_with_other_transport_is_also_a_duplicate(self, client):
        dns = _catalog(client, 53, "DNS")
        assert _vm_port(client, "vm-1", dns["id"], transport_protocol="TCP").status_code == 201

        r = _vm_port(client, "vm-1", dns["id"], transport_protocol="UDP")

        assert r.status_code == 422, r.text

    def test_distinct_numbers_and_distinct_owners_are_allowed(self, client):
        http = _catalog(client, 80, "HTTP")
        ssh = _catalog(client, 22, "SSH")
        assert _vm_port(client, "vm-1", http["id"]).status_code == 201
        assert _vm_port(client, "vm-1", ssh["id"]).status_code == 201
        assert _vm_port(client, "vm-2", http["id"]).status_code == 201  # тот же номер у ДРУГОЙ ВМ — не повтор

    def test_update_to_a_number_used_by_a_sibling_is_rejected(self, client):
        http = _catalog(client, 80, "HTTP")
        ssh = _catalog(client, 22, "SSH")
        _vm_port(client, "vm-1", http["id"])
        ssh_row = _vm_port(client, "vm-1", ssh["id"]).json()

        r = client.put(f"{API}/resources/open-ports/{ssh_row['id']}", json={"protocol_catalog_id": http["id"]})

        assert r.status_code == 422, r.text

    def test_unrelated_edit_of_a_legacy_duplicate_row_still_works(self, client, db_session):
        """Уже существующие дубликаты (до появления правила) не блокируют правку описания: проверка
        срабатывает только когда меняется сам порт или владелец."""
        from app.models import OpenPort

        http = _catalog(client, 80, "HTTP")
        proxy = _catalog(client, 80, "HTTP-Proxy-Test")
        legacy = [OpenPort(owner_type="virtual_machine", owner_id="vm-legacy", protocol_catalog_id=c["id"], transport_protocol="TCP") for c in (http, proxy)]
        db_session.add_all(legacy)
        db_session.commit()

        r = client.put(f"{API}/resources/open-ports/{legacy[0].id}", json={"description": "правка описания"})

        assert r.status_code == 200, r.text


class TestInterfaceSync:
    def test_duplicate_numbers_on_one_interface_are_rejected_and_nothing_is_saved(self, client):
        dev = _device(client)
        http = _catalog(client, 80, "HTTP")
        proxy = _catalog(client, 80, "HTTP-Proxy-Test")
        ssh = _catalog(client, 22, "SSH")

        r = _put_interfaces(client, dev["id"], [{"name": "Gi0/1", "open_ports": [{"protocol_catalog_id": http["id"]}, {"protocol_catalog_id": ssh["id"]}, {"protocol_catalog_id": proxy["id"]}]}])

        assert r.status_code == 422, r.text
        assert "Gi0/1" in r.json()["detail"] and "80" in r.json()["detail"]
        assert _stored_open_ports(client, "device_interface") == []

    def test_same_number_on_different_interfaces_is_fine(self, client):
        dev = _device(client)
        http = _catalog(client, 80, "HTTP")

        r = _put_interfaces(client, dev["id"], [{"name": "Gi0/1", "open_ports": [{"protocol_catalog_id": http["id"]}]}, {"name": "Gi0/2", "open_ports": [{"protocol_catalog_id": http["id"]}]}])

        assert r.status_code == 200, r.text
        assert len(_stored_open_ports(client, "device_interface")) == 2

    def test_placeholder_rows_without_catalog_entry_do_not_count(self, client):
        dev = _device(client)
        r = _put_interfaces(client, dev["id"], [{"name": "Gi0/1", "open_ports": [{"protocol_catalog_id": ""}, {"protocol_catalog_id": ""}]}])
        assert r.status_code == 200, r.text


class TestGroups:
    def test_group_managing_open_ports_with_duplicate_numbers_is_rejected(self, client):
        dev = _device(client)
        http = _catalog(client, 80, "HTTP")
        proxy = _catalog(client, 80, "HTTP-Proxy-Test")
        group = {"key": "g1", "name": "Серверные", "manage_open_ports": True, "open_ports": [{"protocol_catalog_id": http["id"]}, {"protocol_catalog_id": proxy["id"]}]}

        r = _put_interfaces(client, dev["id"], [{"name": "Gi0/1", "group_key": "g1"}], [group])

        assert r.status_code == 422, r.text
        assert "Серверные" in r.json()["detail"] and "80" in r.json()["detail"]
        assert client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"] == []

    def test_group_without_open_port_management_ignores_its_list(self, client):
        dev = _device(client)
        http = _catalog(client, 80, "HTTP")
        proxy = _catalog(client, 80, "HTTP-Proxy-Test")
        group = {"key": "g1", "name": "Серверные", "manage_open_ports": False, "open_ports": [{"protocol_catalog_id": http["id"]}, {"protocol_catalog_id": proxy["id"]}]}

        r = _put_interfaces(client, dev["id"], [{"name": "Gi0/1", "group_key": "g1"}], [group])

        assert r.status_code == 200, r.text


class TestDuplicatesDiagnostics:
    def _seed_legacy_duplicates(self, client, db_session):
        from app.models import InterfaceGroup, InterfaceGroupOpenPort, OpenPort, VirtualMachine

        http = _catalog(client, 80, "HTTP")
        proxy = _catalog(client, 80, "HTTP-Proxy-Test")
        ssh = _catalog(client, 22, "SSH")
        vm = VirtualMachine(name="app-server-01")
        dev = _device(client, "SW-DIAG")
        group = InterfaceGroup(physical_device_id=dev["id"], name="Серверные")
        db_session.add_all([vm, group])
        db_session.flush()
        db_session.add_all([
            OpenPort(owner_type="virtual_machine", owner_id=vm.id, protocol_catalog_id=http["id"], transport_protocol="TCP"),
            OpenPort(owner_type="virtual_machine", owner_id=vm.id, protocol_catalog_id=proxy["id"], transport_protocol="TCP"),
            OpenPort(owner_type="virtual_machine", owner_id=vm.id, protocol_catalog_id=ssh["id"], transport_protocol="TCP"),
            InterfaceGroupOpenPort(group_id=group.id, protocol_catalog_id=ssh["id"], transport_protocol="TCP"),
            InterfaceGroupOpenPort(group_id=group.id, protocol_catalog_id=ssh["id"], transport_protocol="UDP"),
        ])
        db_session.commit()
        return vm, group

    def test_reports_existing_duplicates_with_owner_names(self, client, db_session):
        vm, group = self._seed_legacy_duplicates(client, db_session)

        r = client.get(f"{API}/integrity/open-port-duplicates")

        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is False and body["total"] == 2
        by_type = {d["owner_type"]: d for d in body["duplicates"]}
        assert by_type["virtual_machine"] == {"owner_type": "virtual_machine", "owner_id": vm.id, "owner_name": "app-server-01", "port": 80, "count": 2}
        assert by_type["interface_group"]["owner_id"] == group.id
        assert by_type["interface_group"]["owner_name"] == "Серверные"
        assert (by_type["interface_group"]["port"], by_type["interface_group"]["count"]) == (22, 2)

    def test_clean_database_is_ok(self, client):
        r = client.get(f"{API}/integrity/open-port-duplicates")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "total": 0, "duplicates": []}
