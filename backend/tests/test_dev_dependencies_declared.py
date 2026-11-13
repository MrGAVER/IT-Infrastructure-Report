"""
Код-ревью r3, ИА-08: зависимости, которые импортируют тесты, объявлены явно, а обязательные зависимости не «пропускаются» молча.

1. Раньше шесть тестовых модулей делали `import yaml`, а PyYAML нигде не был объявлен — он попадал в lock только транзитивно, через bandit.
   Убрали бы bandit — и тесты упали бы ModuleNotFoundError. Теперь каждый сторонний модуль, который импортируют тесты, должен быть в
   requirements*.txt либо в явном списке ниже (с причиной).
2. `pytest.importorskip("vsdx")` на обязательной зависимости превращает сломанную установку в тихий пропуск 17 тестов. importorskip допустим
   только для того, чего нет в requirements.txt (сборочные инструменты вроде PyInstaller).

Запуск: pytest backend/tests/test_dev_dependencies_declared.py -v
"""

from __future__ import annotations

import ast
import re
import sys
from importlib.metadata import packages_distributions
from pathlib import Path

TESTS = Path(__file__).resolve().parent
BACKEND = TESTS.parent

# Импортируются тестами, не объявлены отдельно — и это осознанно: их гарантирует объявленный пакет (его pin лежит в lock-файле).
TRANSITIVE_BY_DESIGN = {
    "starlette": "ставится вместе с fastapi (TestClient)",
    "h11": "ставится вместе с uvicorn; тест проверяет, что заголовок принимает настоящий HTTP-стек",
    "packaging": "ставится вместе с pytest",
}
# Нужны только для сборки EXE (backend/requirements-build.txt), в среде тестов могут отсутствовать — тесты вызывают importorskip.
BUILD_TOOLS = {"PyInstaller"}


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared(*files: str) -> set[str]:
    names: set[str] = set()
    for file in files:
        for raw in (BACKEND / file).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith(("#", "-")):
                names.add(_normalize(re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line).group(0)))
    return names


def _imports_of_tests() -> dict[str, set[str]]:
    """{верхнеуровневое имя модуля: файлы тестов} — по `import x`, `from x import …` и `pytest.importorskip("x")`; свои и стандартные модули отброшены."""
    local = {path.stem for path in TESTS.glob("*.py")} | {path.name for path in TESTS.iterdir() if path.is_dir()}
    found: dict[str, set[str]] = {}
    for path in TESTS.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            elif isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "importorskip" and node.args and isinstance(node.args[0], ast.Constant):
                names = [str(node.args[0].value)]
            else:
                continue
            for name in (n.split(".")[0] for n in names):
                if name not in sys.stdlib_module_names and name != "app" and name not in local:
                    found.setdefault(name, set()).add(path.name)
    return found


def _distributions(module: str) -> set[str]:
    return {_normalize(dist) for dist in packages_distributions().get(module, [])}


def test_every_third_party_module_imported_by_tests_is_declared():
    declared = _declared("requirements.txt", "requirements-dev.txt", "requirements-build.txt")
    undeclared = {}
    for module, files in _imports_of_tests().items():
        if module in BUILD_TOOLS or module in TRANSITIVE_BY_DESIGN:
            continue
        if not _distributions(module) & declared:
            undeclared[module] = sorted(files)
    assert undeclared == {}, f"тесты импортируют модули, пакеты которых не объявлены в requirements*.txt: {undeclared}"


def test_pyyaml_is_declared_for_the_tests_that_parse_yaml_configs():
    """Конкретный случай из отчёта: `import yaml` в тестах конфигурации (compose, CI, dependabot) держится на pyyaml, а не на bandit."""
    assert "yaml" in _imports_of_tests()
    assert "pyyaml" in _declared("requirements-dev.txt")


def test_the_explicit_lists_do_not_contain_declared_packages():
    """Исключение не должно пережить причину: объявили пакет — запись в списке исключений лишняя."""
    declared = _declared("requirements.txt", "requirements-dev.txt", "requirements-build.txt")
    assert {name for name in TRANSITIVE_BY_DESIGN if _normalize(name) in declared} == set()


def test_importorskip_is_only_used_for_what_is_not_a_runtime_dependency():
    """Обязательная зависимость (requirements.txt) при сломанной установке должна ронять тесты, а не пропускать их молча."""
    runtime = _declared("requirements.txt")
    skipped_runtime = {}
    for path in TESTS.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "importorskip" and node.args and isinstance(node.args[0], ast.Constant):
                module = str(node.args[0].value).split(".")[0]
                if _distributions(module) & runtime:
                    skipped_runtime.setdefault(module, []).append(path.name)
    assert skipped_runtime == {}, f"importorskip на обязательной зависимости (замените обычным import): {skipped_runtime}"
