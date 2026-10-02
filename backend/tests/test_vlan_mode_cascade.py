"""Каскадная смена режима порта (access/trunk) — services/vlan_mode_cascade.py.

Предыдущее поведение: «Применить текущую конфигурацию» в форме устройства писало режим соседнему
порту прямым PUT, не зная о группах. Если порт соседа состоял в группе, задающей режим, значение
возвращалось при следующем сохранении его устройства, а менять режим у всех портов группы и у
связанных с ними портов приходилось вручную.

Главный инвариант: после применения на границе области изменения НЕТ расхождений режима — любое
подключение, один из портов которого изменён, соединяет порты с одинаковым режимом.

Запуск: pytest backend/tests/test_vlan_mode_cascade.py -v
"""
from __future__ import annotations

import pytest

API = "/api/v1"


def _vlan(client, number: int) -> dict:
    r = client.post(f"{API}/resources/vlans", json={"vlan_id": number, "name": f"VLAN {number}"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _device(client, serial: str, vlans: tuple[dict, ...] = ()) -> dict:
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    dt = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    for v in vlans:
        client.post(f"{API}/resources/device-type-vlans", json={"device_type_id": dt["id"], "vlan_id": v["id"]})
    return client.post(f"{API}/resources/devices", json={"device_type_id": dt["id"], "serial_number": serial, "system_name": serial}).json()


def _sync(client, device_id: str, interfaces: list[dict], groups: list[dict] | None = None) -> dict:
    body: dict = {"interfaces": interfaces}
    if groups is not None:
        body["groups"] = groups
    r = client.put(f"{API}/devices/{device_id}/interfaces", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _ports(client, device_id: str) -> dict[str, dict]:
    items = client.get(f"{API}/resources/interfaces", params={"physical_device_id": device_id, "limit": 1000}).json()["items"]
    return {x["name"]: x for x in items}


def _links(client, iface_id: str) -> list[dict]:
    items = client.get(f"{API}/resources/interface-vlans", params={"limit": 1000}).json()["items"]
    return [x for x in items if x["interface_id"] == iface_id]


def _groups(client, device_id: str) -> dict[str, dict]:
    items = client.get(f"{API}/devices/{device_id}/interface-groups").json()["items"]
    return {g["name"]: g for g in items}


@pytest.fixture()
def cable(client) -> str:
    return client.post(f"{API}/resources/connection-types", json={"name": "Витая пара (каскад режима)"}).json()["id"]


def _connect(client, cable_id: str, a: dict, b: dict, **extra) -> None:
    r = client.post(f"{API}/resources/connections", json={"source_interface_id": a["id"], "destination_interface_id": b["id"], "connection_type_id": cable_id, **extra})
    assert r.status_code == 201, r.text


def _edited(device_id: str | None, ports: dict[str, str] | None = None, groups: dict[str, str] | None = None) -> dict | None:
    """Состояние формы редактируемого устройства; без ports/groups сервер берёт режимы из БД."""
    return {"device_id": device_id, "ports": ports or {}, "groups": groups or {}} if device_id else None


def _preview(client, port: dict, mode: str, edited: str | dict | None = None):
    edited = _edited(edited) if isinstance(edited, str) else edited
    return client.post(f"{API}/interfaces/{port['id']}/vlan-mode-cascade/preview", json={"mode": mode, "edited": edited})


def _apply(client, port: dict, mode: str, edited: str | dict | None = None, **override):
    edited = _edited(edited) if isinstance(edited, str) else edited
    plan = _preview(client, port, mode, edited).json()
    body = {"mode": mode, "edited": edited, "plan_hash": plan["hash"], "confirm": True, **override}
    return client.post(f"{API}/interfaces/{port['id']}/vlan-mode-cascade", json=body)


def _modes(client, device_id: str) -> dict[str, str]:
    return {name: p["vlan_mode"] for name, p in _ports(client, device_id).items()}


def _codes(plan: dict) -> set[str]:
    return {w["code"] for w in plan["warnings"]}


# --- Простые случаи -------------------------------------------------------------------------------


def test_single_neighbor_port_is_changed_and_nothing_else(client, cable):
    a, b = _device(client, "CAS-A"), _device(client, "CAS-B")
    _sync(client, a["id"], [{"name": "a1", "vlan_mode": "trunk"}])
    _sync(client, b["id"], [{"name": "b1", "vlan_mode": "access"}, {"name": "b2", "vlan_mode": "access"}])
    a1, b1 = _ports(client, a["id"])["a1"], _ports(client, b["id"])["b1"]
    _connect(client, cable, a1, b1)

    r = _apply(client, b1, "trunk")

    assert r.status_code == 200, r.text
    body = r.json()
    # a1 уже trunk — в область он не входит; меняется только b1
    assert (body["plan"]["totals"]["ports"], body["applied"]["ports"]) == (1, 1)
    assert _modes(client, b["id"]) == {"b1": "trunk", "b2": "access"}  # b2 не связан — не тронут
    assert _modes(client, a["id"]) == {"a1": "trunk"}
    assert [(i["name"], i["vlan_mode"]) for i in body["interfaces"]] == [("b1", "trunk")]  # для обновления кэша клиента


def test_preview_does_not_write_anything(client, cable):
    a, b = _device(client, "CAS-PRV-A"), _device(client, "CAS-PRV-B")
    _sync(client, a["id"], [{"name": "a1", "vlan_mode": "trunk"}])
    _sync(client, b["id"], [{"name": "b1", "vlan_mode": "access"}])
    a1, b1 = _ports(client, a["id"])["a1"], _ports(client, b["id"])["b1"]
    _connect(client, cable, a1, b1)

    plan = _preview(client, b1, "trunk").json()

    assert plan["empty"] is False and plan["totals"]["ports"] == 1
    assert _modes(client, b["id"]) == {"b1": "access"} and _modes(client, a["id"]) == {"a1": "trunk"}


def test_nothing_to_change_gives_empty_plan(client):
    a = _device(client, "CAS-EMPTY")
    _sync(client, a["id"], [{"name": "a1", "vlan_mode": "access"}])
    a1 = _ports(client, a["id"])["a1"]

    plan = _preview(client, a1, "access").json()
    applied = _apply(client, a1, "access").json()

    assert plan["empty"] is True and plan["warnings"] == []
    assert applied["applied"] == {"ports": 0, "groups": 0, "devices": 0}


# --- Группы и каскад ------------------------------------------------------------------------------


def _group_pair(client, cable, *, vlans: bool = True):
    """Два коммутатора с группами по два порта, соединённые «крест-накрест» (a1-b1, a2-b2); режим trunk."""
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    a = _device(client, "CAS-GA", (v10, v20))
    b = _device(client, "CAS-GB", (v10, v20))
    vlan_ids = [v10["id"], v20["id"]] if vlans else []
    for dev, prefix in ((a, "a"), (b, "b")):
        _sync(
            client,
            dev["id"],
            [{"name": f"{prefix}1", "group_key": "g"}, {"name": f"{prefix}2", "group_key": "g"}, {"name": f"{prefix}3"}],
            [{"key": "g", "name": f"Группа {prefix.upper()}", "vlan_mode": "trunk", "vlan_ids": vlan_ids}],
        )
    pa, pb = _ports(client, a["id"]), _ports(client, b["id"])
    _connect(client, cable, pa["a1"], pb["b1"])
    _connect(client, cable, pa["a2"], pb["b2"])
    return a, b, pa, pb, (v10, v20)


def test_group_of_neighbor_changes_as_a_whole_and_cascades_to_the_other_group(client, cable):
    a, b, pa, pb, _ = _group_pair(client, cable)

    r = _apply(client, pb["b1"], "access")

    assert r.status_code == 200, r.text
    plan = r.json()["plan"]
    assert {g["name"] for g in plan["groups"]} == {"Группа A", "Группа B"}
    assert plan["totals"] == {**plan["totals"], "ports": 4, "groups": 2, "devices": 2, "deferred_ports": 0}
    # у обеих групп и у всех их портов — access, и порты вне групп не тронуты
    assert _modes(client, a["id"]) == {"a1": "access", "a2": "access", "a3": "trunk"}
    assert _modes(client, b["id"]) == {"b1": "access", "b2": "access", "b3": "trunk"}
    assert {g["vlan_mode"] for g in [*_groups(client, a["id"]).values(), *_groups(client, b["id"]).values()]} == {"access"}
    assert {"groups", "cascade", "immediate"} <= _codes(plan)


def test_after_apply_no_conflict_remains_on_the_boundary(client, cable):
    a, b, pa, pb, _ = _group_pair(client, cable)

    _apply(client, pb["b1"], "access")

    # повторный предпросмотр из любого порта области — пустой: расхождений не осталось
    for port in (pa["a1"], pa["a2"], pb["b1"], pb["b2"]):
        assert _preview(client, port, "access").json()["empty"] is True


def test_trunk_to_access_keeps_lowest_vlan_in_group_and_ports_and_lists_dropped(client, cable):
    a, b, pa, pb, (v10, v20) = _group_pair(client, cable)

    plan = _preview(client, pb["b1"], "access").json()
    dropped = [(g["name"], [v["vlan_id"] for v in g["dropped_vlans"]]) for g in plan["groups"]]
    assert sorted(dropped) == [("Группа A", [20]), ("Группа B", [20])]
    assert "vlans_dropped" in _codes(plan) and plan["totals"]["dropped_vlans"] == 2

    _apply(client, pb["b1"], "access")

    for dev, ports in ((a, pa), (b, pb)):
        group = next(iter(_groups(client, dev["id"]).values()))
        assert [v for v in group["vlan_ids"]] == [v10["id"]]
        prefix = "a" if dev is a else "b"
        for name in (f"{prefix}1", f"{prefix}2"):
            links = _links(client, _ports(client, dev["id"])[name]["id"])
            assert [(link["vlan_id"], link["mode"]) for link in links] == [(v10["id"], "access")]


def test_access_to_trunk_keeps_assigned_vlans_and_does_not_add_new_ones(client, cable):
    v10, v20 = _vlan(client, 10), _vlan(client, 20)
    a, b = _device(client, "CAS-AT-A", (v10, v20)), _device(client, "CAS-AT-B", (v10, v20))
    for dev, name in ((a, "a1"), (b, "b1")):
        _sync(client, dev["id"], [{"name": name, "group_key": "g"}], [{"key": "g", "name": "Г", "vlan_mode": "access", "vlan_ids": [v10["id"]]}])
    pa, pb = _ports(client, a["id"])["a1"], _ports(client, b["id"])["b1"]
    _connect(client, cable, pa, pb)

    plan = _preview(client, pb, "trunk").json()
    assert "trunk" in _codes(plan) and "vlans_dropped" not in _codes(plan)

    _apply(client, pb, "trunk")

    assert [(x["vlan_id"], x["mode"]) for x in _links(client, _ports(client, b["id"])["b1"]["id"])] == [(v10["id"], "trunk")]
    assert next(iter(_groups(client, b["id"]).values()))["vlan_ids"] == [v10["id"]]


def test_individual_port_with_several_vlans_keeps_lowest_number(client, cable):
    v30, v10 = _vlan(client, 30), _vlan(client, 10)
    a, b = _device(client, "CAS-IND-A", (v10, v30)), _device(client, "CAS-IND-B", (v10, v30))
    _sync(client, a["id"], [{"name": "a1", "vlan_mode": "access"}])
    _sync(client, b["id"], [{"name": "b1", "vlan_mode": "trunk", "vlan_ids": [v30["id"], v10["id"]]}])
    pa, pb = _ports(client, a["id"])["a1"], _ports(client, b["id"])["b1"]
    _connect(client, cable, pa, pb)

    r = _apply(client, pa, "trunk")  # a1 -> trunk: b1 уже trunk, область — только a1
    assert r.json()["plan"]["totals"]["ports"] == 1

    r = _apply(client, pb, "access")  # b1 -> access: два VLAN -> остаётся 10, снимается 30; a1 тоже станет access

    assert r.status_code == 200, r.text
    assert [x["vlan_id"] for x in _links(client, _ports(client, b["id"])["b1"]["id"])] == [v10["id"]]
    assert _modes(client, a["id"]) == {"a1": "access"}


def test_chain_of_three_devices_is_followed_to_the_end(client, cable):
    a, b, c = _device(client, "CAS-CH-A"), _device(client, "CAS-CH-B"), _device(client, "CAS-CH-C")
    _sync(client, a["id"], [{"name": "a1", "vlan_mode": "trunk"}])
    _sync(client, b["id"], [{"name": "b1", "group_key": "g"}, {"name": "b2", "group_key": "g"}], [{"key": "g", "name": "Г", "vlan_mode": "trunk"}])
    _sync(client, c["id"], [{"name": "c1", "vlan_mode": "trunk"}, {"name": "c2", "vlan_mode": "access"}])
    pa, pb, pc = _ports(client, a["id"]), _ports(client, b["id"]), _ports(client, c["id"])
    _connect(client, cable, pa["a1"], pb["b1"])
    _connect(client, cable, pb["b2"], pc["c1"])

    _apply(client, pa["a1"], "access")

    assert _modes(client, a["id"]) == {"a1": "access"}
    assert _modes(client, b["id"]) == {"b1": "access", "b2": "access"}
    assert _modes(client, c["id"]) == {"c1": "access", "c2": "access"}


def test_ports_already_in_target_mode_do_not_extend_the_area(client, cable):
    """b1 уже в целевом режиме — граница области. Собственное расхождение b2 с c1 (другое подключение
    того же устройства) к этой операции не относится и не затрагивается."""
    a, b, c = _device(client, "CAS-ST-A"), _device(client, "CAS-ST-B"), _device(client, "CAS-ST-C")
    _sync(client, a["id"], [{"name": "a1", "vlan_mode": "trunk"}])
    _sync(client, b["id"], [{"name": "b1", "vlan_mode": "access"}, {"name": "b2", "vlan_mode": "access"}])
    _sync(client, c["id"], [{"name": "c1", "vlan_mode": "trunk"}])
    pa, pb, pc = _ports(client, a["id"])["a1"], _ports(client, b["id"]), _ports(client, c["id"])["c1"]
    _connect(client, cable, pa, pb["b1"])
    _connect(client, cable, pb["b2"], pc)  # b2 (access) и c1 (trunk) уже расходятся

    plan = _apply(client, pa, "access").json()["plan"]

    assert plan["totals"]["ports"] == 1
    assert _modes(client, c["id"]) == {"c1": "trunk"}


def test_inactive_connections_are_ignored_and_reported(client, cable):
    a, b = _device(client, "CAS-IN-A"), _device(client, "CAS-IN-B")
    _sync(client, a["id"], [{"name": "a1", "vlan_mode": "trunk"}])
    _sync(client, b["id"], [{"name": "b1", "vlan_mode": "access"}])
    pa, pb = _ports(client, a["id"])["a1"], _ports(client, b["id"])["b1"]
    _connect(client, cable, pa, pb, is_active=False)

    r = _apply(client, pa, "access")

    assert r.json()["plan"]["totals"]["ports"] == 1 and _modes(client, b["id"]) == {"b1": "access"}
    plan = _preview(client, pb, "trunk").json()
    assert plan["totals"]["ports"] == 1 and "inactive" in _codes(plan)  # a1 уже access, соединён неактивно


# --- Редактируемое устройство ---------------------------------------------------------------------


def test_edited_device_is_reported_as_deferred_and_not_written(client, cable):
    a, b, pa, pb, _ = _group_pair(client, cable)

    r = _apply(client, pb["b1"], "access", edited=a["id"])

    assert r.status_code == 200, r.text
    plan = r.json()["plan"]
    assert plan["totals"]["deferred_ports"] == 2 and plan["totals"]["immediate_ports"] == 2
    assert {d["name"]: d["deferred"] for d in plan["devices"]} == {"CAS-GA": True, "CAS-GB": False}
    assert {g["name"]: g["deferred"] for g in plan["groups"]} == {"Группа A": True, "Группа B": False}
    assert _modes(client, a["id"]) == {"a1": "trunk", "a2": "trunk", "a3": "trunk"}  # устройство формы — только в план
    assert _modes(client, b["id"]) == {"b1": "access", "b2": "access", "b3": "trunk"}
    assert next(iter(_groups(client, a["id"]).values()))["vlan_mode"] == "trunk"
    assert {"deferred", "immediate"} <= _codes(plan)
    assert r.json()["applied"] == {"ports": 2, "groups": 1, "devices": 1}


# --- Протокол предпросмотр/применение ------------------------------------------------------------


def test_apply_requires_explicit_confirmation(client, cable):
    a, b, pa, pb, _ = _group_pair(client, cable)

    r = _apply(client, pb["b1"], "access", confirm=False)

    assert r.status_code == 422
    assert _modes(client, b["id"])["b1"] == "trunk"


def test_apply_rejects_plan_that_changed_since_preview(client, cable):
    a, b, pa, pb, _ = _group_pair(client, cable)
    stale_hash = _preview(client, pb["b1"], "access").json()["hash"]
    # между предпросмотром и применением кто-то вывел порт из группы
    group_id = next(iter(_groups(client, b["id"]).values()))["id"]
    _sync(
        client,
        b["id"],
        [{"id": pb["b1"]["id"], "name": "b1"}, {"id": pb["b2"]["id"], "name": "b2", "group_key": group_id}, {"id": pb["b3"]["id"], "name": "b3"}],
        [{"id": group_id, "key": group_id, "name": "Группа B", "vlan_mode": "trunk"}],
    )

    r = client.post(f"{API}/interfaces/{pb['b1']['id']}/vlan-mode-cascade", json={"mode": "access", "plan_hash": stale_hash, "confirm": True})

    assert r.status_code == 409


def test_invalid_mode_and_unknown_port(client):
    a = _device(client, "CAS-ERR")
    _sync(client, a["id"], [{"name": "a1"}])
    a1 = _ports(client, a["id"])["a1"]

    assert _preview(client, a1, "hybrid").status_code == 422
    assert client.post(f"{API}/interfaces/no-such-port/vlan-mode-cascade/preview", json={"mode": "access"}).status_code == 404
    assert client.post(f"{API}/interfaces/no-such-port/vlan-mode-cascade", json={"mode": "access", "confirm": True}).status_code == 404


@pytest.mark.parametrize(
    "edited",
    [
        "not-an-object",
        {"ports": {}},  # нет device_id
        {"device_id": "d", "ports": {"p": "hybrid"}},
        {"device_id": "d", "ports": []},  # список вместо объекта
        {"device_id": "d", "groups": {"g": "hybrid"}},
    ],
)
def test_malformed_edited_state_is_rejected(client, edited):
    a = _device(client, "CAS-BAD-EDITED")
    _sync(client, a["id"], [{"name": "a1"}])
    a1 = _ports(client, a["id"])["a1"]

    r = client.post(f"{API}/interfaces/{a1['id']}/vlan-mode-cascade/preview", json={"mode": "access", "edited": edited})

    assert r.status_code == 422


# --- Состояние формы редактируемого устройства ---------------------------------------------------


def _edited_pair(client, cable):
    """Сервер (редактируемый, одиночный порт s1 trunk в БД) соединён с коммутатором (порт w1 trunk).
    В форме пользователь переключил s1 в access — из-за этого расхождение с w1."""
    s, w = _device(client, "CAS-ED-SRV"), _device(client, "CAS-ED-SW")
    _sync(client, s["id"], [{"name": "s1", "vlan_mode": "trunk"}])
    _sync(client, w["id"], [{"name": "w1", "vlan_mode": "trunk"}])
    ps, pw = _ports(client, s["id"])["s1"], _ports(client, w["id"])["w1"]
    _connect(client, cable, ps, pw)
    return s, w, ps, pw


def test_draft_port_already_in_target_mode_is_not_part_of_the_area(client, cable):
    """Без состояния формы план по БД назвал бы изменяемым и сам порт формы (в БД он trunk)."""
    s, w, ps, pw = _edited_pair(client, cable)

    by_db = _preview(client, pw, "access", s["id"]).json()
    by_form = _preview(client, pw, "access", _edited(s["id"], ports={ps["id"]: "access"})).json()

    assert by_db["totals"]["ports"] == 2 and by_db["totals"]["deferred_ports"] == 1
    assert by_form["totals"] == {**by_form["totals"], "ports": 1, "deferred_ports": 0, "immediate_ports": 1}
    assert [p["name"] for p in by_form["ports"]] == ["w1"]


def test_draft_group_already_in_target_mode_is_not_part_of_the_area(client, cable):
    a, b, pa, pb, _ = _group_pair(client, cable)  # группа A (редактируемое устройство) в БД trunk
    group_a = next(iter(_groups(client, a["id"]).values()))
    form = _edited(a["id"], ports={pa["a1"]["id"]: "access", pa["a2"]["id"]: "access"}, groups={group_a["id"]: "access"})

    plan = _preview(client, pb["b1"], "access", form).json()

    assert [g["name"] for g in plan["groups"]] == ["Группа B"]  # группа формы уже access — не меняется и не распространяет
    assert plan["totals"] == {**plan["totals"], "ports": 2, "deferred_ports": 0}


def test_draft_port_that_differs_from_target_is_followed_even_if_db_already_matches(client, cable):
    """В БД порт формы уже access, но в черновике его вернули в trunk: к моменту сохранения формы он
    расходился бы с соседом — значит, он часть области, хотя по БД менять его не нужно."""
    s, w, ps, pw = _edited_pair(client, cable)
    _apply(client, ps, "access")  # БД: s1 -> access (и w1 -> access), затем вернём w1 в trunk
    _apply(client, pw, "trunk")  # БД: w1 -> trunk, s1 -> trunk
    client.put(f"{API}/devices/{s['id']}/interfaces", json={"interfaces": [{"id": ps["id"], "name": "s1", "vlan_mode": "access"}]})
    form = _edited(s["id"], ports={ps["id"]: "trunk"})

    by_db = _preview(client, pw, "access", s["id"]).json()
    by_form = _preview(client, pw, "access", form).json()

    assert [p["name"] for p in by_db["ports"]] == ["w1"]  # по БД s1 уже access — менять нечего
    assert {p["name"]: p["deferred"] for p in by_form["ports"]} == {"s1": True, "w1": False}  # по форме s1 — trunk


def test_group_without_mode_in_draft_is_treated_as_unmanaged(client, cable):
    """Пользователь снял управление режимом у группы формы: её порты — одиночные, по режимам из формы."""
    a, b, pa, pb, _ = _group_pair(client, cable)
    group_a = next(iter(_groups(client, a["id"]).values()))
    form = _edited(a["id"], ports={pa["a1"]["id"]: "trunk", pa["a2"]["id"]: "access"}, groups={group_a["id"]: ""})

    plan = _preview(client, pb["b1"], "access", form).json()

    # группа A не управляется -> a1 (trunk в форме) меняется как одиночный порт, a2 уже access и в область не входит
    assert [g["name"] for g in plan["groups"]] == ["Группа B"]
    assert [(p["name"], p["deferred"]) for p in plan["ports"]] == [("a1", True)]


def test_apply_uses_the_same_form_state_as_preview(client, cable):
    s, w, ps, pw = _edited_pair(client, cable)
    form = _edited(s["id"], ports={ps["id"]: "access"})

    r = _apply(client, pw, "access", form)

    assert r.status_code == 200, r.text
    assert r.json()["applied"] == {"ports": 1, "groups": 0, "devices": 1}
    assert _modes(client, w["id"]) == {"w1": "access"} and _modes(client, s["id"]) == {"s1": "trunk"}  # устройство формы сервер не пишет
    # другое состояние формы при применении -> другой план -> 409
    stale = _preview(client, pw, "trunk", _edited(s["id"], ports={ps["id"]: "access"})).json()["hash"]
    r = client.post(f"{API}/interfaces/{pw['id']}/vlan-mode-cascade", json={"mode": "trunk", "edited": _edited(s["id"], ports={ps["id"]: "trunk"}), "plan_hash": stale, "confirm": True})
    assert r.status_code == 409
