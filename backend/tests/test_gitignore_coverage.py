"""A-21: артефакты покрытия тестами (`pytest --cov`) игнорируются git.

В репозитории был закоммичен backend/.coverage (абсолютные пути рабочей машины), а правила в .gitignore не было. Файл удалён из
репозитория по решению владельца (`git rm backend/.coverage`), правило защищает от его возвращения и от новых артефактов.
Проверка идёт с `--no-index`: она не зависит от того, отслеживается ли файл.
Запуск: pytest backend/tests/test_gitignore_coverage.py -v
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ["backend/.coverage", ".coverage", "backend/.coverage.host.12345.abc", "coverage.xml", "backend/htmlcov/index.html"]


def test_gitignore_lists_the_coverage_artifacts():
    rules = {line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert {".coverage", ".coverage.*", "coverage.xml", "htmlcov/"} <= rules


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="нужны git и рабочая копия репозитория")
@pytest.mark.parametrize("path", ARTIFACTS)
def test_git_ignores_the_artifact(path):
    result = subprocess.run(["git", "check-ignore", "--no-index", "-v", path], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"{path} не игнорируется: {result.stdout}{result.stderr}"
    assert ".gitignore" in result.stdout


@pytest.mark.skipif(shutil.which("git") is None or not (ROOT / ".git").exists(), reason="нужны git и рабочая копия репозитория")
def test_coverage_artifact_is_not_tracked_any_more():
    result = subprocess.run(["git", "ls-files", "--", "backend/.coverage", ".coverage"], cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 0
    assert result.stdout.strip() == "", "backend/.coverage снова отслеживается git"
