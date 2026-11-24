"""Реестр правил проверки согласованности и запуск набора правил.

Правило — функция `check(session, spec)`, возвращающая находки; регистрируется декоратором `@rule(...)`. Один код правила — одна
функция: так правило можно выбрать по коду в запросе, а в интерфейсе показать его название. Правила не должны зависеть друг от
друга и делать число запросов к БД, растущее с числом строк (запросы — константа или по пачкам идентификаторов).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from .model import SEVERITY_ORDER, Category, Finding, Severity

logger = logging.getLogger(__name__)

CheckFunction = Callable[[Session, "RuleSpec"], Iterable[Finding]]


@dataclass(frozen=True, slots=True)
class RuleSpec:
    code: str
    title: str
    severity: Severity
    category: Category
    sheet: int | None
    check: CheckFunction

    def finding(
        self,
        entity_type: str,
        entity_id: str,
        entity_name: str,
        message: str,
        *,
        severity: Severity | None = None,
        **details: Any,
    ) -> Finding:
        """Находка этого правила; `severity` переопределяет важность правила для отдельного случая."""
        return Finding(
            rule=self.code,
            severity=severity or self.severity,
            category=self.category,
            sheet=self.sheet,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            message=message,
            details=details,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "title": self.title,
            "severity": self.severity.value,
            "category": self.category.value,
            "sheet": self.sheet,
        }


RULES: dict[str, RuleSpec] = {}


def rule(code: str, title: str, severity: Severity, category: Category, sheet: int | None = None):
    """Регистрирует функцию как правило. Повторный код — ошибка программиста, поэтому падаем при импорте."""

    def register(check: CheckFunction) -> CheckFunction:
        if code in RULES:
            raise ValueError(f"правило {code!r} уже зарегистрировано")
        RULES[code] = RuleSpec(code=code, title=title, severity=severity, category=category, sheet=sheet, check=check)
        return check

    return register


def run_checks(
    session: Session,
    *,
    rules: Collection[str] | None = None,
    categories: Collection[Category] | None = None,
    severities: Collection[Severity] | None = None,
    sheets: Collection[int] | None = None,
) -> list[Finding]:
    """Запускает правила (все или выбранные) и возвращает находки, отсортированные по важности, правилу и имени объекта.

    `rules` — коды правил; неизвестный код — ValueError (API превращает его в 422). `categories`/`sheets` отбирают ПРАВИЛА до
    запуска (лишние запросы к БД не делаются), `severities` — находки после запуска, потому что важность может зависеть от
    случая. Исключение внутри правила не глотается: падает весь запуск, чтобы сломанная проверка не выглядела как «всё в порядке».
    """
    if rules is not None:
        unknown = sorted(set(rules) - RULES.keys())
        if unknown:
            raise ValueError(f"неизвестные правила: {', '.join(unknown)}")
    selected = [
        spec
        for spec in RULES.values()
        if (rules is None or spec.code in rules)
        and (categories is None or spec.category in categories)
        and (sheets is None or spec.sheet in sheets)
    ]
    findings: list[Finding] = []
    for spec in selected:
        findings.extend(spec.check(session, spec))
    if severities is not None:
        findings = [item for item in findings if item.severity in severities]
    findings.sort(key=lambda item: (SEVERITY_ORDER[item.severity], item.rule, item.entity_name.casefold(), item.entity_id))
    return findings


def summarize(findings: Iterable[Finding]) -> dict[str, dict[str, int]]:
    """Счётчики находок по важности, категории, листу отчёта и правилу — для сводки на странице."""
    summary: dict[str, dict[str, int]] = {"by_severity": {}, "by_category": {}, "by_sheet": {}, "by_rule": {}}
    for item in findings:
        for key, value in (
            ("by_severity", item.severity.value),
            ("by_category", item.category.value),
            ("by_rule", item.rule),
            ("by_sheet", None if item.sheet is None else str(item.sheet)),
        ):
            if value is not None:
                summary[key][value] = summary[key].get(value, 0) + 1
    return summary
