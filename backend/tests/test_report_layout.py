"""
Оформление Excel-отчёта (backend/app/services/excel_layout.py + его применение в reporting.build_report):
рамка вокруг шапки и каждой записи (ИС / устройство / ВМ), объединение повторяющихся данных устройства на
листе 'Организация подключений', закрепление шапки, ширина колонок по данным и высота шапки по числу строк
переноса (заголовки не обрезаются).

Запуск:  python3 -m unittest discover -s backend/tests -v   (или pytest)
Интеграционная часть использует тот же мок SQLAlchemy, что и test_reporting.py (tests/mock_sqlalchemy.py).
"""
from __future__ import annotations

import sys
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

APP_DIR = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_DIR.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import openpyxl
from openpyxl import Workbook
from openpyxl.utils import get_column_letter

from app.services.excel_layout import (
    FRAME_SIDE, LINE_HEIGHT_PT, MAX_COLUMN_WIDTH, MAX_HEADER_LINES, MIN_COLUMN_WIDTH, THIN_SIDE,
    apply_borders, apply_sheet_layout, fit_column_widths, fit_header_height, fit_merged_block_heights,
    fit_sheet_size, freeze_header, header_capacity, merge_vertical, single_row_spans, style_header, text_capacity,
    wrap_lines,
)
from mock_sqlalchemy import FakeSession, empty_table, load_reporting_module
from xlsx_helpers import expanded_rows

SHEET1 = "Перечень ИС"
SHEET2 = "Инвентаризац. физ. устройств ИС"
SHEET3 = "Организация подключений"
SHEET4 = "Организация управления ВМ"
ALL_SHEETS = [SHEET1, SHEET2, SHEET3, SHEET4]


def _sheet(rows):
    """Лист: первая строка — шапка, остальные — данные (3 колонки)."""
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    return ws


def _styles(cell):
    b = cell.border
    return {"left": b.left.style, "right": b.right.style, "top": b.top.style, "bottom": b.bottom.style}


class MergeVerticalTestCase(unittest.TestCase):
    def test_merges_only_groups_of_several_rows(self):
        ws = _sheet([["№", "Устройство", "Порт"], [1, "sw1", "p1"], [2, "sw1", "p2"], [3, "sw2", "p1"]])
        merge_vertical(ws, [(2, 3), (4, 4)], columns=[2])
        self.assertEqual([str(r) for r in ws.merged_cells.ranges], ["B2:B3"])

    def test_value_stays_in_top_cell(self):
        ws = _sheet([["№", "Устройство", "Порт"], [1, "sw1", "p1"], [2, "sw1", "p2"]])
        merge_vertical(ws, [(2, 3)], columns=[2])
        self.assertEqual(ws["B2"].value, "sw1")
        self.assertIsNone(ws["B3"].value)
        self.assertEqual(expanded_rows(ws, min_row=2), [(1, "sw1", "p1"), (2, "sw1", "p2")])

    def test_other_columns_are_left_alone(self):
        ws = _sheet([["№", "Устройство", "Порт"], [1, "sw1", "p1"], [2, "sw1", "p2"]])
        merge_vertical(ws, [(2, 3)], columns=[2])
        self.assertEqual([c.value for c in ws["A"]], ["№", 1, 2])
        self.assertEqual([c.value for c in ws["C"]], ["Порт", "p1", "p2"])


class BordersTestCase(unittest.TestCase):
    def setUp(self):
        self.ws = _sheet([["№", "Устройство", "Порт"], [1, "sw1", "p1"], [2, "sw1", "p2"], [3, "sw2", "p1"]])

    def test_header_is_framed_and_inner_grid_is_thin(self):
        apply_borders(self.ws, [(2, 3), (4, 4)])
        self.assertEqual(_styles(self.ws["A1"]), {"left": "medium", "right": "thin", "top": "medium", "bottom": "medium"})
        self.assertEqual(_styles(self.ws["B1"]), {"left": "thin", "right": "thin", "top": "medium", "bottom": "medium"})
        self.assertEqual(_styles(self.ws["C1"]), {"left": "thin", "right": "medium", "top": "medium", "bottom": "medium"})

    def test_group_is_framed_as_a_whole(self):
        apply_borders(self.ws, [(2, 3), (4, 4)])
        # Группа строк 2-3: рамка по внешнему контуру, внутри тонкая сетка.
        self.assertEqual(_styles(self.ws["A2"]), {"left": "medium", "right": "thin", "top": "medium", "bottom": "thin"})
        self.assertEqual(_styles(self.ws["B3"]), {"left": "thin", "right": "thin", "top": "thin", "bottom": "medium"})
        self.assertEqual(_styles(self.ws["C3"]), {"left": "thin", "right": "medium", "top": "thin", "bottom": "medium"})

    def test_shared_edge_between_groups_is_described_identically_on_both_sides(self):
        """Общая грань соседних записей описана и снизу у верхней, и сверху у нижней ячейки —
        иначе Excel вправе показать любую из двух."""
        apply_borders(self.ws, [(2, 3), (4, 4)])
        for column in "ABC":
            self.assertEqual(self.ws[f"{column}3"].border.bottom.style, "medium")
            self.assertEqual(self.ws[f"{column}4"].border.top.style, "medium")
            self.assertEqual(self.ws[f"{column}1"].border.bottom.style, "medium")
            self.assertEqual(self.ws[f"{column}2"].border.top.style, "medium")

    def test_merged_cells_get_borders_too(self):
        merge_vertical(self.ws, [(2, 3)], columns=[2])
        apply_borders(self.ws, [(2, 3), (4, 4)])
        self.assertEqual(_styles(self.ws["B2"])["top"], "medium")
        self.assertEqual(_styles(self.ws["B3"])["bottom"], "medium")
        self.assertEqual(_styles(self.ws["B3"])["left"], "thin")

    def test_border_colours(self):
        apply_borders(self.ws, [(2, 3), (4, 4)])
        self.assertEqual(self.ws["B2"].border.left.color.rgb[-6:], THIN_SIDE.color.rgb[-6:])
        self.assertEqual(self.ws["A2"].border.left.color.rgb[-6:], FRAME_SIDE.color.rgb[-6:])

    def test_header_only_sheet(self):
        ws = _sheet([["№", "Устройство", "Порт"]])
        apply_borders(ws, [])
        self.assertEqual(_styles(ws["A1"]), {"left": "medium", "right": "thin", "top": "medium", "bottom": "medium"})


class SheetLayoutTestCase(unittest.TestCase):
    def test_freeze_header(self):
        ws = _sheet([["№", "Устройство", "Порт"], [1, "sw1", "p1"]])
        freeze_header(ws)
        self.assertEqual(ws.freeze_panes, "A2")
        freeze_header(ws, header_rows=2)
        self.assertEqual(ws.freeze_panes, "A3")

    def test_single_row_spans(self):
        ws = _sheet([["h"], [1], [2], [3]])
        self.assertEqual(single_row_spans(ws), [(2, 2), (3, 3), (4, 4)])
        self.assertEqual(single_row_spans(_sheet([["h"]])), [])

    def test_default_layout_frames_every_row_and_merges_nothing(self):
        ws = _sheet([["№", "Название", "Описание"], [1, "ИС-1", "a"], [2, "ИС-2", "b"]])
        apply_sheet_layout(ws)
        self.assertEqual(ws.freeze_panes, "A2")
        self.assertEqual(len(ws.merged_cells.ranges), 0)
        for row in (2, 3):
            self.assertEqual(ws[f"B{row}"].border.top.style, "medium")
            self.assertEqual(ws[f"B{row}"].border.bottom.style, "medium")

    def test_empty_spans_list_means_no_records_not_one_per_row(self):
        ws = _sheet([["№", "Название"], [1, "x"], [2, "y"]])
        apply_sheet_layout(ws, spans=[])
        self.assertEqual(ws["B2"].border.bottom.style, "thin")


def _width(ws, column):
    return ws.column_dimensions[get_column_letter(column)].width


class WrapLinesTestCase(unittest.TestCase):
    """Оценка числа строк переноса — основа подбора высоты шапки."""

    def test_empty_and_short_text_is_one_line(self):
        self.assertEqual(wrap_lines("", 10), 1)
        self.assertEqual(wrap_lines("коротко", 10), 1)

    def test_greedy_wrap_by_words(self):
        self.assertEqual(wrap_lines("aaaa bbbb cccc", 10), 2)
        self.assertEqual(wrap_lines("aaaa bbbbb cccc", 10), 2)    # «aaaa bbbbb» ровно 10 — помещается
        self.assertEqual(wrap_lines("aaaa bbbbbb cccc", 10), 3)   # 11 символов — слово уходит на новую строку

    def test_explicit_newlines_are_kept(self):
        self.assertEqual(wrap_lines("a\nb\nc", 10), 3)
        self.assertEqual(wrap_lines("a\n\nb", 10), 3)            # пустая строка — тоже строка

    def test_word_longer_than_line_is_split_by_characters(self):
        self.assertEqual(wrap_lines("x" * 25, 10), 3)
        self.assertEqual(wrap_lines("ab " + "x" * 25, 10), 4)

    def test_capacity(self):
        self.assertLess(header_capacity(30), text_capacity(30))   # жирный шрифт и кнопка фильтра
        self.assertEqual(header_capacity(1), 1.0)                 # не меньше одного символа


class FitColumnWidthsTestCase(unittest.TestCase):
    def test_narrow_column_for_short_header_and_short_data(self):
        ws = _sheet([["№", "Да/Нет"], [1, "Да"], [2, "Нет"]])
        fit_column_widths(ws)
        self.assertEqual(_width(ws, 1), MIN_COLUMN_WIDTH)

    def test_width_follows_data(self):
        ws = _sheet([["Имя"], ["x" * 30]])
        fit_column_widths(ws)
        self.assertEqual(_width(ws, 1), 32)    # самая длинная строка данных + 2

    def test_long_data_is_capped_so_text_wraps_instead(self):
        ws = _sheet([["Описание"], ["слово " * 60]])
        fit_column_widths(ws)
        self.assertEqual(_width(ws, 1), MAX_COLUMN_WIDTH)

    def test_header_text_is_not_counted_as_data(self):
        """Раньше заголовок в 200+ символов раздувал колонку с короткими данными до максимума."""
        ws = _sheet([["слово " * 40], ["12"]])
        fit_column_widths(ws)
        self.assertLess(_width(ws, 1), MAX_COLUMN_WIDTH)

    def test_column_is_never_narrower_than_the_longest_header_word(self):
        ws = _sheet([["Идентификаторы сетей"], ["1"]])
        fit_column_widths(ws)
        self.assertGreaterEqual(header_capacity(_width(ws, 1)), len("Идентификаторы"))

    def test_long_header_widens_column_just_enough_for_the_line_limit(self):
        header = " ".join(["слово"] * 50)
        ws = _sheet([[header], ["1"]])
        fit_column_widths(ws)
        width = _width(ws, 1)
        self.assertLessEqual(wrap_lines(header, header_capacity(width)), MAX_HEADER_LINES)
        self.assertGreater(wrap_lines(header, header_capacity(width - 1)), MAX_HEADER_LINES)  # уже нельзя

    def test_header_that_cannot_fit_gets_max_width_and_a_taller_row(self):
        ws = _sheet([[" ".join(["слово"] * 400)], ["1"]])
        fit_sheet_size(ws)
        self.assertEqual(_width(ws, 1), MAX_COLUMN_WIDTH)
        self.assertGreater(ws.row_dimensions[1].height, MAX_HEADER_LINES * LINE_HEIGHT_PT)


class FitHeaderHeightTestCase(unittest.TestCase):
    def test_one_line_header_is_one_line_high(self):
        ws = _sheet([["№", "Имя"], [1, "a"]])
        fit_sheet_size(ws)
        self.assertEqual(ws.row_dimensions[1].height, LINE_HEIGHT_PT)

    def test_height_follows_the_tallest_header(self):
        short, long_ = "Имя", " ".join(["слово"] * 30)
        ws = _sheet([[short, long_], ["a", "b"]])
        fit_sheet_size(ws)
        lines = wrap_lines(long_, header_capacity(_width(ws, 2)))
        self.assertGreater(lines, 1)
        self.assertEqual(ws.row_dimensions[1].height, lines * LINE_HEIGHT_PT)

    def test_no_header_needs_more_lines_than_the_row_has(self):
        headers = ["№", "Название", "слово " * 25, "Идентификаторы виртуальных локальных вычислительных сетей", "a " * 70]
        ws = _sheet([headers, [1, "x", "y", "z", "w"]])
        fit_sheet_size(ws)
        for column, header in enumerate(headers, 1):
            lines = wrap_lines(header, header_capacity(_width(ws, column)))
            self.assertLessEqual(lines * LINE_HEIGHT_PT, ws.row_dimensions[1].height, header)

    def test_height_is_computed_from_final_widths(self):
        """Высота считается после ширины: тот же заголовок в узкой колонке даёт более высокую шапку."""
        header = " ".join(["слово"] * 30)
        ws = _sheet([[header], ["1"]])
        ws.column_dimensions["A"].width = 12
        fit_header_height(ws)
        narrow = ws.row_dimensions[1].height
        ws.column_dimensions["A"].width = 40
        fit_header_height(ws)
        self.assertGreater(narrow, ws.row_dimensions[1].height)


class StyleHeaderTestCase(unittest.TestCase):
    def test_header_font_and_alignment(self):
        ws = _sheet([["а", "б"], [1, 2]])
        style_header(ws)
        for cell in ws[1]:
            self.assertEqual((cell.font.name, cell.font.sz, cell.font.bold), ("Calibri", 11, True))
            self.assertEqual((cell.alignment.horizontal, cell.alignment.vertical, cell.alignment.wrap_text), ("center", "center", True))
        self.assertFalse(ws["A2"].font.bold)


class MergedBlockHeightTestCase(unittest.TestCase):
    TEXT = "слово " * 30

    def _sheet(self, text, rows=2):
        ws = _sheet([["№", "Устройство", "Порт"]] + [[i + 1, text, f"p{i}"] for i in range(rows)])
        for letter, width in (("A", 8), ("B", 14), ("C", 10)):
            ws.column_dimensions[letter].width = width
        return ws

    def test_block_is_stretched_when_merged_text_does_not_fit(self):
        ws = self._sheet(self.TEXT)
        merge_vertical(ws, [(2, 3)], [2])
        fit_merged_block_heights(ws, [(2, 3)], [2])
        needed = wrap_lines(self.TEXT, text_capacity(14))
        self.assertGreater(needed, 2)
        self.assertEqual(ws.row_dimensions[2].height + ws.row_dimensions[3].height, needed * LINE_HEIGHT_PT)

    def test_extra_lines_are_shared_between_rows_of_the_block(self):
        ws = self._sheet(self.TEXT, rows=3)
        merge_vertical(ws, [(2, 4)], [2])
        fit_merged_block_heights(ws, [(2, 4)], [2])
        heights = [ws.row_dimensions[r].height for r in (2, 3, 4)]
        self.assertLessEqual(max(heights) - min(heights), LINE_HEIGHT_PT)

    def test_block_with_enough_room_keeps_automatic_heights(self):
        ws = self._sheet("sw1")
        merge_vertical(ws, [(2, 3)], [2])
        fit_merged_block_heights(ws, [(2, 3)], [2])
        self.assertIsNone(ws.row_dimensions[2].height)
        self.assertIsNone(ws.row_dimensions[3].height)

    def test_own_content_of_the_rows_counts_as_room(self):
        """Строки блока и так высокие из-за других ячеек — растягивать их под объединённый текст не нужно."""
        ws = self._sheet("слово " * 8)                   # объединённому тексту хватит ~4 строк
        for row in (2, 3):
            ws.cell(row=row, column=3).value = "слово " * 12   # в колонке шириной 10 — много строк
        merge_vertical(ws, [(2, 3)], [2])
        fit_merged_block_heights(ws, [(2, 3)], [2])
        self.assertIsNone(ws.row_dimensions[2].height)

    def test_single_row_groups_and_no_columns_are_ignored(self):
        ws = self._sheet(self.TEXT, rows=1)
        fit_merged_block_heights(ws, [(2, 2)], [2])
        self.assertIsNone(ws.row_dimensions[2].height)
        ws = self._sheet(self.TEXT)
        fit_merged_block_heights(ws, [(2, 3)], [])
        self.assertIsNone(ws.row_dimensions[2].height)

    def test_apply_sheet_layout_stretches_blocks_after_merging(self):
        ws = self._sheet(self.TEXT)
        apply_sheet_layout(ws, spans=[(2, 3)], merge_columns=(2,))
        self.assertEqual(ws.row_dimensions[2].height + ws.row_dimensions[3].height, wrap_lines(self.TEXT, text_capacity(14)) * LINE_HEIGHT_PT)


class ReportLayoutTestCase(unittest.TestCase):
    """Применение оформления в build_report на настоящем выводе всех 4 листов."""

    def setUp(self):
        self.build_report, self.C = load_reporting_module()
        self.table = empty_table()

    def build(self, name: str):
        self.path = self.build_report(FakeSession(self.table), Path(f"/tmp/test_report_layout_{name}"), None, None)
        return openpyxl.load_workbook(self.path)

    def raw_border(self, sheet_number: int, coordinate: str) -> dict:
        """Границы ячейки ровно так, как они записаны в файле (xl/worksheets/sheetN.xml + styles.xml).

        Перечитывать их через openpyxl.load_workbook нельзя: при загрузке openpyxl пересоздаёт все ячейки
        объединения, кроме верхней левой, и берёт их границы от верхней левой — собственные стили ячеек
        объединения теряются, хотя в файле они есть и именно их читает Excel."""
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        with zipfile.ZipFile(self.path) as archive:
            styles = ET.fromstring(archive.read("xl/styles.xml"))
            sheet = ET.fromstring(archive.read(f"xl/worksheets/sheet{sheet_number}.xml"))
        cell = next(c for c in sheet.iter(f"{{{ns['m']}}}c") if c.get("r") == coordinate)
        xf = styles.find("m:cellXfs", ns).findall("m:xf", ns)[int(cell.get("s", 0))]
        border = styles.find("m:borders", ns).findall("m:border", ns)[int(xf.get("borderId", 0))]
        result = {}
        for side in ("left", "right", "top", "bottom"):
            element = border.find(f"m:{side}", ns)
            result[side] = element.get("style") if element is not None else None
        return result

    def _seed_two_devices_two_ports(self, serials=("S-1", "S-2"), names=("sw-1", "sw-2")):
        """Два устройства по два порта (разные IP — порты не склеиваются в одну строку): 4 строки листа 3."""
        C = self.C
        self.table.update({
            "DeviceType": [C["DeviceType"](id="dt1", name="Коммутатор")],
            "PhysicalDevice": [
                C["PhysicalDevice"](id="d1", device_type_id="dt1", serial_number=serials[0], system_name=names[0]),
                C["PhysicalDevice"](id="d2", device_type_id="dt1", serial_number=serials[1], system_name=names[1]),
            ],
            "DeviceInterface": [
                C["DeviceInterface"](id="if1", physical_device_id="d1", name="Gi0/1"),
                C["DeviceInterface"](id="if2", physical_device_id="d1", name="Gi0/2"),
                C["DeviceInterface"](id="if3", physical_device_id="d2", name="Gi0/1"),
                C["DeviceInterface"](id="if4", physical_device_id="d2", name="Gi0/2"),
            ],
            "IPAddress": [
                C["IPAddress"](id="ip1", owner_type="device_interface", owner_id="if1", ip_address="10.0.0.1", prefix_length=24),
                C["IPAddress"](id="ip2", owner_type="device_interface", owner_id="if2", ip_address="10.0.0.2", prefix_length=24),
                C["IPAddress"](id="ip3", owner_type="device_interface", owner_id="if3", ip_address="10.0.1.1", prefix_length=24),
                C["IPAddress"](id="ip4", owner_type="device_interface", owner_id="if4", ip_address="10.0.1.2", prefix_length=24),
            ],
        })

    @staticmethod
    def _ranges(ws, column):
        return sorted((r.min_row, r.max_row) for r in ws.merged_cells.ranges if r.min_col == r.max_col == column)

    def test_header_is_frozen_on_every_sheet(self):
        self._seed_two_devices_two_ports()
        wb = self.build("freeze")
        self.assertEqual(wb.sheetnames, ALL_SHEETS)
        for ws in wb.worksheets:
            self.assertEqual(ws.freeze_panes, "A2", ws.title)

    def test_header_is_frozen_on_empty_registry(self):
        wb = self.build("empty")
        for ws in wb.worksheets:
            self.assertEqual(ws.freeze_panes, "A2", ws.title)
            self.assertEqual(len(ws.merged_cells.ranges), 0, ws.title)
            self.assertEqual(ws["A1"].border.bottom.style, "medium", ws.title)

    def test_every_record_is_framed_on_one_row_per_record_sheets(self):
        self._seed_two_devices_two_ports()
        wb = self.build("frames")
        ws = wb[SHEET2]
        self.assertEqual(ws.max_row, 3)  # шапка + два устройства
        for row in range(1, ws.max_row + 1):
            for column in range(1, ws.max_column + 1):
                cell = ws.cell(row=row, column=column)
                self.assertEqual(cell.border.top.style, "medium", cell.coordinate)
                self.assertEqual(cell.border.bottom.style, "medium", cell.coordinate)
            self.assertEqual(ws.cell(row=row, column=1).border.left.style, "medium")
            self.assertEqual(ws.cell(row=row, column=ws.max_column).border.right.style, "medium")
            self.assertEqual(ws.cell(row=row, column=2).border.left.style, "thin")

    def test_vm_and_is_sheets_are_framed_per_record(self):
        C = self.C
        self.table.update({
            "InformationSystem": [C["InformationSystem"](id="is1", name="ИС-1", crypto_protection_enabled=False),
                                  C["InformationSystem"](id="is2", name="ИС-2", crypto_protection_enabled=False)],
            "VirtualMachine": [C["VirtualMachine"](id="v1", name="VM-1", purpose=""), C["VirtualMachine"](id="v2", name="VM-2", purpose="")],
        })
        wb = self.build("is_vm")
        for title in (SHEET1, SHEET4):
            ws = wb[title]
            self.assertEqual(ws.max_row, 3, title)
            self.assertEqual(self._ranges(ws, 1), [], title)
            for row in (2, 3):
                self.assertEqual(ws.cell(row=row, column=2).border.top.style, "medium", title)
                self.assertEqual(ws.cell(row=row, column=2).border.bottom.style, "medium", title)

    def test_device_data_is_merged_over_its_ports_on_connections_sheet(self):
        self._seed_two_devices_two_ports()
        ws = self.build("merge")[SHEET3]
        self.assertEqual(ws.max_row, 5)  # шапка + 2 порта × 2 устройства
        # Колонки 2-5 (вид, серийный номер, системное имя, ОС): по одному объединению на устройство.
        for column in (2, 3, 4, 5):
            self.assertEqual(self._ranges(ws, column), [(2, 3), (4, 5)], f"колонка {column}")
        # Остальные колонки (№, порт, IP, ...) — по строке на порт, не объединяются.
        merged_columns = {r.min_col for r in ws.merged_cells.ranges}
        self.assertEqual(merged_columns, {2, 3, 4, 5})
        # Данные читаются из верхней ячейки блока, у остальных строк блока значение пустое.
        self.assertEqual([ws.cell(row=r, column=3).value for r in (2, 3, 4, 5)], ["S-1", None, "S-2", None])
        self.assertEqual(expanded_rows(ws, min_row=2)[1][2], "S-1")

    def test_device_block_is_framed_as_a_whole(self):
        """Рамка вокруг блока устройства, включая нижние ячейки объединений (колонки 2-5) — проверяется
        по границам, записанным в файле (см. raw_border)."""
        self._seed_two_devices_two_ports()
        ws = self.build("block_frame")[SHEET3]
        for column in range(1, ws.max_column + 1):
            letter = openpyxl.utils.get_column_letter(column)
            first, second, third, fourth = (self.raw_border(3, f"{letter}{row}") for row in (2, 3, 4, 5))
            self.assertEqual(first["top"], "medium", f"{letter}2")
            self.assertEqual(second["bottom"], "medium", f"{letter}3")
            self.assertEqual(third["top"], "medium", f"{letter}4")
            self.assertEqual(fourth["bottom"], "medium", f"{letter}5")
            # Внутри блока устройства строки порта разделены тонкой линией.
            self.assertEqual(first["bottom"], "thin", f"{letter}2")
            self.assertEqual(second["top"], "thin", f"{letter}3")
        # Внешний контур по бокам: левая граница первой колонки, правая — последней, у всех строк блока.
        last_letter = openpyxl.utils.get_column_letter(ws.max_column)
        for row in (2, 3, 4, 5):
            self.assertEqual(self.raw_border(3, f"A{row}")["left"], "medium")
            self.assertEqual(self.raw_border(3, f"{last_letter}{row}")["right"], "medium")

    def test_different_devices_with_identical_placeholders_are_not_merged_together(self):
        """Блоки определяются по устройству, а не по значениям колонок: у двух разных устройств без
        серийного номера и системного имени все колонки данных устройства — одно и то же '-', но
        объединить их в один блок нельзя."""
        self._seed_two_devices_two_ports(serials=("", ""), names=("", ""))
        ws = self.build("placeholders")[SHEET3]
        self.assertEqual([ws.cell(row=r, column=3).value for r in (2, 3, 4, 5)], ["-", None, "-", None])
        self.assertEqual(self._ranges(ws, 3), [(2, 3), (4, 5)])

    def test_device_with_single_row_is_not_merged(self):
        C = self.C
        self.table.update({
            "DeviceType": [C["DeviceType"](id="dt1", name="Сервер")],
            "PhysicalDevice": [C["PhysicalDevice"](id="d1", device_type_id="dt1", serial_number="S-1", system_name="srv")],
            "DeviceInterface": [C["DeviceInterface"](id="if1", physical_device_id="d1", name="eth0")],
        })
        ws = self.build("single")[SHEET3]
        self.assertEqual(ws.max_row, 2)
        self.assertEqual(len(ws.merged_cells.ranges), 0)
        self.assertEqual(ws["C2"].value, "S-1")
        self.assertEqual(ws["C2"].border.top.style, "medium")
        self.assertEqual(ws["C2"].border.bottom.style, "medium")

    def test_header_row_fits_every_header_on_every_sheet(self):
        """Регрессия: высота шапки была жёстко 72 пт, а заголовки в 200-300 символов при максимальной ширине
        колонки занимали 5-6+ строк и обрезались по нижнему краю."""
        self._seed_two_devices_two_ports()
        wb = self.build("header_fit")
        for ws in wb.worksheets:
            for column in range(1, ws.max_column + 1):
                lines = wrap_lines(ws.cell(row=1, column=column).value, header_capacity(_width(ws, column)))
                self.assertLessEqual(lines * LINE_HEIGHT_PT, ws.row_dimensions[1].height, f"{ws.title}, колонка {column}")
        self.assertGreater(wb[SHEET1].row_dimensions[1].height, 72)

    def test_header_row_fits_on_empty_registry_too(self):
        wb = self.build("header_fit_empty")
        for ws in wb.worksheets:
            for column in range(1, ws.max_column + 1):
                lines = wrap_lines(ws.cell(row=1, column=column).value, header_capacity(_width(ws, column)))
                self.assertLessEqual(lines * LINE_HEIGHT_PT, ws.row_dimensions[1].height, f"{ws.title}, колонка {column}")

    def test_no_header_word_is_broken_in_the_middle(self):
        self._seed_two_devices_two_ports()
        for ws in self.build("header_words").worksheets:
            for column in range(1, ws.max_column + 1):
                longest = max(len(word) for word in ws.cell(row=1, column=column).value.split())
                self.assertGreaterEqual(header_capacity(_width(ws, column)), longest, f"{ws.title}, колонка {column}")

    def test_columns_are_not_inflated_by_headers(self):
        """Ширина — по данным: колонка «№» узкая, а лист в целом заметно уже, чем при ширине всех колонок
        по заголовку (раньше почти все колонки были 55)."""
        self._seed_two_devices_two_ports()
        wb = self.build("widths")
        for title in (SHEET1, SHEET2, SHEET3):
            self.assertEqual(_width(wb[title], 1), MIN_COLUMN_WIDTH, title)
        for ws in wb.worksheets:
            widths = [_width(ws, column) for column in range(1, ws.max_column + 1)]
            self.assertLessEqual(max(widths), MAX_COLUMN_WIDTH, ws.title)
            self.assertLess(sum(widths), 0.8 * MAX_COLUMN_WIDTH * len(widths), ws.title)

    def test_header_style_is_kept_and_data_is_aligned_to_top(self):
        """Регрессия: общий проход выравнивания данных затирал центрирование шапки, и шапки прижимались влево."""
        self._seed_two_devices_two_ports()
        for ws in self.build("styles").worksheets:
            for cell in ws[1]:
                self.assertEqual((cell.font.name, cell.font.sz, cell.font.bold), ("Calibri", 11, True), ws.title)
                self.assertEqual((cell.alignment.horizontal, cell.alignment.vertical), ("center", "center"), ws.title)
                self.assertTrue(cell.alignment.wrap_text)
        data_cell = self.build("styles2")[SHEET3]["F2"]
        self.assertEqual((data_cell.alignment.vertical, data_cell.alignment.wrap_text), ("top", True))

    def test_autofilter_still_covers_the_whole_table(self):
        self._seed_two_devices_two_ports()
        ws = self.build("filter")[SHEET3]
        self.assertEqual(ws.auto_filter.ref, f"A1:{get_column_letter(ws.max_column)}{ws.max_row}")

    def test_data_rows_keep_automatic_height_when_nothing_is_clipped(self):
        self._seed_two_devices_two_ports()
        ws = self.build("auto_rows")[SHEET3]
        self.assertTrue(all(ws.row_dimensions[row].height is None for row in range(2, ws.max_row + 1)))

    def test_device_block_is_stretched_when_its_merged_data_does_not_fit(self):
        """Длинное имя ОС устройства с двумя портами: объединённая ячейка (в подборе высоты строк она не
        участвует) не должна обрезаться — строки блока растягиваются, у соседнего устройства всё по-прежнему."""
        self._seed_two_devices_two_ports()
        os_name = "очень длинное наименование встроенной операционной системы " * 3
        self.table["EmbeddedOperatingSystem"] = [self.C["EmbeddedOperatingSystem"](id="eos1", name=os_name, version="1.0")]
        self.table["PhysicalDevice"][0].embedded_os_id = "eos1"
        ws = self.build("stretch")[SHEET3]
        needed = wrap_lines(ws["E2"].value, text_capacity(_width(ws, 5)))
        self.assertGreater(needed, 2)
        self.assertGreaterEqual(ws.row_dimensions[2].height + ws.row_dimensions[3].height, needed * LINE_HEIGHT_PT)
        self.assertIsNone(ws.row_dimensions[4].height)
        self.assertIsNone(ws.row_dimensions[5].height)

    def test_merging_does_not_change_report_data(self):
        """Объединение только визуальное: «логические» строки листа 3 содержат данные устройства в каждой строке."""
        self._seed_two_devices_two_ports()
        rows = expanded_rows(self.build("data")[SHEET3], min_row=2)
        self.assertEqual([r[2] for r in rows], ["S-1", "S-1", "S-2", "S-2"])
        self.assertEqual([r[3] for r in rows], ["sw-1", "sw-1", "sw-2", "sw-2"])
        self.assertEqual([r[0] for r in rows], [1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
