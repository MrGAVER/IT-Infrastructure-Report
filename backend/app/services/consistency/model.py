"""Модель результата проверок согласованности: находка, её важность и категория.

Находка описывает одно место в реестре, где данные противоречат друг другу (`consistency`) или не заполнены настолько, что
отчёт по листу будет неполным (`completeness`). Проверки только читают БД и ничего не исправляют: решение, какая из двух
версий данных верна, принимает человек.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Category(StrEnum):
    CONSISTENCY = "consistency"
    COMPLETENESS = "completeness"


SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}

# Листы отчёта, к которым относятся проверки полноты: 1 — перечень ИС, 2 — физические устройства, 3 — подключения, 4 — ВМ.
SHEETS = (1, 2, 3, 4)


@dataclass(frozen=True, slots=True)
class Finding:
    """Одна находка. `entity_type`/`entity_id` указывают на объект реестра, к которому ведёт ссылка в интерфейсе."""

    rule: str
    severity: Severity
    category: Category
    entity_type: str
    entity_id: str
    entity_name: str
    message: str
    sheet: int | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "category": self.category.value,
            "sheet": self.sheet,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "message": self.message,
            "details": self.details,
        }
