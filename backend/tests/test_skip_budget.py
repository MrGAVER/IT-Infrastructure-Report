"""
Код-ревью r3, ИА-08: бюджет «неожиданных» пропусков тестов (backend/tests/skip_budget.py).

Штатный отбор по базе (SQLite / PostgreSQL) пропусками «неожиданными» не считается; любой другой пропуск при заданной
INFRA_REGISTRY_MAX_UNEXPECTED_SKIPS сверх бюджета роняет прогон. Без переменной проверка выключена. Часть тестов запускает
вложенный pytest — так проверяется настоящее поведение хука, в том числе под xdist (воркеры не должны проверять сами, главный
процесс видит все пропуски).

Запуск: pytest backend/tests/test_skip_budget.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import skip_budget
import xdist  # noqa: F401  (обязательная dev-зависимость; нужна вложенному pytest с -n)
import yaml

TESTS_DIR = Path(__file__).resolve().parent


def _report(nodeid: str, longrepr) -> SimpleNamespace:
    return SimpleNamespace(nodeid=nodeid, longrepr=longrepr)


# --- Чистые функции
# --------------------------------------------------------------------------------------------------------------------------
def test_skip_reason_reads_the_reason_from_a_longrepr_tuple():
    assert skip_budget.skip_reason(_report("a", ("f.py", 3, "Skipped: нет soffice"))) == "нет soffice"


def test_skip_reason_falls_back_to_the_string_form():
    assert skip_budget.skip_reason(_report("a", "просто текст")) == "просто текст"


def test_database_selection_is_not_an_unexpected_skip():
    reports = [
        _report("t::pg", ("f.py", 1, f"Skipped: {skip_budget.POSTGRES_ONLY_REASON}")),
        _report("t::lite", ("f.py", 2, f"Skipped: {skip_budget.SQLITE_ONLY_REASON}")),
        _report("t::soffice", ("f.py", 3, "Skipped: нет soffice")),
    ]
    assert skip_budget.unexpected_skips(reports) == [("t::soffice", "нет soffice")]


@pytest.mark.parametrize(("raw", "expected"), [(None, None), ("", None), ("  ", None), ("0", 0), (" 3 ", 3)])
def test_parse_budget(raw, expected):
    assert skip_budget.parse_budget(raw) == expected


@pytest.mark.parametrize("raw", ["много", "-1", "1.5"])
def test_a_garbage_budget_is_an_error_not_a_silent_switch_off(raw):
    with pytest.raises(pytest.UsageError):
        skip_budget.parse_budget(raw)


def test_conftest_uses_the_same_reasons_as_the_budget_plugin():
    """Если причину отбора по базе поменять только в conftest.py, штатные пропуски вдруг станут «неожиданными»."""
    source = (TESTS_DIR / "conftest.py").read_text(encoding="utf-8")
    assert "reason=SQLITE_ONLY_REASON" in source and "reason=POSTGRES_ONLY_REASON" in source


# --- Вложенный pytest
# ------------------------------------------------------------------------------------------------------------------------
SAMPLE = (
    """
import pytest

def test_ok():
    pass

def test_skipped_without_reason_in_the_selection_list():
    pytest.skip("нет нужной утилиты")

def test_skipped_by_database_selection():
    pytest.skip("%s")
"""
    % skip_budget.SQLITE_ONLY_REASON
)


def _run_nested(tmp_path: Path, budget: str | None, *extra: str) -> subprocess.CompletedProcess:
    (tmp_path / "test_sample.py").write_text(SAMPLE, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != skip_budget.ENV_VAR and not k.startswith("PYTEST_")}
    env["PYTHONPATH"] = str(TESTS_DIR)
    if budget is not None:
        env[skip_budget.ENV_VAR] = budget
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-rs",
        "-p",
        "no:cacheprovider",
        "-p",
        "skip_budget",
        "--rootdir",
        str(tmp_path),
        "-c",
        "/dev/null",
        *extra,
    ]
    return subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)


def test_without_a_budget_nothing_is_checked(tmp_path):
    result = _run_nested(tmp_path, None)
    assert result.returncode == 0, result.stdout


def test_a_run_within_the_budget_passes(tmp_path):
    result = _run_nested(tmp_path, "1")
    assert result.returncode == 0, result.stdout
    assert "Бюджет" not in result.stdout


def test_a_run_over_the_budget_fails_and_names_the_culprit(tmp_path):
    result = _run_nested(tmp_path, "0")
    assert result.returncode == 1, result.stdout
    assert "Бюджет неожиданных пропусков превышен: 1 при допустимых 0" in result.stdout
    assert "test_skipped_without_reason_in_the_selection_list" in result.stdout and "нет нужной утилиты" in result.stdout
    assert "test_skipped_by_database_selection:" not in result.stdout.split("Бюджет")[1], (
        "отбор по базе в списке нарушителей быть не должен"
    )


def test_the_budget_is_enforced_by_the_main_process_under_xdist(tmp_path):
    result = _run_nested(tmp_path, "0", "-n", "2")
    assert result.returncode == 1, result.stdout
    assert "Бюджет неожиданных пропусков превышен" in result.stdout


# --- Проводка в CI
# ---------------------------------------------------------------------------------------------------------------------------
CI_FILE = TESTS_DIR.parents[1] / ".github" / "workflows" / "ci.yml"
CI_BUDGET = 2  # PyInstaller нет в requirements-dev.lock + дымовой тест LibreOffice, если на раннере нет soffice; рост — только осознанно


def _ci_pytest_steps() -> list[tuple[str, dict]]:
    workflow = yaml.safe_load(CI_FILE.read_text(encoding="utf-8"))
    return [(job, step) for job, body in workflow["jobs"].items() for step in body.get("steps", []) if "pytest" in str(step.get("run", ""))]


def _pytest_commands(step: dict) -> list[str]:
    return [line.strip() for line in str(step["run"]).splitlines() if line.strip().startswith("pytest ")]


def test_every_pytest_step_in_ci_has_the_skip_budget():
    steps = _ci_pytest_steps()
    assert {job for job, _ in steps} >= {"test", "test-postgres", "test-postgres-migrations"}
    for job, step in steps:
        raw = step.get("env", {}).get(skip_budget.ENV_VAR)
        assert raw is not None, f"job {job}: у шага pytest нет {skip_budget.ENV_VAR}"
        assert skip_budget.parse_budget(str(raw)) <= CI_BUDGET, f"job {job}: бюджет пропусков в CI вырос выше {CI_BUDGET}"


def test_every_pytest_command_in_ci_prints_the_skip_reasons():
    commands = [command for _, step in _ci_pytest_steps() for command in _pytest_commands(step)]
    assert len(commands) >= 4, commands  # два вызова в job test (обычные и slow) и по одному в двух job-ах на PostgreSQL
    assert [command for command in commands if " -rs" not in command] == []


# --- Настоящий conftest.py
# -------------------------------------------------------------------------------------------------------------------
# Выбор базы для тестов (conftest.py): вложенный прогон должен идти на SQLite независимо от того, на чём идёт родитель.
DATABASE_SELECTION_ENV = ("INFRA_REGISTRY_TEST_DATABASE_URL", "INFRA_REGISTRY_TEST_SCHEMA")


def _run_real_suite(budget: str, *tests: str) -> subprocess.CompletedProcess:
    env = {
        k: v for k, v in os.environ.items() if k != skip_budget.ENV_VAR and k not in DATABASE_SELECTION_ENV and not k.startswith("PYTEST_")
    }
    env[skip_budget.ENV_VAR] = budget
    command = [sys.executable, "-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", "-p", "no:xdist", *tests]
    return subprocess.run(command, cwd=TESTS_DIR.parents[1], env=env, capture_output=True, text=True, encoding="utf-8", timeout=300)


def test_real_suite_run_does_not_inherit_the_database_selection(monkeypatch):
    """Регрессия: в job-ах PostgreSQL (CI) вложенный прогон наследовал выбор базы родителя.

    Тест ниже проверяет поведение на SQLite («тесты только для PostgreSQL пропускаются штатно»). Но в `test-postgres` и
    `test-postgres-migrations` задан INFRA_REGISTRY_TEST_DATABASE_URL (во втором ещё и INFRA_REGISTRY_TEST_SCHEMA), вложенный pytest
    унаследовал их, пошёл на PostgreSQL, и тесты «только для PostgreSQL» не пропустились, а прошли: в выводе нет слова «skipped»,
    тест падал. В job-е на SQLite (`test`) этого не видно, поэтому наследование проверяется напрямую, подменой запуска.
    """
    monkeypatch.setenv("INFRA_REGISTRY_TEST_DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/db")
    monkeypatch.setenv("INFRA_REGISTRY_TEST_SCHEMA", "migrations")
    passed: dict[str, str] = {}

    def fake_run(command, **kwargs):
        passed.update(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    _run_real_suite("0", "backend/tests/test_migrations_postgres.py")
    assert passed, "вложенный запуск не был перехвачен"
    leaked = sorted(name for name in ("INFRA_REGISTRY_TEST_DATABASE_URL", "INFRA_REGISTRY_TEST_SCHEMA") if name in passed)
    assert not leaked, f"вложенный pytest унаследовал выбор базы родителя: {leaked}"


def test_the_real_conftest_does_not_count_database_selection_as_unexpected():
    """Тест только для PostgreSQL на SQLite пропускается штатно — при нулевом бюджете прогон от этого не падает."""
    result = _run_real_suite("0", "backend/tests/test_migrations_postgres.py")
    assert "skipped" in result.stdout and result.returncode == 0, result.stdout
