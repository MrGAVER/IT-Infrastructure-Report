"""
Тесты на backend/app/services/report_meta.py, report_engine.py, report_render.py — движок
конструктора произвольных отчётов (общие примитивы + формат docx). Формат xlsx (grid-редактор)
тестируется отдельно в test_report_grid.py.

Запуск: python3 -m unittest discover -s backend/tests -v
Требует установленных sqlalchemy/openpyxl/python-docx (как test_referential_integrity.py — здесь
тестируется реальная работа с ORM-метаданными через inspect(), которую сложно достоверно
замокать). Если зависимости недоступны, тесты пропускаются (skip), а не падают.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"

try:
    import sys

    sys.path.insert(0, str(APP_DIR.parent))
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import (
        Base,
        Department,
        DeviceCategory,
        DeviceType,
        InformationSystem,
        ISDepartment,
        PhysicalDevice,
        VirtualMachine,
    )
    from app.services.report_engine import (
        ReportBuilderError,
        ReportContext,
        iter_report_rows,
        render_field,
        substitute_params,
        validate_config,
    )
    from app.services.report_meta import build_entity_metadata, entity_metadata_public
    from app.services.report_render import build_docx, preview_rows

    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/openpyxl/python-docx не установлены в этом окружении")
class ReportMetaTestCase(unittest.TestCase):
    def test_reverse_relation_registered_for_every_foreign_key(self):
        meta = build_entity_metadata()
        # InformationSystem <- ISDepartment.information_system_id
        self.assertIn("is_departments", meta["information-systems"]["to_many"])
        self.assertEqual(meta["information-systems"]["to_many"]["is_departments"]["source"], "is-departments")

    def test_multiple_fks_to_same_target_get_distinct_relation_names(self):
        """Connection ссылается на device_interfaces двумя колонками (source/destination) —
        обе обратные связи должны существовать под разными именами, а не перезаписывать друг друга."""
        meta = build_entity_metadata()
        names = meta["interfaces"]["to_many"].keys()
        self.assertIn("connections_via_source_interface", names)
        self.assertIn("connections_via_destination_interface", names)

    def test_public_metadata_is_json_serializable(self):
        # Провалится с TypeError, если в структуру случайно попадёт объект модели (класс SQLAlchemy).
        json.dumps(entity_metadata_public())


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/openpyxl/python-docx не установлены в этом окружении")
class ReportEngineTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

        self.dep_finance = Department(name="Бухгалтерия")
        self.dep_it = Department(name="ИТ")
        self.session.add_all([self.dep_finance, self.dep_it])
        self.session.flush()

        self.isys = InformationSystem(name="ИС Тест", description="active")
        self.session.add(self.isys)
        self.session.flush()
        self.session.add_all(
            [
                ISDepartment(information_system_id=self.isys.id, department_id=self.dep_finance.id),
                ISDepartment(information_system_id=self.isys.id, department_id=self.dep_it.id),
            ]
        )

        self.device_category = DeviceCategory(name="Серверы и СХД")
        self.session.add(self.device_category)
        self.session.flush()
        self.device_type = DeviceType(name="Сервер", category_id=self.device_category.id)
        self.session.add(self.device_type)
        self.session.flush()
        self.server = PhysicalDevice(device_type_id=self.device_type.id, serial_number="SN1", system_name="SRV1")
        self.empty_server = PhysicalDevice(device_type_id=self.device_type.id, serial_number="SN2", system_name="SRV2")
        self.session.add_all([self.server, self.empty_server])
        self.session.flush()
        self.vm1 = VirtualMachine(name="VM1", physical_device_id=self.server.id, purpose="app")
        self.vm2 = VirtualMachine(name="VM2", physical_device_id=self.server.id, purpose="db")
        self.session.add_all([self.vm1, self.vm2])
        self.session.commit()

        self.ctx = ReportContext(self.session)

    def tearDown(self):
        self.session.close()

    def test_plain_field(self):
        self.assertEqual(render_field(self.ctx, "information-systems", self.isys, "name"), "ИС Тест")

    def test_to_many_through_bridge_table_is_joined(self):
        value = render_field(self.ctx, "information-systems", self.isys, "is_departments[].department.name")
        self.assertIn("Бухгалтерия", value)
        self.assertIn("ИТ", value)

    def test_path_with_two_many_segments_is_rejected(self):
        with self.assertRaises(ReportBuilderError):
            render_field(self.ctx, "information-systems", self.isys, "is_departments[].x[].y")

    def test_path_ending_in_many_segment_is_rejected(self):
        with self.assertRaises(ReportBuilderError):
            render_field(self.ctx, "devices", self.server, "vms[]")

    def test_expand_produces_one_row_per_related_object(self):
        rows = list(iter_report_rows(self.ctx, "devices", expand="vms"))
        server_rows = [r for r in rows if r[0].id == self.server.id]
        self.assertEqual(len(server_rows), 2)
        names = {render_field(self.ctx, "devices", r[0], "vms[].name", expand_relation=r[1], expand_obj=r[2]) for r in server_rows}
        self.assertEqual(names, {"VM1", "VM2"})

    def test_expand_keeps_one_blank_row_for_records_without_related_objects(self):
        rows = list(iter_report_rows(self.ctx, "devices", expand="vms", include_empty_expand=True))
        empty_rows = [r for r in rows if r[0].id == self.empty_server.id]
        self.assertEqual(len(empty_rows), 1)
        self.assertIsNone(empty_rows[0][2])

    def test_expand_can_drop_records_without_related_objects(self):
        rows = list(iter_report_rows(self.ctx, "devices", expand="vms", include_empty_expand=False))
        self.assertFalse([r for r in rows if r[0].id == self.empty_server.id])

    def test_filter_eq(self):
        rows = list(iter_report_rows(self.ctx, "information-systems", filters=[{"path": "description", "op": "eq", "value": "active"}]))
        self.assertEqual(len(rows), 1)
        rows = list(iter_report_rows(self.ctx, "information-systems", filters=[{"path": "description", "op": "eq", "value": "archived"}]))
        self.assertEqual(len(rows), 0)

    def test_boolean_field_rendered_as_yes_no(self):
        self.isys.siem_enabled = True
        self.session.commit()
        self.assertEqual(render_field(self.ctx, "information-systems", self.isys, "siem_enabled"), "Да")

    def test_substitute_params_report_date_and_custom_key(self):
        text = substitute_params("Дата: {{report_date}}, Организация: {{org_name}}", {"org_name": "ООО Ромашка"})
        self.assertIn("ООО Ромашка", text)
        self.assertNotIn("{{", text)

    def test_substitute_params_missing_key_becomes_empty(self):
        self.assertEqual(substitute_params("[{{missing}}]", {}), "[]")

    def test_validate_config_rejects_unknown_block_type(self):
        meta = build_entity_metadata()
        with self.assertRaises(ReportBuilderError):
            validate_config(meta, "docx", {"blocks": [{"type": "no_such_block"}]})

    def test_validate_config_rejects_empty_blocks(self):
        meta = build_entity_metadata()
        with self.assertRaises(ReportBuilderError):
            validate_config(meta, "docx", {"blocks": []})

    def test_validate_config_accepts_well_formed_docx_template(self):
        meta = build_entity_metadata()
        good = {
            "blocks": [
                {"type": "heading", "level": 1, "text": "Заголовок"},
                {
                    "type": "table",
                    "root_entity": "information-systems",
                    "columns": [
                        {"header": "Наименование", "source": "field", "path": "name"},
                        {"header": "Подразделения", "source": "field", "path": "is_departments[].department.name"},
                    ],
                },
            ]
        }
        validate_config(meta, "docx", good)  # не должно бросать исключение


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/openpyxl/python-docx не установлены в этом окружении")
class ReportRenderTestCase(unittest.TestCase):
    """build_docx() и preview_rows() — общая часть движка (используется только форматом docx с
    версии grid-редактора). Рендеринг xlsx тестируется в test_report_grid.py."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()
        self.isys = InformationSystem(name="ИС А", description="active")
        self.session.add(self.isys)
        self.session.commit()
        self.docx_config = {
            "blocks": [
                {"type": "heading", "level": 1, "text": "Заголовок"},
                {
                    "type": "table",
                    "root_entity": "information-systems",
                    "columns": [
                        {"header": "Наименование", "source": "field", "path": "name"},
                    ],
                },
            ]
        }

    def tearDown(self):
        self.session.close()

    def test_build_docx_table_contains_row(self):
        from docx import Document

        path = build_docx(self.session, self.docx_config, Path("/tmp/rb_render_test"), template_name="Т2")
        try:
            doc = Document(str(path))
            table = doc.tables[0]
            self.assertEqual(table.rows[0].cells[0].text, "Наименование")
            self.assertEqual(table.rows[1].cells[0].text, "ИС А")
        finally:
            path.unlink(missing_ok=True)

    def test_preview_rows_does_not_write_any_file(self):
        result = preview_rows(self.session, self.docx_config)
        self.assertEqual(result["sections"][0]["total"], 1)
        self.assertFalse(list(Path("/tmp/rb_render_test").glob("*preview*")))


if __name__ == "__main__":
    unittest.main()
