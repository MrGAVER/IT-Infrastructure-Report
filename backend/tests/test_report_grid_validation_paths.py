"""Каждый путь ошибки проверки строки листа конструктора отчётов (report_grid._validate_row), с текстом сообщения.

Тесты в test_report_grid.py проверяют только тип исключения; текст же видит пользователь конструктора, и функция
из 17 разных отказов раскладывается на шаги при снижении сложности (код-ревью, п. 10) — сообщения менять нельзя.
Запуск: pytest backend/tests/test_report_grid_validation_paths.py -v
"""

from __future__ import annotations

import pytest

from app.services.report_engine import ReportBuilderError
from app.services.report_grid import validate_grid_config
from app.services.report_meta import build_entity_metadata

META = build_entity_metadata()
DS = {"root_entity": "information-systems"}


def cell(col, kind="static", **kw):
    return {"col": col, "kind": kind, **kw}


def static_row(cells, **kw):
    return {"height": 18, "repeat": False, "cells": cells, **kw}


def repeat_row(cells, data_source=DS):
    return {"height": 18, "repeat": True, "data_source": data_source, "cells": cells}


def check(rows, n_cols=3):
    validate_grid_config(META, {"sheets": [{"title": "Лист", "columns": [{"width": 15}] * n_cols, "rows": rows}]})


INVALID = [
    ("row_not_object", ["не объект"], "строка 1 задана некорректно"),
    ("row_without_cells", [static_row([])], "без единой ячейки"),
    ("cell_not_object", [static_row(["не объект"])], "содержит некорректную ячейку"),
    ("column_out_of_range", [static_row([cell(5)])], "некорректный номер колонки 5"),
    ("column_negative", [static_row([cell(-1)])], "некорректный номер колонки -1"),
    ("column_is_bool", [static_row([cell(True)])], "некорректный номер колонки True"),
    ("zero_colspan", [static_row([{"col": 0, "colspan": -1, "kind": "static"}])], "colspan/rowspan должны быть ≥ 1"),
    ("colspan_beyond_sheet", [static_row([cell(2, colspan=2)])], "объединение выходит за границы листа"),
    ("rowspan_in_repeat_row", [repeat_row([cell(0, rowspan=2)])], "объединение по вертикали недопустимо в повторяющейся строке"),
    ("rowspan_beyond_last_row", [static_row([cell(0, rowspan=3)]), static_row([cell(1)])], "объединение выходит за последнюю строку листа"),
    (
        "rowspan_over_repeat_row",
        [static_row([cell(0, rowspan=2)]), repeat_row([cell(1, "field", path="name")])],
        "не может охватывать повторяющуюся строку",
    ),
    ("column_taken_from_above", [static_row([cell(0, rowspan=2)]), static_row([cell(0)])], "уже занята объединением из строки выше"),
    ("overlapping_cells", [static_row([cell(0, colspan=2), cell(1)])], "ячейки в колонке 1 перекрываются"),
    ("unknown_kind", [static_row([cell(0, "волшебная")])], "неизвестный тип ячейки 'волшебная'"),
    ("field_in_static_row", [static_row([cell(0, "field", path="name")])], "поле из БД допустимо только в повторяющейся строке"),
    ("field_without_path", [repeat_row([cell(0, "field")])], "не задан путь поля"),
    ("index_in_static_row", [static_row([cell(0, "index")])], "«№ строки» допустим только в повторяющейся строке"),
    ("formula_without_text", [static_row([cell(0, "formula")])], "не задана формула"),
    ("bad_style_colour", [static_row([cell(0, style={"bg": "красный"})])], "должен быть в формате #RRGGBB"),
]


@pytest.mark.parametrize(("name", "rows", "fragment"), INVALID, ids=[case[0] for case in INVALID])
def test_invalid_row_is_rejected_with_a_specific_message(name, rows, fragment):
    with pytest.raises(ReportBuilderError) as exc_info:
        check(rows)
    assert fragment in str(exc_info.value), f"{name}: {exc_info.value}"


def test_style_error_keeps_its_own_location_format():
    # Ошибки стиля начинаются с «<лист>, строка N, колонка C:» (через запятую) — отличается от остальных («<лист>: строка N»).
    with pytest.raises(ReportBuilderError) as exc_info:
        check([static_row([cell(0)]), static_row([cell(0), cell(1, style={"color": "синий"})])])
    assert ", строка 2, колонка 1: цвет 'color' должен быть в формате #RRGGBB" in str(exc_info.value)


def test_error_message_names_sheet_and_row_for_the_user():
    with pytest.raises(ReportBuilderError) as exc_info:
        check([static_row([cell(0)]), static_row([cell(9)])])
    assert "строка 2" in str(exc_info.value) and "Лист" in str(exc_info.value)


VALID = [
    ("static_cells", [static_row([cell(0, text="a"), cell(1, text="b"), cell(2)])]),
    ("horizontal_merge", [static_row([cell(0, colspan=3)])]),
    ("vertical_merge_over_static_rows", [static_row([cell(0, rowspan=2)]), static_row([cell(1), cell(2)])]),
    ("repeat_row_with_field_and_index", [repeat_row([cell(0, "index"), cell(1, "field", path="name")])]),
    ("formula", [static_row([cell(0, "formula", text="=1+1")])]),
    ("coloured_cell", [static_row([cell(0, style={"bg": "#ffcc00", "color": "#000000"})])]),
    ("merge_released_after_its_rows", [static_row([cell(0, rowspan=2)]), static_row([cell(1)]), static_row([cell(0)])]),
]


@pytest.mark.parametrize(("name", "rows"), VALID, ids=[case[0] for case in VALID])
def test_valid_row_layouts_are_accepted(name, rows):
    check(rows)
