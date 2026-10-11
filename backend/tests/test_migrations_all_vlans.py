"""Миграция f1a6c3d8e279 — «Все VLAN» как сохраняемый признак (device_interfaces.all_vlans, interface_groups.all_vlans).

upgrade(): колонки добавляются, признак проставляется по прежнему правилу формы (trunk и назначены ВСЕ VLAN,
доступные устройству: VLAN типа ∪ VLAN самого устройства, при непустом наборе), а связи таких портов и групп
удаляются — их набор теперь вычисляется из VLAN устройства. downgrade() возвращает связи со всеми VLAN устройства
(прежний код читает именно связи) и снимает колонки; остальные порты и группы не трогаются.

Запуск: pytest backend/tests/test_migrations_all_vlans.py -v
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent
PRE_REVISION = "c4a8f1d6b937"
ALL_VLANS_REV = "f1a6c3d8e279"


def _uid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    """См. идентичную fixture в test_migrations_interface_group_ip_purpose.py."""
    import app.config as app_config

    db_path = tmp_path / "migration_test.db"
    monkeypatch.setattr(app_config, "DATABASE_URL", f"sqlite:///{db_path}")
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg, db_path


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _vlan(conn: sqlite3.Connection, number: int) -> str:
    vlan_id = _uid()
    conn.execute("INSERT INTO vlans (id, vlan_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (vlan_id, number, f"vlan{number}", _now(), _now()))
    return vlan_id


def _device(conn: sqlite3.Connection, *, type_vlans: tuple[str, ...] = (), own_vlans: tuple[str, ...] = ()) -> str:
    category_id = conn.execute("SELECT id FROM device_categories LIMIT 1").fetchone()[0]
    type_id, device_id = _uid(), _uid()
    conn.execute("INSERT INTO device_types (id, name, category_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (type_id, f"Тип {type_id[:8]}", category_id, _now(), _now()))
    for vlan_id in type_vlans:
        conn.execute("INSERT INTO device_type_vlans (id, device_type_id, vlan_id) VALUES (?, ?, ?)", (_uid(), type_id, vlan_id))
    conn.execute(
        "INSERT INTO physical_devices (id, device_type_id, serial_number, siem_enabled, created_at, updated_at) VALUES (?, ?, ?, 0, ?, ?)",
        (device_id, type_id, device_id[:12], _now(), _now()),
    )
    for vlan_id in own_vlans:
        conn.execute("INSERT INTO physical_device_vlans (id, physical_device_id, vlan_id) VALUES (?, ?, ?)", (_uid(), device_id, vlan_id))
    return device_id


def _port(conn: sqlite3.Connection, device_id: str, name: str, mode: str, vlans: tuple[str, ...]) -> str:
    port_id = _uid()
    conn.execute(
        "INSERT INTO device_interfaces (id, physical_device_id, name, is_management, is_data_transfer, vlan_mode, created_at, updated_at) VALUES (?, ?, ?, 0, 0, ?, ?, ?)",
        (port_id, device_id, name, mode, _now(), _now()),
    )
    for vlan_id in vlans:
        conn.execute("INSERT INTO interface_vlans (id, interface_id, vlan_id, mode, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", (_uid(), port_id, vlan_id, mode, _now(), _now()))
    return port_id


def _group(conn: sqlite3.Connection, device_id: str, name: str, mode: str, vlans: tuple[str, ...]) -> str:
    group_id = _uid()
    conn.execute(
        "INSERT INTO interface_groups (id, physical_device_id, name, vlan_mode, manage_open_ports, created_at, updated_at) VALUES (?, ?, ?, ?, 0, ?, ?)",
        (group_id, device_id, name, mode, _now(), _now()),
    )
    for vlan_id in vlans:
        conn.execute("INSERT INTO interface_group_vlans (id, group_id, vlan_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (_uid(), group_id, vlan_id, _now(), _now()))
    return group_id


def _port_links(conn: sqlite3.Connection, port_id: str) -> set[str]:
    return {r[0] for r in conn.execute("SELECT vlan_id FROM interface_vlans WHERE interface_id=?", (port_id,))}


def _group_links(conn: sqlite3.Connection, group_id: str) -> set[str]:
    return {r[0] for r in conn.execute("SELECT vlan_id FROM interface_group_vlans WHERE group_id=?", (group_id,))}


@pytest.fixture()
def legacy(alembic_config):
    """БД на ревизии до миграции с данными, где «Все VLAN» была состоянием (набор == все VLAN устройства)."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    conn = _connect(db_path)
    v10, v20, v30 = _vlan(conn, 10), _vlan(conn, 20), _vlan(conn, 30)
    device = _device(conn, type_vlans=(v10,), own_vlans=(v20,))  # доступны 10 и 20
    bare = _device(conn)  # у устройства нет доступных VLAN
    ids = {
        "all": _port(conn, device, "all", "trunk", (v10, v20)),  # все доступные — будет «Все VLAN»
        "all_plus_foreign": _port(conn, device, "all+foreign", "trunk", (v10, v20, v30)),  # все доступные и чужой VLAN
        "subset": _port(conn, device, "subset", "trunk", (v10,)),
        "access": _port(conn, device, "access", "access", (v10,)),
        "empty_trunk": _port(conn, device, "empty", "trunk", ()),
        "bare_trunk": _port(conn, bare, "bare", "trunk", ()),  # набор доступных пуст — «всех» нет
        "group_all": _group(conn, device, "all", "trunk", (v10, v20)),
        "group_subset": _group(conn, device, "subset", "trunk", (v20,)),
        "group_access": _group(conn, device, "access", "access", (v10,)),
    }
    conn.commit()
    conn.close()
    return cfg, db_path, ids, {"v10": v10, "v20": v20, "v30": v30}


def test_upgrade_adds_columns_flags_all_vlans_ports_and_drops_their_links(legacy):
    cfg, db_path, ids, vlan = legacy

    command.upgrade(cfg, ALL_VLANS_REV)

    conn = _connect(db_path)
    try:
        assert "all_vlans" in _columns(conn, "device_interfaces") and "all_vlans" in _columns(conn, "interface_groups")
        flags = {name: bool(conn.execute("SELECT all_vlans FROM device_interfaces WHERE id=?", (ids[name],)).fetchone()[0]) for name in ("all", "all_plus_foreign", "subset", "access", "empty_trunk", "bare_trunk")}
        assert flags == {"all": True, "all_plus_foreign": True, "subset": False, "access": False, "empty_trunk": False, "bare_trunk": False}
        # набор порта с признаком вычисляется из VLAN устройства — связей у него больше нет
        assert _port_links(conn, ids["all"]) == set() and _port_links(conn, ids["all_plus_foreign"]) == set()
        # остальные порты не тронуты
        assert _port_links(conn, ids["subset"]) == {vlan["v10"]} and _port_links(conn, ids["access"]) == {vlan["v10"]}
    finally:
        conn.close()


def test_upgrade_flags_groups_by_the_same_rule(legacy):
    cfg, db_path, ids, vlan = legacy

    command.upgrade(cfg, ALL_VLANS_REV)

    conn = _connect(db_path)
    try:
        flags = {name: bool(conn.execute("SELECT all_vlans FROM interface_groups WHERE id=?", (ids[name],)).fetchone()[0]) for name in ("group_all", "group_subset", "group_access")}
        assert flags == {"group_all": True, "group_subset": False, "group_access": False}
        assert _group_links(conn, ids["group_all"]) == set()
        assert _group_links(conn, ids["group_subset"]) == {vlan["v20"]} and _group_links(conn, ids["group_access"]) == {vlan["v10"]}
    finally:
        conn.close()


def test_downgrade_restores_links_with_every_vlan_of_the_device_and_drops_the_columns(legacy):
    cfg, db_path, ids, vlan = legacy
    command.upgrade(cfg, ALL_VLANS_REV)

    command.downgrade(cfg, PRE_REVISION)

    conn = _connect(db_path)
    try:
        assert "all_vlans" not in _columns(conn, "device_interfaces") and "all_vlans" not in _columns(conn, "interface_groups")
        both = {vlan["v10"], vlan["v20"]}
        assert _port_links(conn, ids["all"]) == both
        assert _port_links(conn, ids["all_plus_foreign"]) == both  # чужой VLAN признак не хранил — после отката только VLAN устройства
        assert {r["mode"] for r in conn.execute("SELECT mode FROM interface_vlans WHERE interface_id=?", (ids["all"],))} == {"trunk"}
        assert _port_links(conn, ids["subset"]) == {vlan["v10"]} and _port_links(conn, ids["access"]) == {vlan["v10"]}
        assert _port_links(conn, ids["empty_trunk"]) == set() and _port_links(conn, ids["bare_trunk"]) == set()
        assert _group_links(conn, ids["group_all"]) == both
        assert _group_links(conn, ids["group_subset"]) == {vlan["v20"]}
        # сами порты и группы на месте
        assert conn.execute("SELECT count(*) FROM device_interfaces").fetchone()[0] == 6
        assert conn.execute("SELECT count(*) FROM interface_groups").fetchone()[0] == 3
    finally:
        conn.close()


def test_upgrade_after_downgrade_round_trips(legacy):
    cfg, db_path, ids, vlan = legacy

    command.upgrade(cfg, ALL_VLANS_REV)
    command.downgrade(cfg, PRE_REVISION)
    command.upgrade(cfg, ALL_VLANS_REV)

    conn = _connect(db_path)
    try:
        assert bool(conn.execute("SELECT all_vlans FROM device_interfaces WHERE id=?", (ids["all"],)).fetchone()[0]) is True
        assert _port_links(conn, ids["all"]) == set() and _port_links(conn, ids["subset"]) == {vlan["v10"]}
    finally:
        conn.close()
