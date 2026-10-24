"""A-21: артефакты покрытия тестами (`pytest --cov`) игнорируются git.

В репозитории был закоммичен backend/.coverage (абсолютные пути рабочей машины), а правила в .gitignore не было. Файл из индекса
здесь не удаляется (это решение владельца репозитория: `git rm --cached backend/.coverage`) — правило защищает от новых артефактов.
Для уже отслеживаемого файла `git check-ignore` без `--no-index` молчит, поэтому проверка идёт с `--no-index`.
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
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-v", path], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"{path} не игнорируется: {result.stdout}{result.stderr}"
    assert ".gitignore" in result.stdout
