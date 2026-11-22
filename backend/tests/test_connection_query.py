"""Серверная выборка подключений для дашборда: пагинация, фильтры, поиск, итоги, «одобрить все
найденные». Плюс проверка, что статус, посчитанный в SQL (фильтр и счётчики), совпадает со
статусом Python-логики (port_config.evaluate_port_config) на всех комбинациях.

Запуск: pytest backend/tests/test_connection_query.py -v
"""

from __future__ import annotations

from itertools import product

import pytest

from app.models import Connection, DeviceInterface, InterfaceVLAN, VLAN
from app.services.port_config import PortConfig, PortConfigStatus, PortRole, approval_signature, evaluate_port_config, role_from_flags

ROLE_FLAGS = {
    PortRole.NONE: (False, False),
    PortRole.MANAGEMENT: (True, False),
    PortRole.DATA: (False, True),
    PortRole.MANAGEMENT_DATA: (True, True),
}


def _device_type(client) -> str:
    category_id = client.get("/api/v1/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    return client.post("/api/v1/resources/device-types", json={"name": "Тип для выборки", "category_id": category_id}).json()["id"]


@pytest.fixture()
def cable(client) -> str:
    return client.post("/api/v1/resources/connection-types", json={"name": "Витая пара (выборка)"}).json()["id"]


@pytest.fixture()
def device_type(client) -> str:
    return _device_type(client)


def _device(client, device_type_id: str, serial: str, ports: list[dict], system_name: str | None = None) -> list[str]:
    """Создаёт устройство с портами, возвращает id портов в порядке ports."""
    payload = {"device_type_id": device_type_id, "serial_number": serial}
    if system_name:
        payload["system_name"] = system_name
    device = client.post("/api/v1/resources/devices", json=payload).json()
    response = client.put(f"/api/v1/devices/{device['id']}/interfaces", json={"interfaces": ports})
    assert response.status_code == 200, response.text
    by_name = {i["name"]: i["id"] for i in response.json()["items"]}
    return [by_name[p["name"]] for p in ports]


def _port(name: str, role: PortRole = PortRole.DATA) -> dict:
    management, data = ROLE_FLAGS[role]
    return {"name": name, "is_management": management, "is_data_transfer": data}


def _connect(client, source: str, destination: str, cable_id: str, **extra) -> dict:
    response = client.post(
        "/api/v1/resources/connections",
        json={"source_interface_id": source, "destination_interface_id": destination, "connection_type_id": cable_id, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _page(client, **params) -> dict:
    response = client.get("/api/v1/connections", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(page: dict) -> list[str]:
    return [c["id"] for c in page["items"]]


def _many(client, device_type, cable, count: int, role_a=PortRole.DATA, role_b=PortRole.DATA, prefix="L") -> list[dict]:
    """count подключений между двумя устройствами: порты p0..p{count-1}."""
    a = _device(client, device_type, f"{prefix}-A", [_port(f"p{i}", role_a) for i in range(count)], system_name=f"{prefix}-a")
    b = _device(client, device_type, f"{prefix}-B", [_port(f"p{i}", role_b) for i in range(count)], system_name=f"{prefix}-b")
    return [_connect(client, x, y, cable) for x, y in zip(a, b)]


# --- пагинация ---------------------------------------------------------------------------


def test_pagination_returns_slices_in_stable_order_with_total(client, device_type, cable):
    created = _many(client, device_type, cable, 7)

    first = _page(client, offset=0, limit=3)
    second = _page(client, offset=3, limit=3)
    third = _page(client, offset=6, limit=3)

    assert (first["total"], first["offset"], first["limit"]) == (7, 0, 3)
    assert _ids(first) + _ids(second) + _ids(third) == [c["id"] for c in created]
    assert len(third["items"]) == 1


def test_offset_beyond_total_gives_empty_page_but_correct_total(client, device_type, cable):
    _many(client, device_type, cable, 2)
    page = _page(client, offset=50, limit=10)
    assert page["items"] == []
    assert page["total"] == 2


def test_empty_registry(client):
    page = _page(client)
    assert page["items"] == [] and page["total"] == 0
    assert page["summary"] == {"total": 0, "active": 0, "inactive": 0, "mismatch": 0, "approved": 0}


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"port_config_status": "bogus"}, {"is_active": "maybe"}, {"q": "x" * 201}])
def test_invalid_query_params_are_rejected(client, params):
    assert client.get("/api/v1/connections", params=params).status_code == 422


def test_rows_carry_names_roles_and_status(client, device_type, cable):
    (a,) = _device(client, device_type, "N-A", [_port("idrac", PortRole.MANAGEMENT)], system_name="srv-01")
    (b,) = _device(client, device_type, "N-B", [_port("Gi0/5", PortRole.DATA)], system_name="sw-01")
    _connect(client, a, b, cable)

    row = _page(client)["items"][0]

    assert (row["source_device_name"], row["source_interface_name"]) == ("srv-01", "idrac")
    assert (row["destination_device_name"], row["destination_interface_name"]) == ("sw-01", "Gi0/5")
    assert (row["source_port_role"], row["destination_port_role"], row["port_config_status"]) == ("management", "data", "mismatch")
    assert "port_config_approved_signature" not in row


# --- фильтры -----------------------------------------------------------------------------


def test_filter_by_status(client, device_type, cable):
    ok = _many(client, device_type, cable, 2, PortRole.DATA, PortRole.DATA, "OK")
    bad = _many(client, device_type, cable, 3, PortRole.MANAGEMENT, PortRole.DATA, "BAD")
    client.post("/api/v1/connections/port-config/approve", json={"connection_ids": [bad[0]["id"]]})

    assert sorted(_ids(_page(client, port_config_status="ok"))) == sorted(c["id"] for c in ok)
    assert sorted(_ids(_page(client, port_config_status="mismatch"))) == sorted(c["id"] for c in bad[1:])
    assert _ids(_page(client, port_config_status="approved")) == [bad[0]["id"]]


def test_filter_by_activity_and_inactive_are_never_mismatch(client, device_type, cable):
    a, b = _device(client, device_type, "ACT-A", [_port("p1", PortRole.MANAGEMENT)]), _device(client, device_type, "ACT-B", [_port("p1", PortRole.DATA)])
    inactive = _connect(client, a[0], b[0], cable, is_active=False)

    assert _ids(_page(client, is_active="false")) == [inactive["id"]]
    assert _page(client, is_active="true")["items"] == []
    assert _page(client, port_config_status="mismatch")["items"] == []
    assert _page(client)["summary"]["inactive"] == 1


def test_total_reflects_filters_but_summary_does_not(client, device_type, cable):
    _many(client, device_type, cable, 2, PortRole.DATA, PortRole.DATA, "S1")
    _many(client, device_type, cable, 3, PortRole.MANAGEMENT, PortRole.DATA, "S2")

    page = _page(client, port_config_status="mismatch", limit=2)

    assert page["total"] == 3 and len(page["items"]) == 2
    assert page["summary"] == {"total": 5, "active": 5, "inactive": 0, "mismatch": 3, "approved": 0}


# --- поиск -------------------------------------------------------------------------------


def test_database_lower_is_unicode_aware(db_session):
    """Встроенный LOWER() SQLite не трогает кириллицу; без Unicode-aware замены (app/db.py) поиск
    по «Коммутатор» при вводе «коммутатор» ничего бы не находил."""
    from sqlalchemy import text

    assert db_session.execute(text("SELECT lower('Коммутатор ABC')")).scalar() == "коммутатор abc"
    assert db_session.execute(text("SELECT lower(NULL)")).scalar() is None


def test_search_is_case_insensitive_for_cyrillic(client, device_type, cable):
    (a,) = _device(client, device_type, "C-A", [_port("eth0")], system_name="Коммутатор-Ядро")
    (b,) = _device(client, device_type, "C-B", [_port("eth0")], system_name="srv-02")
    target = _connect(client, a, b, cable)
    (other_a,) = _device(client, device_type, "C-C", [_port("eth0")], system_name="fw-01")
    (other_b,) = _device(client, device_type, "C-D", [_port("eth0")], system_name="fw-02")
    _connect(client, other_a, other_b, cable)

    assert _ids(_page(client, q="коммутатор")) == [target["id"]]
    assert _ids(_page(client, q="КОММУТАТОР-ядро")) == [target["id"]]


def test_search_matches_devices_ports_cable_type_and_role_labels(client, device_type, cable):
    (a,) = _device(client, device_type, "F-A", [_port("idrac", PortRole.MANAGEMENT)], system_name="srv-77")
    (b,) = _device(client, device_type, "F-B", [_port("Gi0/9", PortRole.DATA)], system_name="sw-77")
    conn = _connect(client, a, b, cable)
    c, d = _device(client, device_type, "F-C", [_port("x1", PortRole.DATA)]), _device(client, device_type, "F-D", [_port("x2", PortRole.DATA)])
    _connect(client, c[0], d[0], cable)

    for needle in ("srv-77", "SW-77", "idrac", "gi0/9", "витая пара", "управление"):
        assert conn["id"] in _ids(_page(client, q=needle)), needle
    # «управление» есть только у подключения с портом управления; у второго обе роли — данные.
    assert _ids(_page(client, q="управление")) == [conn["id"]]
    assert _page(client, q="нет такого")["items"] == []


def test_search_falls_back_to_serial_number_when_system_name_is_empty(client, device_type, cable):
    (a,) = _device(client, device_type, "SERIAL-XYZ-1", [_port("p1")])
    (b,) = _device(client, device_type, "SERIAL-XYZ-2", [_port("p1")], system_name="named")
    conn = _connect(client, a, b, cable)
    assert _ids(_page(client, q="serial-xyz-1")) == [conn["id"]]


def test_search_treats_percent_and_underscore_literally(client, device_type, cable):
    (a,) = _device(client, device_type, "E-A", [_port("port_1")], system_name="srv_a")
    (b,) = _device(client, device_type, "E-B", [_port("port-1")], system_name="srvXa")
    conn = _connect(client, a, b, cable)

    assert _ids(_page(client, q="srv_a")) == [conn["id"]]  # «_» не «любой символ»
    assert _page(client, q="%")["items"] == []  # «%» не «всё»


def test_search_and_filters_combine_and_paginate(client, device_type, cable):
    _many(client, device_type, cable, 5, PortRole.MANAGEMENT, PortRole.DATA, "Ядро")
    _many(client, device_type, cable, 2, PortRole.DATA, PortRole.DATA, "Ядро2")

    page = _page(client, q="ядро", port_config_status="mismatch", limit=2, offset=2)

    assert page["total"] == 5 and len(page["items"]) == 2
    assert all(c["port_config_status"] == "mismatch" for c in page["items"])


# --- одобрить все найденные --------------------------------------------------------------


def test_approve_match_approves_all_matching_mismatches_across_pages(client, device_type, cable):
    bad = _many(client, device_type, cable, 5, PortRole.MANAGEMENT, PortRole.DATA, "M")
    other = _many(client, device_type, cable, 2, PortRole.MANAGEMENT, PortRole.DATA, "Z")
    ok = _many(client, device_type, cable, 2, PortRole.DATA, PortRole.DATA, "K")

    response = client.post("/api/v1/connections/port-config/approve", json={"match": {"q": "m-a"}})

    assert response.status_code == 200
    assert response.json() == {"items": [], "skipped_ids": [], "approved_count": 5}
    approved = _ids(_page(client, port_config_status="approved", limit=200))
    assert sorted(approved) == sorted(c["id"] for c in bad)
    # Не подпавшие под поиск расхождения и подключения без расхождения не тронуты.
    assert sorted(_ids(_page(client, port_config_status="mismatch"))) == sorted(c["id"] for c in other)
    assert sorted(_ids(_page(client, port_config_status="ok"))) == sorted(c["id"] for c in ok)


def test_approve_match_without_conditions_approves_every_mismatch(client, device_type, cable):
    _many(client, device_type, cable, 3, PortRole.MANAGEMENT, PortRole.DATA, "All")
    assert client.post("/api/v1/connections/port-config/approve", json={"match": {}}).json()["approved_count"] == 3
    assert _page(client)["summary"]["mismatch"] == 0


def test_approve_match_is_idempotent(client, device_type, cable):
    _many(client, device_type, cable, 2, PortRole.MANAGEMENT, PortRole.DATA, "Id")
    client.post("/api/v1/connections/port-config/approve", json={"match": {}})
    assert client.post("/api/v1/connections/port-config/approve", json={"match": {}}).json()["approved_count"] == 0


def test_approve_match_handles_more_rows_than_one_chunk(client, device_type, cable, monkeypatch):
    from app.services import connection_review

    monkeypatch.setattr(connection_review, "_APPROVE_CHUNK", 2)
    _many(client, device_type, cable, 5, PortRole.MANAGEMENT, PortRole.DATA, "Ch")

    assert client.post("/api/v1/connections/port-config/approve", json={"match": {}}).json()["approved_count"] == 5
    assert _page(client)["summary"]["approved"] == 5


def test_approve_match_writes_one_audit_record_per_connection(client, device_type, cable):
    created = _many(client, device_type, cable, 3, PortRole.MANAGEMENT, PortRole.DATA, "Au")
    client.post("/api/v1/connections/port-config/approve", json={"match": {}})
    entries = client.get("/api/v1/resources/audit-log", params={"limit": 1000}).json()["items"]
    approved_entries = [e for e in entries if e["entity_type"] == "connections" and e["details"].startswith("Одобрено расхождение")]
    assert sorted(e["entity_id"] for e in approved_entries) == sorted(c["id"] for c in created)


@pytest.mark.parametrize("match", ["abc", [], {"q": 5}, {"q": "x" * 201}, {"is_active": "yes"}])
def test_approve_match_validates_conditions(client, match):
    assert client.post("/api/v1/connections/port-config/approve", json={"match": match}).status_code == 422


# --- запросы не растут с размером страницы -----------------------------------------------


def test_query_count_does_not_grow_with_page_size(client, device_type, cable, sql_log):
    _many(client, device_type, cable, 12, PortRole.MANAGEMENT, PortRole.DATA, "Q")

    def statements_for(limit: int) -> int:
        sql_log.clear()
        _page(client, limit=limit)
        return len(sql_log)

    small, large = statements_for(2), statements_for(12)
    assert large == small


# --- SQL-статус == Python-статус ---------------------------------------------------------


def test_sql_status_matches_python_status_for_all_combinations(client, db_session, device_type, cable):
    """96 подключений: 4 роли источника × 4 роли назначения × 3 состояния подписи одобрения
    (нет / верная / чужая) × активно-неактивно. Для каждого статус из SQL-фильтра, из счётчиков и
    из строки списка (Python) обязан совпасть с evaluate_port_config()."""
    combos = list(product(PortRole, PortRole, ("none", "right", "wrong"), (True, False)))
    src_ports = _device(client, device_type, "PAR-A", [_port(f"p{i}", src) for i, (src, _, _, _) in enumerate(combos)], system_name="par-a")
    dst_ports = _device(client, device_type, "PAR-B", [_port(f"p{i}", dst) for i, (_, dst, _, _) in enumerate(combos)], system_name="par-b")

    expected: dict[str, PortConfigStatus] = {}
    for (src_role, dst_role, sig_kind, active), src_id, dst_id in zip(combos, src_ports, dst_ports):
        src_cfg, dst_cfg = PortConfig(src_role), PortConfig(dst_role)
        signature = {"none": None, "right": approval_signature(src_cfg, dst_cfg), "wrong": "data>none"}[sig_kind]
        conn = Connection(
            source_interface_id=src_id, destination_interface_id=dst_id, connection_type_id=cable, is_active=active, port_config_approved_signature=signature
        )
        db_session.add(conn)
        db_session.flush()
        expected[conn.id] = evaluate_port_config(src_cfg, dst_cfg, signature, is_active=active)
    db_session.commit()
    assert len(expected) == 96

    everything = _page(client, limit=200)
    assert everything["total"] == 96
    assert {c["id"]: c["port_config_status"] for c in everything["items"]} == {k: v.value for k, v in expected.items()}
    for status in PortConfigStatus:
        wanted = sorted(k for k, v in expected.items() if v is status)
        assert sorted(_ids(_page(client, limit=200, port_config_status=status.value))) == wanted, status
        assert _page(client, port_config_status=status.value)["total"] == len(wanted)
    summary = everything["summary"]
    assert summary["mismatch"] == sum(v is PortConfigStatus.MISMATCH for v in expected.values())
    assert summary["approved"] == sum(v is PortConfigStatus.APPROVED for v in expected.values())
    assert (summary["total"], summary["active"], summary["inactive"]) == (96, 48, 48)
    # Роль порта в строке тоже совпадает с исходной.
    assert {c["source_port_role"] for c in everything["items"]} == {r.value for r in PortRole}
    assert role_from_flags(*ROLE_FLAGS[PortRole.DATA]) is PortRole.DATA


VLAN_SETS = ((), (10,), (10, 20), (20, 10, 30))


def test_sql_status_matches_python_status_for_roles_modes_vlans_and_approvals(client, db_session, device_type, cable):
    """Те же гарантии для режима порта и набора VLAN: 2 роли × 2 роли × 2 режима × 2 режима ×
    4 набора VLAN × 4 набора VLAN × 3 состояния подписи = 768 подключений. Статус из SQL (фильтр,
    счётчики) и из Python (строка списка) обязан совпасть с evaluate_port_config() — в том числе
    формат подписи: подпись, посчитанная Python, должна опознаваться SQL-выражением как «верная»."""
    roles = (PortRole.NONE, PortRole.DATA)
    modes = ("trunk", "access")
    combos = list(product(roles, roles, modes, modes, VLAN_SETS, VLAN_SETS, ("none", "right", "wrong")))
    # Порты не переиспользуются между подключениями, чтобы у каждого был свой набор настроек.
    src_ports = _device(client, device_type, "PV-A", [_port(f"p{i}", c[0]) for i, c in enumerate(combos)], system_name="pv-a")
    dst_ports = _device(client, device_type, "PV-B", [_port(f"p{i}", c[1]) for i, c in enumerate(combos)], system_name="pv-b")

    vlan_rows = {n: VLAN(vlan_id=n, name=f"vlan{n}") for n in (10, 20, 30)}
    db_session.add_all(vlan_rows.values())
    db_session.flush()

    def configure(interface_id: str, mode: str, vlans: tuple[int, ...]) -> None:
        db_session.get(DeviceInterface, interface_id).vlan_mode = mode
        db_session.add_all(InterfaceVLAN(interface_id=interface_id, vlan_id=vlan_rows[n].id, mode=mode) for n in vlans)

    expected: dict[str, PortConfigStatus] = {}
    for (src_role, dst_role, src_mode, dst_mode, src_vlans, dst_vlans, sig_kind), src_id, dst_id in zip(combos, src_ports, dst_ports):
        configure(src_id, src_mode, src_vlans)
        configure(dst_id, dst_mode, dst_vlans)
        src_cfg, dst_cfg = PortConfig(src_role, src_mode, frozenset(src_vlans)), PortConfig(dst_role, dst_mode, frozenset(dst_vlans))
        signature = {"none": None, "right": approval_signature(src_cfg, dst_cfg) or None, "wrong": "data>none|mode:trunk>access"}[sig_kind]
        conn = Connection(source_interface_id=src_id, destination_interface_id=dst_id, connection_type_id=cable, port_config_approved_signature=signature)
        db_session.add(conn)
        db_session.flush()
        expected[conn.id] = evaluate_port_config(src_cfg, dst_cfg, signature)
    db_session.commit()
    assert len(expected) == 768
    assert {PortConfigStatus.OK, PortConfigStatus.MISMATCH, PortConfigStatus.APPROVED} == set(expected.values())

    def fetch_all(**params) -> list[dict]:
        items: list[dict] = []
        while True:
            page = _page(client, limit=200, offset=len(items), **params)
            items += page["items"]
            if len(items) >= page["total"]:
                return items

    assert {c["id"]: c["port_config_status"] for c in fetch_all()} == {k: v.value for k, v in expected.items()}
    for status in PortConfigStatus:
        wanted = sorted(k for k, v in expected.items() if v is status)
        assert sorted(c["id"] for c in fetch_all(port_config_status=status.value)) == wanted, status
    summary = _page(client)["summary"]
    assert summary["mismatch"] == sum(v is PortConfigStatus.MISMATCH for v in expected.values())
    assert summary["approved"] == sum(v is PortConfigStatus.APPROVED for v in expected.values())


def test_status_expression_checks_for_an_approval_before_building_the_signature():
    """Оптимизация горячего пути: подпись расхождения (с отпечатками VLAN обоих портов) строится, только если у подключения
    вообще есть одобрение. Без `IS NOT NULL` впереди СУБД считала бы отпечатки четыре лишних раза на каждое неодобренное
    подключение — счётчики и фильтр по статусу замедлялись втрое-вчетверо на реестре в десятки тысяч подключений."""
    from sqlalchemy.dialects import sqlite

    from app.services.connection_query import _Joined

    sql = str(_Joined().status.compile(dialect=sqlite.dialect()))

    guard = sql.index("connections.port_config_approved_signature IS NOT NULL AND connections.port_config_approved_signature =")
    assert guard > 0
