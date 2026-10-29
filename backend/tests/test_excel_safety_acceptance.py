"""A-17: критерии приёмки тикета на конкретных значениях.

Сама реализация («тип ячейки — строка + quotePrefix, без апострофа в значении») уже в main (коммит 8e74eb8, services/excel_safety.py);
тесты test_excel_safety.py проверяют её на собственных значениях. Здесь — те значения, что названы в тикете, через сохранённый
файл и обратное чтение: формула в файле не появляется, телефон и отрицательные числа-строки читаются без апострофа.
Запуск: pytest backend/tests/test_excel_safety_acceptance.py -v
"""
from __future__ import annotations

import io
import zipfile

import openpyxl
import pytest

from app.services.excel_safety import append_safe_row

VALUES = ['=HYPERLINK("http://evil","x")', "+7 (495) 123", "-", "-5", "@имя", "Обычное имя"]


@pytest.fixture(scope="module")
def saved() -> bytes:
    workbook = openpyxl.Workbook()
    append_safe_row(workbook.active, VALUES)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_a_formula_value_has_no_formula_tag_in_the_file(saved):
    with zipfile.ZipFile(io.BytesIO(saved)) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "<f>" not in sheet_xml and "<f " not in sheet_xml


def test_no_value_gets_a_visible_apostrophe(saved):
    with zipfile.ZipFile(io.BytesIO(saved)) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "<t>'" not in sheet_xml
    reloaded = [cell.value for cell in openpyxl.load_workbook(io.BytesIO(saved)).active[1]]
    assert reloaded == VALUES, "значения читаются обратно ровно такими, какими были записаны"


def test_dash_and_negative_string_are_not_altered(saved):
    cells = openpyxl.load_workbook(io.BytesIO(saved)).active[1]
    assert (cells[2].value, cells[3].value) == ("-", "-5")
    assert not cells[2].quotePrefix, "одиночный «-» — плейсхолдер «нет данных», без признака"


def test_dangerous_looking_cells_are_text_with_the_invisible_prefix(saved):
    cells = openpyxl.load_workbook(io.BytesIO(saved)).active[1]
    guarded = [cells[0], cells[1], cells[3], cells[4]]
    assert all(cell.data_type == "s" and cell.quotePrefix for cell in guarded)
    assert not cells[5].quotePrefix
