"""Согласование портов по правилам: предпросмотр и применение плана на реальных подключениях.

Запуск: pytest backend/tests/test_port_sync_reconcile.py -v
"""
from __future__ import annotations

import pytest

from app.models import AuditLog, Connection, DeviceInterface, InterfaceGroup, InterfaceVLAN, IPAddress, PhysicalDeviceVLAN, VLAN
from app.services.port_vlans import effective_vlan_ids
from app.services.port_sync_rules import ALL_VLANS_BOTH_RULE, ALL_VLANS_RULE, EMPTY_TRUNK_RULE, ROLE_MATCH_RULE, TRUNK_VLANS_UNION_RULE

PREVIEW = "/api/v1/port-sync/preview"
APPLY = "/api/v1/port-sync/apply"
RULES = "/api/v1/port-sync/rules"


class World:
    """Устройства, порты, VLAN и подключения для сценариев согласования."""

    def __init__(self, client, db_session) -> None:
        self.client, self.db = client, db_session
        category = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
        self.device_type = client.post("/api/v1/resources/device-types", json={"name": "Тип для согласования", "category_id": category}).json()["id"]
        self.cable = client.post("/api/v1/resources/connection-types", json={"name": "Кабель (согласование)"}).json()["id"]
        self.vlans: dict[int, VLAN] = {}
        self.devices: dict[str, str] = {}

    def vlan(self, number: int) -> VLAN:
        if number not in self.vlans:
            row = VLAN(vlan_id=number, name=f"vlan{number}")
            self.db.add(row)
            self.db.flush()
            self.vlans[number] = row
        return self.vlans[number]

    def device(self, serial: str, port_names: list[str], *, allowed: tuple[int, ...] = ()) -> list[str]:
        """Устройство с портами (роль «передача данных», trunk, без VLAN); allowed — VLAN устройства."""
        device = self.client.post("/api/v1/resources/devices", json={"device_type_id": self.device_type, "serial_number": serial, "system_name": serial.lower()}).json()
        self.devices[serial] = device["id"]
        for number in allowed:
            self.db.add(PhysicalDeviceVLAN(physical_device_id=device["id"], vlan_id=self.vlan(number).id))
        self.db.commit()
        ports = [{"name": n, "is_management": False, "is_data_transfer": True} for n in port_names]
        response = self.client.put(f"/api/v1/devices/{device['id']}/interfaces", json={"interfaces": ports})
        assert response.status_code == 200, response.text
        by_name = {i["name"]: i["id"] for i in response.json()["items"]}
        return [by_name[n] for n in port_names]

    def configure(self, interface_id: str, *, mode: str | None = None, vlans: tuple[int, ...] | None = None, role: tuple[bool, bool] | None = None, all_vlans: bool = False) -> None:
        """all_vlans=True — порту ставится «Все VLAN»: хранится только признак (связей нет), набор — VLAN его устройства."""
        iface = self.db.get(DeviceInterface, interface_id)
        if mode is not None:
            iface.vlan_mode = mode
        if role is not None:
            iface.is_management, iface.is_data_transfer = role
        if all_vlans:
            iface.all_vlans = True
            vlans = ()
        if vlans is not None:
            for link in self.db.query(InterfaceVLAN).filter_by(interface_id=interface_id).all():
                self.db.delete(link)
            self.db.flush()
            self.db.add_all(InterfaceVLAN(interface_id=interface_id, vlan_id=self.vlan(n).id, mode=iface.vlan_mode) for n in vlans)
        self.db.commit()

    def connect(self, source: str, destination: str, **extra) -> str:
        response = self.client.post(
            "/api/v1/resources/connections",
            json={"source_interface_id": source, "destination_interface_id": destination, "connection_type_id": self.cable, **extra},
        )
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def port(self, interface_id: str) -> dict:
        self.db.expire_all()
        iface = self.db.get(DeviceInterface, interface_id)
        links = self.db.query(InterfaceVLAN).filter_by(interface_id=interface_id).all()
        return {
            "mode": iface.vlan_mode,
            "role": (iface.is_management, iface.is_data_transfer),
            # Набор порта: выбранные VLAN или, при «Все VLAN», все VLAN его устройства (services/port_vlans.py).
            "vlans": sorted(self.db.get(VLAN, vlan_id).vlan_id for vlan_id in effective_vlan_ids(self.db, [interface_id]).get(interface_id, ())),
            "all_vlans": iface.all_vlans,
            "stored_links": len(links),
            "link_modes": {link.mode for link in links},
        }

    def status(self, connection_id: str) -> str:
        items = self.client.get("/api/v1/connections").json()["items"]
        return next(c["port_config_status"] for c in items if c["id"] == connection_id)

    def preview(self, **body) -> dict:
        response = self.client.post(PREVIEW, json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def apply(self, plan: dict | None = None, **body) -> dict:
        plan = plan or self.preview(**body)
        response = self.client.post(APPLY, json={**body, "plan_hash": plan["plan_hash"], "confirm": True})
        assert response.status_code == 200, response.text
        return response.json()

    def audit(self, *needles: str) -> list[str]:
        self.db.expire_all()
        return [e.details for e in self.db.query(AuditLog).all() if all(n in (e.details or "") for n in needles)]

    def rule(self, code: str) -> dict:
        return next(r for r in self.client.get(RULES).json()["items"] if r["code"] == code)


@pytest.fixture()
def world(client, db_session) -> World:
    return World(client, db_session)


def _empty_trunk_pair(world: World, *, neighbor_vlans=(10, 20), allowed=(10, 20, 30)):
    """a — порт с пустым trunk, b — trunk с VLAN; оба устройства знают нужные VLAN.

    По умолчанию VLAN 30 доступен устройствам, но не назначен соседу: назначь он всё доступное устройству —
    это было бы «Все VLAN», и порт перехватило бы правило «Все VLAN → Все VLAN у соседа», а не «пустой trunk»."""
    (a,) = world.device("EMPTY-A", ["Gi0/1"], allowed=allowed)
    (b,) = world.device("FULL-B", ["Gi0/1"], allowed=allowed)
    world.configure(b, mode="trunk", vlans=neighbor_vlans)
    return a, b, world.connect(a, b)


# --- главное: пустой trunk получает VLAN соседа --------------------------------------------------

def test_preview_proposes_the_neighbors_vlans_for_an_empty_trunk(world):
    a, b, connection = _empty_trunk_pair(world)

    plan = world.preview()

    assert plan["summary"]["applicable"] == 1 and plan["summary"]["auto"] == 1
    (item,) = plan["items"]
    assert item["connection_id"] == connection and item["outcome"] == "auto"
    assert item["rule"]["code"] == EMPTY_TRUNK_RULE
    assert item["target"] == "source"  # пустой порт — порт-источник подключения
    assert item["changes"]["vlans"] == {"from": [], "to": [10, 20], "skipped": []}
    assert item["changes"]["role"] is None and item["changes"]["mode"] is None
    assert (item["source"]["interface_id"], item["destination"]["interface_id"]) == (a, b)


def test_preview_changes_nothing(world):
    a, _b, _c = _empty_trunk_pair(world)

    world.preview()

    assert world.port(a)["vlans"] == []


def test_apply_gives_the_empty_trunk_the_neighbors_vlans_and_clears_the_discrepancy(world):
    a, b, connection = _empty_trunk_pair(world)
    assert world.status(connection) == "mismatch"

    result = world.apply()

    assert result["applied"] == {"ports": 1, "connections": 1} and result["connection_ids"] == [connection]
    # Набор выбран явно (не «Все VLAN»): признак не выставлен, VLAN хранятся связями.
    assert world.port(a) == {
        "mode": "trunk", "role": (False, True), "vlans": [10, 20],
        "all_vlans": False, "stored_links": 2, "link_modes": {"trunk"},
    }
    assert world.port(b)["vlans"] == [10, 20]  # сосед не тронут
    assert world.status(connection) == "ok"
    assert world.audit("Согласование порта «Gi0/1»", "Пустой trunk получает VLAN соседа", "VLAN нет → 10, 20")


def test_empty_trunk_on_the_destination_side_is_handled_too(world):
    (full,) = world.device("FULL-S", ["Gi0/1"], allowed=(10, 20))
    (empty,) = world.device("EMPTY-D", ["Gi0/1"], allowed=(10, 20))
    world.configure(full, vlans=(10, 20))
    connection = world.connect(full, empty)

    plan = world.preview()
    world.apply(plan)

    assert plan["items"][0]["target"] == "destination"
    assert world.port(empty)["vlans"] == [10, 20] and world.status(connection) == "ok"


def test_neighbor_with_all_vlans_also_triggers_the_rule(world):
    """«Все VLAN» у соседа — назначены все VLAN, доступные его устройству."""
    a, b, _c = _empty_trunk_pair(world, neighbor_vlans=(10, 20, 30), allowed=(10, 20, 30))

    plan = world.preview()

    assert plan["items"][0]["outcome"] == "auto" and plan["items"][0]["changes"]["vlans"]["to"] == [10, 20, 30]


def test_second_apply_is_a_no_op(world):
    _empty_trunk_pair(world)
    world.apply()

    again = world.preview()

    assert again["summary"]["connections"] == 0 and again["items"] == []
    assert world.apply(again)["applied"] == {"ports": 0, "connections": 0}


# --- VLAN, которых нет у устройства порта -------------------------------------------------------

def test_vlans_missing_on_the_target_device_are_skipped_with_a_warning(world):
    a, b, _c = _empty_trunk_pair(world, neighbor_vlans=(10, 20, 30), allowed=(10, 20, 30))
    other = world.db.get(DeviceInterface, a).physical_device_id
    world.db.query(PhysicalDeviceVLAN).filter_by(physical_device_id=other, vlan_id=world.vlans[30].id).delete()
    world.db.commit()

    plan = world.preview()
    world.apply(plan)

    item = plan["items"][0]
    assert item["outcome"] == "auto" and item["changes"]["vlans"] == {"from": [], "to": [10, 20], "skipped": [30]}
    assert "30" in item["warnings"][0]
    assert world.port(a)["vlans"] == [10, 20]


def test_no_vlan_of_the_neighbor_is_available_to_the_target_device_blocks_the_item(world):
    a, b, _c = _empty_trunk_pair(world, neighbor_vlans=(10, 20), allowed=())
    world.db.add_all(PhysicalDeviceVLAN(physical_device_id=world.db.get(DeviceInterface, b).physical_device_id, vlan_id=world.vlan(n).id) for n in (10, 20))
    world.db.commit()

    plan = world.preview()

    item = plan["items"][0]
    assert item["outcome"] == "blocked" and "не доступен устройству" in item["reason"]
    assert plan["summary"]["applicable"] == 0 and plan["summary"]["blocked"] == 1
    assert world.apply(plan)["applied"]["ports"] == 0
    assert world.port(a)["vlans"] == []


def test_vlans_are_matched_by_number_to_the_record_available_to_the_target(world):
    """У устройств разные записи справочника с одним номером — переносится запись, доступная целевому порту."""
    (a,) = world.device("NUM-A", ["Gi0/1"])
    (b,) = world.device("NUM-B", ["Gi0/1"])
    mine = VLAN(vlan_id=10, name="vlan10-A")
    world.db.add(mine)
    world.db.flush()
    world.db.add(PhysicalDeviceVLAN(physical_device_id=world.db.get(DeviceInterface, a).physical_device_id, vlan_id=mine.id))
    world.db.add(PhysicalDeviceVLAN(physical_device_id=world.db.get(DeviceInterface, b).physical_device_id, vlan_id=world.vlan(10).id))
    world.db.commit()
    world.configure(b, vlans=(10,))
    world.connect(a, b)

    world.apply()

    link = world.db.query(InterfaceVLAN).filter_by(interface_id=a).one()
    assert link.vlan_id == mine.id  # запись VLAN, доступная устройству целевого порта


# --- запреты -----------------------------------------------------------------------------------

def test_port_in_a_group_that_sets_mode_and_vlans_is_never_changed_individually(world):
    a, b, connection = _empty_trunk_pair(world)
    iface = world.db.get(DeviceInterface, a)
    group = InterfaceGroup(physical_device_id=iface.physical_device_id, name="Серверные порты", vlan_mode="trunk")
    world.db.add(group)
    world.db.flush()
    iface.group_id = group.id
    world.db.commit()

    plan = world.preview()

    item = plan["items"][0]
    assert item["outcome"] == "blocked" and "Серверные порты" in item["reason"] and "группу" in item["reason"]
    assert world.apply(plan)["applied"]["ports"] == 0 and world.port(a)["vlans"] == []


def test_a_group_without_a_mode_does_not_block_the_change(world):
    a, _b, _c = _empty_trunk_pair(world)
    iface = world.db.get(DeviceInterface, a)
    group = InterfaceGroup(physical_device_id=iface.physical_device_id, name="Только IP", vlan_mode=None)
    world.db.add(group)
    world.db.flush()
    iface.group_id = group.id
    world.db.commit()

    assert world.preview()["items"][0]["outcome"] == "auto"


def test_copying_several_vlans_into_an_access_port_is_blocked(world):
    (a,) = world.device("ACC-A", ["Gi0/1"], allowed=(10, 20))
    (b,) = world.device("ACC-B", ["Gi0/1"], allowed=(10, 20))
    world.configure(a, mode="access", vlans=())
    world.configure(b, mode="access", vlans=(10,))
    world.configure(b, mode="trunk", vlans=(10, 20))
    rule = world.client.post(RULES, json={"name": "Копировать VLAN в любой порт", "action": "auto", "priority": 1, "target": {"vlans": "none"}, "source": {"vlans": "set"}, "apply": {"vlans": "copy"}}).json()
    world.connect(a, b)

    plan = world.preview(rule_id=rule["id"])

    item = plan["items"][0]
    assert item["outcome"] == "blocked" and "access" in item["reason"]


def test_a_port_with_two_connections_is_changed_by_the_first_only(world):
    (empty,) = world.device("HUB", ["Gi0/1"], allowed=(10, 20))
    (n1,) = world.device("N1", ["Gi0/1"], allowed=(10, 20))
    (n2,) = world.device("N2", ["Gi0/1"], allowed=(10, 20))
    world.configure(n1, vlans=(10,))
    world.configure(n2, vlans=(20,))
    first = world.connect(empty, n1)
    # API не даёт включить порт в два активных подключения, но в старых данных такое бывает — создаём напрямую. Порт — источник в первом подключении и
    # назначение во втором: одноролевой дубль (источник дважды) с A-01 этап 2 запрещён уникальным индексом, разноролевой индекс по одной колонке не ловит.
    duplicate = Connection(source_interface_id=n2, destination_interface_id=empty, connection_type_id=world.cable, is_active=True)
    world.db.add(duplicate)
    world.db.commit()
    second = duplicate.id

    plan = world.preview()
    world.apply(plan)

    outcomes = {i["connection_id"]: i["outcome"] for i in plan["items"]}
    assert outcomes == {first: "auto", second: "blocked"}
    assert "другим подключением" in next(i["reason"] for i in plan["items"] if i["connection_id"] == second)
    assert world.port(empty)["vlans"] == [10]


# --- что не согласуется ------------------------------------------------------------------------

def test_role_mismatch_is_reported_as_manual_with_both_directions_and_is_not_applied(world):
    (a,) = world.device("ROLE-A", ["Gi0/1"])
    (b,) = world.device("ROLE-B", ["Gi0/1"])
    world.configure(a, role=(True, False))
    connection = world.connect(a, b)

    plan = world.preview()
    result = world.apply(plan)

    (item,) = plan["items"]
    assert item["outcome"] == "manual" and item["rule"]["code"] == ROLE_MATCH_RULE and item["rule"]["action"] == "manual"
    assert sorted(o["target"] for o in item["options"]) == ["destination", "source"]
    assert next(o for o in item["options"] if o["target"] == "source")["changes"]["role"] == "data"
    assert plan["summary"]["manual"] == 1 and plan["summary"]["applicable"] == 0
    assert result["applied"]["ports"] == 0 and world.status(connection) == "mismatch"


def test_approved_and_inactive_connections_are_left_alone_and_explained_for_an_explicit_list(world):
    a, b, connection = _empty_trunk_pair(world)
    world.client.post("/api/v1/connections/port-config/approve", json={"connection_ids": [connection]})
    (c,) = world.device("INACT-A", ["Gi0/1"], allowed=(10,))
    (d,) = world.device("INACT-B", ["Gi0/1"], allowed=(10,))
    world.configure(d, vlans=(10,))
    inactive = world.connect(c, d, is_active=False)

    bulk = world.preview()
    explicit = world.preview(connection_ids=[connection, inactive])

    assert bulk["items"] == [] and bulk["summary"]["connections"] == 0
    reasons = {i["connection_id"]: (i["outcome"], i["reason"]) for i in explicit["items"]}
    assert reasons[connection][0] == "skipped" and "одобрено" in reasons[connection][1]
    assert reasons[inactive][0] == "skipped" and "неактивно" in reasons[inactive][1]


def test_connections_without_a_discrepancy_are_not_listed_in_bulk_mode(world):
    (a,) = world.device("SAME-A", ["Gi0/1"], allowed=(10,))
    (b,) = world.device("SAME-B", ["Gi0/1"], allowed=(10,))
    world.configure(a, vlans=(10,))
    world.configure(b, vlans=(10,))
    world.connect(a, b)

    assert world.preview()["summary"]["connections"] == 0


# --- явный список и правило --------------------------------------------------------------------

def test_apply_with_connection_ids_touches_only_those_connections(world):
    a1, b1, c1 = _empty_trunk_pair(world)
    (a2,) = world.device("EMPTY-A2", ["Gi0/1"], allowed=(10, 20))
    (b2,) = world.device("FULL-B2", ["Gi0/1"], allowed=(10, 20))
    world.configure(b2, vlans=(10, 20))
    c2 = world.connect(a2, b2)

    result = world.apply(connection_ids=[c2])

    assert result["connection_ids"] == [c2]
    assert world.port(a2)["vlans"] == [10, 20] and world.port(a1)["vlans"] == []
    assert world.status(c1) == "mismatch"


def test_unknown_connection_id_is_404_and_changes_nothing(world):
    a, _b, connection = _empty_trunk_pair(world)

    response = world.client.post(PREVIEW, json={"connection_ids": [connection, "nope"]})

    assert response.status_code == 404 and world.port(a)["vlans"] == []


@pytest.mark.parametrize("body", [{"connection_ids": []}, {"connection_ids": "x"}, {"connection_ids": [1]}, {"connection_ids": ["x"] * 501}, {"rule_id": ""}, {"rule_id": 5}])
def test_preview_rejects_malformed_scope(world, body):
    assert world.client.post(PREVIEW, json=body).status_code == 422


def test_preview_requires_a_json_object(world):
    assert world.client.post(PREVIEW, json=[1]).status_code == 422


def test_rule_id_limits_the_check_to_one_rule_even_if_it_is_disabled(world):
    a, _b, _c = _empty_trunk_pair(world)
    rule = world.rule(EMPTY_TRUNK_RULE)
    world.client.put(f"{RULES}/{rule['id']}", json={"enabled": False})

    without = world.preview()
    with_rule = world.preview(rule_id=rule["id"])

    assert without["items"][0]["rule"]["code"] != EMPTY_TRUNK_RULE  # без правила остаётся обычное расхождение VLAN
    assert without["items"][0]["outcome"] == "manual"
    assert with_rule["items"][0]["outcome"] == "auto" and with_rule["items"][0]["rule"]["code"] == EMPTY_TRUNK_RULE


def test_rule_preview_lists_only_the_connections_the_rule_matches(world):
    _empty_trunk_pair(world)
    (c,) = world.device("OTHER-A", ["Gi0/1"])
    (d,) = world.device("OTHER-B", ["Gi0/1"])
    world.configure(c, role=(True, False))
    world.connect(c, d)
    rule = world.rule(EMPTY_TRUNK_RULE)

    plan = world.preview(rule_id=rule["id"])

    assert [i["outcome"] for i in plan["items"]] == ["auto"]
    assert plan["summary"]["connections"] == 2 and plan["summary"]["none"] == 1


def test_unknown_rule_id_is_404(world):
    assert world.client.post(PREVIEW, json={"rule_id": "nope"}).status_code == 404


# --- правила пользователя вступают в силу -------------------------------------------------------

def test_a_user_rule_can_copy_the_role_and_mirrors_it_to_the_ports_ip_addresses(world):
    (a,) = world.device("UR-A", ["Gi0/1"])
    (b,) = world.device("UR-B", ["Gi0/1"])
    world.configure(a, role=(False, False))
    world.configure(b, role=(True, False))
    world.db.add(IPAddress(owner_type="device_interface", owner_id=a, ip_address="10.0.0.5", prefix_length=24, is_management=False))
    world.db.commit()
    connection = world.connect(a, b)
    world.client.post(RULES, json={"name": "Порт без роли берёт роль соседа", "action": "auto", "priority": 1, "target": {"role": "none"}, "apply": {"role": True}})

    plan = world.preview()
    world.apply(plan)

    assert plan["items"][0]["changes"]["role"] == {"from": "none", "to": "management"}
    assert world.port(a)["role"] == (True, False) and world.status(connection) == "ok"
    world.db.expire_all()
    assert world.db.query(IPAddress).filter_by(owner_id=a).one().is_management is True  # адреса порта зеркалируют его роль
    assert world.audit("Порт без роли берёт роль соседа", "роль не задано → Управление активами")


def test_mode_rule_adapts_vlans_when_the_target_becomes_access(world):
    (a,) = world.device("AD-A", ["Gi0/1"], allowed=(10, 20, 30))
    (b,) = world.device("AD-B", ["Gi0/1"], allowed=(10, 20, 30))
    world.configure(a, mode="trunk", vlans=(30, 10, 20))
    world.configure(b, mode="access", vlans=(10,))
    connection = world.connect(a, b)
    assert world.status(connection) == "mismatch"
    world.client.post(RULES, json={"name": "Trunk берёт access соседа", "action": "auto", "priority": 1, "target": {"mode": "trunk"}, "source": {"mode": "access"}, "apply": {"mode": True, "vlans": "adapt"}})

    world.apply()

    assert world.port(a) == {
        "mode": "access", "role": (False, True), "vlans": [10],
        "all_vlans": False, "stored_links": 1, "link_modes": {"access"},
    }
    assert world.status(connection) == "ok"
    assert world.audit("режим trunk → access", "VLAN 10, 20, 30 → 10")


def test_ignore_rule_excludes_pairs_from_automatic_changes(world):
    a, _b, _c = _empty_trunk_pair(world)
    world.client.post(RULES, json={"name": "Не трогать порты управления", "action": "ignore", "priority": 1, "target": {"role": "data"}})

    plan = world.preview()

    assert plan["items"][0]["outcome"] == "ignored" and plan["summary"]["applicable"] == 0
    assert world.apply(plan)["applied"]["ports"] == 0 and world.port(a)["vlans"] == []


# --- безопасность применения --------------------------------------------------------------------

def test_apply_requires_confirmation(world):
    _empty_trunk_pair(world)
    plan = world.preview()

    response = world.client.post(APPLY, json={"plan_hash": plan["plan_hash"]})

    assert response.status_code == 422 and "confirm" in response.json()["detail"]


def test_apply_with_a_stale_plan_is_rejected_with_409(world):
    a, b, _c = _empty_trunk_pair(world)
    plan = world.preview()
    world.configure(b, vlans=(10,))  # сосед изменился после предпросмотра

    response = world.client.post(APPLY, json={"plan_hash": plan["plan_hash"], "confirm": True})

    assert response.status_code == 409 and world.port(a)["vlans"] == []


def test_apply_with_a_wrong_hash_is_rejected(world):
    a, _b, _c = _empty_trunk_pair(world)

    response = world.client.post(APPLY, json={"plan_hash": "0" * 64, "confirm": True})

    assert response.status_code == 409 and world.port(a)["vlans"] == []


def test_the_plan_hash_is_stable_between_identical_previews(world):
    _empty_trunk_pair(world)

    assert world.preview()["plan_hash"] == world.preview()["plan_hash"]


def test_a_change_to_the_rules_changes_the_plan_hash(world):
    _empty_trunk_pair(world)
    first = world.preview()["plan_hash"]
    world.client.post(RULES, json={"name": "Раньше всех", "action": "auto", "priority": 1, "target": {"vlans": "none"}, "source": {"vlans": "set"}, "apply": {"vlans": "copy"}})

    assert world.preview()["plan_hash"] != first  # то же изменение данных, но другое правило — другой план


def test_apply_is_atomic_when_a_write_fails(world, monkeypatch):
    a1, _b1, _c1 = _empty_trunk_pair(world)
    (a2,) = world.device("EMPTY-A9", ["Gi0/1"], allowed=(10, 20))
    (b2,) = world.device("FULL-B9", ["Gi0/1"], allowed=(10, 20))
    world.configure(b2, vlans=(10, 20))
    world.connect(a2, b2)
    plan = world.preview()
    from app.services import port_sync_reconcile as module

    original = module.write_port_vlans
    calls = {"n": 0}

    def flaky(port, mode, keep, session, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("сбой записи")
        return original(port, mode, keep, session, **kwargs)

    monkeypatch.setattr(module, "write_port_vlans", flaky)
    with pytest.raises(RuntimeError):
        world.client.post(APPLY, json={"plan_hash": plan["plan_hash"], "confirm": True})
    world.db.rollback()

    assert world.port(a1)["vlans"] == [] and world.port(a2)["vlans"] == []  # не записано ничего


def test_preview_query_count_does_not_grow_with_the_number_of_connections(world, sql_log):
    def build(count: int, prefix: str) -> None:
        for i in range(count):
            (x,) = world.device(f"{prefix}-X{i}", ["Gi0/1"], allowed=(10,))
            (y,) = world.device(f"{prefix}-Y{i}", ["Gi0/1"], allowed=(10,))
            world.configure(y, vlans=(10,))
            world.connect(x, y)

    build(2, "S")
    sql_log.clear()
    world.preview()
    small = len(sql_log)
    build(8, "L")
    sql_log.clear()
    world.preview()

    assert len(sql_log) == small


# --- trunk с разными наборами VLAN: объединение на обоих портах ----------------------------------

def _trunk_pair(world: World, *, a_vlans=(10, 20), b_vlans=(20, 30), a_allowed=(10, 20, 30), b_allowed=(10, 20, 30)):
    (a,) = world.device("TRUNK-A", ["Gi0/1"], allowed=a_allowed)
    (b,) = world.device("TRUNK-B", ["Gi0/1"], allowed=b_allowed)
    world.configure(a, mode="trunk", vlans=a_vlans)
    world.configure(b, mode="trunk", vlans=b_vlans)
    return a, b, world.connect(a, b)


def test_preview_plans_the_union_for_both_trunk_ports(world):
    a, b, connection = _trunk_pair(world)

    plan = world.preview()

    assert plan["summary"]["auto"] == 1 and plan["summary"]["applicable"] == 2  # одно подключение, два порта
    (item,) = plan["items"]
    assert item["connection_id"] == connection and item["outcome"] == "auto" and item["rule"]["code"] == TRUNK_VLANS_UNION_RULE
    assert item["target"] == "both" and item["changes"] is None
    by_target = {t["target"]: t for t in item["targets"]}
    assert by_target["source"]["changes"]["vlans"] == {"from": [10, 20], "to": [10, 20, 30], "skipped": []}
    assert by_target["destination"]["changes"]["vlans"] == {"from": [20, 30], "to": [10, 20, 30], "skipped": []}
    assert not any(t["blocked"] for t in item["targets"])
    assert world.port(a)["vlans"] == [10, 20] and world.port(b)["vlans"] == [20, 30]  # предпросмотр ничего не пишет


def test_apply_merges_vlans_on_both_ports_and_clears_the_mismatch(world):
    a, b, connection = _trunk_pair(world)
    assert world.status(connection) == "mismatch"

    result = world.apply()

    assert result["applied"] == {"ports": 2, "connections": 1} and result["connection_ids"] == [connection]
    assert world.port(a)["vlans"] == [10, 20, 30] and world.port(b)["vlans"] == [10, 20, 30]
    assert world.port(a)["link_modes"] == {"trunk"} and world.port(b)["link_modes"] == {"trunk"}
    assert world.status(connection) == "ok"
    assert len(world.audit("Согласование порта", "Trunk: наборы VLAN")) == 2  # по записи аудита на порт


def test_a_trunk_port_that_already_carries_everything_is_left_alone(world):
    a, b, _c = _trunk_pair(world, a_vlans=(10, 20, 30), b_vlans=(20,), a_allowed=(10, 20, 30, 50))  # A не «Все VLAN»

    plan = world.preview()
    assert [t["target"] for t in plan["items"][0]["targets"]] == ["destination"] and plan["items"][0]["target"] == "destination"
    assert plan["summary"]["applicable"] == 1

    world.apply(plan)
    assert world.port(a)["vlans"] == [10, 20, 30] and world.port(b)["vlans"] == [10, 20, 30]


def test_a_vlan_the_device_does_not_have_is_skipped_for_that_port_only(world):
    # У устройства A нет VLAN 30: A остаётся как есть, B получает VLAN 10 и всё равно применяется.
    a, b, connection = _trunk_pair(world, a_allowed=(10, 20, 50))  # 50 не назначен: A не «Все VLAN»

    plan = world.preview()

    (item,) = plan["items"]
    assert item["outcome"] == "auto" and plan["summary"]["applicable"] == 1
    by_target = {t["target"]: t for t in item["targets"]}
    assert "не доступен устройству" in by_target["source"]["blocked"] and by_target["destination"]["blocked"] is None
    assert any("30" in w for w in item["warnings"]) or by_target["source"]["changes"]["vlans"]["skipped"] == [30]

    world.apply(plan)
    assert world.port(a)["vlans"] == [10, 20] and world.port(b)["vlans"] == [10, 20, 30]
    assert world.status(connection) == "mismatch"  # объединение неполное — расхождение остаётся и видно


def test_both_ports_blocked_blocks_the_connection(world):
    a, b, _c = _trunk_pair(world, a_vlans=(10,), b_vlans=(20,), a_allowed=(10, 50), b_allowed=(20, 60))  # свободные 50/60 — ни один порт не «Все VLAN»

    plan = world.preview()

    (item,) = plan["items"]
    assert item["outcome"] == "blocked" and plan["summary"]["applicable"] == 0
    assert item["reason"].count("Порт «Gi0/1»") == 2
    assert world.apply(plan)["applied"] == {"ports": 0, "connections": 0}
    assert world.port(a)["vlans"] == [10] and world.port(b)["vlans"] == [20]


def test_a_group_port_does_not_stop_the_other_side_from_being_merged(world):
    a, b, _c = _trunk_pair(world)
    iface = world.db.get(DeviceInterface, a)
    group = InterfaceGroup(physical_device_id=iface.physical_device_id, name="Магистрали", vlan_mode="trunk")
    world.db.add(group)
    world.db.flush()
    iface.group_id = group.id
    world.db.commit()

    plan = world.preview()

    (item,) = plan["items"]
    assert item["outcome"] == "auto"
    by_target = {t["target"]: t for t in item["targets"]}
    assert "Магистрали" in by_target["source"]["blocked"] and by_target["destination"]["blocked"] is None
    world.apply(plan)
    assert world.port(a)["vlans"] == [10, 20] and world.port(b)["vlans"] == [10, 20, 30]  # группу единичным порт не меняет


def test_two_connections_cannot_merge_into_the_same_port_in_one_plan(world):
    (a,) = world.device("HUB-A", ["Gi0/1"], allowed=(10, 20, 30))
    (b,) = world.device("HUB-B", ["Gi0/1"], allowed=(10, 20, 30))
    (c,) = world.device("HUB-C", ["Gi0/1"], allowed=(10, 20, 30))
    world.configure(a, mode="trunk", vlans=(10,))
    world.configure(b, mode="trunk", vlans=(20,))
    world.configure(c, mode="trunk", vlans=(30,))
    first = world.connect(a, b)
    # API не даёт включить порт в два активных подключения, но в старых данных такое бывает — создаём напрямую. Порт a — источник в первом подключении
    # и назначение во втором: одноролевой дубль с A-01 этап 2 запрещён уникальным индексом, разноролевой индекс по одной колонке не ловит.
    duplicate = Connection(source_interface_id=c, destination_interface_id=a, connection_type_id=world.cable, is_active=True)
    world.db.add(duplicate)
    world.db.commit()
    second = duplicate.id

    plan = world.preview()

    by_connection = {i["connection_id"]: i for i in plan["items"]}
    assert by_connection[first]["outcome"] == "auto" and len(by_connection[first]["targets"]) == 2
    # Порт a уже изменяется первым подключением — во втором ему ничего не применяется, порт c объединяется.
    blocked = {t["target"]: t["blocked"] for t in by_connection[second]["targets"]}
    assert "другим подключением" in blocked["destination"] and blocked["source"] is None
    assert plan["summary"]["applicable"] == 3  # a и b по первому подключению + c по второму

    world.apply(plan)
    assert world.port(a)["vlans"] == [10, 20] and world.port(c)["vlans"] == [10, 30]


def test_default_merge_rule_is_created_for_an_existing_installation(world):
    from app.models import PortSyncRule
    from app.services.port_sync_store import ensure_default_rules

    row = world.db.query(PortSyncRule).filter_by(code=TRUNK_VLANS_UNION_RULE).one()
    world.db.delete(row)  # установка, созданная до появления правила
    world.db.commit()

    assert ensure_default_rules(world.db) == 1

    created = world.rule(TRUNK_VLANS_UNION_RULE)
    assert created["action"] == "auto" and created["apply"] == {"role": False, "mode": False, "vlans": "union"} and created["priority"] == 15


# --- массовое применение: число запросов не растёт с числом портов -------------------------------

def _statements_while(db, action) -> list[str]:
    """SQL-запросы, выполненные во время `action` (через событие движка)."""
    from sqlalchemy import event

    engine = db.get_bind()
    seen: list[str] = []

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        action()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    return seen


def test_applying_many_ports_does_not_query_or_flush_per_port(world):
    count = 40
    a_ports = world.device("MASS-A", [f"p{i}" for i in range(count)], allowed=(10, 20, 30))
    b_ports = world.device("MASS-B", [f"p{i}" for i in range(count)], allowed=(10, 20, 30))
    for a, b in zip(a_ports, b_ports):
        world.configure(a, mode="trunk", vlans=(10, 20))
        world.configure(b, mode="trunk", vlans=(10, 30))
        world.connect(a, b)
    plan = world.preview()
    assert plan["summary"]["applicable"] == 2 * count

    statements = _statements_while(world.db, lambda: world.apply(plan))

    # Связи порт–VLAN читаются порциями (≤ 400 id в запросе), а не запросом на порт: 80 портов — одна порция.
    link_reads = [s for s in statements if s.lstrip().upper().startswith("SELECT") and "interface_vlans" in s and "FROM interface_vlans" in s]
    # Запись связей уходит пачками (executemany), поэтому INSERT-ов заметно меньше, чем новых связей.
    link_inserts = [s for s in statements if s.lstrip().upper().startswith("INSERT INTO INTERFACE_VLANS")]
    assert len(link_reads) <= 6, link_reads
    assert len(link_inserts) <= 4, len(link_inserts)
    for a, b in zip(a_ports, b_ports):
        assert world.port(a)["vlans"] == [10, 20, 30] and world.port(b)["vlans"] == [10, 20, 30]


# --- неполный результат: расхождение после применения останется ----------------------------------

def test_a_complete_merge_is_not_partial(world):
    _trunk_pair(world)

    plan = world.preview()

    assert plan["items"][0]["partial"] is False and plan["summary"]["partial"] == 0


def test_a_blocked_half_of_the_pair_makes_the_connection_partial(world):
    _trunk_pair(world, a_allowed=(10, 20, 50))  # у A нет VLAN 30 (а 50 свободен, A не «Все VLAN») — изменится только B

    plan = world.preview()

    assert plan["items"][0]["outcome"] == "auto" and plan["items"][0]["partial"] is True
    assert plan["summary"]["partial"] == 1


def test_vlans_skipped_on_a_port_that_is_still_changed_make_the_connection_partial(world):
    # A: 10, 20, 40; B: 20, 30; у B нет VLAN 40. Оба порта меняются (A получает 30, B — 10), но 40 до B не дойдёт.
    a, b, _c = _trunk_pair(world, a_vlans=(10, 20, 40), b_vlans=(20, 30), a_allowed=(10, 20, 30, 40), b_allowed=(10, 20, 30))

    plan = world.preview()

    (item,) = plan["items"]
    assert item["outcome"] == "auto" and plan["summary"]["applicable"] == 2
    assert not any(t["blocked"] for t in item["targets"])
    assert item["partial"] is True and plan["summary"]["partial"] == 1
    world.apply(plan)
    assert world.port(a)["vlans"] == [10, 20, 30, 40] and world.port(b)["vlans"] == [10, 20, 30]


def test_partial_counts_connections_across_the_whole_plan_not_only_the_shown_items(world, monkeypatch):
    from app.services import port_sync_reconcile

    monkeypatch.setattr(port_sync_reconcile, "MAX_PREVIEW_ITEMS", 1)
    for index in range(3):
        a, b, _c = _trunk_pair_numbered(world, index)

    plan = world.preview()

    assert len(plan["items"]) == 1 and plan["summary"]["total_items"] == 3
    assert plan["summary"]["partial"] == 3  # считаются все подключения плана, а не показанные


def _trunk_pair_numbered(world: World, index: int):
    (a,) = world.device(f"PART-A{index}", ["Gi0/1"], allowed=(10, 20, 50))  # у A нет VLAN 30; 50 свободен — A не «Все VLAN»
    (b,) = world.device(f"PART-B{index}", ["Gi0/1"], allowed=(10, 20, 30))
    world.configure(a, mode="trunk", vlans=(10, 20))
    world.configure(b, mode="trunk", vlans=(20, 30))
    return a, b, world.connect(a, b)


# --- «Все VLAN» на порту → «Все VLAN» у соседа ----------------------------------------------------

def _all_vlans_pair(world: World, *, a_allowed=(10, 20, 30), b_allowed=(10, 20, 30), a_vlans=(10,)):
    """a — trunk с частью VLAN; b — trunk с «Все VLAN» (признак; набор — все VLAN его устройства)."""
    (a,) = world.device("ALLA", ["Gi0/1"], allowed=a_allowed)
    (b,) = world.device("ALLB", ["Gi0/1"], allowed=b_allowed)
    world.configure(a, mode="trunk", vlans=a_vlans)
    world.configure(b, mode="trunk", all_vlans=True)
    return a, b, world.connect(a, b)


def test_all_vlans_port_gives_the_neighbor_all_vlans_of_its_own_device(world):
    a, b, connection = _all_vlans_pair(world)

    plan = world.preview()
    world.apply(plan)

    (item,) = plan["items"]
    assert item["outcome"] == "auto" and item["rule"]["code"] == ALL_VLANS_RULE  # а не «объединение наборов»
    assert item["target"] == "source" and item["changes"]["vlans"] == {"from": [10], "to": [10, 20, 30], "skipped": []}
    assert item["partial"] is False and item["warnings"] == []
    assert world.port(a)["vlans"] == [10, 20, 30] and world.port(b)["vlans"] == [10, 20, 30]
    # Порту a записан признак «Все VLAN», а не набор связей: хранится только он.
    assert world.port(a)["all_vlans"] is True and world.port(a)["stored_links"] == 0
    assert world.status(connection) == "ok"
    assert world.audit("Согласование порта", "Gi0/1", "все")  # в журнале видно, что назначено «Все VLAN»


def test_all_vlans_is_decided_by_the_neighbors_device_not_by_the_sources_numbers(world):
    """У устройства соседа есть VLAN 40, которого нет у порта-источника: «Все VLAN» включает и его."""
    a, _b, connection = _all_vlans_pair(world, a_allowed=(10, 20, 30, 40))

    plan = world.preview()
    world.apply(plan)

    (item,) = plan["items"]
    assert item["changes"]["vlans"]["to"] == [10, 20, 30, 40]
    assert item["partial"] is True and "40" in item["warnings"][0]  # наборы всё равно различаются — предупреждаем до подтверждения
    assert world.port(a)["vlans"] == [10, 20, 30, 40]
    assert world.status(connection) == "mismatch"


def test_all_vlans_is_the_devices_vlans_and_does_not_keep_a_vlan_the_device_cannot_carry(world):
    """«Все VLAN» хранится признаком, а набор — все VLAN устройства: VLAN 99 есть в справочнике, но недоступен
    устройству a, поэтому у порта со «Все VLAN» его нет (раньше «все» дописывались к уже назначенным)."""
    (a,) = world.device("KEEPA", ["Gi0/1"], allowed=(10, 20, 30))
    (b,) = world.device("KEEPB", ["Gi0/1"], allowed=(10, 20, 30))
    world.configure(a, mode="trunk", vlans=(10, 99))
    world.configure(b, mode="trunk", all_vlans=True)
    world.connect(a, b)

    world.apply()

    assert world.port(a)["vlans"] == [10, 20, 30] and world.port(a)["all_vlans"] is True


def test_the_same_vlans_chosen_by_hand_are_not_all_vlans_and_do_not_trigger_the_rule(world):
    """Набор из всех VLAN устройства, выбранных вручную, «Все VLAN» не включает: галочка — отдельный признак."""
    (a,) = world.device("HANDA", ["Gi0/1"], allowed=(10, 20, 30))
    (b,) = world.device("HANDB", ["Gi0/1"], allowed=(10, 20, 30))
    world.configure(a, mode="trunk", vlans=(10,))
    world.configure(b, mode="trunk", vlans=(10, 20, 30))  # все VLAN устройства, но без признака
    world.connect(a, b)

    plan = world.preview()

    (item,) = plan["items"]
    assert item["rule"]["code"] != ALL_VLANS_RULE


def test_all_vlans_second_apply_is_a_no_op(world):
    _all_vlans_pair(world)
    world.apply()

    again = world.preview()

    assert again["summary"]["connections"] == 0 and again["items"] == []


def test_all_vlans_is_not_applied_to_a_port_of_a_group_that_sets_mode_and_vlans(world):
    a, _b, _c = _all_vlans_pair(world)
    iface = world.db.get(DeviceInterface, a)
    group = InterfaceGroup(physical_device_id=iface.physical_device_id, name="Магистраль", vlan_mode="trunk")
    world.db.add(group)
    world.db.flush()
    iface.group_id = group.id
    world.db.commit()

    plan = world.preview()

    item = plan["items"][0]
    assert item["outcome"] == "blocked" and "Магистраль" in item["reason"]
    assert world.apply(plan)["applied"]["ports"] == 0 and world.port(a)["vlans"] == [10]


def test_all_vlans_does_not_touch_a_neighbor_in_access_mode(world):
    a, b, _c = _all_vlans_pair(world)
    world.configure(a, mode="access", vlans=(10,))

    plan = world.preview()

    (item,) = plan["items"]
    assert item["rule"]["code"] != ALL_VLANS_RULE and item["outcome"] == "manual"  # «Все VLAN» в access невозможно
    assert world.apply(plan)["applied"]["ports"] == 0 and world.port(a)["vlans"] == [10]


# --- постраничный предпросмотр и кэш плана --------------------------------------------------------

def _auto_pairs(world: World, count: int) -> list[str]:
    """count подключений с решением auto (пустой trunk получает VLAN соседа)."""
    ids = []
    for index in range(count):
        (a,) = world.device(f"PAGE-A{index}", ["Gi0/1"], allowed=(10, 20))
        (b,) = world.device(f"PAGE-B{index}", ["Gi0/1"], allowed=(10, 20))
        world.configure(b, mode="trunk", vlans=(10, 20))
        ids.append(world.connect(a, b))
    return ids


@pytest.fixture()
def compute_calls(monkeypatch) -> list[int]:
    """Список, в который попадает запись при каждом расчёте плана (а не показе страницы из кэша)."""
    from app.services import port_sync_reconcile

    calls: list[int] = []
    real = port_sync_reconcile._compute

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(port_sync_reconcile, "_compute", counting)
    return calls


def test_preview_pages_cover_the_whole_plan_once_in_a_stable_order(world):
    _auto_pairs(world, 5)
    full = world.preview()

    first = world.preview(limit=2)
    pages = [first]
    for offset in (2, 4):
        pages.append(world.preview(limit=2, offset=offset, plan_hash=first["plan_hash"]))

    assert [len(p["items"]) for p in pages] == [2, 2, 1]
    assert [p["page"] for p in pages] == [
        {"offset": 0, "limit": 2, "total": 5, "has_more": True},
        {"offset": 2, "limit": 2, "total": 5, "has_more": True},
        {"offset": 4, "limit": 2, "total": 5, "has_more": False},
    ]
    assert [i["connection_id"] for p in pages for i in p["items"]] == [i["connection_id"] for i in full["items"]]
    # Сводка и хеш — по всему плану и одинаковые на каждой странице; shown — число элементов в странице.
    assert {p["plan_hash"] for p in pages} == {full["plan_hash"]}
    assert all(p["summary"]["total_items"] == 5 and p["summary"]["applicable"] == 5 for p in pages)
    assert [p["summary"]["shown"] for p in pages] == [2, 2, 1]


def test_next_pages_are_served_from_the_cache_without_recomputing(world, compute_calls):
    _auto_pairs(world, 4)

    first = world.preview(limit=2)
    second = world.preview(limit=2, offset=2, plan_hash=first["plan_hash"])
    again = world.preview(limit=2, offset=0, plan_hash=first["plan_hash"])

    assert len(compute_calls) == 1
    assert len(second["items"]) == 2 and again["items"] == first["items"]


def test_preview_without_plan_hash_always_recomputes(world, compute_calls):
    _auto_pairs(world, 2)

    world.preview(limit=1)
    world.preview(limit=1)

    assert len(compute_calls) == 2


def test_cache_miss_recomputes_and_serves_the_same_plan(world, compute_calls):
    from app.services.port_sync_plan_cache import plan_cache

    _auto_pairs(world, 3)
    first = world.preview(limit=2)
    plan_cache.clear()  # срок снимка истёк / он вытеснен / запрос попал в другой воркер

    second = world.preview(limit=2, offset=2, plan_hash=first["plan_hash"])

    assert len(compute_calls) == 2
    assert [i["connection_id"] for i in second["items"]] == [i["connection_id"] for i in world.preview()["items"]][2:]


def test_page_of_a_plan_that_changed_after_a_cache_miss_is_409(world):
    from app.services.port_sync_plan_cache import plan_cache

    _auto_pairs(world, 3)
    first = world.preview(limit=2)
    plan_cache.clear()
    # Пока снимка в кэше нет, появляется ещё одно подключение с расхождением — план другой.
    (a,) = world.device("PAGE-A-NEW", ["Gi0/1"], allowed=(10, 20))
    (b,) = world.device("PAGE-B-NEW", ["Gi0/1"], allowed=(10, 20))
    world.configure(b, mode="trunk", vlans=(10, 20))
    world.connect(a, b)

    response = world.client.post(PREVIEW, json={"limit": 2, "offset": 2, "plan_hash": first["plan_hash"]})

    assert response.status_code == 409, response.text


def test_apply_never_uses_the_cache_and_drops_it(world, compute_calls):
    from app.services.port_sync_plan_cache import plan_cache

    _auto_pairs(world, 2)
    plan = world.preview(limit=1)
    assert len(plan_cache) == 1

    world.apply(plan)

    assert len(compute_calls) == 2  # предпросмотр + пересчёт при применении (кэш не читался)
    assert len(plan_cache) == 0


def test_rule_changes_drop_cached_plans(world):
    from app.services.port_sync_plan_cache import plan_cache

    _auto_pairs(world, 1)
    world.preview()
    assert len(plan_cache) == 1

    rule = world.rule(EMPTY_TRUNK_RULE)
    response = world.client.put(f"{RULES}/{rule['id']}", json={"enabled": False})

    assert response.status_code == 200, response.text
    assert len(plan_cache) == 0


@pytest.mark.parametrize(
    "body",
    [{"offset": -1}, {"offset": "0"}, {"offset": True}, {"limit": 0}, {"limit": 100000}, {"limit": 1.5}, {"plan_hash": ""}, {"plan_hash": 5}],
)
def test_preview_rejects_malformed_page_parameters(world, body):
    response = world.client.post(PREVIEW, json=body)
    assert response.status_code == 422, response.text


def test_offset_past_the_end_gives_an_empty_page(world):
    _auto_pairs(world, 2)
    first = world.preview(limit=1)

    page = world.preview(limit=1, offset=10, plan_hash=first["plan_hash"])

    assert page["items"] == [] and page["page"] == {"offset": 10, "limit": 1, "total": 2, "has_more": False}


# --- «Все VLAN» на обоих портах, но номера различаются --------------------------------------------

def test_all_vlans_on_both_ports_with_different_numbers_is_excluded_from_the_plan_not_blocked(world):
    """У устройств разные наборы VLAN: ни «объединить», ни «взять набор» не поможет — пара остаётся как есть и
    называется «Исключено правилом», а не «Нельзя применить» с непонятной причиной."""
    (a,) = world.device("BOTHA", ["Gi0/1"], allowed=(10, 20, 30))
    (b,) = world.device("BOTHB", ["Gi0/1"], allowed=(10, 20))
    world.configure(a, mode="trunk", all_vlans=True)
    world.configure(b, mode="trunk", all_vlans=True)
    connection = world.connect(a, b)

    plan = world.preview()

    (item,) = plan["items"]
    assert item["connection_id"] == connection and item["outcome"] == "ignored"
    assert item["rule"]["code"] == ALL_VLANS_BOTH_RULE
    assert plan["summary"]["ignored"] == 1 and plan["summary"]["blocked"] == 0 and plan["summary"]["applicable"] == 0
    assert world.apply(plan)["applied"] == {"ports": 0, "connections": 0}
    assert world.port(a)["vlans"] == [10, 20, 30] and world.port(b)["vlans"] == [10, 20]
    assert world.status(connection) == "mismatch"  # в сверке расхождение остаётся: его можно одобрить на дашборде


def test_all_vlans_on_both_ports_still_lets_a_role_mismatch_through(world):
    (a,) = world.device("ROLEA", ["Gi0/1"], allowed=(10, 20, 30))
    (b,) = world.device("ROLEB", ["Gi0/1"], allowed=(10, 20, 30))
    world.configure(a, mode="trunk", all_vlans=True)
    world.configure(b, mode="trunk", all_vlans=True, role=(True, False))
    world.connect(a, b)

    plan = world.preview()

    (item,) = plan["items"]
    assert item["rule"]["code"] == ROLE_MATCH_RULE and item["outcome"] == "manual"  # роль решает человек, как и раньше
