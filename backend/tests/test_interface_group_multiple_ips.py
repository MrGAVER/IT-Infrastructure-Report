"""Несколько общих IP-адресов у группы портов: payload['groups'][i]['ips'] (models.InterfaceGroupIP).

Группа с хотя бы одним IP управляет IP-адресами портов ПОЛНЫМ списком (как открытыми портами и подинтерфейсами):
каждому порту группы записываются все её адреса, лишние IP порта удаляются. Запись порта обновляется на месте,
пока совпадает смысл строки (адрес + префикс) или есть свободная запись, — id и дата создания сохраняются.

Запуск: pytest backend/tests/test_interface_group_multiple_ips.py -v
"""

from __future__ import annotations

import pytest

from test_interface_groups import API, _device, _ips, _port, _stored_interfaces, _sync

_IPS = [
    {"ip_address": "10.0.0.5", "prefix_length": 24, "purpose": "Управление"},
    {"ip_address": "10.0.1.5", "prefix_length": 24, "purpose": "Данные"},
]


def _group(key: str = "g1", **extra) -> dict:
    return {"key": key, "name": "Серверные", "ips": _IPS, **extra}


def _port_ips(client, dev: dict, name: str) -> list[tuple]:
    iface = _stored_interfaces(client, dev["id"])[name]
    return sorted((i["ip_address"], i["prefix_length"], i["purpose"]) for i in _ips(client, iface["id"]))


def test_every_ip_of_group_is_written_into_every_member_port(client):
    dev = _device(client, serial="SW-MIPS-1")

    r = _sync(client, dev["id"], [_port("Gi0/1", "g1"), _port("Gi0/2", "g1"), _port("Gi0/3")], [_group()])

    assert r.status_code == 200, r.text
    (group,) = r.json()["groups"]
    assert [(i["ip_address"], i["prefix_length"], i["purpose"]) for i in group["ips"]] == [
        ("10.0.0.5", 24, "Управление"),
        ("10.0.1.5", 24, "Данные"),
    ]
    expected = [("10.0.0.5", 24, "Управление"), ("10.0.1.5", 24, "Данные")]
    assert _port_ips(client, dev, "Gi0/1") == expected
    assert _port_ips(client, dev, "Gi0/2") == expected
    assert _port_ips(client, dev, "Gi0/3") == []  # порт вне группы не затронут


def test_group_ips_replace_own_ips_of_port_and_keep_row_ids_in_place(client):
    dev = _device(client, serial="SW-MIPS-2")
    own = [{"ip_address": "10.0.0.5", "prefix_length": 24, "purpose": "Своё"}, {"ip_address": "192.168.9.9", "prefix_length": 24}]
    _sync(client, dev["id"], [_port("Gi0/1", ips=own)], None)
    before = {i["ip_address"]: i["id"] for i in _ips(client, _stored_interfaces(client, dev["id"])["Gi0/1"]["id"])}
    iface = _stored_interfaces(client, dev["id"])["Gi0/1"]

    r = _sync(
        client,
        dev["id"],
        [
            {
                "id": iface["id"],
                "name": "Gi0/1",
                "group_key": "g1",
                "ips": [{"id": v, "ip_address": k, "prefix_length": 24} for k, v in before.items()],
            }
        ],
        [_group()],
    )

    assert r.status_code == 200, r.text
    after = {i["ip_address"]: i["id"] for i in _ips(client, iface["id"])}
    assert set(after) == {"10.0.0.5", "10.0.1.5"}  # собственный 192.168.9.9 заменён вторым IP группы
    assert after["10.0.0.5"] == before["10.0.0.5"]  # совпавший по смыслу IP остался той же записью
    assert after["10.0.1.5"] == before["192.168.9.9"]  # лишняя запись порта переиспользована под новый IP группы


def test_removing_ip_from_group_removes_it_from_member_ports(client):
    dev = _device(client, serial="SW-MIPS-3")
    (group,) = _sync(client, dev["id"], [_port("Gi0/1", "g1")], [_group()]).json()["groups"]

    r = _sync(client, dev["id"], [_port("Gi0/1", group["id"])], [{**_group(group["id"]), "id": group["id"], "ips": [group["ips"][0]]}])

    assert r.status_code == 200, r.text
    assert [i["ip_address"] for i in r.json()["groups"][0]["ips"]] == ["10.0.0.5"]
    assert _port_ips(client, dev, "Gi0/1") == [("10.0.0.5", 24, "Управление")]


def test_group_without_ips_does_not_touch_ips_of_member_ports(client):
    dev = _device(client, serial="SW-MIPS-4")
    own = [{"ip_address": "192.168.1.9", "prefix_length": 24, "purpose": "Своё"}]

    r = _sync(
        client, dev["id"], [_port("Gi0/1", "g1", ips=own)], [_group(ips=[{"ip_address": "  ", "prefix_length": ""}])]
    )  # пустой плейсхолдер формы

    assert r.status_code == 200, r.text
    assert r.json()["groups"][0]["ips"] == []
    assert _port_ips(client, dev, "Gi0/1") == [("192.168.1.9", 24, "Своё")]


def test_purpose_is_trimmed_and_blank_purpose_is_stored_as_null(client):
    dev = _device(client, serial="SW-MIPS-5")

    r = _sync(
        client,
        dev["id"],
        [_port("Gi0/1", "g1")],
        [_group(ips=[{"ip_address": "10.0.0.5", "purpose": "  Доступ  "}, {"ip_address": "10.0.1.5", "purpose": "   "}])],
    )

    assert r.status_code == 200, r.text
    assert sorted((i["ip_address"], i["purpose"]) for i in r.json()["groups"][0]["ips"]) == [("10.0.0.5", "Доступ"), ("10.0.1.5", None)]


@pytest.mark.parametrize(
    "ips, expected",
    [
        ([{"ip_address": "10.0.0.5"}, {"ip_address": "999.1.1.1"}], "IP-адрес"),
        ([{"ip_address": "10.0.0.5"}, {"ip_address": "10.0.0.6", "prefix_length": 40}], "префикс"),
        ([{"ip_address": "10.0.0.5", "prefix_length": 24}, {"ip_address": "10.0.0.5", "prefix_length": 16}], "повторяться"),
        ([{"ip_address": "10.0.0.5", "purpose": "x" * 256}], "назначение"),
        ([{"ip_address": "10.0.0.5", "id": "no-such-row"}], "не принадлежит"),
        ("10.0.0.5", "массивом"),
        (["10.0.0.5"], "объектом"),
    ],
)
def test_invalid_group_ips_are_rejected_with_422_and_nothing_is_saved(client, ips, expected):
    dev = _device(client, serial="SW-MIPS-6")

    r = _sync(client, dev["id"], [_port("Gi0/1", "g1")], [_group(ips=ips)])

    assert r.status_code == 422 and expected in r.text, r.text
    assert client.get(f"{API}/devices/{dev['id']}/interface-groups").json()["items"] == []


def test_ips_of_a_group_are_listed_in_numeric_order(client):
    dev = _device(client, serial="SW-MIPS-7")

    r = _sync(client, dev["id"], [], [_group(ips=[{"ip_address": "10.0.0.10"}, {"ip_address": "10.0.0.9"}, {"ip_address": "10.0.0.100"}])])

    assert [i["ip_address"] for i in r.json()["groups"][0]["ips"]] == ["10.0.0.9", "10.0.0.10", "10.0.0.100"]


def test_deleting_device_removes_group_ips(client, db_session):
    from app.models import InterfaceGroupIP

    dev = _device(client, serial="SW-MIPS-8")
    _sync(client, dev["id"], [], [_group()])
    assert db_session.query(InterfaceGroupIP).count() == 2

    assert client.delete(f"{API}/resources/devices/{dev['id']}").status_code in (200, 204)

    assert db_session.query(InterfaceGroupIP).count() == 0


def test_dropping_group_removes_its_ips_but_keeps_values_written_into_ports(client, db_session):
    from app.models import InterfaceGroupIP

    dev = _device(client, serial="SW-MIPS-9")
    (group,) = _sync(client, dev["id"], [_port("Gi0/1", "g1")], [_group()]).json()["groups"]
    iface = _stored_interfaces(client, dev["id"])["Gi0/1"]
    kept = [
        {"id": i["id"], "ip_address": i["ip_address"], "prefix_length": i["prefix_length"], "purpose": i["purpose"]}
        for i in _ips(client, iface["id"])
    ]

    r = _sync(client, dev["id"], [{"id": iface["id"], "name": "Gi0/1", "ips": kept}], [])

    assert r.status_code == 200, r.text
    assert db_session.query(InterfaceGroupIP).count() == 0
    assert _port_ips(client, dev, "Gi0/1") == [("10.0.0.5", 24, "Управление"), ("10.0.1.5", 24, "Данные")]
