"""
Код-ревью r3, A-10: защита цепочки поставок — образы по digest, автообновление зависимостей, статический анализ безопасности в CI.

* Базовые образы Dockerfile закреплены только тегами (`node:22-slim`, `python:3.12-slim`): тег переписывается издателем, и образ, собранный
  завтра, мог оказаться другим, чем проверенный сегодня. Теперь к тегу добавлен digest (`node:22-slim@sha256:…`); тег остаётся для
  читателя и для Dependabot, который обновляет их вместе.
* `.github/dependabot.yml` — автообновление pip, npm, docker и github-actions (действия CI закреплены по SHA, и обновлять их
  вручную некому).
* В CI есть шаг `bandit -r backend/app -ll`, а сам bandit — в закреплённых dev-зависимостях с хешами.

Тест статический: docker daemon и доступ к реестрам в окружении разработки недоступны, поэтому сборку образа проверяет CI (`docker build`).
Запуск: pytest backend/tests/test_supply_chain_config.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "backend" / "Dockerfile"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
DEV_REQUIREMENTS = ROOT / "backend" / "requirements-dev.txt"
DEV_LOCK = ROOT / "backend" / "requirements-dev.lock"

PINNED_FROM = re.compile(r"^FROM (?P<image>[a-z0-9./_-]+):(?P<tag>[\w.-]+)@sha256:(?P<digest>[0-9a-f]{64})(?: AS (?P<stage>[\w-]+))?$")


def _from_lines() -> list[str]:
    return [line.strip() for line in DOCKERFILE.read_text(encoding="utf-8").splitlines() if line.strip().startswith("FROM ")]


# --- Образы по digest -------------------------------------------------------------------------------------------------------------
def test_the_dockerfile_has_both_base_images():
    assert len(_from_lines()) == 2, "ожидаются два FROM: сборка фронтенда и итоговый образ"


@pytest.mark.parametrize("line", _from_lines())
def test_every_base_image_is_pinned_by_digest_and_keeps_its_tag(line):
    match = PINNED_FROM.match(line)
    assert match, f"образ должен быть `имя:тег@sha256:<64 hex>`, а здесь: {line!r}"
    assert match["tag"] != "latest"


def test_the_pinned_images_match_the_versions_ci_runs_on():
    """Образ и CI живут на одной версии: сборка в Docker и проверки в CI не должны расходиться по Node и Python.

    Версию задаёт ci.yml (`node-version`, `python-version`), а Dockerfile обязан её повторять. Так смена Node или Python остаётся
    одной миграцией (Dockerfile и ci.yml вместе), а PR Dependabot, который меняет только образ (как были #7 и #8), ловится этим
    тестом, а не уже в
    CI на пустом месте.
    """
    images = {m["image"]: m["tag"] for m in map(PINNED_FROM.match, _from_lines()) if m}
    ci = CI.read_text(encoding="utf-8")
    node = set(re.findall(r'node-version:\s*"?([0-9]+)"?', ci))
    python = set(re.findall(r'python-version:\s*"?([0-9]+\.[0-9]+)"?', ci))
    assert len(node) == 1 and len(python) == 1, (
        f"в ci.yml везде должна быть одна версия Node и одна Python, а сейчас: {sorted(node)}, {sorted(python)}"
    )
    assert images == {"node": f"{node.pop()}-slim", "python": f"{python.pop()}-slim"}


def test_a_digest_is_not_reused_for_two_different_images():
    digests = [m["digest"] for m in map(PINNED_FROM.match, _from_lines()) if m]
    assert len(digests) == len(set(digests))


# --- Dependabot -------------------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def dependabot() -> dict:
    assert DEPENDABOT.is_file(), ".github/dependabot.yml отсутствует"
    return yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))


def test_dependabot_covers_the_four_ecosystems(dependabot):
    assert dependabot["version"] == 2
    assert {update["package-ecosystem"] for update in dependabot["updates"]} == {"pip", "npm", "docker", "github-actions"}


def test_every_dependabot_entry_points_at_a_real_directory_with_its_manifest(dependabot):
    manifests = {
        "pip": "requirements.txt",
        "npm": "package.json",
        "docker": "Dockerfile",
        "github-actions": "workflows/ci.yml",  # для github-actions каталог — корень репозитория, манифесты лежат в .github/
    }
    for update in dependabot["updates"]:
        ecosystem, directory = update["package-ecosystem"], update["directory"]
        assert directory.startswith("/"), f"{ecosystem}: каталог задаётся от корня репозитория"
        base = ROOT / directory.lstrip("/")
        manifest = (ROOT / ".github" / manifests[ecosystem]) if ecosystem == "github-actions" else base / manifests[ecosystem]
        assert manifest.is_file(), f"{ecosystem}: в {directory} нет {manifests[ecosystem]}"
        assert update["schedule"]["interval"] in {"daily", "weekly", "monthly"}


def test_dependabot_limits_the_flood_of_pull_requests(dependabot):
    for update in dependabot["updates"]:
        assert 0 < update.get("open-pull-requests-limit", 10) <= 10, update["package-ecosystem"]


def _ignore_rules(dependabot: dict, ecosystem: str) -> dict[str, dict]:
    update = next(u for u in dependabot["updates"] if u["package-ecosystem"] == ecosystem)
    return {rule["dependency-name"]: rule for rule in update.get("ignore", [])}


def test_dependabot_does_not_propose_runtime_or_toolchain_version_jumps(dependabot):
    """Python и TypeScript меняются отдельной миграцией, а не PR Dependabot (PR #7 и #20 были красными).

    Образ python:3.12-slim закреплён сознательно (CI, lock-файлы и тесты идут на 3.12; у Python нет LTS: каждая минорная линия
    поддерживается 5 лет, а исправления безопасности приходят обновлением digest тега). TypeScript 7 не ставится из-за
    peer-зависимостей vue-tsc и
    typescript-eslint. Правила не должны пропасть незаметно. Node в этом списке нет: он на LTS, и его следующие линии Dependabot
    предлагает сам.
    """
    docker = _ignore_rules(dependabot, "docker")
    assert set(docker["python"]["update-types"]) >= {"version-update:semver-minor", "version-update:semver-major"}  # 3.12 → 3.15 — минорное
    assert set(_ignore_rules(dependabot, "npm")["typescript"]["update-types"]) >= {"version-update:semver-major"}


# --- bandit в CI -------------------------------------------------------------------------------------------------------------------
def _ci_run_steps() -> list[str]:
    jobs = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]
    return [step["run"] for step in jobs["test"]["steps"] if "run" in step]


def test_ci_runs_bandit_on_the_application_code_at_medium_and_above():
    assert any("bandit -r backend/app -ll" in run for run in _ci_run_steps())


def test_the_bandit_step_blocks_the_merge():
    steps = yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]["test"]["steps"]
    step = next(step for step in steps if "bandit -r backend/app" in step.get("run", ""))
    assert not step.get("continue-on-error"), "шаг bandit — gate: срабатывание среднего и высокого уровня блокирует слияние"


def test_bandit_is_a_pinned_dev_dependency():
    assert re.search(r"^bandit\b", DEV_REQUIREMENTS.read_text(encoding="utf-8"), re.MULTILINE)
    lock = DEV_LOCK.read_text(encoding="utf-8")
    entry = re.search(r"^bandit==[\d.]+ \\\n((?:\s+--hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)", lock, re.MULTILINE)
    assert entry, "bandit должен быть закреплён в requirements-dev.lock с хешами"
