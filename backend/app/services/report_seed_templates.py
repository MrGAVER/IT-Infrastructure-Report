"""
Конфигурация шаблона конструктора отчётов "Регламентированный отчёт — заготовка" — точное
воспроизведение вывода регламентированного 4-листового отчёта (backend/app/reporting.py, см. также
"Общее описание приложения" в исходном ТЗ проекта), но собранное через grid-движок конструктора
(services/report_grid.py) и открытое для дальнейшей правки в визуальном редакторе.

Как достигнута точность 1:1, а не приближение: каждый лист здесь подключён к своей "виртуальной"
сущности из services/report_registry_rows.py — уже полностью посчитанному плоскому списку строк,
переиспользующему ДОСЛОВНО ТЕ ЖЕ функции, что и reporting.py (_is_row_values/_device_row_values/
_connection_row_values_list/_vm_row_values), а не пытающемуся повторить их логику обобщёнными
путями полей вида "a.b[].c". Такой путь не может выразить фолбэк-цепочки источников, объединение
нескольких разных связей в одну колонку, фильтрацию внутри развёрнутого списка (см. подробности в
report_registry_rows.py и report_grid.py) — а функция, вызванная напрямую, может, потому что это
обычный Python, а не путь по графу связей. Поэтому у каждой строки этого шаблона — простые плоские
поля без единой связи для обхода; конструктору достаточно взять готовое значение по имени поля.

Точная эквивалентность с оригиналом на одних и тех же данных проверяется тестом
test_report_registry_rows.py::ExactParityTestCase (собирает оба отчёта на одинаковой выборке и
сравнивает содержимое ячеек лист-в-лист, а не только структуру конфигурации).

Это не мешает шаблону быть настраиваемым: набор столбцов/порядок/стили/фильтры — обычные ячейки
grid-движка, как в любом другом шаблоне. "Точность" касается только источника данных каждой ячейки
(поля виртуальной сущности), а не иммутабельности самого шаблона — пользователь может удалить любую
колонку, добавить свою (по обычным путям к сущностям реестра, не только к "виртуальным"), изменить
оформление, или удалить эти листы целиком и начать с чистого листа. Отредактированный шаблон,
разумеется, перестаёт быть точной копией — в этом и есть его предназначение: отправная точка.
"""
from __future__ import annotations

from typing import Any

from ..reporting import HEADERS1, HEADERS2, HEADERS3, HEADERS4
from .report_registry_rows import VIRTUAL_ENTITIES

TEMPLATE_NAME = "Регламентированный отчёт — заготовка (4 листа)"

TEMPLATE_DESCRIPTION = (
    "Точное воспроизведение регламентированного отчёта (4 листа — см. кнопку «Отчёт Excel» на "
    "дашборде) в визуальном редакторе: то же содержимое строк и колонок, но открытое для правки — "
    "перетаскивайте поля, добавляйте фильтры/колонки/листы, меняйте оформление. Кнопка «Отчёт "
    "Excel» остаётся основным источником для сдачи/проверки; оба используют одну и ту же логику "
    "расчёта (backend/app/services/report_registry_rows.py), поэтому расхождений между ними быть "
    "не должно, пока вы не отредактируете этот шаблон в конструкторе — тогда он, конечно, "
    "перестанет быть точной копией: в этом и есть его предназначение — отправная точка для "
    "собственных отчётов на основе тех же данных реестра."
)

_TITLE_STYLE = {"bold": True, "align": "center", "valign": "middle", "bg": "#DCE6FA", "wrap": True}
_HEADER_STYLE = {"bold": True, "align": "center", "valign": "middle", "bg": "#EEF2FF", "wrap": True}
_DATA_STYLE = {"wrap": True, "valign": "top"}
_INDEX_STYLE = {"wrap": True, "valign": "top", "align": "center"}


def _title_row(n_cols: int, text: str) -> dict[str, Any]:
    return {"height": 26, "repeat": False, "data_source": None,
            "cells": [{"col": 0, "colspan": n_cols, "kind": "static", "text": text, "style": _TITLE_STYLE}]}


def _header_row(headers: list[str]) -> dict[str, Any]:
    return {"height": 46, "repeat": False, "data_source": None, "cells": [
        {"col": i, "kind": "static", "text": h, "style": _HEADER_STYLE} for i, h in enumerate(headers)
    ]}


def _sheet(title: str, entity_key: str, headers: list[str], widths: list[int]) -> dict[str, Any]:
    """entity_key — ключ виртуальной сущности из report_registry_rows.VIRTUAL_ENTITIES: строка
    листа — один в один поля этой сущности, в том же порядке, никаких путей через связи не нужно
    (все значения уже готовы). headers — точный текст заголовков колонок оригинального отчёта
    (HEADERSn из reporting.py: для листов 1-3 уже включает "№" первым элементом, для листа 4 такой
    колонки в оригинале нет — см. reporting.py); используется как есть, чтобы заголовки в файле
    совпадали с оригиналом, а не только данные. Подписи полей в самой сущности (VirtualField.label)
    — отдельные, короче, для палитры конструктора, где 200-значные официальные формулировки
    неудобны как текст перетаскиваемого чипа."""
    fields = VIRTUAL_ENTITIES[entity_key].fields
    numbered = len(headers) == len(fields) + 1
    n_cols = len(headers)
    assert len(widths) == n_cols, (title, len(widths), n_cols)

    cells = []
    if numbered:
        cells.append({"col": 0, "kind": "index", "style": _INDEX_STYLE})
    offset = 1 if numbered else 0
    for i, f in enumerate(fields):
        cells.append({"col": i + offset, "kind": "field", "path": f.name, "separator": "; ", "style": _DATA_STYLE})

    data_row = {
        "height": 20, "repeat": True,
        # Виртуальные сущности уже отдают строки в нужном порядке (для листа 3 — уже
        # отсортированном/сгруппированном как в оригинале) — дополнительная sort_by здесь была бы
        # лишней и могла бы разойтись с порядком строк оригинального отчёта.
        "data_source": {"root_entity": entity_key, "expand": "", "include_empty_expand": True,
                         "filters": [], "sort_by": ""},
        "cells": cells,
    }
    return {
        "title": title,
        "columns": [{"width": w} for w in widths],
        "rows": [_title_row(n_cols, f"{title} — по состоянию на {{{{report_date}}}}"), _header_row(headers), data_row],
    }


def default_registry_template_config() -> dict[str, Any]:
    """Конфигурация xlsx-шаблона конструктора (config для report_templates.config). Структурная
    валидация — test_report_seed_templates.py; точная эквивалентность с оригиналом на реальных
    данных (данные И заголовки) — test_report_registry_rows.py::ExactParityTestCase."""

    sheet1 = _sheet(
        "Перечень ИС", "registry-is-rows", HEADERS1,
        widths=[5, 26, 32, 26, 20, 18, 34, 26, 24, 16, 12, 24, 20, 30, 26, 22, 22, 22],
    )
    sheet2 = _sheet(
        "Инвентаризац. физ. устройств ИС", "registry-device-rows", HEADERS2,
        widths=[5, 20, 20, 20, 22, 20, 20, 22, 12, 20, 26, 20, 20],
    )
    sheet3 = _sheet(
        "Организация подключений", "registry-connection-rows", HEADERS3,
        widths=[5, 18, 20, 20, 20, 14, 18, 22, 16, 12, 16, 16, 22, 18, 20, 20, 20, 18],
    )
    sheet4 = _sheet(
        "Организация управления ВМ", "registry-vm-rows", HEADERS4,
        widths=[22, 20, 20, 24, 20, 24, 22, 26, 20, 26],
    )

    return {"params": [], "sheets": [sheet1, sheet2, sheet3, sheet4]}
