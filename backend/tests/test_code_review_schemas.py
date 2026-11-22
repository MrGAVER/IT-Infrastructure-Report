"""Тесты типизированных тел запросов синхронизации и массовых операций (код-ревью, п. 8).

Главный риск, который закрывают схемы: опечатка в имени поля («interfases») раньше молча давала пустой
список, и PUT на полный список УДАЛЯЛ все записи устройства.

Запуск: pytest backend/tests/test_code_review_schemas.py -v
"""

from __future__ import annotations

import pytest


def _device(client, serial: str = "SCH-1") -> dict:
    categories = client.get("/api/v1/resources/device-categories").json()["items"]
    device_type = client.post("/api/v1/resources/device-types", json={"name": f"Тип {serial}", "category_id": categories[0]["id"]}).json()
    r = client.post("/api/v1/resources/devices", json={"device_type_id": device_type["id"], "serial_number": serial})
    assert r.status_code == 201, r.text
    return r.json()


def _interfaces(client, device_id: str) -> list[dict]:
    return client.get(f"/api/v1/resources/interfaces?physical_device_id={device_id}").json()["items"]


def _put_interfaces(client, device_id: str, names: list[str]):
    return client.put(f"/api/v1/devices/{device_id}/interfaces", json={"interfaces": [{"name": n} for n in names]})


class TestInterfacesSync:
    def test_typo_in_field_name_is_rejected_and_data_survives(self, client):
        device = _device(client)
        assert _put_interfaces(client, device["id"], ["eth0", "eth1"]).status_code == 200
        r = client.put(f"/api/v1/devices/{device['id']}/interfaces", json={"interfases": []})
        assert r.status_code == 422
        assert "interfases" in r.text
        assert len(_interfaces(client, device["id"])) == 2  # раньше все порты были бы удалены

    def test_wrong_types_are_rejected_with_422(self, client):
        device = _device(client)
        for body in ({"interfaces": "eth0"}, {"interfaces": ["eth0"]}, {"interfaces": [], "groups": "g"}):
            assert client.put(f"/api/v1/devices/{device['id']}/interfaces", json=body).status_code == 422, body

    def test_valid_body_still_syncs_and_empty_list_still_means_delete_all(self, client):
        device = _device(client)
        assert _put_interfaces(client, device["id"], ["eth0", "eth1"]).status_code == 200
        assert {i["name"] for i in _interfaces(client, device["id"])} == {"eth0", "eth1"}
        assert client.put(f"/api/v1/devices/{device['id']}/interfaces", json={"interfaces": []}).status_code == 200
        assert _interfaces(client, device["id"]) == []

    def test_missing_groups_key_leaves_groups_untouched_while_empty_list_removes_them(self, client):
        device = _device(client)
        group = {"key": "g1", "name": "Группа 1", "vlan_mode": None, "vlan_ids": []}
        assert (
            client.put(f"/api/v1/devices/{device['id']}/interfaces", json={"groups": [group], "interfaces": [{"name": "eth0", "group_key": "g1"}]}).status_code
            == 200
        )
        groups = lambda: client.get(f"/api/v1/devices/{device['id']}/interface-groups").json()["items"]  # noqa: E731
        assert len(groups()) == 1
        assert _put_interfaces(client, device["id"], ["eth0"]).status_code == 200  # без ключа groups
        assert len(groups()) == 1
        assert client.put(f"/api/v1/devices/{device['id']}/interfaces", json={"groups": [], "interfaces": [{"name": "eth0"}]}).status_code == 200
        assert groups() == []


class TestOtherSyncBodies:
    def test_device_vlans_and_software_reject_unknown_keys(self, client):
        device = _device(client)
        assert client.put(f"/api/v1/devices/{device['id']}/vlans", json={"vlan": []}).status_code == 422
        assert client.put(f"/api/v1/devices/{device['id']}/deployed-software", json={"software": []}).status_code == 422
        assert client.put(f"/api/v1/devices/{device['id']}/vlans", json={"vlans": []}).status_code == 200
        assert client.put(f"/api/v1/devices/{device['id']}/deployed-software", json={"deployed_software": []}).status_code == 200

    def test_vm_sync_bodies_reject_unknown_keys(self, client):
        for path, key in (("open-ports", "open_ports"), ("ip-addresses", "ip_addresses"), ("deployed-software", "deployed_software")):
            r = client.put(f"/api/v1/vms/no-such-vm/{path}", json={key + "_typo": []})
            assert r.status_code == 422, path
            assert client.put(f"/api/v1/vms/no-such-vm/{path}", json={key: []}).status_code == 404, path  # тело принято, ВМ нет

    def test_bulk_assign_validates_the_envelope(self, client):
        assert client.post("/api/v1/device-vlans/bulk-assign", json={"physical_device_ids": [], "vlan_id": "x"}).status_code == 422
        assert client.post("/api/v1/device-vlans/bulk-assign", json={"physical_device_ids": "abc", "vlan_id": "x"}).status_code == 422
        assert client.post("/api/v1/device-vlans/bulk-assign", json={"physical_device_ids": ["a"], "vlan_id": "x", "extra": 1}).status_code == 422
        r = client.post("/api/v1/device-vlans/bulk-assign", json={"physical_device_ids": ["a"], "vlan_id": "нет"})
        assert r.status_code == 404  # тело корректно, VLAN не существует

    def test_vlan_copy_rejects_a_misspelled_source_key(self, client):
        target = _device(client, "CP-T")
        r = client.post(f"/api/v1/devices/{target['id']}/vlan-copy", json={"source_device": "x"})
        assert r.status_code == 422
        assert client.post(f"/api/v1/devices/{target['id']}/vlan-copy", json={}).status_code == 404

    def _domain(self, client, name: str) -> dict:
        source = _device(client, f"DOM-{name}")
        r = client.post("/api/v1/resources/vlan-domains", json={"name": name, "source_device_id": source["id"]})
        assert r.status_code == 201, r.text
        return r.json()

    def test_domain_sync_accepts_empty_body_and_replace_flag_only(self, client):
        domain = self._domain(client, "Домен схем")
        assert client.post(f"/api/v1/vlan-domains/{domain['id']}/sync", json={}).status_code == 200
        assert client.post(f"/api/v1/vlan-domains/{domain['id']}/sync", json={"replace": True}).status_code == 200
        assert client.post(f"/api/v1/vlan-domains/{domain['id']}/sync", json={"replace": "возможно"}).status_code == 422
        assert client.post(f"/api/v1/vlan-domains/{domain['id']}/sync", json={"replase": True}).status_code == 422

    def test_domain_sync_without_a_body_at_all_still_works(self, client):
        domain = self._domain(client, "Домен без тела")
        assert client.post(f"/api/v1/vlan-domains/{domain['id']}/sync").status_code == 200

    def test_members_endpoints_keep_their_404_and_check_types(self, client):
        domain = client.post("/api/v1/resources/vlan-domains", json={"name": "Домен членов"}).json()
        assert client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={}).status_code == 404
        assert client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"physical_device_id": 5}).status_code == 422
        assert client.post(f"/api/v1/vlan-domains/{domain['id']}/members", json={"device_id": "x"}).status_code == 422

    def test_stack_member_position_must_be_positive_and_defaults_to_one(self, client):
        stack = client.post("/api/v1/resources/device-stacks", json={"name": "Стек схем"}).json()
        device = _device(client, "ST-1")
        assert client.post(f"/api/v1/device-stacks/{stack['id']}/members", json={"physical_device_id": device["id"], "position": 0}).status_code == 422
        r = client.post(f"/api/v1/device-stacks/{stack['id']}/members", json={"physical_device_id": device["id"]})
        assert r.status_code == 200, r.text
        assert r.json()["position"] == 1


def test_openapi_documents_the_request_bodies():
    # HTTP-маршрут /openapi.json по умолчанию выключен (A-18) — схему берём у самого приложения.
    from app.main import app

    spec = app.openapi()
    schemas = spec["components"]["schemas"]
    for name in (
        "DeviceInterfacesSync",
        "DeviceVlansSync",
        "DeployedSoftwareSync",
        "VMOpenPortsSync",
        "VMIPAddressesSync",
        "VlanCopyRequest",
        "BulkVlanAssignRequest",
        "VLANDomainMemberRequest",
        "VLANDomainSyncRequest",
        "DeviceStackMemberRequest",
    ):
        assert name in schemas, name
        assert schemas[name].get("additionalProperties") is False, name  # extra="forbid" виден и в документации
    body = spec["paths"]["/api/v1/devices/{device_id}/interfaces"]["put"]["requestBody"]["content"]["application/json"]["schema"]
    assert body["$ref"].endswith("/DeviceInterfacesSync")


@pytest.mark.parametrize("path", ["/api/v1/devices/x/interfaces", "/api/v1/devices/x/vlans", "/api/v1/devices/x/deployed-software"])
def test_unknown_device_is_still_404_not_422_for_a_valid_body(client, path):
    body = {"interfaces": []} if path.endswith("interfaces") else {"vlans": []} if path.endswith("vlans") else {"deployed_software": []}
    assert client.put(path, json=body).status_code == 404
