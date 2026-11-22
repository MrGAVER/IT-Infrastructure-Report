"""Smoke-запуск собранного EXE и еженедельная сборка под Windows в CI.

Job `build-windows` собирает `InfraRegistry.exe` тем же `installer\\build_windows.bat`, что и разработчик, но до сих пор не проверял, что
собранный EXE вообще запускается: пакет без `alembic` или без `frontend-vue/dist` собирался «успешно» и падал только у пользователя. Теперь после
сборки EXE стартует на свободном порту с данными во временном каталоге, и CI проверяет `/api/v1/health`, версию (она совпадает с APP_VERSION из
`backend/app/config.py`; публичный health версию не отдаёт, поэтому она читается из `/openapi.json`), раздачу собранного интерфейса и то,
что миграции действительно создали схему в `infra_registry.db`.

Кроме того, `build-windows` идёт по расписанию раз в неделю: новая уязвимость в уже влитых зависимостях иначе осталась бы незамеченной до
следующего PR. По расписанию выполняется только этот job — остальные пропускаются условием `if`.

Тест статический (запустить Windows-job здесь негде): разбирает ci.yml. Саму сборку и запуск проверяет сам job.
Запуск: pytest backend/tests/test_windows_exe_smoke_ci.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
README = ROOT / "README.md"

CRON = re.compile(r"^\S+ \S+ \S+ \S+ \S+$")


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def steps(workflow) -> list[dict]:
    return workflow["jobs"]["build-windows"]["steps"]


def _smoke(steps: list[dict]) -> dict:
    found = [step for step in steps if "InfraRegistry.exe" in step.get("run", "") and "Start-Process" in step.get("run", "")]
    assert len(found) == 1, "ровно один шаг запускает собранный EXE"
    return found[0]


# ---------------------------------------------------------------------------------------------------------------------
# расписание
# ---------------------------------------------------------------------------------------------------------------------
def _triggers(workflow: dict) -> dict:
    return workflow.get("on") or workflow[True]  # PyYAML читает ключ `on` как True


def test_ci_runs_weekly_on_a_schedule_and_can_be_started_by_hand(workflow):
    triggers = _triggers(workflow)
    crons = [entry["cron"] for entry in triggers["schedule"]]
    assert len(crons) == 1 and CRON.match(crons[0]), crons
    day_of_week = crons[0].split()[4]
    assert day_of_week.isdigit() and crons[0].split()[2:4] == ["*", "*"], "раз в неделю: день месяца и месяц — «любой»"
    assert "workflow_dispatch" in triggers, "ручной запуск нужен, чтобы проверить сборку без коммита"
    assert {"push", "pull_request"} <= set(triggers), "обычные запуски не потеряны"


def test_only_the_windows_build_runs_on_a_schedule(workflow):
    jobs = workflow["jobs"]
    guarded = {name: job.get("if", "") for name, job in jobs.items() if name != "build-windows"}
    assert guarded, "в ci.yml есть и другие job"
    for name, condition in guarded.items():
        assert "github.event_name != 'schedule'" in condition, f"job {name} не должен запускаться по расписанию"
    assert "if" not in jobs["build-windows"], "build-windows по расписанию как раз и нужен"


# ---------------------------------------------------------------------------------------------------------------------
# smoke-запуск EXE
# ---------------------------------------------------------------------------------------------------------------------
def test_the_smoke_step_comes_after_the_build_and_the_result_check(steps):
    build = next(i for i, step in enumerate(steps) if "build_windows.bat" in step.get("run", ""))
    checked = next(i for i, step in enumerate(steps) if "dist\\README_EXE.md" in step.get("run", ""))
    smoke = steps.index(_smoke(steps))
    assert build < checked < smoke


def test_the_smoke_step_runs_the_built_exe_on_its_own_port_and_data_dir(steps):
    step = _smoke(steps)
    run = step["run"]
    assert step.get("shell") == "pwsh" and not step.get("continue-on-error")
    assert "--no-browser" in run, "на раннере нет браузера"
    assert "INFRA_REGISTRY_DATA_DIR" in run and "RUNNER_TEMP" in run, "база — во временном каталоге, а не рядом с EXE"
    assert "--port" in run, "свой порт, чтобы не конфликтовать с чем-то на раннере"
    assert 2 <= step["timeout-minutes"] <= 10


def test_the_smoke_step_checks_health_version_frontend_and_migrations(steps):
    run = _smoke(steps)["run"]
    assert "/api/v1/health" in run and "infra-registry" in run
    assert "APP_VERSION" in run and "backend\\app\\config.py" in run, "версия сверяется с backend/app/config.py"
    assert 'id="app"' in run, "раздаётся собранный интерфейс (frontend-vue/dist внутри EXE)"
    assert "infra_registry.db" in run and "alembic_version" in run, "миграции прошли внутри EXE, а не только ответил /health"


def test_the_smoke_step_reads_the_version_from_openapi_because_the_public_health_does_not_return_it(steps):
    """`GET /api/v1/health` версию не отдаёт (api/system.py: версия помогает подбирать известные уязвимости), поэтому сверка с `$health.version`
    падала бы всегда. Версия есть в `/openapi.json`, а он включается только флагом INFRA_REGISTRY_ENABLE_DOCS: smoke выставляет его себе."""
    run = _smoke(steps)["run"]
    assert "INFRA_REGISTRY_ENABLE_DOCS" in run and "/openapi.json" in run and "$openapi.info.version" in run
    assert "$health.version" not in run, "версии в health нет"


def test_the_smoke_step_stops_the_exe_with_its_children_and_fails_when_it_dies_early(steps):
    run = _smoke(steps)["run"]
    assert "finally" in run and "taskkill" in run and "/T" in run, "onefile-EXE — загрузчик и дочерний процесс: убиваем дерево"
    assert "HasExited" in run, "если EXE упал при старте, шаг говорит об этом сразу, а не ждёт таймаут"


def test_the_exe_logs_are_printed_when_the_job_fails(steps):
    smoke = steps.index(_smoke(steps))
    logs = [step for step in steps[smoke + 1 :] if step.get("if") == "failure()"]
    assert len(logs) == 1 and "exe.out.log" in logs[0]["run"] and "exe.err.log" in logs[0]["run"]
    assert "exe.out.log" in _smoke(steps)["run"]


def test_the_failure_reason_is_published_as_an_annotation(steps):
    """Текст исключения и хвост логов EXE уходят в аннотации (`::error`): они видны на странице запуска и в API, а не только в журнале шага."""
    smoke = steps.index(_smoke(steps))
    assert "catch" in _smoke(steps)["run"] and "::error" in _smoke(steps)["run"]
    logs = next(step for step in steps[smoke + 1 :] if step.get("if") == "failure()")
    assert "::error" in logs["run"] and "%0A" in logs["run"], "переводы строк в команде workflow кодируются как %0A"


def test_the_smoke_step_does_not_mention_the_build_script(steps):
    """Тест A-15/A-11 ищут единственный шаг со сборкой по имени скрипта: smoke не должен путать эту проверку."""
    assert "build_windows.bat" not in _smoke(steps)["run"]


# ---------------------------------------------------------------------------------------------------------------------
# README
# ---------------------------------------------------------------------------------------------------------------------
def test_readme_describes_the_smoke_start_and_the_weekly_run():
    text = README.read_text(encoding="utf-8")
    assert "smoke" in text.lower() and "раз в неделю" in text
    assert "workflow_dispatch" in text or "вручную" in text
