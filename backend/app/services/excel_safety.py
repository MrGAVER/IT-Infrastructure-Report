"""Защита от Excel Formula Injection.

reporting.py (`ws.append(...)` в _populate_sheet1..4), services/audit_export.py и services/report_grid.py
(`xl_cell.value = ...`) записывают пользовательские текстовые поля в ячейки openpyxl. openpyxl автоматически
помечает строку, начинающуюся с «=», тегом <f> (формула) в итоговом .xlsx: пользователь с правом записи может внести
в имя устройства/ИС/примечание значение вида "=HYPERLINK(...)", а получатель отчёта (часто с более высокими правами)
выполнит эту формулу, просто открыв файл в Excel.

Защита делается на уровне ячейки, а не правкой значения. Раньше к значению дописывался апостроф, но в файле он обычный
символ и в Excel ВИДЕН («'+7 495…», «'-core» вместо «+7 495…», «-core»). Теперь значение остаётся как есть, а ячейка

  • получает тип «строка» (`data_type = "s"`): значение хранится как текст, формулой <f> оно не станет;
  • получает стилевой признак `quotePrefix` — тот самый «невидимый апостроф» Excel: текст показывается без апострофа, а если
    пользователь позже отредактирует ячейку (F2 → Enter), Excel не превратит её в формулу.

Единая точка защиты для всех генераторов отчётов — правило одно на проект, а не по копии в каждом.
"""

from __future__ import annotations

from typing import Any

# «=», «+», «-», «@» — ведущие символы, которые Excel трактует как начало формулы; табуляция и возврат каретки — по
# рекомендации OWASP: Excel отбрасывает их перед разбором, и "\t=cmd|..." иначе проходил бы мимо проверки.
_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")

# Исключение: одиночный "-" (без ничего после) — не пользовательский ввод, а зарезервированный по всему проекту
# плейсхолдер "нет данных" (reporting.py: _link_purpose_label, _connection_row_values_list и т.п.). Формулой одиночный
# дефис быть не может, а признак на каждой пустой ячейке только раздул бы стили. Любая строка вида "-что-то"
# (потенциальный payload вроде "-2+3+cmd|...") по-прежнему защищается.
_SAFE_PLACEHOLDER = "-"


def needs_text_guard(value: Any) -> bool:
    """Строка, которую Excel мог бы принять за формулу. Нестроковые значения (числа, None, даты) формулой стать не могут."""
    return isinstance(value, str) and value != _SAFE_PLACEHOLDER and value.startswith(_FORMULA_TRIGGER_CHARS)


def guard_text_cell(cell: Any) -> None:
    """Делает ячейку openpyxl (обычную или WriteOnlyCell) текстовой, если её значение похоже на формулу.

    Вызывать ПОСЛЕ присвоения значения: именно при присвоении openpyxl выбирает тип ячейки. Остальные ячейки не
    затрагиваются. Не использовать для ячеек, где формула задумана автором (kind == "formula" в report_grid)."""
    if needs_text_guard(cell.value):
        cell.data_type = "s"
        cell.quotePrefix = True


def append_safe_row(worksheet: Any, row: list[Any]) -> None:
    """worksheet.append(row) с защитой каждой ячейки строки (обычный лист; для write-only — guard_text_cell на WriteOnlyCell)."""
    worksheet.append(row)
    for cell in worksheet[worksheet.max_row]:
        guard_text_cell(cell)
