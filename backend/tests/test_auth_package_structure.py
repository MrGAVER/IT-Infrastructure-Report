"""
Код-ревью, BE-06: services/auth.py нарезан на пакет services/auth/. Тесты фиксируют то, что нарезка обязана сохранить, и то, что
иначе ломается молча.

* Публичные имена прежнего модуля остались доступны из пакета: `from ..services.auth import …` в роутерах и main.py работает.
* __init__.py — только реэкспорт, логики в нём нет (иначе она снова разрослась бы в одном файле).
* Подмодули не зависят друг от друга по кругу.
* Имя логгера прежнее — на него могут быть настроены фильтры журнала.
* Тесты не подменяют имена на самом пакете: такая подмена не действует на функции подмодулей и проходила бы без ошибки,
  оставляя в тесте настоящий (не подменённый) код.

Запуск: pytest backend/tests/test_auth_package_structure.py -v
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

import app.services.auth as auth
from app.services.auth import proxy_headers

PACKAGE_DIR = Path(auth.__file__).resolve().parent
TESTS_DIR = Path(__file__).resolve().parent

# Публичные имена модуля services/auth.py до нарезки (по его AST).
LEGACY_PUBLIC_NAMES = [
    "hash_password",
    "verify_password",
    "validate_password_strength",
    "find_user_by_username",
    "ensure_not_last_admin",
    "create_user",
    "update_user",
    "delete_user",
    "change_own_password",
    "serialize_user",
    "get_or_create_auth_settings",
    "reset_auth_enabled_cache",
    "set_auth_enabled",
    "create_session",
    "cleanup_expired_sessions",
    "resolve_session",
    "revoke_session",
    "revoke_all_sessions",
    "revoke_all_sessions_except",
    "revoke_session_by_id",
    "list_active_sessions",
    "serialize_session",
    "authenticate",
    "WRITE_METHODS",
    "PUBLIC_API_PATHS",
    "ROLE_CHECK_EXEMPT_PATHS",
    "ROLE_CHECK_EXEMPT_PREFIXES",
    "READ_ONLY_POST_PATHS",
    "AuthGateMiddleware",
    "require_setup_access",
    "require_admin_if_auth_enabled",
    "require_admin",
    "Actor",
    "current_actor",  # реэкспортировались и раньше (__all__ старого модуля)
]
# Имена старого модуля, которые намеренно НЕ реэкспортируются: это изменяемое состояние и настройка, которые подменяют в тестах.
# Подмена такого имени на пакете не подействовала бы, поэтому обращаться к ним нужно в подмодуле (login, passwords).
NOT_RE_EXPORTED = ["PBKDF2_ALGORITHM", "PBKDF2_ITERATIONS", "login_throttle", "ip_throttle", "logger"]


def _submodule_names() -> list[str]:
    return sorted(p.stem for p in PACKAGE_DIR.glob("*.py") if p.stem != "__init__")


@pytest.mark.parametrize("name", LEGACY_PUBLIC_NAMES)
def test_every_legacy_public_name_is_still_importable_from_the_package(name):
    assert hasattr(auth, name), f"{name} пропало из app.services.auth"
    assert name in auth.__all__


@pytest.mark.parametrize("name", NOT_RE_EXPORTED)
def test_mutable_state_and_tunables_are_not_re_exported(name):
    # Реэкспорт изменяемого состояния дал бы ложное чувство, что его можно подменить на пакете.
    assert not hasattr(auth, name), f"{name} не должно быть на пакете: его место в подмодуле"


def test_all_lists_only_existing_names_and_nothing_private():
    assert sorted(set(auth.__all__)) == sorted(auth.__all__), "дубли в __all__"
    missing = [name for name in auth.__all__ if not hasattr(auth, name)]
    assert missing == []
    assert [name for name in auth.__all__ if name.startswith("_")] == []


def test_re_exported_callables_are_the_objects_defined_in_the_submodules():
    for name in auth.__all__:
        obj = getattr(auth, name)
        module = getattr(obj, "__module__", "")
        if callable(obj) and module.startswith("app.services.auth"):
            assert module != "app.services.auth", f"{name} определена в __init__.py, а не в подмодуле"
            assert getattr(importlib.import_module(module), obj.__name__) is obj


def test_package_init_holds_only_imports_and_the_export_list():
    tree = ast.parse((PACKAGE_DIR / "__init__.py").read_text(encoding="utf-8"))
    allowed = (ast.Import, ast.ImportFrom)
    stray = [
        node
        for node in tree.body
        if not isinstance(node, allowed)
        and not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str))  # докстринг
        and not (isinstance(node, ast.Assign) and [t.id for t in node.targets if isinstance(t, ast.Name)] == ["__all__"])
    ]
    assert stray == [], f"в auth/__init__.py есть логика, её место в подмодуле: {[ast.dump(n)[:60] for n in stray]}"


def test_submodules_do_not_depend_on_each_other_in_a_cycle():
    graph: dict[str, set[str]] = {}
    for name in _submodule_names():
        tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
        graph[name] = {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module and node.module.split(".")[0] in _submodule_names()
        }
    resolved: set[str] = set()
    while len(resolved) < len(graph):
        ready = [name for name, deps in graph.items() if name not in resolved and deps <= resolved]
        assert ready, f"цикл между подмодулями: {sorted(set(graph) - resolved)}"
        resolved.update(ready)


def test_package_modules_are_the_expected_set():
    # Новый модуль в пакете — осознанное решение: добавьте его сюда и в «Состав пакета» докстринга __init__.py.
    assert _submodule_names() == [
        "_common",
        "gate",
        "guards",
        "lockout",
        "login",
        "passwords",
        "proxy_headers",
        "security_headers",
        "sessions",
        "settings",
        "users",
    ]
    docstring = auth.__doc__ or ""
    assert [name for name in _submodule_names() if name not in docstring] == []


def test_the_warning_logger_keeps_its_name_from_before_the_split():
    assert proxy_headers.logger.name == "app.services.auth"


def test_tests_do_not_patch_names_on_the_package_itself():
    # monkeypatch.setattr(auth_module, "audit", …) подменил бы имя на пакете, а функции users/login/… читают своё, подмодульное:
    # тест прошёл бы с настоящим кодом. Подменять нужно в подмодуле, который имя читает.
    pattern = re.compile(r"setattr\(\s*(?:auth_module|auth)\s*,")
    offenders = [
        path.name
        for path in sorted(TESTS_DIR.glob("*.py"))
        if path.name != Path(__file__).name and pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"подмена имени на пакете services.auth: {offenders}"
