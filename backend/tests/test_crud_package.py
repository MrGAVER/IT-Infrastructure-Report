"""Тесты структуры пакета app.services.crud (бывший crud.py на 1382 строки, код-ревью п. 10).

Разбиение не должно ломать вызывающий код: публичный API прежний, а модули зависят друг от друга в одну
сторону. Запуск: pytest backend/tests/test_crud_package.py -v
"""
from __future__ import annotations

import ast
import importlib
import subprocess
import sys
from pathlib import Path

import pytest

import app.services.crud as crud

PACKAGE_DIR = Path(crud.__file__).parent
SUBMODULES = sorted(p.stem for p in PACKAGE_DIR.glob("*.py") if p.stem != "__init__")

# Всё, что остальное приложение и тесты импортировали из services.crud до разбиения.
PUBLIC_API = [
    "audit", "columns_for", "allowed_columns", "model_for", "ensure_writable", "validate_payload_schema",
    "list_resource", "create_resource", "update_resource", "delete_resource", "assert_deletable", "validate_resource",
    "assign_domain_vlans_to_device", "get_information_system_details", "sync_information_system_details",
    "get_interface_groups", "list_interface_groups", "sync_interfaces", "sync_device_vlans",
    "sync_device_deployed_software", "sync_vm_open_ports", "sync_vm_ip_addresses", "sync_vm_deployed_software",
    "sync_owner_open_ports", "sync_owner_ip_addresses", "sync_owner_deployed_software",
    # приватные имена, на которые ссылаются тесты
    "_RESOURCE_VALIDATORS", "_find_referencing_counts", "_POLYMORPHIC_OWNER_CLEANUP",
]


@pytest.mark.parametrize("name", PUBLIC_API)
def test_name_is_still_importable_from_the_package(name):
    assert hasattr(crud, name), f"{name} пропал из app.services.crud"


def test_audit_is_the_function_not_a_submodule():
    # подмодуль назван audit_log именно для этого: crud.audit(...) должен остаться вызовом функции
    assert callable(crud.audit) and crud.audit.__module__.endswith("crud.audit_log")


@pytest.mark.parametrize("module", SUBMODULES)
def test_every_submodule_imports_on_its_own(module):
    # Свежий интерпретатор: цикл между модулями проявился бы только при определённом порядке импорта.
    result = subprocess.run(
        [sys.executable, "-c", f"import app.services.crud.{module}"],
        capture_output=True, text=True, cwd=PACKAGE_DIR.parents[2],
    )
    assert result.returncode == 0, result.stderr


def test_dependencies_between_modules_have_no_cycles():
    graph: dict[str, set[str]] = {m: set() for m in SUBMODULES}
    for module in SUBMODULES:
        tree = ast.parse((PACKAGE_DIR / f"{module}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module in graph:
                graph[module].add(node.module)

    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in done:
            return
        assert node not in visiting, f"цикл зависимостей: {' -> '.join(path + [node])}"
        visiting.add(node)
        for neighbour in sorted(graph[node]):
            visit(neighbour, path + [node])
        visiting.discard(node)
        done.add(node)

    for module in SUBMODULES:
        visit(module, [])


def test_all_lists_every_public_definition_and_every_name_resolves():
    # Публичные имена (без «_») обязаны быть в __all__: так внешний код видит весь API пакета. Приватные помощники,
    # добавленные при рефакторинге (например, _apply_filters), переэкспортировать не нужно: в __all__ остаются только
    # приватные имена, существовавшие до разбиения crud.py (на них ссылались тесты).
    defined: set[str] = set()
    for module in SUBMODULES:
        tree = ast.parse((PACKAGE_DIR / f"{module}.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                target = node.targets[0] if isinstance(node, ast.Assign) else node.target
                defined.add(target.id)
    public = {name for name in defined if not name.startswith("_")}
    assert public <= set(crud.__all__), f"публичные имена вне __all__: {sorted(public - set(crud.__all__))}"
    for name in crud.__all__:
        assert hasattr(crud, name), f"{name} есть в __all__, но не импортируется из пакета"


def test_every_name_in_all_resolves_to_its_defining_module():
    for name in crud.__all__:
        value = getattr(crud, name)
        owner = getattr(value, "__module__", None)
        if owner:  # константы и словари __module__ не имеют
            assert owner.startswith("app.services.crud."), name


def test_modules_are_small_enough_to_review():
    # Цель п. 10 — перестать держать 1300 строк в одном файле; порог оставляет запас на рост.
    for module in SUBMODULES:
        lines = len((PACKAGE_DIR / f"{module}.py").read_text(encoding="utf-8").splitlines())
        assert lines <= 400, f"{module}.py вырос до {lines} строк — разрежьте его"


def test_old_flat_module_is_gone():
    assert not (PACKAGE_DIR.parent / "crud.py").exists()
    assert importlib.import_module("app.services.crud") is crud
