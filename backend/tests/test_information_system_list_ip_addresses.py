"""Список ИС (GET /api/v1/information-systems) отдаёт IP-адреса системы — для столбца «IP-адреса» на экране ИС.

Набор адресов тот же, что в столбце «IP-адреса» листа 1 регламентного отчёта (reporting._is_row_values): адреса
ручных источников и адреса связанных ВМ (у ВМ — с префиксом). Адреса связанных контейнеров и устройств сюда не входят
(у отчёта для устройств отдельный столбец — IP управления).
"""
from __future__ import annotations

API = "/api/v1"


def _system(client, name: str) -> dict:
    r = client.post(f"{API}/resources/information-systems", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _vm(client, name: str, addresses: list[tuple[str, int | None]]) -> dict:
    vm = client.post(f"{API}/resources/vms", json={"name": name}).json()
    rows = [{"ip_address": ip, "prefix_length": prefix, "purpose": None, "is_management": False} for ip, prefix in addresses]
    r = client.put(f"{API}/vms/{vm['id']}/ip-addresses", json={"ip_addresses": rows})
    assert r.status_code == 200, r.text
    return vm


def _set_sources(client, system_id: str, sources: list[dict]) -> None:
    r = client.put(f"{API}/resources/information-systems/{system_id}/details", json={"sources": sources})
    assert r.status_code == 200, r.text


def _listed(client) -> dict[str, dict]:
    r = client.get(f"{API}/information-systems")
    assert r.status_code == 200, r.text
    return {row["name"]: row for row in r.json()}


class TestInformationSystemListIpAddresses:
    def test_system_without_sources_has_an_empty_list(self, client):
        _system(client, "ИС без источников")

        row = _listed(client)["ИС без источников"]

        assert row["ip_addresses"] == []
        assert row["ip_addresses_summary"] == ""

    def test_manual_source_addresses_are_listed(self, client):
        system = _system(client, "ИС с ручными адресами")
        _set_sources(client, system["id"], [{"source_type": "manual", "ips": [{"ip_address": "10.1.1.5"}, {"ip_address": "10.1.1.6"}]}])

        row = _listed(client)["ИС с ручными адресами"]

        assert row["ip_addresses"] == ["10.1.1.5", "10.1.1.6"]
        assert row["ip_addresses_summary"] == "10.1.1.5; 10.1.1.6"

    def test_linked_vm_addresses_are_listed_with_prefix(self, client):
        system = _system(client, "ИС на ВМ")
        vm = _vm(client, "ВМ для списка ИС", [("192.168.5.10", 24), ("192.168.5.11", None)])
        _set_sources(client, system["id"], [{"source_type": "vm", "owner_id": vm["id"]}])

        row = _listed(client)["ИС на ВМ"]

        assert row["ip_addresses"] == ["192.168.5.10/24", "192.168.5.11"]

    def test_manual_and_vm_addresses_are_combined_without_duplicates_and_containers_add_nothing(self, client):
        system = _system(client, "ИС со смешанными источниками")
        vm = _vm(client, "ВМ смешанной ИС", [("172.16.0.7", 16)])
        container = client.post(f"{API}/resources/containers", json={"name": "контейнер смешанной ИС"}).json()
        _set_sources(
            client,
            system["id"],
            [
                {"source_type": "manual", "ips": [{"ip_address": "203.0.113.5"}]},
                {"source_type": "manual", "ips": [{"ip_address": "203.0.113.5"}]},
                {"source_type": "vm", "owner_id": vm["id"]},
                {"source_type": "container", "owner_id": container["id"]},
            ],
        )

        row = _listed(client)["ИС со смешанными источниками"]

        assert row["ip_addresses"] == ["203.0.113.5", "172.16.0.7/16"]
        assert row["ip_addresses_summary"] == "203.0.113.5; 172.16.0.7/16"

    def test_addresses_do_not_leak_between_systems(self, client):
        first = _system(client, "ИС А")
        _system(client, "ИС Б")
        _set_sources(client, first["id"], [{"source_type": "manual", "ips": [{"ip_address": "10.9.9.1"}]}])

        rows = _listed(client)

        assert rows["ИС А"]["ip_addresses"] == ["10.9.9.1"]
        assert rows["ИС Б"]["ip_addresses"] == []

    def test_list_keeps_system_fields_and_name_order(self, client):
        client.post(f"{API}/resources/information-systems", json={"name": "Яблоко", "siem_enabled": True})
        _system(client, "Арбуз")

        r = client.get(f"{API}/information-systems")

        assert [row["name"] for row in r.json()] == ["Арбуз", "Яблоко"]
        apple = next(row for row in r.json() if row["name"] == "Яблоко")
        assert apple["siem_enabled"] is True
        assert {"id", "purpose", "support_organization_id", "crypto_protection_enabled"} <= apple.keys()
