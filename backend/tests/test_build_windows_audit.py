"""Проверка уязвимостей пакетов при сборке EXE (installer/build_windows.bat) и сборка под Windows в CI.

Раньше `build_windows.bat` собирал EXE без единой проверки на известные уязвимости: `npm audit` и `pip-audit` работали только в
Linux-job `test` CI, а сборку под Windows не запускал никто. Теперь скрипт сам останавливается на уязвимостях в runtime-зависимостях,
а отдельный job CI `build-windows` на windows-latest гоняет именно этот скрипт.

Правила те же, что у соответствующих шагов Linux-job: `npm run audit:gate` и `pip-audit` по `requirements.lock` блокируют сборку,
`pip-audit` по `requirements-build.lock` (PyInstaller и его хуки изредка дают замечания, не относящиеся к рантайму) только сообщает.

Тест статический (запустить .bat здесь негде — нет Windows): разбирает скрипт, ci.yml и lock-файл. Саму сборку проверяет job
`build-windows`. Запуск: pytest backend/tests/test_build_windows_audit.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
BAT = ROOT / "installer" / "build_windows.bat"
CI = ROOT / ".github" / "workflows" / "ci.yml"
README = ROOT / "README.md"
BUILD_TXT = BACKEND / "requirements-build.txt"
BUILD_LOCK = BACKEND / "requirements-build.lock"

PINNED_ACTION = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _commands() -> list[str]:
    """Команды скрипта без пустых строк и комментариев `rem`."""
    lines = (line.strip() for line in BAT.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.lower().startswith("rem ")]


def _index(commands: list[str], needle: str, start: int = 0) -> int:
    return next(i for i in range(start, len(commands)) if needle.lower() in commands[i].lower())


def _blocks_on_failure(commands: list[str], index: int) -> bool:
    """Сразу после команды `if errorlevel 1` ведёт к `exit /b 1` (в одной строке или в блоке из нескольких echo)."""
    following = [line.replace(" ", "").lower() for line in commands[index + 1 : index + 7]]
    return bool(following) and following[0].startswith("iferrorlevel1") and "exit/b1" in "".join(following[:6])


def _jobs() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


# ---------------------------------------------------------------------------------------------------------------------
# build_windows.bat
# ---------------------------------------------------------------------------------------------------------------------
def test_frontend_audit_gate_runs_between_npm_ci_and_the_build_and_blocks():
    commands = _commands()
    install, gate, build = (_index(commands, key) for key in ("npm ci", "npm run audit:gate", "npm run build"))
    assert install < gate < build, "gate по npm — после установки и до сборки фронтенда"
    assert commands[gate].lower().startswith("call "), "без call .bat теряет управление после npm.cmd"
    assert commands[gate + 1].replace(" ", "").lower() == "iferrorlevel1exit/b1"


def _audit_index(commands: list[str], lock: str) -> int:
    return next(i for i, line in enumerate(commands) if "pip_audit" in line and f"backend\\{lock}" in line)


def test_runtime_lock_audit_runs_after_the_install_and_before_pyinstaller_and_blocks():
    commands = _commands()
    audit = _audit_index(commands, "requirements.lock")
    assert _index(commands, "pip install") < audit < _index(commands, "PyInstaller")
    assert "--require-hashes" in commands[audit] and commands[audit].startswith("python -m pip_audit "), (
        "pip-audit из venv, куда поставлен lock"
    )
    assert "--disable-pip" in commands[audit], "lock полный и с хешами: второй venv с повторной установкой всего набора не нужен"
    assert _blocks_on_failure(commands, audit), "уязвимость в runtime-зависимости должна останавливать сборку EXE"


def test_build_lock_audit_only_reports():
    commands = _commands()
    audit = _audit_index(commands, "requirements-build.lock")
    assert _audit_index(commands, "requirements.lock") < audit < _index(commands, "PyInstaller")
    assert "--require-hashes" in commands[audit] and "--disable-pip" in commands[audit]
    follow_up = commands[audit + 1]
    assert follow_up.lower().startswith("if errorlevel 1 echo") and "exit" not in follow_up.lower()


def test_the_script_still_has_exactly_one_package_install():
    """Тест A-11: сборка ставит пакеты одной командой по lock; pip-audit приходит в venv через тот же lock, а не вторым `pip install`."""
    assert sum("pip install" in line for line in _commands()) == 1


def test_pip_audit_is_part_of_the_hashed_build_lock():
    declared = [line.split("#", 1)[0].strip().lower() for line in BUILD_TXT.read_text(encoding="utf-8").splitlines()]
    assert any(line.startswith("pip-audit") for line in declared), "requirements-build.txt должен объявлять pip-audit"
    lock = BUILD_LOCK.read_text(encoding="utf-8")
    entry = re.search(r"^pip-audit==[\d.]+ \\\n((?:\s+--hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)", lock, re.MULTILINE)
    assert entry, "pip-audit закреплён в requirements-build.lock точной версией с хешами"


# ---------------------------------------------------------------------------------------------------------------------
# CI: сборка под Windows
# ---------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def windows_job() -> dict:
    jobs = _jobs()
    assert "build-windows" in jobs, "в ci.yml нет job build-windows"
    return jobs["build-windows"]


def test_the_job_runs_on_windows_with_a_timeout(windows_job):
    assert windows_job["runs-on"] == "windows-latest"
    assert 10 <= windows_job["timeout-minutes"] <= 40


def test_the_job_runs_the_same_bat_as_developers_and_does_not_hide_failures(windows_job):
    builds = [step for step in windows_job["steps"] if "build_windows.bat" in step.get("run", "")]
    assert len(builds) == 1
    build = builds[0]
    assert build["run"].strip() == "call installer\\build_windows.bat", "единственная команда шага: код возврата шага — код .bat"
    assert build.get("shell") == "cmd"
    assert not build.get("continue-on-error") and not windows_job.get("continue-on-error")


def test_the_job_checks_that_the_build_produced_the_exe_and_its_files(windows_job):
    steps = windows_job["steps"]
    build = next(i for i, step in enumerate(steps) if "build_windows.bat" in step.get("run", ""))
    check = "\n".join(step.get("run", "") for step in steps[build + 1 :])
    for name in ("InfraRegistry.exe", "README_EXE.md", "run_infra_registry.bat"):
        assert f"dist\\{name}" in check, f"после сборки не проверяется dist\\{name}"


def test_every_action_in_the_job_is_pinned_by_sha(windows_job):
    used = [step["uses"] for step in windows_job["steps"] if "uses" in step]
    assert used and all(PINNED_ACTION.match(item) for item in used), used


def test_the_job_uses_the_same_node_and_python_as_the_test_job(windows_job):
    def versions(job: dict) -> dict[str, str]:
        found = {}
        for step in job["steps"]:
            if step.get("uses", "").startswith("actions/setup-python@"):
                found["python"] = str(step["with"]["python-version"])
            if step.get("uses", "").startswith("actions/setup-node@"):
                found["node"] = str(step["with"]["node-version"])
        return found

    expected = versions(_jobs()["test"])
    assert set(expected) == {"python", "node"} and versions(windows_job) == expected


# ---------------------------------------------------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------------------------------------------------
def test_readme_describes_the_audits_of_the_windows_build():
    text = README.read_text(encoding="utf-8")
    for needle in ("build-windows", "audit:gate", "pip_audit", "requirements-build.lock"):
        assert needle in text, f"в README нет «{needle}»"
