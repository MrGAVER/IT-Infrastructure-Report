"""IP-адреса и открытые порты портов устройства читаются запросом ПО УСТРОЙСТВУ, а не общим списком реестра.

Раньше форма устройства брала generic-списки `ip-addresses` и `open-ports` (owner_type = device_interface) с потолком
в 1000 записей, oldest-first, и отбирала строки своих портов на клиенте. Когда в реестре набиралось больше 1000
таких строк, строки свежих портов отрезались: форма открывалась без их IP и открытых портов, а повторное сохранение
удаляло их в БД — та же ошибка, что была с VLAN портов. GET /devices/{id}/interface-ips и /interface-open-ports
ограничены одним устройством и отдают строки в том же виде, что generic-списки.

Запуск: pytest backend/tests/test_device_scoped_loads.py -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.constants import OwnerType
from app.models import IPAddress, OpenPort, ProtocolPortCatalog

API = "/api/v1"
GENERIC_LIMIT = 1000  # потолок generic-списка, за которым строки «пропадали»


def _device(client, serial: str) -> str:
    category = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    device_type = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category}).json()["id"]
    return client.post(f"{API}/resources/devices", json={"device_type_id": device_type, "serial_number": serial}).json()["id"]


def _catalog(db_session, port: int, protocol: str) -> ProtocolPortCatalog:
    """Запись справочника «порт + протокол»: стандартные записи уже есть в БД, поэтому сначала ищем."""
    entry = db_session.scalar(select(ProtocolPortCatalog).where(ProtocolPortCatalog.port == port, ProtocolPortCatalog.protocol_type == protocol))
    if entry is None:
        entry = ProtocolPortCatalog(port=port, protocol_type=protocol)
        db_session.add(entry)
        db_session.commit()
    return entry


def _ports(client, device_id: str, names: list[str], **extra) -> dict[str, str]:
    """Создаёт порты устройства, возвращает {имя: id}."""
    response = client.put(f"{API}/devices/{device_id}/interfaces", json={"interfaces": [{"name": name, **extra.get(name, {})} for name in names]})
    assert response.status_code == 200, response.text
    return {item["name"]: item["id"] for item in response.json()["items"]}


def _get(client, device_id: str, what: str):
    return client.get(f"{API}/devices/{device_id}/{what}")


def test_ips_and_open_ports_of_the_device_come_with_their_owner_port(client, db_session):
    https, ssh = _catalog(db_session, 443, "HTTPS"), _catalog(db_session, 22, "SSH")
    device = _device(client, "SW-SCOPED-1")
    saved = client.put(
        f"{API}/devices/{device}/interfaces",
        json={
            "interfaces": [
                {
                    "name": "Gi0/1",
                    "ips": [{"ip_address": "10.0.0.1", "prefix_length": 24, "purpose": "управление"}],
                    "open_ports": [{"protocol_catalog_id": https.id, "transport_protocol": "TCP", "description": "веб"}, {"protocol_catalog_id": ssh.id}],
                },
                {"name": "Gi0/2", "ips": [{"ip_address": "10.0.0.2", "prefix_length": 24}]},
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    port_ids = {item["name"]: item["id"] for item in saved.json()["items"]}

    ips = _get(client, device, "interface-ips")
    ports = _get(client, device, "interface-open-ports")

    assert ips.status_code == 200 and ports.status_code == 200
    assert {(row["owner_id"], row["ip_address"], row["prefix_length"], row["purpose"]) for row in ips.json()["items"]} == {
        (port_ids["Gi0/1"], "10.0.0.1", 24, "управление"),
        (port_ids["Gi0/2"], "10.0.0.2", 24, None),
    }
    assert all(row["owner_type"] == "device_interface" for row in ips.json()["items"])
    # открытые порты — в виде generic-списка: с port/protocol, подставленными из справочника
    assert {(row["owner_id"], row["port"], row["protocol"], row["transport_protocol"]) for row in ports.json()["items"]} == {
        (port_ids["Gi0/1"], 443, "HTTPS", "TCP"),
        (port_ids["Gi0/1"], 22, "SSH", "TCP"),
    }
    assert {row["description"] for row in ports.json()["items"]} == {"веб", None}


def test_other_devices_and_other_owner_kinds_are_not_returned(client, db_session):
    https = _catalog(db_session, 443, "HTTPS")
    mine, theirs = _device(client, "SW-MINE"), _device(client, "SW-THEIRS")
    for device, address in ((mine, "10.1.0.1"), (theirs, "10.2.0.1")):
        saved = client.put(
            f"{API}/devices/{device}/interfaces",
            json={"interfaces": [{"name": "Gi0/1", "ips": [{"ip_address": address}], "open_ports": [{"protocol_catalog_id": https.id}]}]},
        )
        assert saved.status_code == 200, saved.text
    # строки того же вида, но у другого владельца (например, ВМ), в ответ не попадают
    db_session.add(IPAddress(owner_type=OwnerType.VIRTUAL_MACHINE, owner_id="vm-1", ip_address="10.3.0.1"))
    db_session.add(OpenPort(owner_type=OwnerType.VIRTUAL_MACHINE, owner_id="vm-1", protocol_catalog_id=https.id))
    db_session.commit()

    assert [row["ip_address"] for row in _get(client, mine, "interface-ips").json()["items"]] == ["10.1.0.1"]
    assert len(_get(client, mine, "interface-open-ports").json()["items"]) == 1
    assert [row["ip_address"] for row in _get(client, theirs, "interface-ips").json()["items"]] == ["10.2.0.1"]


def test_device_without_ports_rows_and_unknown_device(client):
    device = _device(client, "SW-EMPTY")
    _ports(client, device, ["Gi0/1"])

    assert _get(client, device, "interface-ips").json() == {"items": []}
    assert _get(client, device, "interface-open-ports").json() == {"items": []}
    for what in ("interface-ips", "interface-open-ports"):
        assert _get(client, "no-such-device", what).status_code == 404


def test_rows_beyond_the_generic_list_limit_are_still_returned(client, db_session):
    """Регрессия: 1000 старых строк реестра вытесняют строки нового устройства из generic-списка —
    запрос по устройству их отдаёт."""
    https = _catalog(db_session, 443, "HTTPS")
    old_device, new_device = _device(client, "SW-OLD"), _device(client, "SW-NEW")
    old_port = _ports(client, old_device, ["Gi0/1"])["Gi0/1"]
    new_port = _ports(client, new_device, ["Gi0/1"])["Gi0/1"]
    base = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db_session.add_all(
        [IPAddress(owner_type=OwnerType.DEVICE_INTERFACE, owner_id=old_port, ip_address=f"10.9.{i // 250}.{i % 250 + 1}", created_at=base + timedelta(seconds=i)) for i in range(GENERIC_LIMIT)]
        + [OpenPort(owner_type=OwnerType.DEVICE_INTERFACE, owner_id=old_port, protocol_catalog_id=https.id, created_at=base + timedelta(seconds=i)) for i in range(GENERIC_LIMIT)]
        + [
            IPAddress(owner_type=OwnerType.DEVICE_INTERFACE, owner_id=new_port, ip_address="10.20.0.1", created_at=base + timedelta(days=1)),
            OpenPort(owner_type=OwnerType.DEVICE_INTERFACE, owner_id=new_port, protocol_catalog_id=https.id, created_at=base + timedelta(days=1)),
        ]
    )
    db_session.commit()

    for resource in ("ip-addresses", "open-ports"):
        page = client.get(f"{API}/resources/{resource}", params={"owner_type": "device_interface", "limit": GENERIC_LIMIT}).json()
        assert all(row["owner_id"] != new_port for row in page["items"]), "предпосылка: generic-список отрезает строки нового порта"

    ips = _get(client, new_device, "interface-ips").json()["items"]
    ports = _get(client, new_device, "interface-open-ports").json()["items"]
    assert [(row["owner_id"], row["ip_address"]) for row in ips] == [(new_port, "10.20.0.1")]
    assert [(row["owner_id"], row["port"]) for row in ports] == [(new_port, 443)]
    assert len(_get(client, old_device, "interface-ips").json()["items"]) == GENERIC_LIMIT
