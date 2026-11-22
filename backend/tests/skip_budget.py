"""Бюджет «неожиданных» пропусков тестов (код-ревью r3, ИА-08).

Пропуск теста — тихий провал: сломанная установка или забытый `skip` превращаются в зелёную сборку, где часть проверок просто не выполнялась.
Штатные пропуски — отбор по базе данных в conftest.py (тесты только для SQLite / только для PostgreSQL) — их число зависит от job-а и тут
не считается. Всё остальное (`pytest.skip`, `skipif`, `importorskip`, `xfail`-подобное) — «неожиданные» пропуски: если задана переменная
`INFRA_REGISTRY_MAX_UNEXPECTED_SKIPS`, их число не должно её превышать, иначе прогон завершается с ошибкой. Без переменной (локальный
запуск) ничего не проверяется. CI запускает pytest с `-rs`, поэтому причины пропусков видны в сводке; поднять бюджет можно только осознанно —
правкой числа в .github/workflows/ci.yml вместе с описанием, зачем появился новый пропуск.

Хук `pytest_sessionfinish` импортируется в conftest.py (так pytest его регистрирует; через `pytest_plugins` модуль был бы импортирован
дважды). Запуск проверок: pytest backend/tests/test_skip_budget.py -v
"""

from __future__ import annotations

import os

import pytest

ENV_VAR = "INFRA_REGISTRY_MAX_UNEXPECTED_SKIPS"
SQLITE_ONLY_REASON = "тест только для SQLite (INFRA_REGISTRY_TEST_DATABASE_URL задан)"
POSTGRES_ONLY_REASON = "тест требует PostgreSQL (задайте INFRA_REGISTRY_TEST_DATABASE_URL)"
SELECTION_REASONS = frozenset({SQLITE_ONLY_REASON, POSTGRES_ONLY_REASON})


def skip_reason(report) -> str:
    """Причина пропуска из отчёта: у пропусков по меткам и по `pytest.skip()` `longrepr` — тройка (файл, строка, «Skipped: причина»)."""
    longrepr = report.longrepr
    reason = longrepr[2] if isinstance(longrepr, tuple) and len(longrepr) == 3 else str(longrepr)
    return reason.removeprefix("Skipped: ")


def unexpected_skips(skipped_reports) -> list[tuple[str, str]]:
    """[(id теста, причина)] для пропусков, которые не являются штатным отбором по базе данных."""
    return [(report.nodeid, reason) for report in skipped_reports if (reason := skip_reason(report)) not in SELECTION_REASONS]


def parse_budget(raw: str | None) -> int | None:
    """None — бюджет не задан (проверка выключена); иначе неотрицательное целое. Мусор в переменной — ошибка, а не молчаливое отключение."""
    if raw is None or not raw.strip():
        return None
    try:
        budget = int(raw)
    except ValueError:
        raise pytest.UsageError(f"{ENV_VAR} должна быть целым числом, получено {raw!r}") from None
    if budget < 0:
        raise pytest.UsageError(f"{ENV_VAR} не может быть отрицательной: {budget}")
    return budget


def pytest_sessionfinish(session, exitstatus):
    budget = parse_budget(os.environ.get(ENV_VAR))
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if budget is None or reporter is None:  # у воркера xdist терминального репортёра нет: проверяет только главный процесс
        return
    found = unexpected_skips(reporter.stats.get("skipped", []))
    if len(found) <= budget:
        return
    reporter.write_line(f"Бюджет неожиданных пропусков превышен: {len(found)} при допустимых {budget} ({ENV_VAR}).", red=True, bold=True)
    for nodeid, reason in found:
        reporter.write_line(f"  {nodeid}: {reason}", red=True)
    if exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
