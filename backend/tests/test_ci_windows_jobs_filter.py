"""Windows-задания CI идут не на каждом PR (F-12 код-ревью).

`windows-smoke` и `build-windows` занимают до 30 минут на Windows-раннере и запускались даже при правке одной документации. Фильтр
`paths:` на уровне workflow отключил бы вообще все задания (а обязательные проверки остались бы «в ожидании»), поэтому решение
принимает дешёвое задание `changes`: на pull_request оно сравнивает merge-коммит с вершиной main, а Windows-задания пропускаются
условием `if` (пропущенное задание считается пройденным). Push, расписание и ручной запуск проверяют Windows всегда.

Проверяется и структура ci.yml, и сам скрипт: он выполняется настоящей оболочкой на смоделированных merge-коммитах PR.
Запуск: pytest backend/tests/test_ci_windows_jobs_filter.py -v
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CI = ROOT / ".github" / "workflows" / "ci.yml"
WINDOWS_JOBS = ("windows-smoke", "build-windows")


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def filter_script(workflow, tmp_path_factory) -> Path:
    (step,) = [step for step in workflow["jobs"]["changes"]["steps"] if step.get("id") == "filter"]
    path = tmp_path_factory.mktemp("ci") / "filter.sh"
    path.write_text(step["run"], encoding="utf-8")
    return path


class TestWorkflowStructure:
    def test_windows_jobs_wait_for_the_decision_and_use_it(self, workflow):
        for name in WINDOWS_JOBS:
            job = workflow["jobs"][name]
            assert job["needs"] == "changes", name
            assert "needs.changes.outputs.windows == 'true'" in job["if"], name

    def test_the_weekly_schedule_still_runs_only_the_windows_build(self, workflow):
        """Расписание: `changes` не пропускается (иначе build-windows остался бы без решения), windows-smoke по расписанию не нужен."""
        assert "if" not in workflow["jobs"]["changes"]
        assert "schedule" not in workflow["jobs"]["build-windows"]["if"]
        assert "!= 'schedule'" in workflow["jobs"]["windows-smoke"]["if"]
        assert workflow["jobs"]["changes"]["outputs"] == {"windows": "${{ steps.filter.outputs.windows }}"}

    def test_other_jobs_do_not_depend_on_the_filter(self, workflow):
        for name, job in workflow["jobs"].items():
            if name not in (*WINDOWS_JOBS, "changes"):
                assert "changes" not in (job.get("needs") or []), f"{name} не должен зависеть от фильтра Windows"

    def test_there_is_no_workflow_level_paths_filter_that_would_switch_off_every_job(self, workflow):
        triggers = workflow.get("on") or workflow[True]  # PyYAML читает ключ `on` как булево True
        for event in ("push", "pull_request"):
            assert "paths" not in triggers[event] and "paths-ignore" not in triggers[event], event

    def test_the_merge_commit_and_both_parents_are_fetched(self, workflow):
        checkout = workflow["jobs"]["changes"]["steps"][0]
        assert checkout["uses"].startswith("actions/checkout@")
        assert checkout["with"]["fetch-depth"] >= 2, "HEAD^1 (main) нужен для сравнения"


def _decide(script: Path, tmp_path: Path, files: list[str], event: str = "pull_request", with_base: bool = True) -> str:
    """Смоделированный PR: ветка с `files` вливается merge-коммитом в main, который успел уйти вперёд; запускается скрипт `changes`."""
    repo = tmp_path / "repo"
    shutil.rmtree(repo, ignore_errors=True)
    repo.mkdir()

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args], check=True, capture_output=True
        )

    git("init", "-q", "-b", "main")
    (repo / "base.txt").write_text("base", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")
    if with_base:
        git("checkout", "-qb", "pr")
        for name in files:
            target = repo / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("x", encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "pr")
        git("checkout", "-q", "main")
        (repo / "main_moved.txt").write_text("m", encoding="utf-8")  # main ушёл вперёд: в сравнение это попадать не должно
        git("add", "-A")
        git("commit", "-qm", "main moved")
        git("merge", "-q", "--no-ff", "pr", "-m", "merge ref")
    output = tmp_path / "github_output"
    output.write_text("", encoding="utf-8")
    environment = {"PATH": os.environ["PATH"], "EVENT_NAME": event, "GITHUB_OUTPUT": str(output), "TMPDIR": str(tmp_path)}
    subprocess.run(["sh", str(script)], cwd=repo, env=environment, check=True, capture_output=True)
    (line,) = output.read_text(encoding="utf-8").splitlines()
    assert line in ("windows=true", "windows=false"), line
    return line.removeprefix("windows=")


@pytest.mark.skipif(shutil.which("sh") is None or shutil.which("git") is None, reason="нужны sh и git")
class TestFilterScript:
    @pytest.mark.parametrize(
        "changed",
        [
            "launcher.py",
            "infra_registry.spec",
            "installer/build_windows.bat",
            "backend/app/main.py",
            "backend/requirements.lock",
            "backend/тест_кириллица.py",
            "frontend-vue/src/App.vue",
            "frontend-vue/package-lock.json",
            ".github/workflows/ci.yml",
        ],
    )
    def test_files_the_exe_depends_on_switch_the_windows_jobs_on(self, filter_script, tmp_path, changed):
        assert _decide(filter_script, tmp_path, [changed]) == "true"

    def test_documentation_and_compose_only_pr_skips_windows(self, filter_script, tmp_path):
        files = ["README.md", "CHANGELOG.md", "docs/guide.md", "docker-compose.yml", ".env.example", ".github/workflows/other.yml"]
        assert _decide(filter_script, tmp_path, files) == "false"

    def test_one_relevant_file_among_irrelevant_ones_is_enough(self, filter_script, tmp_path):
        assert _decide(filter_script, tmp_path, ["README.md", "docs/a.md", "launcher.py"]) == "true"

    @pytest.mark.parametrize("event", ["push", "schedule", "workflow_dispatch"])
    def test_other_events_always_run_windows(self, filter_script, tmp_path, event):
        assert _decide(filter_script, tmp_path, ["README.md"], event=event) == "true"

    def test_without_a_base_to_compare_it_is_safer_to_run(self, filter_script, tmp_path):
        assert _decide(filter_script, tmp_path, [], with_base=False) == "true"
