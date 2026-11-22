"""
A-06 (приоритет 1, код-ревью main @ b375f58): GET /api/v1/vlan-dashboard — основной источник данных экрана VLAN (frontend-vue/src/stores/vlans.ts), а на бэкенде
функцию build_vlan_dashboard не вызывал ни один тест.

Контракт ответа: `{"items": [{"vlan_id": N, "definitions": [{id, vlan_id, name, description, domain_id, domain_name, devices: [...]}]}]}`.
Один номер VLAN может иметь несколько определений (в разных доменах и локальное); группы идут по возрастанию номера, определения внутри
группы — по имени; у VLAN вне
домена domain_name — «Локальный VLAN»; к каждому определению приложены только его собственные назначения устройств (подпись устройства —
системное имя, а без него серийный номер).

Запуск: pytest backend/tests/test_vlan_dashboard.py -v
"""

from __future__ import annotations

import pytest

from app.models import VLAN, DeviceCategory, DeviceType, PhysicalDevice, PhysicalDeviceVLAN, VLANDomain

URL = "/api/v1/vlan-dashboard"
LOCAL = "Локальный VLAN"


@pytest.fixture()
def device_type(db_session):
    category = DeviceCategory(name="Сетевое оборудование")
    db_session.add(category)
    db_session.flush()
    kind = DeviceType(name="Коммутатор", category_id=category.id)
    db_session.add(kind)
    db_session.commit()
    return kind


def _device(db_session, device_type, *, system_name: str | None, serial: str) -> PhysicalDevice:
    device = PhysicalDevice(device_type_id=device_type.id, serial_number=serial, system_name=system_name)
    db_session.add(device)
    db_session.flush()
    return device


def _items(client) -> list[dict]:
    response = client.get(URL)
    assert response.status_code == 200, response.text
    return response.json()["items"]


def test_empty_database_gives_an_empty_list(client):
    assert client.get(URL).json() == {"items": []}


def test_the_same_vlan_number_keeps_separate_definitions_with_their_own_devices(client, db_session, device_type):
    domain = VLANDomain(name="Кампус")
    db_session.add(domain)
    db_session.flush()
    in_domain = VLAN(vlan_id=10, name="Серверы", description="Серверный сегмент", domain_id=domain.id)
    local = VLAN(vlan_id=10, name="Лаборатория")  # тот же номер, без домена и без описания
    unused = VLAN(vlan_id=2, name="Резерв", domain_id=domain.id)  # ни одного устройства
    db_session.add_all([in_domain, local, unused])
    core = _device(db_session, device_type, system_name="core-sw", serial="SN-CORE")
    edge = _device(db_session, device_type, system_name="  ", serial="SN-EDGE")  # имя из пробелов — подпись берётся из серийного номера
    db_session.flush()
    db_session.add_all(
        [
            PhysicalDeviceVLAN(physical_device_id=core.id, vlan_id=in_domain.id, ip_address="10.0.10.1", is_management=True),
            PhysicalDeviceVLAN(physical_device_id=edge.id, vlan_id=local.id, ip_address=None, is_management=False),
        ]
    )
    db_session.commit()

    items = _items(client)

    assert [group["vlan_id"] for group in items] == [2, 10], "группы — по возрастанию номера VLAN"
    reserve = items[0]["definitions"]
    assert [d["name"] for d in reserve] == ["Резерв"] and reserve[0]["devices"] == [], "VLAN без устройств остаётся в списке с пустым перечнем"
    assert reserve[0]["domain_name"] == "Кампус"

    labs, servers = items[1]["definitions"]  # внутри группы — по имени: «Лаборатория» раньше «Серверы»
    assert (labs["name"], labs["domain_id"], labs["domain_name"], labs["description"]) == ("Лаборатория", None, LOCAL, ""), (
        "VLAN вне домена — «Локальный VLAN», описание None → ''"
    )
    assert labs["devices"] == [{"device_id": edge.id, "device_name": "SN-EDGE", "ip_address": None, "is_management": False}]
    assert (servers["id"], servers["vlan_id"], servers["description"], servers["domain_id"], servers["domain_name"]) == (
        in_domain.id,
        10,
        "Серверный сегмент",
        domain.id,
        "Кампус",
    )
    assert servers["devices"] == [{"device_id": core.id, "device_name": "core-sw", "ip_address": "10.0.10.1", "is_management": True}]


def test_one_device_on_several_vlans_is_attached_to_each_definition(client, db_session, device_type):
    first, second = VLAN(vlan_id=20, name="Гости"), VLAN(vlan_id=30, name="Камеры")
    db_session.add_all([first, second])
    device = _device(db_session, device_type, system_name="sw-1", serial="SN-1")
    db_session.flush()
    db_session.add_all([PhysicalDeviceVLAN(physical_device_id=device.id, vlan_id=vlan.id) for vlan in (first, second)])
    db_session.commit()

    items = _items(client)

    assert [(g["vlan_id"], [d["device_name"] for d in g["definitions"][0]["devices"]]) for g in items] == [(20, ["sw-1"]), (30, ["sw-1"])]


def test_definitions_with_the_same_number_are_ordered_by_name(client, db_session):
    db_session.add_all([VLAN(vlan_id=5, name="Ь-второй"), VLAN(vlan_id=5, name="А-первый")])
    db_session.commit()

    (group,) = _items(client)

    assert [d["name"] for d in group["definitions"]] == ["А-первый", "Ь-второй"]
