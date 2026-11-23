"""CI проверяет Windows — продукт поставляется как Windows-EXE.

Само задание можно проверить только на раннере GitHub (здесь Windows нет), поэтому тест страхует его описание: что задание существует, идёт
на windows-latest, гоняет именно платформенно-зависимые тесты (и эти файлы существуют), запускает launcher.py и спрашивает /api/v1/health,
а действия закреплены по SHA, как во всех остальных заданиях.

Запуск: pytest backend/tests/test_review_p2_ci_windows_smoke.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
PLATFORM_TESTS = ("test_launcher_backup.py", "test_pyinstaller_spec.py", "test_build_windows_bat.py")


@pytest.fixture(scope="module")
def job() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]["windows-smoke"]


def _run_scripts(job: dict) -> str:
    return "\n".join(step.get("run", "") for step in job["steps"])


def test_the_job_runs_on_windows_with_a_timeout(job):
    assert job["runs-on"] == "windows-latest"
    assert job["timeout-minutes"] <= 30


def test_it_runs_the_platform_dependent_tests_and_they_exist(job):
    scripts = _run_scripts(job)
    for name in PLATFORM_TESTS:
        assert f"backend/tests/{name}" in scripts, f"в задании нет {name}"
        assert (ROOT / "backend" / "tests" / name).is_file()


def test_pyinstaller_is_installed_so_that_the_spec_test_does_not_skip(job):
    assert "requirements-build.lock" in _run_scripts(job)


def test_windows_installs_the_locked_packages_through_python_m_pip(job):
    """Lock-файлы закрепляют и сам pip; `pip.exe` на Windows не может заменить сам себя («To modify pip, please run python -m pip install»),
    поэтому установка падала, не поставив ни одного пакета, а следующий шаг не находил `pytest`."""
    installs = [line.strip() for line in _run_scripts(job).splitlines() if "pip install" in line]
    assert installs, "в задании нет установки зависимостей"
    assert all(line.startswith("python -m pip install") for line in installs), installs


def test_it_starts_the_launcher_and_checks_health_on_the_same_port(job):
    scripts = _run_scripts(job)
    port = re.search(r"'--port', '(\d+)'", scripts).group(1)
    assert "launcher.py" in scripts and "'--no-browser'" in scripts
    assert f"http://127.0.0.1:{port}/api/v1/health" in scripts
    assert "Stop-Process" in scripts, "запущенный сервер нужно остановить, даже если проверка упала"


def test_actions_are_pinned_by_commit_sha(job):
    uses = [step["uses"] for step in job["steps"] if "uses" in step]
    assert uses and all(re.fullmatch(r"[\w./-]+@[0-9a-f]{40}( .*)?", value) for value in uses), uses


def test_the_job_uses_the_same_python_as_the_other_jobs(job):
    versions = {step["with"]["python-version"] for step in job["steps"] if "setup-python" in step.get("uses", "")}
    assert versions == {"3.12"}
