"""Перенос VLAN из одного домена в другой (PUT /resources/vlans/{id} с новым domain_id).

Раньше VLAN, перенесённый в другой домен, оставался на устройствах прежнего домена: новый домен получал
его (_auto_assign_new_domain_vlan_to_domain_devices), а старые участники — нет, хотя он им больше не
принадлежит. Следующее сохранение такого устройства упиралось в 422 «Устройство не включено в домен
этого VLAN». Теперь VLAN снимается с устройств прежнего домена, которых нет в новом, вместе со связями
с их портами и группами портов (services/crud/vlan_domains.py:_unassign_moved_vlan_from_former_domain_devices).
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog

API = "/api/v1"


def _device_type(client, name: str, *, allow_vlan: dict | None = None) -> dict:
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    device_type = client.post(f"{API}/resources/device-types", json={"name": name, "category_id": category_id}).json()
    if allow_vlan:
        client.post(f"{API}/resources/device-type-vlans", json={"device_type_id": device_type["id"], "vlan_id": allow_vlan["id"]})
    return device_type


def _device(client, device_type: dict, serial: str) -> dict:
    r = client.post(f"{API}/resources/devices", json={"device_type_id": device_type["id"], "serial_number": serial})
    assert r.status_code == 201, r.text
    return r.json()


def _domain(client, name: str, source: dict | None = None, members: tuple[dict, ...] = ()) -> dict:
    body = {"name": name, **({"source_device_id": source["id"]} if source else {})}
    domain = client.post(f"{API}/resources/vlan-domains", json=body).json()
    for device in members:
        assert client.post(f"{API}/vlan-domains/{domain['id']}/members", json={"physical_device_id": device["id"]}).status_code == 200
    return domain


def _vlan(client, number: int, domain: dict | None = None) -> dict:
    r = client.post(
        f"{API}/resources/vlans", json={"vlan_id": number, "name": f"VLAN {number}", **({"domain_id": domain["id"]} if domain else {})}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _move(client, vlan: dict, domain: dict | None):
    return client.put(f"{API}/resources/vlans/{vlan['id']}", json={"domain_id": domain["id"] if domain else None})


def _assigned(client, device: dict) -> list[str]:
    return [
        row["vlan_id"]
        for row in client.get(f"{API}/resources/device-vlans", params={"physical_device_id": device["id"], "limit": 1000}).json()["items"]
    ]


def _port(client, device: dict, name: str, vlan: dict, group_key: str | None = None) -> None:
    port = {"name": name, "vlan_mode": "access", "vlan_ids": [vlan["id"]], **({"group_key": group_key} if group_key else {})}
    groups = [{"key": group_key, "name": "Группа", "vlan_mode": "access", "vlan_ids": [vlan["id"]]}] if group_key else None
    body = {"interfaces": [port], **({"groups": groups} if groups is not None else {})}
    r = client.put(f"{API}/devices/{device['id']}/interfaces", json=body)
    assert r.status_code == 200, r.text


def _port_vlans(client, device: dict) -> list[str]:
    ports = client.get(f"{API}/resources/interfaces", params={"physical_device_id": device["id"], "limit": 1000}).json()["items"]
    links = client.get(f"{API}/resources/interface-vlans", params={"limit": 1000}).json()["items"]
    port_ids = {p["id"] for p in ports}
    return [link["vlan_id"] for link in links if link["interface_id"] in port_ids]


def _group_vlans(client, device: dict) -> list[str]:
    groups = client.get(f"{API}/devices/{device['id']}/interface-groups").json()["items"]
    return [vlan_id for group in groups for vlan_id in group["vlan_ids"]]


class TestVlanMovedBetweenDomains:
    def test_vlan_leaves_devices_of_old_domain_and_reaches_new_domain(self, client):
        dt = _device_type(client, "Тип переноса")
        old_source, old_member = _device(client, dt, "MV-SRC"), _device(client, dt, "MV-OLD")
        new_member = _device(client, dt, "MV-NEW")
        old_domain = _domain(client, "Старый домен", old_source, (old_member,))
        new_domain = _domain(client, "Новый домен", None, (new_member,))
        vlan = _vlan(client, 301, old_domain)
        assert _assigned(client, old_source) == _assigned(client, old_member) == [vlan["id"]]

        r = _move(client, vlan, new_domain)

        assert r.status_code == 200, r.text
        assert _assigned(client, old_source) == [] and _assigned(client, old_member) == []
        assert _assigned(client, new_member) == [vlan["id"]]

    def test_device_that_is_in_both_domains_keeps_the_vlan(self, client):
        dt = _device_type(client, "Тип в обоих доменах")
        shared, only_old = _device(client, dt, "MV-SHARED"), _device(client, dt, "MV-ONLYOLD")
        old_domain = _domain(client, "Старый общий", None, (shared, only_old))
        new_domain = _domain(client, "Новый общий", None, (shared,))
        vlan = _vlan(client, 302, old_domain)

        _move(client, vlan, new_domain)

        assert _assigned(client, shared) == [vlan["id"]]
        assert _assigned(client, only_old) == []

    def test_new_domain_source_is_not_stripped_even_without_membership(self, client):
        dt = _device_type(client, "Тип источника нового домена")
        old_member, new_source = _device(client, dt, "MV-OLDM"), _device(client, dt, "MV-NSRC")
        old_domain = _domain(client, "Старый для источника", None, (old_member, new_source))
        new_domain = _domain(client, "Новый с источником", new_source)
        vlan = _vlan(client, 303, old_domain)

        _move(client, vlan, new_domain)

        assert _assigned(client, new_source) == [vlan["id"]]
        assert _assigned(client, old_member) == []

    def test_other_vlans_of_the_old_domain_and_unrelated_devices_are_untouched(self, client):
        dt = _device_type(client, "Тип прочих VLAN")
        old_member, outsider = _device(client, dt, "MV-KEEP"), _device(client, dt, "MV-OUT")
        old_domain = _domain(client, "Старый для прочих", None, (old_member,))
        new_domain = _domain(client, "Новый для прочих")
        moved, stays = _vlan(client, 304, old_domain), _vlan(client, 305, old_domain)
        local = _vlan(client, 306)
        client.post(f"{API}/resources/device-vlans", json={"physical_device_id": outsider["id"], "vlan_id": local["id"]})

        _move(client, moved, new_domain)

        assert _assigned(client, old_member) == [stays["id"]]  # другой VLAN прежнего домена остался
        assert _assigned(client, outsider) == [local["id"]]  # устройство вне доменов не затронуто

    def test_ports_and_port_groups_of_former_members_lose_the_vlan_too(self, client):
        dt = _device_type(client, "Тип портов")
        former, kept = _device(client, dt, "MV-PORTS"), _device(client, dt, "MV-KEPT")
        old_domain = _domain(client, "Старый с портами", None, (former, kept))
        new_domain = _domain(client, "Новый с портами", None, (kept,))
        vlan = _vlan(client, 307, old_domain)
        _port(client, former, "Gi0/1", vlan)
        _port(client, kept, "Gi0/1", vlan, group_key="g1")
        assert _port_vlans(client, former) == [vlan["id"]]
        assert _group_vlans(client, kept) == [vlan["id"]]

        _move(client, vlan, new_domain)

        assert _port_vlans(client, former) == []
        assert _port_vlans(client, kept) == [vlan["id"]] and _group_vlans(client, kept) == [
            vlan["id"]
        ]  # устройство осталось в новом домене

    def test_group_of_former_member_loses_the_vlan(self, client):
        dt = _device_type(client, "Тип групп")
        former = _device(client, dt, "MV-GRP")
        old_domain = _domain(client, "Старый с группой", None, (former,))
        new_domain = _domain(client, "Новый без участников")
        vlan = _vlan(client, 308, old_domain)
        _port(client, former, "Gi0/1", vlan, group_key="g1")
        assert _group_vlans(client, former) == [vlan["id"]]

        _move(client, vlan, new_domain)

        assert _group_vlans(client, former) == [] and _port_vlans(client, former) == []

    def test_port_vlan_stays_when_device_type_allows_the_vlan(self, client):
        plain_type = _device_type(client, "Тип без каталога VLAN")
        vlan_holder = _vlan(client, 309)  # VLAN нужен для каталога типа до привязки к домену
        typed = _device_type(client, "Тип с каталогом VLAN", allow_vlan=vlan_holder)
        former = _device(client, typed, "MV-TYPED")
        old_domain = _domain(client, "Старый с типовым VLAN", None, (former,))
        new_domain = _domain(client, "Новый с типовым VLAN")
        assert client.put(f"{API}/resources/vlans/{vlan_holder['id']}", json={"domain_id": old_domain["id"]}).status_code == 200
        _port(client, former, "Gi0/1", vlan_holder)
        assert _assigned(client, former) == [vlan_holder["id"]]
        del plain_type

        _move(client, vlan_holder, new_domain)

        assert _assigned(client, former) == []  # назначение на устройстве снято
        assert _port_vlans(client, former) == [vlan_holder["id"]]  # порт вправе использовать VLAN из каталога типа

    def test_moving_to_no_domain_or_editing_other_fields_removes_nothing(self, client):
        dt = _device_type(client, "Тип без переноса")
        member = _device(client, dt, "MV-LOCAL")
        domain = _domain(client, "Домен без переноса", None, (member,))
        vlan = _vlan(client, 310, domain)

        assert client.put(f"{API}/resources/vlans/{vlan['id']}", json={"description": "правка описания"}).status_code == 200
        assert _assigned(client, member) == [vlan["id"]]

        assert _move(client, vlan, None).status_code == 200  # стал локальным VLAN
        assert _assigned(client, member) == [vlan["id"]]

    def test_attaching_local_vlan_to_domain_does_not_strip_other_devices(self, client):
        dt = _device_type(client, "Тип локального VLAN")
        holder, member = _device(client, dt, "MV-HOLD"), _device(client, dt, "MV-MEMB")
        domain = _domain(client, "Домен для локального", None, (member,))
        vlan = _vlan(client, 311)
        client.post(f"{API}/resources/device-vlans", json={"physical_device_id": holder["id"], "vlan_id": vlan["id"]})

        _move(client, vlan, domain)

        assert _assigned(client, holder) == [vlan["id"]]  # «прежнего домена» нет — не трогаем
        assert _assigned(client, member) == [vlan["id"]]

    def test_former_member_device_can_be_saved_after_the_move(self, client):
        dt = _device_type(client, "Тип повторного сохранения")
        former = _device(client, dt, "MV-SAVE")
        old_domain = _domain(client, "Старый для сохранения", None, (former,))
        new_domain = _domain(client, "Новый для сохранения")
        vlan = _vlan(client, 312, old_domain)
        _port(client, former, "Gi0/1", vlan)

        _move(client, vlan, new_domain)

        saved_ports = client.get(f"{API}/resources/interfaces", params={"physical_device_id": former["id"], "limit": 1000}).json()["items"]
        r = client.put(
            f"{API}/devices/{former['id']}/interfaces",
            json={
                "interfaces": [
                    {"id": p["id"], "name": p["name"], "vlan_mode": p["vlan_mode"], "vlan_ids": _port_vlans(client, former)}
                    for p in saved_ports
                ]
            },
        )
        assert r.status_code == 200, r.text
        assert client.put(f"{API}/devices/{former['id']}/vlans", json={"vlans": []}).status_code == 200

    def test_audit_mentions_how_many_devices_lost_the_vlan(self, client, db_session):
        dt = _device_type(client, "Тип аудита переноса")
        first, second = _device(client, dt, "MV-AUD1"), _device(client, dt, "MV-AUD2")
        old_domain = _domain(client, "Старый для аудита", None, (first, second))
        new_domain = _domain(client, "Новый для аудита")
        vlan = _vlan(client, 313, old_domain)

        _move(client, vlan, new_domain)

        details = db_session.scalars(
            select(AuditLog.details).where(AuditLog.entity_type == "vlans", AuditLog.entity_id == vlan["id"])
        ).all()
        assert "VLAN снят с устройств прежнего домена: 2" in details


class TestSubinterfacesOnMovedVlan:
    """Подинтерфейс на перенесённом VLAN не удаляется (у него свои IP и открытые порты), но остаётся без
    разрешённого VLAN — об этом пишется запись аудита, а форма устройства покажет его с предупреждением."""

    def _router_with_subinterface(self, client, vlan: dict, device_type: dict, serial: str, domain: dict) -> dict:
        """Устройство — участник домена (VLAN домена назначается ему при включении), на порту подинтерфейс на этом VLAN."""
        device = _device(client, device_type, serial)
        assert client.post(f"{API}/vlan-domains/{domain['id']}/members", json={"physical_device_id": device["id"]}).status_code == 200
        assert vlan["id"] in _assigned(client, device)
        r = client.put(
            f"{API}/devices/{device['id']}/interfaces",
            json={
                "interfaces": [
                    {
                        "name": "Gi0/0",
                        "vlan_mode": "trunk",
                        "all_vlans": True,
                        "subinterfaces": [
                            {"name": "Gi0/0.10", "vlan_id": vlan["id"], "ips": [{"ip_address": "10.0.10.1", "prefix_length": 24}]}
                        ],
                    },
                ]
            },
        )
        assert r.status_code == 200, r.text
        return device

    def test_audit_lists_subinterfaces_left_on_the_vlan_the_device_no_longer_has(self, client, db_session):
        dt = _device_type(client, "Тип подинтерфейсов переноса")
        source = _device(client, dt, "MV-SUB-SRC")
        old_domain = _domain(client, "Старый для подинтерфейсов", source)
        new_domain = _domain(client, "Новый для подинтерфейсов")
        vlan = _vlan(client, 410, old_domain)
        assert vlan["id"] in _assigned(client, source)
        router = self._router_with_subinterface(client, vlan, dt, "MV-SUB-RTR", old_domain)

        _move(client, vlan, new_domain)

        details = db_session.scalars(
            select(AuditLog.details).where(AuditLog.entity_type == "vlans", AuditLog.entity_id == vlan["id"])
        ).all()
        stale = [d for d in details if d.startswith("Подинтерфейсы остались на VLAN, не разрешённом устройству")]
        assert stale and "MV-SUB-RTR / Gi0/0 / Gi0/0.10" in stale[0]
        # подинтерфейс не удалён и не перенесён
        subs = client.get(f"{API}/devices/{router['id']}/subinterfaces").json()["items"]
        assert [(s["name"], s["vlan_id"]) for s in subs] == [("Gi0/0.10", vlan["id"])]

    def test_no_subinterface_note_when_the_device_type_still_allows_the_vlan(self, client, db_session):
        vlan_domain = _domain(client, "Старый домен каталога")
        new_domain = _domain(client, "Новый домен каталога")
        vlan = _vlan(client, 411, vlan_domain)
        dt = _device_type(client, "Тип с VLAN в каталоге", allow_vlan=vlan)
        self._router_with_subinterface(client, vlan, dt, "MV-SUB-CAT", vlan_domain)

        _move(client, vlan, new_domain)

        details = db_session.scalars(
            select(AuditLog.details).where(AuditLog.entity_type == "vlans", AuditLog.entity_id == vlan["id"])
        ).all()
        assert not [d for d in details if d.startswith("Подинтерфейсы остались")]

    def test_audit_lists_group_subinterface_templates_left_on_the_vlan_the_group_lost(self, client, db_session):
        from app.models import InterfaceGroupSubinterface, InterfaceGroupVLAN

        dt = _device_type(client, "Тип шаблонов групп при переносе")
        source = _device(client, dt, "MV-GRP-SRC")
        old_domain = _domain(client, "Старый для шаблонов групп", source)
        new_domain = _domain(client, "Новый для шаблонов групп")
        vlan = _vlan(client, 412, old_domain)
        router = _device(client, dt, "MV-GRP-RTR")
        assert client.post(f"{API}/vlan-domains/{old_domain['id']}/members", json={"physical_device_id": router["id"]}).status_code == 200
        r = client.put(
            f"{API}/devices/{router['id']}/interfaces",
            json={
                "interfaces": [{"name": "Gi0/0", "group_key": "g1"}],
                "groups": [
                    {
                        "key": "g1",
                        "name": "Серверные",
                        "vlan_mode": "trunk",
                        "vlan_ids": [vlan["id"]],
                        "manage_subinterfaces": True,
                        "subinterfaces": [{"vlan_id": vlan["id"], "ips": [{"ip_address": "10.4.12.1", "prefix_length": 24}]}],
                    }
                ],
            },
        )
        assert r.status_code == 200, r.text
        group_id = r.json()["groups"][0]["id"]

        _move(client, vlan, new_domain)

        details = db_session.scalars(
            select(AuditLog.details).where(AuditLog.entity_type == "vlans", AuditLog.entity_id == vlan["id"])
        ).all()
        noted = [d for d in details if d.startswith("Подинтерфейсы групп портов остались")]
        assert noted and "(1)" in noted[0] and "MV-GRP-RTR / Серверные" in noted[0]
        # VLAN у группы снят вместе с устройством, шаблон не удалён и не перенесён
        assert db_session.query(InterfaceGroupVLAN).filter_by(group_id=group_id).count() == 0
        assert db_session.query(InterfaceGroupSubinterface).filter_by(group_id=group_id).count() == 1

    def test_no_group_note_when_the_group_keeps_the_vlan(self, client, db_session):
        vlan_domain = _domain(client, "Старый домен каталога групп")
        new_domain = _domain(client, "Новый домен каталога групп")
        vlan = _vlan(client, 413, vlan_domain)
        dt = _device_type(client, "Тип с VLAN в каталоге для групп", allow_vlan=vlan)
        router = _device(client, dt, "MV-GRP-CAT")
        assert client.post(f"{API}/vlan-domains/{vlan_domain['id']}/members", json={"physical_device_id": router["id"]}).status_code == 200
        r = client.put(
            f"{API}/devices/{router['id']}/interfaces",
            json={
                "interfaces": [{"name": "Gi0/0", "group_key": "g1"}],
                "groups": [
                    {
                        "key": "g1",
                        "name": "Серверные",
                        "vlan_mode": "trunk",
                        "vlan_ids": [vlan["id"]],
                        "manage_subinterfaces": True,
                        "subinterfaces": [{"vlan_id": vlan["id"]}],
                    }
                ],
            },
        )
        assert r.status_code == 200, r.text

        _move(client, vlan, new_domain)

        details = db_session.scalars(
            select(AuditLog.details).where(AuditLog.entity_type == "vlans", AuditLog.entity_id == vlan["id"])
        ).all()
        assert not [d for d in details if d.startswith("Подинтерфейсы групп портов остались")]
