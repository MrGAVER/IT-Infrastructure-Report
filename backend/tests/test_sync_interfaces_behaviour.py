"""Поведение sync_interfaces / _sync_single_interface (crud/interfaces.py), зафиксированное до снижения их сложности
(код-ревью, п. 10; обе функции имели сложность 18). Тесты написаны на прежнем коде и проходят без правок после него.

Вызывается сам сервис (а не только HTTP): схемы тел запросов уже отсекают часть некорректных значений, а сервис —
последний рубеж для любого вызывающего. Запуск: pytest backend/tests/test_sync_interfaces_behaviour.py -v
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import DeviceInterface, InterfaceVLAN, IPAddress, OpenPort
from app.services.crud import sync_interfaces

API = "/api/v1"


def _device(client, serial: str = "SYNC-I-1") -> dict:
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    device_type = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    return client.post(f"{API}/resources/devices", json={"device_type_id": device_type["id"], "serial_number": serial}).json()


def _vlans_on_device(client, device: dict, *numbers: int) -> list[dict]:
    """Создаёт VLAN и назначает их устройству ОДНИМ запросом: PUT /vlans заменяет весь список VLAN устройства."""
    vlans = [client.post(f"{API}/resources/vlans", json={"vlan_id": number, "name": f"v{number}"}).json() for number in numbers]
    assert client.put(f"{API}/devices/{device['id']}/vlans", json={"vlans": [{"vlan_id": v["id"]} for v in vlans]}).status_code == 200, (
        "VLAN не назначены устройству"
    )
    return vlans


def _put(client, device_id: str, rows: list[dict], **extra):
    r = client.put(f"{API}/devices/{device_id}/interfaces", json={"interfaces": rows, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _rejected(db_session, device_id: str, payload: dict) -> HTTPException:
    with pytest.raises(HTTPException) as exc_info:
        sync_interfaces(device_id, payload, db_session)
    return exc_info.value


def _ports(db_session, device_id: str) -> list[DeviceInterface]:
    db_session.expire_all()
    return list(
        db_session.scalars(
            select(DeviceInterface).where(DeviceInterface.physical_device_id == device_id).order_by(DeviceInterface.sort_order)
        ).all()
    )


class TestInputValidation:
    def test_unknown_device_is_404(self, db_session):
        error = _rejected(db_session, "нет-такого", {"interfaces": []})
        assert error.status_code == 404 and "не найдено" in error.detail

    @pytest.mark.parametrize(
        ("payload", "fragment"),
        [
            ({"interfaces": "eth0"}, "Поле interfaces должно быть массивом"),
            ({"interfaces": [], "groups": "g"}, "Поле groups должно быть массивом"),
            ({"interfaces": ["eth0"]}, "Каждый интерфейс должен быть объектом"),
            ({"interfaces": [{"name": "a", "id": "чужой"}]}, "Интерфейс не принадлежит выбранному физическому устройству"),
            ({"interfaces": [{"name": "a", "vlan_mode": "hybrid"}]}, "vlan_mode интерфейса должно быть 'access' или 'trunk'"),
            ({"interfaces": [{"name": "a", "all_vlans": "yes"}]}, "all_vlans интерфейса должно быть true или false"),
            ({"interfaces": [{"name": "a", "vlan_mode": "access", "all_vlans": True}]}, "«Все VLAN» возможно только в режиме trunk"),
            ({"interfaces": [{"name": "a", "vlan_ids": "10"}]}, "vlan_ids интерфейса должно быть массивом"),
            ({"interfaces": [{"name": "a", "vlan_ids": ["не-разрешён"]}]}, "не разрешены для типа данного устройства"),
            ({"interfaces": [{"name": "a", "ips": "10.0.0.1"}]}, "ips интерфейса должно быть массивом"),
            (
                {"interfaces": [{"name": "a", "ips": [{"ip_address": "10.0.0.1", "id": "чужой-ip"}]}]},
                "IP не принадлежит выбранному интерфейсу",
            ),
        ],
    )
    def test_invalid_item_is_rejected_with_a_specific_message(self, client, db_session, payload, fragment):
        device = _device(client)
        error = _rejected(db_session, device["id"], payload)
        assert error.status_code == 422 and fragment in error.detail, error.detail

    def test_access_port_cannot_have_two_vlans(self, client, db_session):
        device = _device(client)
        first, second = _vlans_on_device(client, device, 10, 20)
        error = _rejected(
            db_session, device["id"], {"interfaces": [{"name": "a", "vlan_mode": "access", "vlan_ids": [first["id"], second["id"]]}]}
        )
        assert error.status_code == 422 and "не более одного VLAN" in error.detail

    def test_invalid_ipv4_is_rejected(self, client, db_session):
        device = _device(client)
        error = _rejected(db_session, device["id"], {"interfaces": [{"name": "a", "ips": [{"ip_address": "999.1.1.1"}]}]})
        assert error.status_code == 422

    def test_error_in_a_later_row_rolls_back_the_earlier_ones(self, client, db_session):
        device = _device(client)
        _put(client, device["id"], [{"name": "keep"}])
        error = _rejected(db_session, device["id"], {"interfaces": [{"name": "new-1"}, {"name": "bad", "vlan_mode": "hybrid"}]})
        assert error.status_code == 422
        assert [p.name for p in _ports(db_session, device["id"])] == ["keep"]


class TestSavedState:
    def test_vlan_mode_and_vlans_are_stored_deduplicated(self, client, db_session):
        device = _device(client)
        (vlan,) = _vlans_on_device(client, device, 10)
        _put(client, device["id"], [{"name": "t1", "vlan_mode": "trunk", "vlan_ids": [vlan["id"], vlan["id"]]}])
        (port,) = _ports(db_session, device["id"])
        links = db_session.scalars(select(InterfaceVLAN).where(InterfaceVLAN.interface_id == port.id)).all()
        assert port.vlan_mode == "trunk" and [(link.vlan_id, link.mode) for link in links] == [(vlan["id"], "trunk")]

    def test_vlan_mode_defaults_to_trunk_and_empty_vlans_clear_the_old_ones(self, client, db_session):
        device = _device(client)
        (vlan,) = _vlans_on_device(client, device, 10)
        created = _put(client, device["id"], [{"name": "p", "vlan_ids": [vlan["id"]]}])["items"][0]
        _put(client, device["id"], [{"id": created["id"], "name": "p", "vlan_ids": []}])
        (port,) = _ports(db_session, device["id"])
        assert port.vlan_mode == "trunk"
        assert db_session.scalars(select(InterfaceVLAN).where(InterfaceVLAN.interface_id == port.id)).all() == []

    def test_all_vlans_port_stores_only_the_flag_and_ignores_vlan_ids(self, client, db_session):
        device = _device(client)
        (vlan,) = _vlans_on_device(client, device, 10)
        _put(client, device["id"], [{"name": "p", "vlan_mode": "trunk", "all_vlans": True, "vlan_ids": [vlan["id"], "что-угодно"]}])
        (port,) = _ports(db_session, device["id"])
        assert port.all_vlans is True
        assert db_session.scalars(select(InterfaceVLAN).where(InterfaceVLAN.interface_id == port.id)).all() == []

    def test_ips_are_diffed_by_id_and_inherit_management_flag(self, client, db_session):
        device = _device(client)
        port = _put(
            client,
            device["id"],
            [{"name": "m", "is_management": True, "ips": [{"ip_address": "10.0.0.1", "prefix_length": 24}, {"ip_address": "10.0.0.2"}]}],
        )["items"][0]
        kept_id = next(ip["id"] for ip in port["ips"] if ip["ip_address"] == "10.0.0.1")
        result = _put(
            client,
            device["id"],
            [
                {
                    "id": port["id"],
                    "name": "m",
                    "is_management": False,
                    "ips": [{"id": kept_id, "ip_address": "10.0.0.1", "prefix_length": 25, "purpose": "mgmt"}, {"ip_address": "10.0.0.3"}],
                }
            ],
        )
        ips = {ip["ip_address"]: ip for ip in result["items"][0]["ips"]}
        assert set(ips) == {"10.0.0.1", "10.0.0.3"}  # 10.0.0.2 удалён, 10.0.0.3 добавлен
        assert ips["10.0.0.1"]["id"] == kept_id and ips["10.0.0.1"]["prefix_length"] == 25 and ips["10.0.0.1"]["purpose"] == "mgmt"
        assert all(ip["is_management"] is False for ip in ips.values())  # флаг порта проставлен всем его IP

    def test_ip_entries_without_address_are_skipped(self, client, db_session):
        device = _device(client)
        result = _put(client, device["id"], [{"name": "p", "ips": [{"prefix_length": 24}, "мусор", {"ip_address": "10.1.1.1"}]}])
        assert [ip["ip_address"] for ip in result["items"][0]["ips"]] == ["10.1.1.1"]


class TestPortSet:
    def test_order_of_the_payload_becomes_sort_order(self, client, db_session):
        device = _device(client)
        _put(client, device["id"], [{"name": "c"}, {"name": "a"}, {"name": "b"}])
        assert [(p.name, p.sort_order) for p in _ports(db_session, device["id"])] == [("c", 0), ("a", 1), ("b", 2)]

    def test_ports_missing_from_the_payload_are_deleted_with_their_ips_and_open_ports(self, client, db_session):
        device = _device(client)
        created = _put(client, device["id"], [{"name": "stay"}, {"name": "go", "ips": [{"ip_address": "10.2.2.2"}]}])["items"]
        gone = next(p for p in created if p["name"] == "go")
        stay = next(p for p in created if p["name"] == "stay")
        _put(client, device["id"], [{"id": stay["id"], "name": "stay"}])
        db_session.expire_all()
        assert [p.name for p in _ports(db_session, device["id"])] == ["stay"]
        assert db_session.scalars(select(IPAddress).where(IPAddress.owner_id == gone["id"])).all() == []
        assert db_session.scalars(select(OpenPort).where(OpenPort.owner_id == gone["id"])).all() == []

    def test_empty_list_deletes_every_port(self, client, db_session):
        device = _device(client)
        _put(client, device["id"], [{"name": "a"}, {"name": "b"}])
        _put(client, device["id"], [])
        assert _ports(db_session, device["id"]) == []

    def test_response_has_groups_and_ordered_items_with_nested_lists(self, client, db_session):
        device = _device(client)
        result = _put(client, device["id"], [{"name": "z"}, {"name": "y"}])
        assert set(result) == {"groups", "items"} and result["groups"] == []
        assert [p["name"] for p in result["items"]] == ["z", "y"]
        assert all({"ips", "open_ports", "subinterfaces"} <= set(p) for p in result["items"])

    def test_audit_entry_counts_the_synchronised_ports(self, client, db_session):
        device = _device(client)
        _put(client, device["id"], [{"name": "a"}, {"name": "b"}])
        entries = client.get(f"{API}/audit-log", params={"entity_type": "interfaces"}).json()["items"]
        assert any("Синхронизация интерфейсов: 2" in (e["details"] or "") for e in entries)
