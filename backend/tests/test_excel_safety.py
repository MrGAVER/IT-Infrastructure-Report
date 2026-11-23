"""Защита отчётов Excel от «формульной инъекции» (app/services/excel_safety.py).

Было: к значению дописывался апостроф — в файле это обычный символ, и в Excel он виден («'+7 495…», «'-core»).
Стало: значение остаётся как есть, а ячейка становится текстовой (тип «строка», без <f>) и получает `quotePrefix` —
невидимый «апостроф» Excel. Здесь проверяется и объект ячейки, и сам файл (XML), потому что угроза — именно тег <f>.
Запуск: pytest backend/tests/test_excel_safety.py -v
"""

from __future__ import annotations

import io
import re
import zipfile

import openpyxl
import pytest
from openpyxl.cell import WriteOnlyCell

from app.services.excel_safety import append_safe_row, guard_text_cell, needs_text_guard

TRIGGERS = ['=HYPERLINK("http://evil")', "=1+1", "+7 495 000-00-00", "-core-sw", "-2+3+cmd|' /C calc'!A0", "@SUM(A1)", "\t=cmd", "\r=cmd"]


def _saved(workbook) -> bytes:
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _xml(data: bytes, part: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read(part).decode("utf-8")


class TestWhatNeedsAGuard:
    @pytest.mark.parametrize("value", TRIGGERS)
    def test_text_that_excel_could_read_as_a_formula(self, value):
        assert needs_text_guard(value) is True

    @pytest.mark.parametrize("value", ["Обычный текст", "", "a=b", "name+", "Gi0/1", " =leading space"])
    def test_ordinary_text_is_not_touched(self, value):
        assert needs_text_guard(value) is False

    def test_lone_dash_is_the_project_wide_no_data_placeholder(self):
        assert needs_text_guard("-") is False

    @pytest.mark.parametrize("value", [42, 3.5, None, True, ["=x"]])
    def test_only_strings_can_become_formulas(self, value):
        assert needs_text_guard(value) is False


class TestCell:
    @pytest.mark.parametrize("value", TRIGGERS)
    def test_value_is_kept_and_the_cell_becomes_text(self, value):
        cell = openpyxl.Workbook().active["A1"]
        cell.value = value
        guard_text_cell(cell)
        assert cell.value == value  # никакого апострофа в значении
        assert cell.data_type == "s" and cell.quotePrefix is True

    def test_openpyxl_would_have_made_a_formula_without_the_guard(self):
        """Фиксирует исходную угрозу: без защиты «=…» превращается в формулу."""
        cell = openpyxl.Workbook().active["A1"]
        cell.value = "=1+1"
        assert cell.data_type == "f"

    @pytest.mark.parametrize("value", ["Обычный текст", "-", 42, None])
    def test_other_cells_are_left_alone(self, value):
        cell = openpyxl.Workbook().active["A1"]
        cell.value = value
        before = cell.data_type
        guard_text_cell(cell)
        assert cell.data_type == before and not cell.quotePrefix


class TestWorksheetRow:
    def test_appended_row_guards_only_the_dangerous_cells(self):
        sheet = openpyxl.Workbook().active
        append_safe_row(sheet, [1, "=evil()", "Обычное имя", "-", None, "+7 495"])
        cells = sheet[1]
        assert [c.value for c in cells[:4]] == [1, "=evil()", "Обычное имя", "-"] and cells[5].value == "+7 495"
        assert [c.quotePrefix for c in cells] == [False, True, False, False, False, True]
        assert cells[1].data_type == "s"

    def test_each_appended_row_is_guarded_in_its_own_position(self):
        sheet = openpyxl.Workbook().active
        append_safe_row(sheet, ["первая"])
        append_safe_row(sheet, ["=вторая"])
        assert (sheet["A1"].quotePrefix, sheet["A2"].quotePrefix) == (False, True)


class TestSavedFile:
    def test_the_file_holds_text_without_a_formula_tag_and_without_an_apostrophe(self):
        workbook = openpyxl.Workbook()
        append_safe_row(workbook.active, ['=HYPERLINK("http://evil")', "+7 495", "ordinary"])
        data = _saved(workbook)

        sheet_xml = _xml(data, "xl/worksheets/sheet1.xml")
        assert "<f>" not in sheet_xml and "<f " not in sheet_xml  # угроза — именно тег формулы
        # openpyxl хранит строки как inlineStr: значение целиком, без апострофа, у опасных ячеек — стиль с quotePrefix
        assert re.search(
            r'<c r="A1" s="\d+" t="inlineStr"><is><t>=HYPERLINK\(&quot;http://evil&quot;\)</t></is></c>|<c r="A1" s="\d+" '
            r't="inlineStr"><is><t>=HYPERLINK\("http://evil"\)</t></is></c>',
            sheet_xml,
        )
        assert "<t>'" not in sheet_xml
        assert re.search(r'<c r="B1" s="\d+" t="inlineStr"><is><t>\+7 495</t></is></c>', sheet_xml)
        assert re.search(r'<c r="C1" t="inlineStr">', sheet_xml)  # обычный текст без стиля-защиты
        assert 'quotePrefix="1"' in _xml(data, "xl/styles.xml")

    def test_reloaded_cells_keep_value_type_and_prefix(self):
        workbook = openpyxl.Workbook()
        append_safe_row(workbook.active, ["=1+1", "+7 495", "ordinary"])
        sheet = openpyxl.load_workbook(io.BytesIO(_saved(workbook))).active
        assert [c.value for c in sheet[1]] == ["=1+1", "+7 495", "ordinary"]
        assert [c.data_type for c in sheet[1]] == ["s", "s", "s"]
        assert [bool(c.quotePrefix) for c in sheet[1]] == [True, True, False]

    def test_a_formula_the_author_wrote_on_purpose_stays_a_formula(self):
        """Шаблоны отчётов (report_grid, kind == "formula") — формулы задуманные: guard_text_cell для них не вызывается."""
        workbook = openpyxl.Workbook()
        workbook.active["A1"].value = "=1+1"
        assert "<f>1+1</f>" in _xml(_saved(workbook), "xl/worksheets/sheet1.xml")

    def test_write_only_workbook_is_guarded_too(self):
        """Выгрузка журнала аудита пишет потоком (WriteOnlyCell)."""
        workbook = openpyxl.Workbook(write_only=True)
        sheet = workbook.create_sheet()
        cells = []
        for value in ['=HYPERLINK("http://evil")', "plain"]:
            cell = WriteOnlyCell(sheet, value=value)
            guard_text_cell(cell)
            cells.append(cell)
        sheet.append(cells)
        data = _saved(workbook)

        assert "<f>" not in _xml(data, "xl/worksheets/sheet1.xml")
        reloaded = openpyxl.load_workbook(io.BytesIO(data)).active
        assert (reloaded["A1"].value, reloaded["A1"].data_type, bool(reloaded["A1"].quotePrefix)) == (
            '=HYPERLINK("http://evil")',
            "s",
            True,
        )
        assert (reloaded["B1"].value, bool(reloaded["B1"].quotePrefix)) == ("plain", False)
