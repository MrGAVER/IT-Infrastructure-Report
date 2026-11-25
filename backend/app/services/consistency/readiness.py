"""«Готовность отчёта»: по каждому листу Excel-отчёта — сколько объектов не имеют незакрытых проблем проверки данных.

Считается по тем же находкам, что и экран «Проверка данных», поэтому числа на дашборде и на экране проверки не расходятся. Объект
«готов», если у него нет находок, требующих внимания; одобренные находки (services/consistency/approvals.py) не мешают. Лист 3
считается по активным подключениям: неактивное в отчёт не попадает.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...models import Connection, Container, InformationSystem, PhysicalDevice, VirtualMachine
from .approvals import load_approvals
from .engine import RULES, run_checks
from .model import Finding

TOP_RULES = 3


@dataclass(frozen=True, slots=True)
class SheetSpec:
    sheet: int
    title: str
    # Типы объектов листа (entity_type находок) и таблицы, по которым считается их общее число.
    entity_types: tuple[str, ...]
    models: tuple[type, ...]
    # False — для листа нет правил (сейчас проверяются все четыре, поле оставлено для будущих листов).
    checked: bool = True
    # Считать только активные записи (у подключения есть признак активности: неактивное в отчёт не попадает).
    active_only: bool = False


SHEETS: tuple[SheetSpec, ...] = (
    SheetSpec(1, "Информационные системы", ("information_system",), (InformationSystem,)),
    SheetSpec(2, "Физические устройства", ("physical_device",), (PhysicalDevice,)),
    SheetSpec(3, "Подключения", ("connection",), (Connection,), active_only=True),
    SheetSpec(4, "Виртуальные машины и контейнеры", ("virtual_machine", "container"), (VirtualMachine, Container)),
)


def affected_objects(finding: Finding) -> set[tuple[str, str]]:
    """Объекты, которых касается находка. У находок про повтор имени и адреса сам «объект» — имя или IP, а проблемные объекты лежат
    в details (devices / holders): считаем их, иначе повтор имени зацепил бы одно устройство из нескольких."""
    nested = finding.details.get("devices") or finding.details.get("holders")
    if isinstance(nested, list):
        found = {
            (str(item.get("entity_type") or "physical_device"), str(item["entity_id"]))
            for item in nested
            if isinstance(item, dict) and "entity_id" in item
        }
        if found:
            return found
    return {(finding.entity_type, finding.entity_id)}


def _total(session: Session, spec: SheetSpec) -> int:
    def count(model: type) -> int:
        query = select(func.count()).select_from(model)
        return session.scalar(query.where(model.is_active.is_(True)) if spec.active_only else query) or 0

    return sum(count(model) for model in spec.models)


def _percent(ready: int, total: int) -> int | None:
    """Доля готовых объектов, округлённая ВНИЗ: 100 % показывается только когда готовы все, а не «299 из 300»."""
    return None if total == 0 else ready * 100 // total


def _sheet_entry(session: Session, spec: SheetSpec, active: list[Finding], approved: list[Finding]) -> dict[str, Any]:
    total = _total(session, spec)
    entry: dict[str, Any] = {"sheet": spec.sheet, "title": spec.title, "total": total, "checked": spec.checked}
    if not spec.checked:
        return {**entry, "affected": None, "ready": None, "percent": None, "problems": 0, "approved": 0, "top_rules": []}
    affected = {obj for finding in active for obj in affected_objects(finding) if obj[0] in spec.entity_types}
    counts = Counter(finding.rule for finding in active)
    top = sorted(counts.items(), key=lambda pair: (-pair[1], RULES[pair[0]].title.casefold()))[:TOP_RULES]
    return {
        **entry,
        "affected": len(affected),
        "ready": total - len(affected),
        "percent": _percent(total - len(affected), total),
        "problems": len(active),
        "approved": len(approved),
        "top_rules": [{"rule": code, "title": RULES[code].title, "count": count} for code, count in top],
    }


def build_report_readiness(session: Session) -> dict[str, Any]:
    """Готовность по листам отчёта и число проблем, не привязанных к листу (повтор IP и т. п. — они задевают сразу несколько листов).

    `affected` — сколько разных объектов листа имеют проблемы, требующие внимания, `problems` — сколько таких проблем (у объекта их
    может быть несколько), `approved` — сколько проблем листа одобрено. `percent` — доля готовых объектов, None — объектов нет
    или лист не проверяется.
    """
    approvals = load_approvals(session)
    findings = [(item, item.fingerprint in approvals) for item in run_checks(session)]
    sheets = []
    for spec in SHEETS:
        on_sheet = [(item, done) for item, done in findings if item.sheet == spec.sheet]
        sheets.append(_sheet_entry(session, spec, [item for item, done in on_sheet if not done], [item for item, done in on_sheet if done]))
    return {"sheets": sheets, "unassigned": sum(1 for item, done in findings if item.sheet is None and not done)}
