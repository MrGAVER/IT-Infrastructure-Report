"""A-11: сборка EXE ставит зависимости по lock-файлу с хешами.

Раньше `installer/build_windows.bat` выполнял `pip install -r backend\\requirements-build.txt` (диапазоны версий) после
`pip install --upgrade pip`: в EXE попадали версии, не проходившие ни CI, ни pip-audit, сборки в разные дни расходились, а
подмена пакета в индексе не обнаруживалась. Docker и CI при этом ставили всё из `requirements*.lock` с `--require-hashes`.

Тест статический (собрать Windows EXE здесь негде): следит за lock-файлом, bat-скриптом, CI и README.
Запуск: pytest backend/tests/test_build_lock.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
BUILD_LOCK = BACKEND / "requirements-build.lock"
RUNTIME_LOCK = BACKEND / "requirements.lock"
BAT = ROOT / "installer" / "build_windows.bat"
CI = ROOT / ".github" / "workflows" / "ci.yml"
README = ROOT / "README.md"

_ENTRY = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[^\]]*\])?==(?P<version>[^\s;\\]+)(?:\s*;\s*(?P<marker>[^\\]+?))?\s*\\?$")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_lock(path: Path) -> dict[str, dict]:
    """{имя: {version, marker, hashes}} — по записям формата uv: `имя==версия ; маркер \\` + строки `--hash=…`."""
    entries: dict[str, dict] = {}
    current = None
    for raw in _read(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--hash="):
            assert current is not None, f"хеш без пакета: {line[:60]}"
            current["hashes"].append(line.rstrip(" \\"))
            continue
        match = _ENTRY.match(line)
        assert match, f"строка lock не похожа на закреплённый пакет с хешем: {line[:100]}"
        current = {"version": match["version"], "marker": (match["marker"] or "").strip(), "hashes": []}
        key = _normalize(match["name"])
        assert key not in entries or entries[key]["marker"] != current["marker"], f"{key} закреплён дважды"
        entries.setdefault(key, current)
    return entries


@pytest.fixture(scope="module")
def build_lock() -> dict[str, dict]:
    return _parse_lock(BUILD_LOCK)


# ---------------------------------------------------------------------------------------------------------------------
# lock-файл
# ---------------------------------------------------------------------------------------------------------------------
def test_every_package_is_pinned_exactly_and_has_hashes(build_lock):
    assert len(build_lock) > 30
    without_hashes = [name for name, entry in build_lock.items() if not entry["hashes"]]
    assert without_hashes == [], "pip --require-hashes отвергнет пакет без хеша"
    assert all(h.startswith("--hash=sha256:") and len(h) == len("--hash=sha256:") + 64 for e in build_lock.values() for h in e["hashes"])


def test_hashes_are_findable_like_in_the_acceptance_check():
    """Критерий приёмки: `findstr /c:"--hash=" backend\\requirements-build.lock` находит хеши."""
    assert "--hash=sha256:" in _read(BUILD_LOCK)


def test_pyinstaller_is_pinned_inside_the_declared_range(build_lock):
    declared = next(Requirement(line) for line in _read(BACKEND / "requirements-build.txt").splitlines() if line.lower().startswith("pyinstaller"))
    assert "pyinstaller" in build_lock
    assert Version(build_lock["pyinstaller"]["version"]) in declared.specifier


def test_build_lock_has_the_runtime_versions_from_requirements_lock(build_lock):
    """В EXE — те же версии общих пакетов, что в Docker и CI (прошедшие pip-audit по requirements.lock)."""
    runtime = _parse_lock(RUNTIME_LOCK)
    different = {name: (entry["version"], build_lock.get(name, {}).get("version")) for name, entry in runtime.items() if build_lock.get(name, {}).get("version") != entry["version"] or build_lock[name]["marker"] != entry["marker"]}
    assert different == {}, f"версии runtime в requirements-build.lock расходятся с requirements.lock: {different}"
    assert set(build_lock) - set(runtime), "в сборочном lock должны быть пакеты сборки (PyInstaller и его зависимости)"


def test_every_direct_requirement_of_both_inputs_is_locked(build_lock):
    names = set()
    for source in ("requirements.txt", "requirements-build.txt"):
        for line in _read(BACKEND / source).splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith("-"):
                names.add(_normalize(Requirement(line).name))
    assert names and names <= set(build_lock), f"не закреплены: {sorted(names - set(build_lock))}"


def test_windows_only_dependencies_of_pyinstaller_are_in_the_universal_lock(build_lock):
    """Lock собирается --universal: Windows-пакеты PyInstaller (pefile, pywin32-ctypes) есть с маркером платформы."""
    for name in ("pefile", "pywin32-ctypes"):
        assert name in build_lock and "win32" in build_lock[name]["marker"], name


# ---------------------------------------------------------------------------------------------------------------------
# bat-скрипт сборки
# ---------------------------------------------------------------------------------------------------------------------
def _bat_commands() -> list[str]:
    return [line.strip() for line in _read(BAT).splitlines() if line.strip() and not line.strip().lower().startswith("rem ")]


def test_bat_installs_from_the_lock_with_hashes_and_stops_on_failure():
    commands = _bat_commands()
    install = [i for i, line in enumerate(commands) if "pip install" in line]
    assert len(install) == 1, "в скрипте ровно одна установка пакетов"
    line = commands[install[0]]
    assert "--require-hashes" in line and "backend\\requirements-build.lock" in line and "-r " in line
    assert commands[install[0] + 1].lower().startswith("if errorlevel 1 exit /b 1"), "сбой установки не должен приводить к сборке из чего придётся"


def test_bat_no_longer_upgrades_pip_or_reads_unpinned_requirements():
    text = _read(BAT).lower()
    assert "--upgrade pip" not in text
    assert "requirements-build.txt" not in "\n".join(_bat_commands()).lower()


def test_bat_installs_inside_the_venv_before_pyinstaller_runs():
    commands = _bat_commands()
    position = {key: next(i for i, line in enumerate(commands) if key in line) for key in ("activate.bat", "pip install", "PyInstaller")}
    assert position["activate.bat"] < position["pip install"] < position["PyInstaller"]


# ---------------------------------------------------------------------------------------------------------------------
# CI и документация
# ---------------------------------------------------------------------------------------------------------------------
def test_ci_checks_that_the_build_lock_is_up_to_date():
    text = _read(CI)
    assert "uv pip compile requirements-build.txt --universal --generate-hashes --python-version 3.12 -o requirements-build.lock --no-header" in text
    diff = next(line for line in text.splitlines() if "git diff --exit-code" in line)
    assert "requirements-build.lock" in diff and "requirements.lock" in diff and "requirements-dev.lock" in diff


def test_ci_audits_the_build_lock_without_blocking_the_build():
    text = _read(CI)
    step = text[text.index("pip-audit набора для сборки EXE") :]
    step = step.split("\n      - name:", 1)[0]
    assert "pip-audit -r backend/requirements-build.lock --require-hashes" in step
    assert "continue-on-error: true" in step
    # runtime-аудит остаётся блокирующим
    runtime = text[text.index("pip-audit (известные уязвимости") :].split("\n      - name:", 1)[0]
    assert "continue-on-error" not in runtime and "requirements.lock" in runtime


def test_readme_describes_the_build_lock():
    text = _read(README)
    assert "requirements-build.lock" in text
    assert "uv pip compile requirements-build.txt --universal --generate-hashes --python-version 3.12 -o requirements-build.lock" in text
    assert "ставят пакеты по диапазонам" not in text and "пока\nставит пакеты по диапазонам" not in text
