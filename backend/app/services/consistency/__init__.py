"""Проверки согласованности и полноты данных реестра (только чтение).

Правила собраны в модулях `rules_*`; импорт ниже их регистрирует. Публичный вход — `run_checks`, `summarize` и `RULES`.
"""

from . import rules_addressing, rules_information_systems, rules_inventory, rules_virtualization  # noqa: F401  (регистрация правил)
from .engine import RULES, RuleSpec, run_checks, summarize
from .model import SHEETS, Category, Finding, Severity

__all__ = ["RULES", "SHEETS", "Category", "Finding", "RuleSpec", "Severity", "run_checks", "summarize"]
