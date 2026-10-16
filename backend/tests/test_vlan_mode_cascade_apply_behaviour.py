"""Применение каскада смены режима порта — что именно записывается, считается и попадает в журнал
(services/vlan_mode_cascade.py: apply_vlan_mode_cascade и _load_details). Фиксирует поведение до снижения
сложности этих функций (код-ревью, п. 10; сложность 18 и 16) и дополняет tests/test_vlan_mode_cascade.py,
который проверяет построение плана: сюда вынесено то, что там не проверялось — тексты аудита, счётчики
applied, перезапись связей порта и группы, группа с «Все VLAN», единичный порт устройства с открытой формой.

Тесты написаны на прежнем коде и проходят без правок после рефакторинга.
Запуск: pytest backend/tests/test_vlan_mode_cascade_apply_behaviour.py -v
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models import AuditLog, InterfaceGroup, InterfaceGroupVLAN, InterfaceVLAN
from app.services.vlan_mode_cascade import apply_vlan_mode_cascade, preview_vlan_mode_cascade

API = "/api/v1"


# Файлы тестов самодостаточны (общих хелперов в репозитории нет), поэтому сценарии собираются здесь же.
def _vlan(client, number: int) -> dict:
    return client.post(f"{API}/resources/vlans", json={"vlan_id": number, "name": f"VLAN {number}"}).json()


def _device(client, serial: str, vlans: tuple[dict, ...]) -> dict:
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    device_type = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    for vlan in vlans:
        client.post(f"{API}/resources/device-type-vlans", json={"device_type_id": device_type["id"], "vlan_id": vlan["id"]})
    return client.post(f"{API}/resources/devices", json={"device_type_id": device_type["id"], "serial_number": serial, "system_name": serial}).json()


def _sync(client, device_id: str, interfaces: list[dict], groups: list[dict] | None = None) -> None:
    body: dict = {"interfaces": interfaces}
    if groups is not None:
        body["groups"] = groups
    response = client.put(f"{API}/devices/{device_id}/interfaces", json=body)
    assert response.status_code == 200, response.text


def _ports(client, device_id: str) -> dict[str, dict]:
    items = client.get(f"{API}/resources/interfaces", params={"physical_device_id": device_id, "limit": 1000}).json()["items"]
    return {item["name"]: item for item in items}


@pytest.fixture()
def cable(client) -> str:
    return client.post(f"{API}/resources/connection-types", json={"name": "Витая пара (применение каскада)"}).json()["id"]


def _connect(client, cable_id: str, a: dict, b: dict) -> None:
    response = client.post(f"{API}/resources/connections", json={"source_interface_id": a["id"], "destination_interface_id": b["id"], "connection_type_id": cable_id})
    assert response.status_code == 201, response.text


def _cascade(client, port: dict, mode: str, edited: dict | None = None):
    """Предпросмотр, затем применение с хешем из него — как делает форма."""
    plan = client.post(f"{API}/interfaces/{port['id']}/vlan-mode-cascade/preview", json={"mode": mode, "edited": edited}).json()
    return client.post(f"{API}/interfaces/{port['id']}/vlan-mode-cascade", json={"mode": mode, "edited": edited, "plan_hash": plan["hash"], "confirm": True})


def _edited_device(device_id: str, ports: dict | None = None) -> dict:
    return {"device_id": device_id, "ports": ports or {}, "groups": {}}


def _audit_by_device(db_session, **names: str) -> dict[str, str]:
    """Записи аудита каскада: {имя устройства: текст}. names: {имя: id устройства}."""
    db_session.expire_all()
    by_id = {value: key for key, value in names.items()}
    rows = db_session.query(AuditLog).filter(AuditLog.details.like("Каскадная смена%")).all()
    assert all(row.action == "UPDATE" and row.entity_type == "interfaces" for row in rows)
    return {by_id[row.entity_id]: row.details for row in rows}


def _links(db_session, port_id: str) -> list[InterfaceVLAN]:
    db_session.expire_all()
    return list(db_session.query(InterfaceVLAN).filter_by(interface_id=port_id).all())


@pytest.fixture()
def group_pair(client, cable):
    """Два устройства (VLAN 10 и 20), у каждого группа из двух портов trunk, a1–b1 и a2–b2 соединены."""
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    devices = {name: _device(client, f"APL-{name}", (v10, v20)) for name in ("A", "B")}
    for name, device in devices.items():
        _sync(client, device["id"], [{"name": f"{name.lower()}1", "group_key": "g"}, {"name": f"{name.lower()}2", "group_key": "g"}],
              [{"key": "g", "name": f"Группа {name}", "vlan_mode": "trunk", "vlan_ids": [v10["id"], v20["id"]]}])
    pa, pb = _ports(client, devices["A"]["id"]), _ports(client, devices["B"]["id"])
    _connect(client, cable, pa["a1"], pb["b1"])
    _connect(client, cable, pa["a2"], pb["b2"])
    return devices, pa, pb, (v10, v20)


class TestRequestChecks:
    @pytest.mark.parametrize("body", [[], "mode", None, 5])
    @pytest.mark.parametrize("operation", [apply_vlan_mode_cascade, preview_vlan_mode_cascade])
    def test_body_must_be_an_object(self, db_session, operation, body):
        with pytest.raises(HTTPException) as exc_info:
            operation("any-port", body, db_session)
        assert (exc_info.value.status_code, exc_info.value.detail) == (422, "Тело запроса должно быть объектом")

    @pytest.mark.parametrize("confirm", [None, False, "true", 1, "yes"])
    def test_only_boolean_true_confirms_the_apply(self, db_session, confirm):
        with pytest.raises(HTTPException) as exc_info:
            apply_vlan_mode_cascade("any-port", {"mode": "access", "confirm": confirm}, db_session)
        assert (exc_info.value.status_code, exc_info.value.detail) == (422, "Применение требует подтверждения: confirm = true")

    def test_mode_and_edited_are_checked_before_confirmation(self, db_session):
        with pytest.raises(HTTPException) as bad_mode:
            apply_vlan_mode_cascade("any-port", {"mode": "hybrid"}, db_session)
        with pytest.raises(HTTPException) as bad_edited:
            apply_vlan_mode_cascade("any-port", {"mode": "access", "edited": []}, db_session)
        assert bad_mode.value.detail == "Режим порта должен быть 'access' или 'trunk'"
        assert bad_edited.value.detail == "Поле edited должно быть объектом с непустым device_id"

    def test_confirmation_is_checked_before_the_port_is_looked_up(self, db_session):
        with pytest.raises(HTTPException) as exc_info:
            apply_vlan_mode_cascade("нет-такого", {"mode": "access"}, db_session)
        assert exc_info.value.status_code == 422
        with pytest.raises(HTTPException) as unknown:
            apply_vlan_mode_cascade("нет-такого", {"mode": "access", "confirm": True}, db_session)
        assert (unknown.value.status_code, unknown.value.detail) == (404, "Порт не найден")

    def test_missing_plan_hash_is_a_conflict_and_writes_nothing(self, client, db_session, group_pair):
        devices, pa, pb, _ = group_pair
        response = client.post(f"{API}/interfaces/{pb['b1']['id']}/vlan-mode-cascade", json={"mode": "access", "confirm": True})
        assert response.status_code == 409
        assert response.json()["detail"] == "Данные изменились после предпросмотра — повторите операцию и проверьте новый план"
        assert {p["vlan_mode"] for p in [*_ports(client, devices["A"]["id"]).values(), *_ports(client, devices["B"]["id"]).values()]} == {"trunk"}
        assert _audit_by_device(db_session, A=devices["A"]["id"], B=devices["B"]["id"]) == {}


class TestAppliedGroups:
    def test_result_counts_ports_groups_devices_and_returns_written_ports(self, client, group_pair):
        _, _, pb, _ = group_pair
        body = _cascade(client, pb["b1"], "access").json()
        assert body["applied"] == {"ports": 4, "groups": 2, "devices": 2}
        assert body["port_written"] is False
        assert sorted(i["name"] for i in body["interfaces"]) == ["a1", "a2", "b1", "b2"]
        assert {i["vlan_mode"] for i in body["interfaces"]} == {"access"}

    def test_audit_has_one_record_per_device_with_group_and_dropped_vlan_text(self, client, db_session, group_pair):
        devices, _, pb, _ = group_pair
        _cascade(client, pb["b1"], "access")
        assert _audit_by_device(db_session, A=devices["A"]["id"], B=devices["B"]["id"]) == {
            "A": "Каскадная смена режима порта → access (инициатор: порт «b1» устройства «APL-B»); группы: «Группа A» (2 портов); сняты VLAN 20 у «Группа A»",
            "B": "Каскадная смена режима порта → access (инициатор: порт «b1» устройства «APL-B»); группы: «Группа B» (2 портов); сняты VLAN 20 у «Группа B»",
        }

    def test_kept_vlan_rows_of_group_and_ports_are_updated_in_place_and_dropped_ones_deleted(self, client, db_session, group_pair):
        _, pa, _, (v10, v20) = group_pair
        group_row_ids_before = {r.id for r in db_session.query(InterfaceGroupVLAN).all()}
        assert len(group_row_ids_before) == 4  # две группы по два VLAN
        port_links = {link.vlan_id: link.id for link in _links(db_session, pa["a1"]["id"])}
        assert set(port_links) == {v10["id"], v20["id"]}

        _cascade(client, pa["a1"], "access")

        db_session.expire_all()
        after_rows = db_session.query(InterfaceGroupVLAN).all()
        assert [r.vlan_id for r in after_rows] == [v10["id"]] * 2  # у каждой из двух групп осталась одна строка — VLAN 10
        assert {r.id for r in after_rows} <= group_row_ids_before  # оставшиеся строки — прежние записи, а не пересозданные
        for port_name, ports in (("a1", pa), ("a2", pa)):
            links = _links(db_session, ports[port_name]["id"])
            assert [(link.vlan_id, link.mode) for link in links] == [(v10["id"], "access")]
        assert [link.id for link in _links(db_session, pa["a1"]["id"])] == [port_links[v10["id"]]]
        assert all(g.vlan_mode == "access" and g.all_vlans is False for g in db_session.query(InterfaceGroup).all())

    def test_trunk_keeps_every_vlan_and_only_switches_link_mode(self, client, db_session, cable):
        v10, v20 = _vlan(client, 10), _vlan(client, 20)
        a, b = _device(client, "APL-TA", (v10, v20)), _device(client, "APL-TB", (v10, v20))
        _sync(client, a["id"], [{"name": "a1", "vlan_mode": "access", "vlan_ids": [v10["id"]]}])
        _sync(client, b["id"], [{"name": "b1", "vlan_mode": "access", "vlan_ids": [v20["id"]]}])
        pa, pb = _ports(client, a["id"])["a1"], _ports(client, b["id"])["b1"]
        _connect(client, cable, pa, pb)

        body = _cascade(client, pa, "trunk").json()

        assert body["applied"] == {"ports": 2, "groups": 0, "devices": 2}
        assert [(link.vlan_id, link.mode) for link in _links(db_session, pa["id"])] == [(v10["id"], "trunk")]
        assert [(link.vlan_id, link.mode) for link in _links(db_session, pb["id"])] == [(v20["id"], "trunk")]
        assert _audit_by_device(db_session, A=a["id"], B=b["id"]) == {
            "A": "Каскадная смена режима порта → trunk (инициатор: порт «a1» устройства «APL-TA»); порты: a1",
            "B": "Каскадная смена режима порта → trunk (инициатор: порт «a1» устройства «APL-TA»); порты: b1",
        }


class TestGroupWithAllVlans:
    """У группы с «Все VLAN» своих строк VLAN нет: набор — все VLAN устройства (services/port_vlans.py)."""

    @pytest.fixture()
    def scenario(self, client, cable):
        v10, v20 = _vlan(client, 10), _vlan(client, 20)
        a, b = _device(client, "APL-VA", (v10, v20)), _device(client, "APL-VB", (v10, v20))
        _sync(client, a["id"], [{"name": "a1", "vlan_mode": "trunk", "vlan_ids": [v10["id"], v20["id"]]}])
        _sync(client, b["id"], [{"name": "b1", "group_key": "g"}, {"name": "b2", "group_key": "g"}], [{"key": "g", "name": "Все", "vlan_mode": "trunk", "all_vlans": True}])
        pa, pb = _ports(client, a["id"]), _ports(client, b["id"])
        _connect(client, cable, pa["a1"], pb["b1"])
        return a, b, pa, pb, (v10, v20)

    def test_plan_takes_all_device_vlans_as_before_and_lowest_as_after(self, client, scenario):
        _, _, pa, _, (v10, v20) = scenario
        plan = _cascade(client, pa["a1"], "access").json()["plan"]
        (group,) = plan["groups"]
        assert [v["vlan_id"] for v in group["vlans_before"]] == [10, 20]
        assert [v["vlan_id"] for v in group["vlans_after"]] == [10]
        assert [v["vlan_id"] for v in group["dropped_vlans"]] == [20]
        assert group["vlans_before"][0]["id"] == v10["id"] and group["dropped_vlans"][0]["id"] == v20["id"]

    def test_flag_is_dropped_and_explicit_vlan_rows_are_written_for_group_and_ports(self, client, db_session, scenario):
        a, b, pa, pb, (v10, _) = scenario
        assert db_session.query(InterfaceGroupVLAN).count() == 0

        body = _cascade(client, pa["a1"], "access").json()

        assert body["applied"] == {"ports": 3, "groups": 1, "devices": 2}
        assert sorted(i["name"] for i in body["interfaces"]) == ["a1", "b1", "b2"]
        db_session.expire_all()
        group = db_session.query(InterfaceGroup).one()
        assert (group.vlan_mode, group.all_vlans) == ("access", False)
        assert [r.vlan_id for r in db_session.query(InterfaceGroupVLAN).all()] == [v10["id"]]
        for port in (pb["b1"], pb["b2"], pa["a1"]):
            assert [(link.vlan_id, link.mode) for link in _links(db_session, port["id"])] == [(v10["id"], "access")]
        assert {i["name"]: i["all_vlans"] for i in body["interfaces"]} == {"a1": False, "b1": False, "b2": False}
        assert _audit_by_device(db_session, A=a["id"], B=b["id"]) == {
            "A": "Каскадная смена режима порта → access (инициатор: порт «a1» устройства «APL-VA»); порты: a1; сняты VLAN 20 у «a1»",
            "B": "Каскадная смена режима порта → access (инициатор: порт «a1» устройства «APL-VA»); группы: «Все» (2 портов); сняты VLAN 20 у «Все»",
        }


class TestDeferredSinglePort:
    """Порт устройства с открытой формой (edited) попадает в план, но не пишется, не считается и не журналируется."""

    @pytest.fixture()
    def scenario(self, client, cable):
        v10, v20 = _vlan(client, 10), _vlan(client, 20)
        a, b = _device(client, "APL-DA", (v10, v20)), _device(client, "APL-DB", (v10, v20))
        for device, name in ((a, "a1"), (b, "b1")):
            _sync(client, device["id"], [{"name": name, "vlan_mode": "trunk", "vlan_ids": [v10["id"], v20["id"]]}])
        pa, pb = _ports(client, a["id"])["a1"], _ports(client, b["id"])["b1"]
        _connect(client, cable, pa, pb)
        return a, b, pa, pb, (v10, v20)

    def test_edited_devices_port_is_only_planned(self, client, db_session, scenario):
        a, b, pa, pb, (v10, v20) = scenario

        body = _cascade(client, pb, "access", _edited_device(a["id"])).json()

        assert {p["name"]: p["deferred"] for p in body["plan"]["ports"]} == {"a1": True, "b1": False}
        assert body["plan"]["totals"] == {**body["plan"]["totals"], "ports": 2, "deferred_ports": 1, "immediate_ports": 1, "immediate_devices": 1}
        assert body["applied"] == {"ports": 1, "groups": 0, "devices": 1}
        assert [i["name"] for i in body["interfaces"]] == ["b1"]
        assert _ports(client, a["id"])["a1"]["vlan_mode"] == "trunk"
        assert {link.vlan_id for link in _links(db_session, pa["id"])} == {v10["id"], v20["id"]}
        assert [(link.vlan_id, link.mode) for link in _links(db_session, pb["id"])] == [(v10["id"], "access")]
        assert _audit_by_device(db_session, A=a["id"], B=b["id"]) == {
            "B": "Каскадная смена режима порта → access (инициатор: порт «b1» устройства «APL-DB»); порты: b1; сняты VLAN 20 у «b1»",
        }

    def test_draft_vlan_of_a_form_port_is_taken_into_the_plan_deduplicated(self, client, scenario):
        a, _, pa, pb, (v10, v20) = scenario
        draft = _edited_device(a["id"], {pa["id"]: {"mode": "trunk", "vlan_ids": [v20["id"], v10["id"], v20["id"]]}})

        plan = client.post(f"{API}/interfaces/{pb['id']}/vlan-mode-cascade/preview", json={"mode": "access", "edited": draft}).json()

        port = next(p for p in plan["ports"] if p["name"] == "a1")
        assert [v["vlan_id"] for v in port["vlans_before"]] == [10, 20]  # по номеру VLAN, без повтора
        assert [v["vlan_id"] for v in port["vlans_after"]] == [10] and [v["vlan_id"] for v in port["dropped_vlans"]] == [20]

    def test_draft_vlan_missing_from_the_catalog_sorts_first_and_is_kept_in_access(self, client, scenario):
        """VLAN, которого нет в справочнике (id из черновика устарел), считается наименьшим: остаётся он, а настоящий снимается."""
        a, _, pa, pb, (v10, _) = scenario
        draft = _edited_device(a["id"], {pa["id"]: {"mode": "trunk", "vlan_ids": [v10["id"], "устарел"]}})

        plan = client.post(f"{API}/interfaces/{pb['id']}/vlan-mode-cascade/preview", json={"mode": "access", "edited": draft}).json()

        port = next(p for p in plan["ports"] if p["name"] == "a1")
        assert port["vlans_before"] == [{"id": "устарел", "vlan_id": None, "name": ""}, {"id": v10["id"], "vlan_id": 10, "name": "VLAN 10"}]
        assert [v["id"] for v in port["vlans_after"]] == ["устарел"] and [v["id"] for v in port["dropped_vlans"]] == [v10["id"]]
