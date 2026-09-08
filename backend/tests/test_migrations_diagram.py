"""
Тесты на миграции d359e0bd414c (device_categories) и 38e9b2624a53 (device_types.category_id +
деструктивная очистка) — ТЗ диаграммы топологии сети, раздел 13:
  - "итоговая колонка device_types.category_id реально NOT NULL в DDL, а не только по
    метаданным SQLAlchemy (на SQLite ограничение может молча потеряться при
    batch_alter_table)" — проверяется через PRAGMA table_info, а не через ORM.
  - "ни один PhysicalDevice не остаётся без валидного device_type_id" (косвенно: ни один
    device_type не остаётся без category_id, и ни одно устройство удаляемых типов не выживает
    частично — либо удалено целиком со всеми зависимостями, либо не удалено вовсе).

Гоняется на одноразовой SQLite БД в /tmp — не трогает приложение и его тестовую БД.

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_migrations_diagram.py -v
"""
from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent
PRE_CATEGORY_REVISION = "0fcebbb67ac0"  # последняя ревизия до фичи диаграммы топологии сети
CATEGORIES_REVISION = "d359e0bd414c"  # device_categories создана и засеяна
DEVICE_TYPES_REVISION = "38e9b2624a53"  # деструктивная: category_id NOT NULL + очистка
DIAGRAM_ICONS_REVISION = "aa2365249bf7"  # diagram_icons + diagram_icon_id на моделях/устройствах
SAVED_DIAGRAMS_REVISION = "d4ba3ad6a222"  # saved_diagrams/diagram_layouts/diagram_group_states


def _uid() -> str:
    return str(uuid.uuid4())


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    """env.py всегда читает app.config.DATABASE_URL напрямую (см. alembic/env.py: `from
    app.config import DATABASE_URL`), игнорируя Config.set_main_option("sqlalchemy.url", ...) —
    поэтому URL временной БД подставляется через monkeypatch самого атрибута модуля, а не через
    Config. env.py исполняется заново при каждом вызове command.upgrade()/downgrade(), поэтому
    `from app.config import DATABASE_URL` там каждый раз подхватывает актуальное пропатченное
    значение."""
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


def test_device_categories_hierarchy_and_style(alembic_config):
    """Раздел 4.1 ТЗ: 8 категорий (7 из таблицы ТЗ + технический fallback), подкатегория
    'Коммутаторы' наследует цвет от родителя (сама его не задаёт), верхнеуровневая категория
    задаёт полный стиль."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, CATEGORIES_REVISION)
    conn = _connect(db_path)
    rows = {r["name"]: r for r in conn.execute("SELECT * FROM device_categories").fetchall()}
    assert len(rows) == 8
    switches = rows["Коммутаторы"]
    assert switches["parent_id"] == rows["Сетевая инфраструктура"]["id"]
    assert switches["diagram_shape"] == "switch"
    assert switches["diagram_color"] is None
    servers = rows["Серверы и СХД"]
    assert servers["parent_id"] is None
    assert servers["diagram_shape"] == "server"
    assert servers["diagram_color"] == "#4f7cff"
    conn.close()


def test_device_types_category_id_backfilled_and_not_null_in_ddl(alembic_config):
    """Раздел 13 ТЗ: category_id реально NOT NULL в DDL (PRAGMA table_info), не только по
    метаданным ORM; все 10 сохранённых стандартных типов получают верную категорию по карте
    раздела 4.1."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, DEVICE_TYPES_REVISION)
    conn = _connect(db_path)

    columns = {r["name"]: r for r in conn.execute("PRAGMA table_info(device_types)").fetchall()}
    assert columns["category_id"]["notnull"] == 1, "category_id должен быть NOT NULL в реальном DDL"

    rows = conn.execute(
        "SELECT dt.name AS type_name, dc.name AS category_name FROM device_types dt "
        "JOIN device_categories dc ON dt.category_id = dc.id"
    ).fetchall()
    by_type = {r["type_name"]: r["category_name"] for r in rows}
    assert by_type["Сервер"] == "Серверы и СХД"
    assert by_type["Точка доступа Wi-Fi"] == "Сетевая инфраструктура"
    assert by_type["Рабочий ПК администратора безопасности"] == "Администраторские рабочие места"
    # Ни одного типа устройства без категории не осталось (пустых category_id быть не может —
    # тут же дополнительно проверяем отсутствие NULL, раз DDL уже гарантирует NOT NULL).
    assert conn.execute("SELECT count(*) FROM device_types WHERE category_id IS NULL").fetchone()[0] == 0
    conn.close()


def test_removed_device_types_are_gone(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, DEVICE_TYPES_REVISION)
    conn = _connect(db_path)
    names = {r["name"] for r in conn.execute("SELECT name FROM device_types").fetchall()}
    assert "Сетевое оборудование" not in names
    assert "Средство защиты информации" not in names
    assert len(names) == 10  # 12 исходных - 2 удалённых; 7 новых добавляет seed_defaults() при старте приложения
    conn.close()


def test_destructive_cleanup_cascades_fully_and_spares_unrelated_device(alembic_config):
    """Основной сценарий раздела 4.2/13 ТЗ на реальной (не пустой) БД: устройство удаляемого типа
    со всеми зависимостями (интерфейс, подключение к ДРУГОМУ устройству, VLAN, размещённая VM
    с её IP/ПО/контейнером, отдельный контейнер на устройстве, связь с ИС, открытый порт) должно
    исчезнуть целиком; несвязанное устройство сохраняемого типа и его данные не должны
    пострадать; домен VLAN должен выжить с обнулённым source_device_id."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, CATEGORIES_REVISION)
    conn = _connect(db_path)
    now = "2026-01-01 00:00:00"

    def insert(table: str, **cols) -> None:
        keys = ",".join(cols)
        placeholders = ",".join("?" for _ in cols)
        conn.execute(f"INSERT INTO {table} ({keys}) VALUES ({placeholders})", list(cols.values()))

    def get_or_create_named(table: str, name: str) -> str:
        row = conn.execute(f"SELECT id FROM {table} WHERE name=?", (name,)).fetchone()
        if row:
            return row["id"]
        new_id = _uid()
        insert(table, id=new_id, name=name, created_at=now, updated_at=now)
        return new_id

    net_type = get_or_create_named("device_types", "Сетевое оборудование")
    server_type = get_or_create_named("device_types", "Сервер")

    switch, server = _uid(), _uid()
    insert("physical_devices", id=switch, device_type_id=net_type, serial_number="SW-1", system_name="sw-01", siem_enabled=0, created_at=now, updated_at=now)
    insert("physical_devices", id=server, device_type_id=server_type, serial_number="SRV-1", system_name="srv-01", siem_enabled=0, created_at=now, updated_at=now)

    iface_sw, iface_srv = _uid(), _uid()
    insert("device_interfaces", id=iface_sw, physical_device_id=switch, name="Gi0/1", is_management=1, is_data_transfer=0, created_at=now, updated_at=now)
    insert("device_interfaces", id=iface_srv, physical_device_id=server, name="eth0", is_management=0, is_data_transfer=1, created_at=now, updated_at=now)

    conn_type = get_or_create_named("connection_types", "Витая пара")
    connection = _uid()
    insert("connections", id=connection, source_interface_id=iface_sw, destination_interface_id=iface_srv, connection_type_id=conn_type, is_active=1, created_at=now, updated_at=now)

    vlan_domain = _uid()
    insert("vlan_domains", id=vlan_domain, name="Домен", source_device_id=switch, auto_sync=0, created_at=now, updated_at=now)
    vlan = _uid()
    insert("vlans", id=vlan, vlan_id=10, name="mgmt", domain_id=vlan_domain, created_at=now, updated_at=now)
    insert("physical_device_vlans", id=_uid(), physical_device_id=switch, vlan_id=vlan, is_management=1, created_at=now, updated_at=now)
    insert("interface_vlans", id=_uid(), interface_id=iface_sw, vlan_id=vlan, created_at=now, updated_at=now)

    vm = _uid()
    insert("virtual_machines", id=vm, name="vm-on-switch", physical_device_id=switch, status="active", created_at=now, updated_at=now)
    insert("vm_ips", id=_uid(), virtual_machine_id=vm, ip_address="10.0.0.50", is_management=0, created_at=now, updated_at=now)
    software = _uid()
    insert("software_assets", id=software, name="TestSoft", created_at=now, updated_at=now)
    insert("vm_software", id=_uid(), virtual_machine_id=vm, software_asset_id=software, created_at=now, updated_at=now)
    insert("device_software", id=_uid(), physical_device_id=switch, software_asset_id=software, created_at=now, updated_at=now)

    container_on_device, container_on_vm = _uid(), _uid()
    insert("containers", id=container_on_device, name="ctr-on-switch", physical_device_id=switch, created_at=now, updated_at=now)
    insert("containers", id=container_on_vm, name="ctr-on-vm", virtual_machine_id=vm, created_at=now, updated_at=now)
    insert("open_ports", id=_uid(), owner_type="physical_device", owner_id=switch, transport_protocol="TCP", port=22, created_at=now, updated_at=now)
    insert("open_ports", id=_uid(), owner_type="virtual_machine", owner_id=vm, transport_protocol="TCP", port=80, created_at=now, updated_at=now)

    isys = _uid()
    insert("information_systems", id=isys, name="ИС на удаляемом типе", type="ИС", siem_enabled=0, crypto_protection_enabled=0, status="active", created_at=now, updated_at=now)
    insert("information_system_devices", id=_uid(), information_system_id=isys, physical_device_id=switch, created_at=now, updated_at=now)
    insert("information_system_vms", id=_uid(), information_system_id=isys, virtual_machine_id=vm, created_at=now, updated_at=now)
    insert("information_system_containers", id=_uid(), information_system_id=isys, container_id=container_on_device, created_at=now, updated_at=now)
    insert("information_system_sources", id=_uid(), information_system_id=isys, source_type="device", physical_device_id=switch, external_interaction=0, created_at=now, updated_at=now)
    insert("information_system_ips", id=_uid(), information_system_id=isys, ip_address="10.0.0.1", external_interaction=0, physical_device_id=switch, created_at=now, updated_at=now)
    conn.commit()
    conn.close()

    command.upgrade(cfg, DEVICE_TYPES_REVISION)

    conn = _connect(db_path)

    def count(sql: str, *params) -> int:
        return conn.execute(sql, params).fetchone()[0]

    assert count("SELECT count(*) FROM device_types WHERE id=?", net_type) == 0
    assert count("SELECT count(*) FROM physical_devices WHERE id=?", switch) == 0
    assert count("SELECT count(*) FROM physical_devices WHERE id=?", server) == 1, "несвязанное устройство сохраняемого типа не должно пострадать"
    assert count("SELECT count(*) FROM device_interfaces WHERE id=?", iface_srv) == 1, "интерфейс сохраняемого устройства должен выжить"
    assert count("SELECT count(*) FROM connections WHERE id=?", connection) == 0, "связь с ОДНИМ концом на удаляемом устройстве удаляется целиком"
    assert count("SELECT count(*) FROM interface_vlans") == 0
    assert count("SELECT count(*) FROM physical_device_vlans") == 0
    assert count("SELECT count(*) FROM virtual_machines WHERE id=?", vm) == 0
    assert count("SELECT count(*) FROM vm_ips") == 0
    assert count("SELECT count(*) FROM vm_software") == 0
    assert count("SELECT count(*) FROM device_software") == 0
    assert count("SELECT count(*) FROM containers WHERE id=?", container_on_device) == 0
    assert count("SELECT count(*) FROM containers WHERE id=?", container_on_vm) == 0, "контейнер ВНУТРИ удаляемой ВМ тоже должен исчезнуть"
    assert count("SELECT count(*) FROM open_ports") == 0
    assert count("SELECT count(*) FROM information_system_devices") == 0
    assert count("SELECT count(*) FROM information_system_vms") == 0
    assert count("SELECT count(*) FROM information_system_containers") == 0
    assert count("SELECT count(*) FROM information_system_sources") == 0
    assert count("SELECT count(*) FROM information_system_ips") == 0
    assert count("SELECT count(*) FROM information_systems WHERE id=?", isys) == 1, "сама ИС — не устройство, не удаляется"

    domain_row = conn.execute("SELECT source_device_id FROM vlan_domains WHERE id=?", (vlan_domain,)).fetchone()
    assert domain_row is not None, "домен VLAN сам по себе не привязан к конкретному устройству — не удаляется"
    assert domain_row["source_device_id"] is None, "ссылка на удалённое устройство-источник обнуляется, а не блокирует удаление"
    conn.close()


def test_destructive_migration_downgrade_is_explicitly_unsupported(alembic_config):
    """downgrade() должен явно отказывать (не молча ломать БД и не притворяться, что откатил
    необратимо удалённые данные)."""
    cfg, _ = alembic_config
    command.upgrade(cfg, DEVICE_TYPES_REVISION)
    with pytest.raises(RuntimeError, match="не поддерживается"):
        command.downgrade(cfg, PRE_CATEGORY_REVISION)


def test_categories_migration_upgrade_downgrade_upgrade_cycle(alembic_config):
    """Раздел 5 ТЗ: миграция 1 (аддитивная, в отличие от миграции 2) должна проходить
    upgrade -> downgrade -> upgrade на одноразовой БД без ошибок."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, CATEGORIES_REVISION)
    command.downgrade(cfg, PRE_CATEGORY_REVISION)
    conn = _connect(db_path)
    table_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='device_categories'"
    ).fetchone()
    assert table_exists is None
    conn.close()
    command.upgrade(cfg, CATEGORIES_REVISION)
    conn = _connect(db_path)
    assert conn.execute("SELECT count(*) FROM device_categories").fetchone()[0] == 8
    conn.close()


def test_diagram_icons_migration_creates_table_and_fk_columns(alembic_config):
    """Миграция 3 (аддитивная): каталог diagram_icons + diagram_icon_id на device_models и
    physical_devices, с именованными FK-констрейнтами через batch_alter_table (раздел 4.3 ТЗ —
    ручное переопределение иконки на уровне модели/конкретного устройства)."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, DIAGRAM_ICONS_REVISION)
    conn = _connect(db_path)
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='diagram_icons'"
    ).fetchone() is not None
    model_cols = {r["name"] for r in conn.execute("PRAGMA table_info(device_models)").fetchall()}
    device_cols = {r["name"] for r in conn.execute("PRAGMA table_info(physical_devices)").fetchall()}
    assert "diagram_icon_id" in model_cols
    assert "diagram_icon_id" in device_cols
    conn.close()

    command.downgrade(cfg, DEVICE_TYPES_REVISION)
    conn = _connect(db_path)
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='diagram_icons'"
    ).fetchone() is None
    conn.close()
    command.upgrade(cfg, DIAGRAM_ICONS_REVISION)


def test_saved_diagrams_migration_creates_tables_with_cascade(alembic_config):
    """Миграция 4 (аддитивная): saved_diagrams/diagram_layouts/diagram_group_states, с
    ON DELETE CASCADE на дочерних таблицах (раздел 7 ТЗ — DELETE /diagrams/{id} каскадно удаляет
    layouts/group_states на уровне БД, не Python-логикой)."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, SAVED_DIAGRAMS_REVISION)
    conn = _connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    now = "2026-01-01 00:00:00"
    conn.execute(
        "INSERT INTO saved_diagrams (id, name, scope_filter, group_by, collapse_threshold, created_at, updated_at) "
        "VALUES ('d1', 'Диаграмма 1', '{}', 'structural_unit', 20, ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO diagram_layouts (id, saved_diagram_id, node_positions, auto_layout_algorithm, created_at, updated_at) "
        "VALUES ('l1', 'd1', '{}', 'hierarchical', ?, ?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO diagram_group_states (id, saved_diagram_id, group_key, is_collapsed, device_count, created_at, updated_at) "
        "VALUES ('g1', 'd1', 'structural_unit:1', 1, 25, ?, ?)",
        (now, now),
    )
    conn.commit()

    conn.execute("DELETE FROM saved_diagrams WHERE id='d1'")
    conn.commit()
    assert conn.execute("SELECT count(*) FROM diagram_layouts").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM diagram_group_states").fetchone()[0] == 0
    conn.close()

    command.downgrade(cfg, DIAGRAM_ICONS_REVISION)
    conn = _connect(db_path)
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='saved_diagrams'"
    ).fetchone() is None
    conn.close()
    command.upgrade(cfg, SAVED_DIAGRAMS_REVISION)
