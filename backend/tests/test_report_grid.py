"""
Тесты на backend/app/services/report_grid.py — grid-движок конструктора отчётов (формат xlsx):
валидация листа (объединение ячеек, типы ячеек, источники данных), материализация физических
строк и рендеринг в реальный файл xlsx (стили, объединение, формулы, числовой формат).

Запуск: python3 -m unittest discover -s backend/tests -v
Требует sqlalchemy/openpyxl (как test_report_builder.py) — при их отсутствии тесты пропускаются.
"""
from __future__ import annotations

import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"

try:
    import sys
    sys.path.insert(0, str(APP_DIR.parent))
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import Base, Department, DeviceType, InformationSystem, ISDepartment
    from app.services.report_engine import ReportBuilderError
    from app.services.report_grid import build_xlsx_grid, preview_grid, validate_grid_config
    from app.services.report_meta import build_entity_metadata

    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False


def _cell(col, kind="static", **kw):
    return {"col": col, "kind": kind, **kw}


def _static_row(cells, height=18, **kw):
    return {"height": height, "repeat": False, "cells": cells, **kw}


def _repeat_row(cells, data_source, height=18):
    return {"height": height, "repeat": True, "data_source": data_source, "cells": cells}


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/openpyxl не установлены в этом окружении")
class ValidateGridConfigTestCase(unittest.TestCase):
    def setUp(self):
        self.meta = build_entity_metadata()

    def _sheet(self, rows, n_cols=3):
        return {"title": "Лист", "columns": [{"width": 15}] * n_cols, "rows": rows}

    def test_rejects_empty_sheets(self):
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": []})

    def test_rejects_sheet_without_columns(self):
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [{"title": "x", "columns": [], "rows": [
                _static_row([_cell(0, text="a")])
            ]}]})

    def test_rejects_sheet_without_rows(self):
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [self._sheet([])]})

    def test_accepts_purely_static_sheet(self):
        """Лист может быть полностью статическим (титульная страница) — без повторяющихся строк."""
        sheet = self._sheet([_static_row([_cell(0, text="Титул", colspan=3)])])
        validate_grid_config(self.meta, {"sheets": [sheet]})  # не должно бросать

    def test_accepts_well_formed_repeat_row(self):
        sheet = self._sheet([
            _static_row([_cell(0, text="№"), _cell(1, text="Наименование"), _cell(2, text="Статус")]),
            _repeat_row(
                [_cell(0, "index"), _cell(1, "field", path="name"), _cell(2, "field", path="status")],
                {"root_entity": "information-systems"},
            ),
        ])
        validate_grid_config(self.meta, {"sheets": [sheet]})  # не должно бросать

    def test_rejects_field_cell_outside_repeat_row(self):
        sheet = self._sheet([_static_row([_cell(0, "field", path="name")])])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})

    def test_rejects_index_cell_outside_repeat_row(self):
        sheet = self._sheet([_static_row([_cell(0, "index")])])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})

    def test_rejects_repeat_row_without_data_source(self):
        sheet = self._sheet([{"height": 18, "repeat": True, "cells": [_cell(0, "index")]}])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})

    def test_rejects_unknown_root_entity(self):
        sheet = self._sheet([_repeat_row([_cell(0, "index")], {"root_entity": "no-such-entity"})])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})

    def test_rejects_unknown_field_path(self):
        sheet = self._sheet([_repeat_row(
            [_cell(0, "field", path="no_such_field")], {"root_entity": "information-systems"},
        )])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})

    def test_rejects_rowspan_in_repeat_row(self):
        sheet = self._sheet([_repeat_row(
            [_cell(0, "index", rowspan=2)], {"root_entity": "information-systems"},
        )])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})

    def test_rejects_rowspan_spanning_into_repeat_row(self):
        sheet = self._sheet([
            _static_row([_cell(0, text="Заголовок", rowspan=2)]),
            _repeat_row([_cell(0, "index")], {"root_entity": "information-systems"}),
        ])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})

    def test_accepts_rowspan_across_two_static_rows(self):
        sheet = self._sheet([
            _static_row([_cell(0, text="A", rowspan=2), _cell(1, text="B1"), _cell(2, text="C1")]),
            _static_row([_cell(1, text="B2"), _cell(2, text="C2")]),
        ])
        validate_grid_config(self.meta, {"sheets": [sheet]})  # не должно бросать

    def test_rejects_overlapping_cells_in_same_row(self):
        sheet = self._sheet([_static_row([_cell(0, text="a", colspan=2), _cell(1, text="b")])])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})

    def test_rejects_cell_under_rowspan_from_above(self):
        sheet = self._sheet([
            _static_row([_cell(0, text="A", rowspan=2), _cell(1, text="B1"), _cell(2, text="C1")]),
            _static_row([_cell(0, text="занято сверху"), _cell(1, text="B2"), _cell(2, text="C2")]),
        ])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})

    def test_rejects_unknown_cell_kind(self):
        sheet = self._sheet([_static_row([_cell(0, kind="bogus", text="x")])])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})

    def test_rejects_formula_cell_without_text(self):
        sheet = self._sheet([_static_row([_cell(0, "formula")])])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})

    def test_rejects_invalid_style_color(self):
        sheet = self._sheet([_static_row([_cell(0, text="a", style={"bg": "red"})])])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})

    def test_rejects_filter_with_unknown_op(self):
        sheet = self._sheet([_repeat_row(
            [_cell(0, "index")],
            {"root_entity": "information-systems", "filters": [{"path": "status", "op": "bogus", "value": "x"}]},
        )])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})

    def test_rejects_unknown_expand_relation(self):
        sheet = self._sheet([_repeat_row(
            [_cell(0, "index")], {"root_entity": "devices", "expand": "no_such_relation"},
        )])
        with self.assertRaises(ReportBuilderError):
            validate_grid_config(self.meta, {"sheets": [sheet]})


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/openpyxl не установлены в этом окружении")
class BuildXlsxGridTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

        self.dep_it = Department(name="ИТ")
        self.session.add(self.dep_it)
        self.session.flush()

        self.isys1 = InformationSystem(name="ИС Альфа", status="active")
        self.isys2 = InformationSystem(name="ИС Бета", status="archived")
        self.session.add_all([self.isys1, self.isys2])
        self.session.flush()
        self.session.add(ISDepartment(information_system_id=self.isys1.id, department_id=self.dep_it.id))

        self.device_type = DeviceType(name="Сервер")
        self.session.add(self.device_type)
        self.session.flush()
        self.session.commit()

    def tearDown(self):
        self.session.close()

    def _basic_config(self, extra_row_kwargs=None):
        return {"sheets": [{
            "title": "Лист1",
            "columns": [{"width": 8}, {"width": 25}, {"width": 15}],
            "rows": [
                _static_row([_cell(0, text="№", style={"bold": True}),
                             _cell(1, text="Наименование", style={"bold": True}),
                             _cell(2, text="Статус", style={"bold": True})]),
                _repeat_row(
                    [_cell(0, "index"), _cell(1, "field", path="name"),
                     _cell(2, "field", path="status", **(extra_row_kwargs or {}))],
                    {"root_entity": "information-systems", "sort_by": "name"},
                ),
            ],
        }]}

    def test_build_writes_header_and_data_rows(self):
        import openpyxl
        path = build_xlsx_grid(self.session, self._basic_config(), Path("/tmp/rb_grid_test"), template_name="Т1")
        try:
            wb = openpyxl.load_workbook(path)
            ws = wb["Лист1"]
            rows = list(ws.iter_rows(values_only=True))
            self.assertEqual(rows[0], ("№", "Наименование", "Статус"))
            self.assertEqual(rows[1], (1, "ИС Альфа", "active"))
            self.assertEqual(rows[2], (2, "ИС Бета", "archived"))
        finally:
            path.unlink(missing_ok=True)

    def test_header_row_is_bold(self):
        import openpyxl
        path = build_xlsx_grid(self.session, self._basic_config(), Path("/tmp/rb_grid_test"), template_name="Т1")
        try:
            wb = openpyxl.load_workbook(path)
            self.assertTrue(wb["Лист1"]["A1"].font.bold)
            self.assertFalse(wb["Лист1"]["A2"].font.bold)
        finally:
            path.unlink(missing_ok=True)

    def test_merged_static_header_cell(self):
        import openpyxl
        config = {"sheets": [{
            "title": "Лист1",
            "columns": [{"width": 15}, {"width": 15}, {"width": 15}],
            "rows": [
                _static_row([_cell(0, text="Заголовок отчёта", colspan=3, style={"align": "center"})]),
                _repeat_row([_cell(0, "index"), _cell(1, "field", path="name"), _cell(2, "field", path="status")],
                            {"root_entity": "information-systems"}),
            ],
        }]}
        path = build_xlsx_grid(self.session, config, Path("/tmp/rb_grid_test"), template_name="Т1")
        try:
            wb = openpyxl.load_workbook(path)
            ws = wb["Лист1"]
            self.assertIn("A1:C1", [str(r) for r in ws.merged_cells.ranges])
            self.assertEqual(ws["A1"].value, "Заголовок отчёта")
            self.assertEqual(ws["A1"].alignment.horizontal, "center")
        finally:
            path.unlink(missing_ok=True)

    def test_column_widths_applied(self):
        import openpyxl
        path = build_xlsx_grid(self.session, self._basic_config(), Path("/tmp/rb_grid_test"), template_name="Т1")
        try:
            wb = openpyxl.load_workbook(path)
            ws = wb["Лист1"]
            self.assertEqual(ws.column_dimensions["B"].width, 25)
        finally:
            path.unlink(missing_ok=True)

    def test_formula_cell_written_verbatim_with_leading_equals(self):
        import openpyxl
        config = {"sheets": [{
            "title": "Лист1", "columns": [{"width": 10}, {"width": 10}],
            "rows": [_static_row([_cell(0, text="5"), _cell(1, "formula", text="A1*2")])],
        }]}
        path = build_xlsx_grid(self.session, config, Path("/tmp/rb_grid_test"), template_name="Т1")
        try:
            wb = openpyxl.load_workbook(path)
            self.assertEqual(wb["Лист1"]["B1"].value, "=A1*2")
        finally:
            path.unlink(missing_ok=True)

    def test_number_format_applied_from_style(self):
        import openpyxl
        config = {"sheets": [{
            "title": "Лист1", "columns": [{"width": 10}],
            "rows": [_static_row([_cell(0, text="1234.5", style={"number_format": "0.00"})])],
        }]}
        path = build_xlsx_grid(self.session, config, Path("/tmp/rb_grid_test"), template_name="Т1")
        try:
            wb = openpyxl.load_workbook(path)
            self.assertEqual(wb["Лист1"]["A1"].number_format, "0.00")
        finally:
            path.unlink(missing_ok=True)

    def test_bg_color_applied(self):
        import openpyxl
        config = {"sheets": [{
            "title": "Лист1", "columns": [{"width": 10}],
            "rows": [_static_row([_cell(0, text="x", style={"bg": "#FFCC00"})])],
        }]}
        path = build_xlsx_grid(self.session, config, Path("/tmp/rb_grid_test"), template_name="Т1")
        try:
            wb = openpyxl.load_workbook(path)
            self.assertEqual(wb["Лист1"]["A1"].fill.start_color.rgb, "00FFCC00")
        finally:
            path.unlink(missing_ok=True)

    def test_filters_narrow_repeat_row_records(self):
        import openpyxl
        config = self._basic_config()
        config["sheets"][0]["rows"][1]["data_source"]["filters"] = [
            {"path": "status", "op": "eq", "value": "active"}
        ]
        path = build_xlsx_grid(self.session, config, Path("/tmp/rb_grid_test"), template_name="Т1")
        try:
            wb = openpyxl.load_workbook(path)
            rows = list(wb["Лист1"].iter_rows(values_only=True))
            self.assertEqual(len(rows), 2)  # заголовок + 1 подходящая запись
            self.assertEqual(rows[1][1], "ИС Альфа")
        finally:
            path.unlink(missing_ok=True)

    def test_bridge_relation_field_joins_multiple_values(self):
        import openpyxl
        config = {"sheets": [{
            "title": "Лист1", "columns": [{"width": 15}, {"width": 20}],
            "rows": [_repeat_row(
                [_cell(0, "field", path="name"), _cell(1, "field", path="is_departments[].department.name")],
                {"root_entity": "information-systems", "filters": [{"path": "name", "op": "eq", "value": "ИС Альфа"}]},
            )],
        }]}
        path = build_xlsx_grid(self.session, config, Path("/tmp/rb_grid_test"), template_name="Т1")
        try:
            wb = openpyxl.load_workbook(path)
            rows = list(wb["Лист1"].iter_rows(values_only=True))
            self.assertEqual(rows[0], ("ИС Альфа", "ИТ"))
        finally:
            path.unlink(missing_ok=True)

    def test_duplicate_sheet_titles_are_disambiguated(self):
        import openpyxl
        one = self._basic_config()["sheets"][0]
        two = dict(one)
        config = {"sheets": [one, two]}
        path = build_xlsx_grid(self.session, config, Path("/tmp/rb_grid_test"), template_name="Т1")
        try:
            wb = openpyxl.load_workbook(path)
            self.assertEqual(set(wb.sheetnames), {"Лист1", "Лист1(2)"})
        finally:
            path.unlink(missing_ok=True)


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/openpyxl не установлены в этом окружении")
class PreviewGridTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
        for i in range(5):
            self.session.add(InformationSystem(name=f"ИС {i}", status="active"))
        self.session.commit()

    def tearDown(self):
        self.session.close()

    def test_preview_truncates_repeat_rows_but_reports_total(self):
        config = {"sheets": [{
            "title": "Лист1", "columns": [{"width": 15}],
            "rows": [_repeat_row([_cell(0, "field", path="name")], {"root_entity": "information-systems"})],
        }]}
        result = preview_grid(self.session, config, limit=2)
        section = result["sections"][0]
        self.assertEqual(section["total_records"], 5)
        self.assertEqual(len(section["rows"]), 2)

    def test_preview_does_not_write_any_file(self):
        config = {"sheets": [{
            "title": "Лист1", "columns": [{"width": 15}],
            "rows": [_repeat_row([_cell(0, "field", path="name")], {"root_entity": "information-systems"})],
        }]}
        preview_grid(self.session, config)
        self.assertFalse(list(Path("/tmp/rb_grid_test").glob("*preview*")))

    def test_preview_reports_error_for_broken_sheet_without_raising(self):
        config = {"sheets": [{
            "title": "Плохой лист", "columns": [{"width": 15}],
            "rows": [_repeat_row([_cell(0, "field", path="name")], {"root_entity": "no-such-entity"})],
        }]}
        result = preview_grid(self.session, config)
        self.assertIn("error", result["sections"][0])


if __name__ == "__main__":
    unittest.main()
