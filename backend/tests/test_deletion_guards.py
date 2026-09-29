"""Тесты защит ссылочной целостности для связей без настоящего FK (см. services/integrity.py).

Пять уровней защиты InformationSystemSource.owner_id (миграция 944bd490d967):
1. crud.assert_deletable() — единая точка проверки «можно ли удалить»;
2. before_delete на PhysicalDevice/VirtualMachine/Container — любое ORM-удаление;
3. триггеры БД (миграция 5b1e7c94a2d8) — тесты в test_migrations_information_system_source_delete_guard_triggers.py;
4. find_orphaned_owner_references() + GET /api/v1/integrity — диагностика уже висящих ссылок;
5. статическая проверка исходников (TestNoUnreviewedDeletionPaths ниже) — новый путь прямого
   удаления в app/ без явного разрешения роняет тест.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.constants import OwnerType, SourceType
from app.models import (
    Container, DeployedSoftware, DeviceCategory, DeviceInterface, DeviceType, IPAddress,
    InformationSystem, InformationSystemSource, OpenPort, PhysicalDevice, ProtocolPortCatalog,
    SoftwareAsset, VirtualMachine,
)
from app.services import crud
from app.services.integrity import (
    ReferencedRecordError, find_orphaned_owner_references, format_referenced_message,
)

APP_DIR = Path(__file__).resolve().parent.parent / "app"


# --- Уровень 5: статическая проверка путей удаления ---------------------------------------------

# Разрешённые прямые удаления в app/: (файл, функция, выражение-аргумент). Каждая запись
# просмотрена и удаляет ДОЧЕРНИЕ/служебные записи либо сама выполняет очистку зависимых данных.
# Новый путь удаления устройства/ВМ/контейнера сюда добавлять НЕЛЬЗЯ — он должен идти через
# crud.assert_deletable() (см. docstring services/integrity.py).
ALLOWED_DELETIONS = {
    # сессии и учётные записи
    ("app/services/auth.py", "delete_user", "user"),
    ("app/services/auth.py", "cleanup_expired_sessions", "AuthSession"),
    ("app/services/auth.py", "resolve_session", "row"),
    ("app/services/auth.py", "revoke_session", "AuthSession"),
    ("app/services/auth.py", "revoke_all_sessions", "AuthSession"),
    ("app/services/auth.py", "revoke_all_sessions_except", "AuthSession"),
    ("app/services/auth.py", "revoke_session_by_id", "AuthSession"),
    # диаграммы и шаблоны отчётов
    ("app/api/diagrams.py", "delete_diagram", "diagram"),
    ("app/api/report_builder.py", "delete_template", "ReportTemplateVersion"),
    ("app/api/report_builder.py", "delete_template", "t"),
    # назначения VLAN
    ("app/api/system.py", "sync_vlan_domain", "PhysicalDeviceVLAN"),
    # generic-удаление: перед ним вызывается assert_deletable(), затем очистка полиморфных дочерних
    ("app/services/crud.py", "delete_resource", "cleanup_model"),
    ("app/services/crud.py", "delete_resource", "obj"),
    # синхронизация дочерних записей формы (интерфейсы устройства, порты, IP, источники ИС): удаляет
    # дочерние строки и сама подчищает их полиморфных потомков
    ("app/services/crud.py", "_sync_single_interface", "InterfaceVLAN"),
    ("app/services/crud.py", "_sync_single_interface", "old_ip"),
    ("app/services/crud.py", "_sync_interface_open_ports", "old_port"),
    ("app/services/crud.py", "sync_interfaces", "IPAddress"),
    ("app/services/crud.py", "sync_interfaces", "OpenPort"),
    ("app/services/crud.py", "sync_interfaces", "obj"),
    # VLAN устройства (PhysicalDeviceVLAN) — дочерняя запись без входящих ссылок (ни FK, ни
    # полиморфных: проверено reflection'ом по MODEL_MAP), поэтому assert_deletable() ей не нужен
    ("app/services/crud.py", "sync_device_vlans", "obj"),
    ("app/services/crud.py", "_sync_linked_table", "obj"),
    ("app/services/crud.py", "_sync_source_ip_addresses", "old_ip"),
    ("app/services/crud.py", "_sync_information_system_sources", "IPAddress"),
    ("app/services/crud.py", "_sync_information_system_sources", "obj"),
}

# Модели, на которые ссылаются связи без FK: Core-удаление delete(<Модель>) запрещено везде —
# оно обходит и before_delete, и assert_deletable (остаётся только триггер БД).
PROTECTED_MODELS = {"PhysicalDevice", "VirtualMachine", "Container", "InformationSystemSource", "DeviceInterface"}

_RAW_DELETE_SQL = re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE)


def _scan_deletions() -> tuple[set[tuple[str, str, str]], list[str]]:
    """Возвращает (найденные прямые удаления, найденные нарушения жёстких правил)."""
    found: set[tuple[str, str, str]] = set()
    violations: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        rel = "app/" + path.relative_to(APP_DIR).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))

        def visit(node: ast.AST, func: str) -> None:
            for child in ast.iter_child_nodes(node):
                child_func = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else func
                if isinstance(child, ast.Call):
                    f = child.func
                    is_delete = (isinstance(f, ast.Attribute) and f.attr == "delete") or (isinstance(f, ast.Name) and f.id == "delete")
                    first = child.args[0] if child.args else None
                    is_route_decorator = isinstance(first, ast.Constant) and isinstance(first.value, str)  # @router.delete('/path')
                    if is_delete and not is_route_decorator:
                        arg = ast.unparse(first) if first is not None else ""
                        found.add((rel, func, arg))
                        if isinstance(f, ast.Name) and arg in PROTECTED_MODELS:
                            violations.append(f"{rel}:{child.lineno} — delete({arg}) в функции {func}()")
                if isinstance(child, ast.Constant) and isinstance(child.value, str) and _RAW_DELETE_SQL.search(child.value):
                    violations.append(f"{rel}:{child.lineno} — сырой SQL 'DELETE FROM' в функции {func}()")
                visit(child, child_func)

        visit(tree, "<module>")
    return found, violations


class TestNoUnreviewedDeletionPaths:
    def test_no_new_direct_deletion_paths(self):
        found, _ = _scan_deletions()
        new = sorted(found - ALLOWED_DELETIONS)
        assert not new, (
            "Найдены новые пути прямого удаления в app/, не прошедшие ревью:\n  "
            + "\n  ".join(f"{f} → {fn}() удаляет {arg or '<query>'}" for f, fn, arg in new)
            + "\nУдаление устройства/ВМ/контейнера должно идти через crud.delete_resource() / "
            "crud.assert_deletable() (см. services/integrity.py). Если это удаление ДОЧЕРНИХ записей "
            "и оно безопасно — добавьте его в ALLOWED_DELETIONS с комментарием."
        )

    def test_protected_models_never_deleted_via_core_or_raw_sql(self):
        _, violations = _scan_deletions()
        assert not violations, (
            "Массовое удаление защищённых моделей / сырой DELETE в обход ORM-защит:\n  " + "\n  ".join(violations)
        )

    def test_scanner_detects_a_forbidden_pattern(self):
        """Сам сторож не должен молча ослепнуть: проверяем его на искусственном коде."""
        tree = ast.parse("from sqlalchemy import delete\ndef f(session):\n    session.execute(delete(PhysicalDevice))\n")
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "delete"]
        assert len(calls) == 1 and ast.unparse(calls[0].args[0]) in PROTECTED_MODELS


# --- Фабрики тестовых данных ---------------------------------------------------------------------

def _device(session, serial: str = "SN-GUARD-1") -> PhysicalDevice:
    category = session.query(DeviceCategory).first() or DeviceCategory(name="Категория теста")
    session.add(category)
    session.flush()
    dtype = session.query(DeviceType).first() or DeviceType(name="Тип теста", category_id=category.id)
    session.add(dtype)
    session.flush()
    device = PhysicalDevice(device_type_id=dtype.id, serial_number=serial)
    session.add(device)
    session.flush()
    return device


def _owner(session, kind: str):
    if kind == SourceType.DEVICE:
        return _device(session)
    model, name = (VirtualMachine, "vm-guard") if kind == SourceType.VM else (Container, "ct-guard")
    obj = model(name=name)
    session.add(obj)
    session.flush()
    return obj


def _source(session, source_type: str, owner_id: str | None) -> InformationSystemSource:
    isys = session.query(InformationSystem).first() or InformationSystem(name="ИС теста")
    session.add(isys)
    session.flush()
    source = InformationSystemSource(information_system_id=isys.id, source_type=source_type, owner_id=owner_id)
    session.add(source)
    session.flush()
    return source


OWNER_KINDS = [SourceType.DEVICE, SourceType.VM, SourceType.CONTAINER]
RESOURCE_BY_KIND = {SourceType.DEVICE: "devices", SourceType.VM: "vms", SourceType.CONTAINER: "containers"}


# --- Уровень 2: before_delete на уровне ORM ------------------------------------------------------

class TestOrmDeleteGuard:
    @pytest.mark.parametrize("kind", OWNER_KINDS)
    def test_orm_delete_of_referenced_owner_is_blocked(self, db_session, kind):
        owner = _owner(db_session, kind)
        _source(db_session, kind, owner.id)
        db_session.commit()

        db_session.delete(owner)
        with pytest.raises(ReferencedRecordError) as exc:
            db_session.flush()
        assert "ИС ↔ источники размещения: 1" in str(exc.value)

        db_session.rollback()
        assert db_session.get(type(owner), owner.id) is not None

    @pytest.mark.parametrize("kind", OWNER_KINDS)
    def test_orm_delete_allowed_after_source_removed(self, db_session, kind):
        owner = _owner(db_session, kind)
        source = _source(db_session, kind, owner.id)
        db_session.commit()

        db_session.delete(source)
        db_session.flush()  # источник должен уйти РАНЬШЕ владельца — см. ограничения в integrity.py
        db_session.delete(owner)
        db_session.flush()
        assert db_session.get(type(owner), owner.id) is None

    def test_source_of_another_type_with_same_id_does_not_block(self, db_session):
        device = _device(db_session)
        _source(db_session, SourceType.VM, device.id)
        db_session.commit()

        db_session.delete(device)
        db_session.flush()
        assert db_session.get(PhysicalDevice, device.id) is None

    def test_guard_registered_exactly_once(self):
        from sqlalchemy import event

        from app.services import integrity

        integrity.register_delete_guards()
        integrity.register_delete_guards()
        for model in (PhysicalDevice, VirtualMachine, Container):
            assert event.contains(model, "before_delete", integrity._guard_before_delete)
            dispatch = model.__mapper__.dispatch.before_delete
            assert sum(1 for fn in dispatch if fn is integrity._guard_before_delete) <= 1

    def test_http_layer_returns_409_when_orm_guard_fires_behind_assert_deletable(self, client, db_session, monkeypatch):
        """Если новый путь удаления забыл assert_deletable(), ORM-защита всё равно должна дать
        клиенту 409 в том же формате, а не 500."""
        device = _device(db_session)
        _source(db_session, SourceType.DEVICE, device.id)
        db_session.commit()
        monkeypatch.setattr(crud, "assert_deletable", lambda *a, **k: None)

        r = client.delete(f"/api/v1/resources/devices/{device.id}")
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "REFERENCED_BY_OTHER_RECORDS"
        assert "ИС ↔ источники размещения: 1" in r.json()["detail"]["message"]

        db_session.rollback()
        assert db_session.get(PhysicalDevice, device.id) is not None


# --- Уровень 1: единая точка проверки ------------------------------------------------------------

class TestAssertDeletable:
    @pytest.mark.parametrize("kind", OWNER_KINDS)
    def test_raises_409_for_referenced_owner(self, db_session, kind):
        owner = _owner(db_session, kind)
        _source(db_session, kind, owner.id)
        db_session.commit()

        with pytest.raises(HTTPException) as exc:
            crud.assert_deletable(RESOURCE_BY_KIND[kind], owner.id, db_session)
        assert exc.value.status_code == 409
        assert exc.value.detail["code"] == "REFERENCED_BY_OTHER_RECORDS"
        assert exc.value.detail["message"] == format_referenced_message([("ИС ↔ источники размещения", 1)])

    def test_passes_for_unreferenced_owner(self, db_session):
        device = _device(db_session)
        db_session.commit()
        crud.assert_deletable("devices", device.id, db_session)

    def test_message_format_is_shared(self):
        assert format_referenced_message([("A", 2), ("B", 1)]) == "Нельзя удалить: запись используется в других данных (A: 2, B: 1)."


# --- Уровень 4: диагностика «висячих» ссылок -----------------------------------------------------

def _seed_orphan_dataset(session):
    """Корректные ссылки + по одной висячей во всех четырёх моделях без FK + запись с неизвестным
    owner_type."""
    device = _device(session)
    iface = DeviceInterface(physical_device_id=device.id, name="eth0")
    vm = VirtualMachine(name="vm-ok")
    session.add_all([iface, vm])
    session.flush()
    catalog = ProtocolPortCatalog(port=54321, protocol_type="GUARD-TEST")  # уникальная запись: client-фикстура засевает справочник стандартными протоколами
    software = SoftwareAsset(name="ПО теста")
    session.add_all([catalog, software])
    session.flush()
    good_source = _source(session, SourceType.DEVICE, device.id)

    # корректные
    session.add_all([
        IPAddress(owner_type=OwnerType.DEVICE_INTERFACE, owner_id=iface.id, ip_address="10.0.0.1"),
        IPAddress(owner_type=OwnerType.INFORMATION_SYSTEM_SOURCE, owner_id=good_source.id, ip_address="10.0.0.2"),
        OpenPort(owner_type=OwnerType.VIRTUAL_MACHINE, owner_id=vm.id, protocol_catalog_id=catalog.id),
        DeployedSoftware(owner_type=OwnerType.PHYSICAL_DEVICE, owner_id=device.id, software_asset_id=software.id),
    ])
    # висячие
    session.add_all([
        OpenPort(owner_type=OwnerType.VIRTUAL_MACHINE, owner_id="ghost-vm", protocol_catalog_id=catalog.id),
        DeployedSoftware(owner_type=OwnerType.PHYSICAL_DEVICE, owner_id="ghost-device", software_asset_id=software.id),
        IPAddress(owner_type=OwnerType.INFORMATION_SYSTEM_SOURCE, owner_id="ghost-source", ip_address="10.9.9.9"),
        IPAddress(owner_type="bogus_owner", owner_id="whatever", ip_address="10.9.9.8"),
    ])
    _source(session, SourceType.CONTAINER, "ghost-container")
    session.commit()


class TestOrphanDiagnostics:
    def test_clean_database_has_no_orphans(self, db_session):
        assert find_orphaned_owner_references(db_session) == []

    def test_valid_references_are_not_reported(self, db_session):
        device = _device(db_session)
        _source(db_session, SourceType.DEVICE, device.id)
        db_session.commit()
        assert find_orphaned_owner_references(db_session) == []

    def test_orphans_found_in_all_four_models(self, db_session):
        _seed_orphan_dataset(db_session)
        found = {(o["table"], o["owner_type"], o["owner_id"], o["reason"]) for o in find_orphaned_owner_references(db_session)}
        assert found == {
            ("open_ports", OwnerType.VIRTUAL_MACHINE, "ghost-vm", "owner_missing"),
            ("deployed_software", OwnerType.PHYSICAL_DEVICE, "ghost-device", "owner_missing"),
            ("ip_addresses", OwnerType.INFORMATION_SYSTEM_SOURCE, "ghost-source", "owner_missing"),
            ("ip_addresses", "bogus_owner", "whatever", "unknown_owner_type"),
            ("information_system_sources", SourceType.CONTAINER, "ghost-container", "owner_missing"),
        }

    def test_manual_source_without_owner_is_not_an_orphan(self, db_session):
        _source(db_session, SourceType.MANUAL, None)
        db_session.commit()
        assert find_orphaned_owner_references(db_session) == []

    def test_endpoint_reports_ok_then_orphans(self, client, db_session):
        r = client.get("/api/v1/integrity")
        assert r.status_code == 200
        assert r.json() == {"ok": True, "total": 0, "orphans": []}

        _seed_orphan_dataset(db_session)
        body = client.get("/api/v1/integrity").json()
        assert body["ok"] is False
        assert body["total"] == 5
        assert {o["reason"] for o in body["orphans"]} == {"owner_missing", "unknown_owner_type"}
