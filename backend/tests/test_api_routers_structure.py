"""Тесты структуры HTTP-слоя после разбиения api/system.py на роутеры (код-ревью п. 10).

Что защищают: адреса эндпоинтов не потерялись при переносе, обработчики остаются «тонкими» (разбор запроса и вызов
сервиса — без моделей и SQL), а служебный роутер system.py не разросся обратно. Запуск:
pytest backend/tests/test_api_routers_structure.py -v
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.api import device_stacks, frontend_assets, listings, reports, system, vlan, vms

API_DIR = Path(system.__file__).parent

# (метод, путь) каждого эндпоинта бывшего system.py и роутер, который теперь за него отвечает.
EXPECTED_ROUTES = {
    "system": (system, {
        ("GET", "/api/v1/health"), ("GET", "/api/v1/integrity"), ("GET", "/api/v1/integrity/open-port-duplicates"),
        ("GET", "/api/v1/integrity/stale-subinterfaces"),
        ("GET", "/api/v1/dashboard"), ("POST", "/api/v1/seed"),
    }),
    "listings": (listings, {
        ("GET", "/api/v1/information-systems"), ("GET", "/api/v1/devices"), ("GET", "/api/v1/vms"),
    }),
    "vms": (vms, {
        ("PUT", "/api/v1/vms/{vm_id}/open-ports"), ("PUT", "/api/v1/vms/{vm_id}/ip-addresses"),
        ("PUT", "/api/v1/vms/{vm_id}/deployed-software"),
    }),
    "vlan": (vlan, {
        ("GET", "/api/v1/vlan-dashboard"), ("POST", "/api/v1/vlan-domains/{domain_id}/members"),
        ("POST", "/api/v1/vlan-domains/{domain_id}/sync"), ("POST", "/api/v1/devices/{device_id}/vlan-copy"),
        ("POST", "/api/v1/device-vlans/bulk-assign"),
    }),
    "reports": (reports, {
        ("POST", "/api/v1/reports/inventory"), ("POST", "/api/v1/reports/audit-log"),
        ("GET", "/api/v1/reports/download/{filename}"),
    }),
    "device_stacks": (device_stacks, {
        ("GET", "/api/v1/device-stacks/{stack_id}/detail"), ("POST", "/api/v1/device-stacks/{stack_id}/members"),
        ("GET", "/api/v1/device-stacks/{stack_id}/vlans"), ("PUT", "/api/v1/device-stacks/{stack_id}/vlans/{vlan_id}"),
    }),
    "frontend_assets": (frontend_assets, {("GET", "/icons.svg"), ("GET", "/favicon.ico")}),
}


def _routes_of(module) -> set[tuple[str, str]]:
    return {(method, route.path) for route in module.router.routes for method in route.methods}


@pytest.mark.parametrize("name", sorted(EXPECTED_ROUTES))
def test_router_owns_exactly_its_endpoints(name):
    module, expected = EXPECTED_ROUTES[name]
    assert _routes_of(module) == expected


def test_every_documented_endpoint_is_served_by_the_application(client):
    # app.routes хранит вложенные роутеры лениво, поэтому «что подключено» читаем из OpenAPI, где они развёрнуты.
    spec = client.get("/openapi.json").json()["paths"]
    served = {(method.upper(), path) for path, operations in spec.items() for method in operations}
    for name, (_module, expected) in EXPECTED_ROUTES.items():
        if name == "frontend_assets":
            continue  # include_in_schema=False; их раздачу проверяет test_frontend_serving.py
        missing = expected - served
        assert not missing, f"{name}: не подключены {sorted(missing)}"


def test_no_endpoint_is_declared_twice():
    seen: dict[tuple[str, str], str] = {}
    for name, (module, _expected) in EXPECTED_ROUTES.items():
        for key in _routes_of(module):
            assert key not in seen, f"{key} объявлен и в {seen[key]}, и в {name}"
            seen[key] = name


@pytest.mark.parametrize("module_name", ["vlan", "device_stacks"])
def test_thin_controllers_do_not_touch_models_or_sql(module_name):
    tree = ast.parse((API_DIR / f"{module_name}.py").read_text(encoding="utf-8"))
    imported = {
        (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any(name == "sqlalchemy" or name.startswith("sqlalchemy.") and name != "sqlalchemy.orm" for name in imported)
    assert "..models" not in imported
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            statements = [s for s in node.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
            assert len(statements) == 1 and isinstance(statements[0], ast.Return), f"{node.name}: обработчик должен только вызывать сервис"


def test_system_router_stays_small():
    lines = len((API_DIR / "system.py").read_text(encoding="utf-8").splitlines())
    assert lines <= 120, f"api/system.py вырос до {lines} строк — вынесите логику в сервисы или отдельный роутер"


def test_legacy_list_handler_has_a_descriptive_name():
    assert hasattr(listings, "list_information_systems") and not hasattr(listings, "list_is")
