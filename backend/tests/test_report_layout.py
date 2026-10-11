"""
Оформление Excel-отчёта (backend/app/services/excel_layout.py + его применение в reporting.build_report):
рамка вокруг шапки и каждой записи (ИС / устройство / ВМ), объединение повторяющихся данных устройства на
листе 'Организация подключений', закрепление шапки.

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

from app.services.excel_layout import (
    FRAME_SIDE, THIN_SIDE, apply_borders, apply_sheet_layout, freeze_header, merge_vertical, single_row_spans,
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

    def test_merging_does_not_change_report_data(self):
        """Объединение только визуальное: «логические» строки листа 3 содержат данные устройства в каждой строке."""
        self._seed_two_devices_two_ports()
        rows = expanded_rows(self.build("data")[SHEET3], min_row=2)
        self.assertEqual([r[2] for r in rows], ["S-1", "S-1", "S-2", "S-2"])
        self.assertEqual([r[3] for r in rows], ["sw-1", "sw-1", "sw-2", "sw-2"])
        self.assertEqual([r[0] for r in rows], [1, 2, 3, 4])


if __name__ == "__main__":
    unittest.main()
