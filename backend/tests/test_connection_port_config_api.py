"""Интеграционные тесты проверки конфигураций портов-соседей подключений: статус в списке
подключений, точечная смена роли порта, одобрение (в том числе пакетное) и его отзыв.

Запуск: pytest backend/tests/test_connection_port_config_api.py -v
"""
from __future__ import annotations

import pytest


def _device_type(client, name: str) -> dict:
    category_id = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    return client.post("/api/v1/resources/device-types", json={"name": name, "category_id": category_id}).json()


def _device_with_port(client, device_type_id: str, serial: str, *, management: bool = False, data: bool = False, ip: str | None = None) -> str:
    device = client.post("/api/v1/resources/devices", json={"device_type_id": device_type_id, "serial_number": serial}).json()
    port: dict = {"name": "port1", "is_management": management, "is_data_transfer": data}
    if ip:
        port["ips"] = [{"ip_address": ip}]
    response = client.put(f"/api/v1/devices/{device['id']}/interfaces", json={"interfaces": [port]})
    assert response.status_code == 200, response.text
    return response.json()["items"][0]["id"]


@pytest.fixture()
def cable(client) -> str:
    return client.post("/api/v1/resources/connection-types", json={"name": "Витая пара (тест порт-конфиг)"}).json()["id"]


@pytest.fixture()
def device_type(client) -> str:
    return _device_type(client, "Тип для проверки портов")["id"]


def _connect(client, source: str, destination: str, cable_id: str, **extra) -> dict:
    response = client.post(
        "/api/v1/resources/connections",
        json={"source_interface_id": source, "destination_interface_id": destination, "connection_type_id": cable_id, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _listed(client, connection_id: str) -> dict:
    items = client.get("/api/v1/resources/connections", params={"limit": 1000}).json()["items"]
    return next(c for c in items if c["id"] == connection_id)


def test_list_reports_roles_and_mismatch_status(client, device_type, cable):
    server_port = _device_with_port(client, device_type, "PC-01", management=True)
    switch_port = _device_with_port(client, device_type, "PC-02", data=True)
    conn = _connect(client, server_port, switch_port, cable)

    row = _listed(client, conn["id"])
    assert row["source_port_role"] == "management"
    assert row["destination_port_role"] == "data"
    assert row["port_config_status"] == "mismatch"
    assert "port_config_approved_signature" not in row


def test_matching_roles_are_ok(client, device_type, cable):
    a = _device_with_port(client, device_type, "PC-03", data=True)
    b = _device_with_port(client, device_type, "PC-04", data=True)
    assert _listed(client, _connect(client, a, b, cable)["id"])["port_config_status"] == "ok"


def test_inactive_connection_is_not_reported_as_mismatch(client, device_type, cable):
    a = _device_with_port(client, device_type, "PC-05", management=True)
    b = _device_with_port(client, device_type, "PC-06", data=True)
    conn = _connect(client, a, b, cable, is_active=False)
    assert _listed(client, conn["id"])["port_config_status"] == "ok"


def test_set_port_role_updates_only_flags_and_mirrors_ip_management_flag(client, device_type):
    port_id = _device_with_port(client, device_type, "PC-07", data=True, ip="10.20.30.40")

    response = client.put(f"/api/v1/interfaces/{port_id}/port-role", json={"is_management": True, "is_data_transfer": False})

    assert response.status_code == 200
    body = response.json()
    assert (body["is_management"], body["is_data_transfer"], body["name"]) == (True, False, "port1")
    ips = client.get("/api/v1/resources/ip-addresses", params={"owner_id": port_id}).json()["items"]
    assert [ip["is_management"] for ip in ips] == [True]


@pytest.mark.parametrize("payload", [{}, {"is_management": True}, {"is_management": "yes", "is_data_transfer": False}])
def test_set_port_role_rejects_invalid_payload(client, device_type, payload):
    port_id = _device_with_port(client, device_type, "PC-08")
    assert client.put(f"/api/v1/interfaces/{port_id}/port-role", json=payload).status_code == 422


def test_set_port_role_unknown_port_is_404(client):
    response = client.put("/api/v1/interfaces/no-such-port/port-role", json={"is_management": False, "is_data_transfer": True})
    assert response.status_code == 404


def test_aligning_a_port_removes_the_mismatch(client, device_type, cable):
    a = _device_with_port(client, device_type, "PC-09", management=True)
    b = _device_with_port(client, device_type, "PC-10", data=True)
    conn = _connect(client, a, b, cable)

    client.put(f"/api/v1/interfaces/{b}/port-role", json={"is_management": True, "is_data_transfer": False})

    assert _listed(client, conn["id"])["port_config_status"] == "ok"


def test_approve_marks_mismatch_as_approved(client, device_type, cable):
    a = _device_with_port(client, device_type, "PC-11", management=True)
    b = _device_with_port(client, device_type, "PC-12", data=True)
    conn = _connect(client, a, b, cable)

    response = client.post("/api/v1/connections/port-config/approve", json={"connection_ids": [conn["id"]]})

    assert response.status_code == 200
    assert [c["port_config_status"] for c in response.json()["items"]] == ["approved"]
    assert response.json()["skipped_ids"] == []
    assert _listed(client, conn["id"])["port_config_status"] == "approved"


def test_approval_is_dropped_when_a_port_role_changes_afterwards(client, device_type, cable):
    a = _device_with_port(client, device_type, "PC-13", management=True)
    b = _device_with_port(client, device_type, "PC-14", data=True)
    conn = _connect(client, a, b, cable)
    client.post("/api/v1/connections/port-config/approve", json={"connection_ids": [conn["id"]]})

    client.put(f"/api/v1/interfaces/{b}/port-role", json={"is_management": True, "is_data_transfer": True})

    assert _listed(client, conn["id"])["port_config_status"] == "mismatch"


def test_bulk_approve_skips_connections_without_mismatch(client, device_type, cable):
    a, b = (_device_with_port(client, device_type, f"PC-{n}", management=True) for n in (15, 16))
    c, d = _device_with_port(client, device_type, "PC-17", management=True), _device_with_port(client, device_type, "PC-18", data=True)
    same = _connect(client, a, b, cable)
    different = _connect(client, c, d, cable)

    response = client.post("/api/v1/connections/port-config/approve", json={"connection_ids": [same["id"], different["id"], different["id"]]})

    body = response.json()
    assert body["skipped_ids"] == [same["id"]]
    assert [c["id"] for c in body["items"]] == [different["id"]]


def test_approve_validates_payload_and_unknown_ids(client, device_type, cable):
    assert client.post("/api/v1/connections/port-config/approve", json={"connection_ids": []}).status_code == 422
    assert client.post("/api/v1/connections/port-config/approve", json={"connection_ids": "abc"}).status_code == 422
    assert client.post("/api/v1/connections/port-config/approve", json={"connection_ids": ["missing"]}).status_code == 404
    too_many = [f"id-{i}" for i in range(501)]
    assert client.post("/api/v1/connections/port-config/approve", json={"connection_ids": too_many}).status_code == 422


def test_revoke_returns_connection_to_mismatch(client, device_type, cable):
    a = _device_with_port(client, device_type, "PC-19", management=True)
    b = _device_with_port(client, device_type, "PC-20", data=True)
    conn = _connect(client, a, b, cable)
    client.post("/api/v1/connections/port-config/approve", json={"connection_ids": [conn["id"]]})

    response = client.delete(f"/api/v1/connections/{conn['id']}/port-config/approval")

    assert response.status_code == 200
    assert response.json()["port_config_status"] == "mismatch"
    assert client.delete("/api/v1/connections/missing/port-config/approval").status_code == 404


def test_generic_crud_cannot_write_the_approval_signature(client, device_type, cable):
    a = _device_with_port(client, device_type, "PC-21", management=True)
    b = _device_with_port(client, device_type, "PC-22", data=True)
    conn = _connect(client, a, b, cable, port_config_approved_signature="management>data")

    assert _listed(client, conn["id"])["port_config_status"] == "mismatch"
    client.put(f"/api/v1/resources/connections/{conn['id']}", json={"port_config_approved_signature": "management>data"})
    assert _listed(client, conn["id"])["port_config_status"] == "mismatch"


def test_legacy_purpose_field_from_old_clients_is_ignored(client, device_type, cable):
    a = _device_with_port(client, device_type, "PC-23", data=True)
    b = _device_with_port(client, device_type, "PC-24", data=True)
    conn = _connect(client, a, b, cable, purpose="Передача данных")
    assert "purpose" not in conn


def test_review_endpoint_lists_only_requested_status(client, device_type, cable):
    a = _device_with_port(client, device_type, "PC-25", management=True)
    b = _device_with_port(client, device_type, "PC-26", data=True)
    conn = _connect(client, a, b, cable)

    pending = client.get("/api/v1/connections/port-config").json()
    assert [c["id"] for c in pending["items"]] == [conn["id"]]
    assert pending["total"] == 1

    client.post("/api/v1/connections/port-config/approve", json={"connection_ids": [conn["id"]]})
    assert client.get("/api/v1/connections/port-config").json()["items"] == []
    assert [c["id"] for c in client.get("/api/v1/connections/port-config", params={"status": "approved"}).json()["items"]] == [conn["id"]]
    assert client.get("/api/v1/connections/port-config", params={"status": "bogus"}).status_code == 422
