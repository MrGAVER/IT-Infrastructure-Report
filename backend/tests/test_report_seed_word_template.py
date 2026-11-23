"""
Тесты на backend/app/services/report_seed_word_template.py — конфигурацию Word-шаблона "Приложение
к структурной схеме" (по образцу приложенного пользователем документа), и на data-миграцию
alembic/versions/b44cd42f9fa0_seed_structural_appendix_word_template.py, которая добавляет этот
шаблон в report_templates при обновлении.

Запуск: python3 -m unittest discover -s backend/tests -v
Требует sqlalchemy/python-docx/alembic (как test_report_seed_templates.py) — при их отсутствии
тесты пропускаются.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
ALEMBIC_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"

try:
    sys.path.insert(0, str(APP_DIR.parent))
    import docx
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import (
        Base,
        Connection,
        ConnectionType,
        DeviceCategory,
        DeviceInterface,
        DeviceModel,
        DeviceType,
        EmbeddedOperatingSystem,
        Manufacturer,
        PhysicalDevice,
        PhysicalDeviceVLAN,
        VLAN,
    )
    from app.services.report_engine import ReportBuilderError, validate_config
    from app.services.report_meta import build_entity_metadata
    from app.services.report_render import build_docx
    from app.services.report_seed_word_template import (
        TEMPLATE_DESCRIPTION,
        TEMPLATE_NAME,
        default_structural_appendix_config,
    )

    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False


def _load_migration_module():
    path = ALEMBIC_VERSIONS_DIR / "b44cd42f9fa0_seed_structural_appendix_word_template.py"
    spec = importlib.util.spec_from_file_location("seed_migration_b44cd42f9fa0", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeOp:
    """См. test_report_seed_templates.py — та же минимальная замена alembic.op для юнит-теста
    миграции на голом sqlalchemy-соединении, без активного MigrationContext."""

    def __init__(self, conn):
        self._conn = conn

    def get_bind(self):
        return self._conn

    def bulk_insert(self, table, rows):
        self._conn.execute(table.insert(), rows)

    def execute(self, stmt):
        self._conn.execute(stmt)


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/python-docx не установлены в этом окружении")
class StructuralAppendixConfigTestCase(unittest.TestCase):
    """Структурная валидация — без обращения к БД (та же проверка, что при сохранении шаблона
    через API конструктора)."""

    def test_passes_validate_config(self):
        cfg = default_structural_appendix_config()
        try:
            validate_config(build_entity_metadata(), "docx", cfg)
        except ReportBuilderError as e:
            self.fail(f"Конфигурация Word-шаблона не проходит validate_config(): {e}")

    def test_three_tables_with_is_name_param(self):
        cfg = default_structural_appendix_config()
        table_blocks = [b for b in cfg["blocks"] if b["type"] == "table"]
        self.assertEqual(len(table_blocks), 3)
        self.assertEqual([p["key"] for p in cfg["params"]], ["is_name"])
        self.assertEqual(cfg["params"][0]["default"], "ТО")

    def test_description_explains_deviation_from_source_document(self):
        self.assertIn("не побитовая копия", TEMPLATE_DESCRIPTION)
        self.assertTrue(TEMPLATE_NAME)

    def test_is_pure_function_no_shared_mutable_state(self):
        cfg1 = default_structural_appendix_config()
        cfg2 = default_structural_appendix_config()
        cfg1["blocks"][0]["text"] = "испорчено"
        self.assertNotEqual(cfg1["blocks"][0]["text"], cfg2["blocks"][0]["text"])


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/python-docx не установлены в этом окружении")
class BuildStructuralAppendixTestCase(unittest.TestCase):
    """Рендер шаблона на реальных данных реестра — проверяет, что все пути полей (включая
    device-vlans — обычную, не виртуальную сущность) резолвятся на настоящих ORM-объектах."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

        category = DeviceCategory(name="Коммутаторы")
        self.session.add(category)
        self.session.flush()
        dtype = DeviceType(name="Сетевое оборудование", category_id=category.id)
        manufacturer = Manufacturer(name="Cisco")
        embedded_os = EmbeddedOperatingSystem(name="IOS", version="15")
        self.session.add_all([dtype, manufacturer, embedded_os])
        self.session.flush()
        model = DeviceModel(manufacturer_id=manufacturer.id, device_type_id=dtype.id, model="WS-C3750G-24T")
        self.session.add(model)
        self.session.flush()

        self.switch = PhysicalDevice(
            device_type_id=dtype.id,
            manufacturer_id=manufacturer.id,
            model_id=model.id,
            serial_number="SN-321",
            system_name="C2960X_210",
            embedded_os_id=embedded_os.id,
        )
        self.server = PhysicalDevice(
            device_type_id=dtype.id,
            manufacturer_id=manufacturer.id,
            serial_number="SN-123",
            system_name="srv-204",
            embedded_os_id=embedded_os.id,
        )
        self.session.add_all([self.switch, self.server])
        self.session.flush()

        iface1 = DeviceInterface(physical_device_id=self.switch.id, name="eth1", is_data_transfer=True)
        iface2 = DeviceInterface(physical_device_id=self.server.id, name="mgm1", is_management=True)
        self.session.add_all([iface1, iface2])
        self.session.flush()

        ctype = ConnectionType(name="Витая пара")
        self.session.add(ctype)
        self.session.flush()
        self.session.add(Connection(source_interface_id=iface1.id, destination_interface_id=iface2.id, connection_type_id=ctype.id))

        vlan = VLAN(vlan_id=100, name="Servers")
        self.session.add(vlan)
        self.session.flush()
        self.session.add(
            PhysicalDeviceVLAN(physical_device_id=self.switch.id, vlan_id=vlan.id, ip_address="10.9.100.204", prefix_length=24)
        )
        self.session.commit()

    def tearDown(self):
        self.session.close()

    def test_builds_real_docx_with_expected_content(self):
        cfg = default_structural_appendix_config()
        out_dir = Path(__file__).resolve().parent / "_tmp_report_seed_word_template"
        out_dir.mkdir(exist_ok=True)
        try:
            path = build_docx(self.session, cfg, out_dir, template_name=TEMPLATE_NAME, params={"is_name": "ТО"})
            doc = docx.Document(path)

            heading_texts = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
            self.assertIn("Приложение к структурной схеме", heading_texts)
            self.assertIn("ИС ТО", heading_texts, "параметр {{is_name}} должен подставиться в заголовок")

            self.assertEqual(len(doc.tables), 3)

            conn_table = doc.tables[0]
            conn_rows = [[c.text for c in row.cells] for row in conn_table.rows]
            self.assertEqual(conn_rows[0], ["Устройство", "Порт", "Соседнее устройство", "Назначение"])
            self.assertIn(["C2960X_210", "eth1", "srv-204", "Передача данных"], conn_rows)

            vlan_table = doc.tables[1]
            vlan_rows = [[c.text for c in row.cells] for row in vlan_table.rows]
            self.assertIn(["C2960X_210", "SN-321", "100", "Servers", "10.9.100.204", "24"], vlan_rows)

            device_table = doc.tables[2]
            device_rows = [[c.text for c in row.cells] for row in device_table.rows]
            self.assertIn(["Cisco", "WS-C3750G-24T", "SN-321", "C2960X_210", "", "", ""], device_rows)
        finally:
            for f in out_dir.glob("*"):
                f.unlink()
            out_dir.rmdir()

    def test_missing_param_substitutes_to_empty_not_default(self):
        """default в params — подсказка для UI (rbGenerateTemplate спрашивает значение у
        пользователя, предзаполняя его default'ом, перед формированием файла), а не то, что
        подставляет сам движок при отсутствии параметра — substitute_params() в этом случае
        подставляет пустую строку (см. report_engine.py). Это поведение движка, общее для всех
        шаблонов, не специфика этого — тест фиксирует его, чтобы не запутаться при чтении шаблона."""
        cfg = default_structural_appendix_config()
        out_dir = Path(__file__).resolve().parent / "_tmp_report_seed_word_template2"
        out_dir.mkdir(exist_ok=True)
        try:
            path = build_docx(self.session, cfg, out_dir, template_name=TEMPLATE_NAME, params={})
            doc = docx.Document(path)
            heading_texts = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
            self.assertIn("ИС ", heading_texts)
        finally:
            for f in out_dir.glob("*"):
                f.unlink()
            out_dir.rmdir()


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/python-docx не установлены в этом окружении")
class SeedMigrationTestCase(unittest.TestCase):
    """Data-миграция b44cd42f9fa0: идемпотентная вставка + осторожный откат — тот же паттерн, что
    и у миграции b1f0a2265711 (тест копирует структуру test_report_seed_templates.py)."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.migration = _load_migration_module()

    def _table_rows(self, conn):
        return conn.execute(self.migration._report_templates.select()).mappings().all()

    def test_upgrade_inserts_exactly_one_row_and_is_idempotent(self):
        with self.engine.begin() as conn:
            self.migration.op = _FakeOp(conn)
            self.migration.upgrade()
            rows = self._table_rows(conn)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], TEMPLATE_NAME)
            self.assertEqual(rows[0]["format"], "docx")
            self.assertEqual(json.loads(rows[0]["config"]), default_structural_appendix_config())

            self.migration.upgrade()
            self.assertEqual(len(self._table_rows(conn)), 1)

    def test_downgrade_removes_unedited_row(self):
        with self.engine.begin() as conn:
            self.migration.op = _FakeOp(conn)
            self.migration.upgrade()
            self.migration.downgrade()
            self.assertEqual(len(self._table_rows(conn)), 0)

    def test_downgrade_preserves_row_edited_by_user(self):
        with self.engine.begin() as conn:
            self.migration.op = _FakeOp(conn)
            self.migration.upgrade()
            conn.execute(self.migration._report_templates.update().values(config=json.dumps({"blocks": [], "params": []})))
            self.migration.downgrade()
            self.assertEqual(len(self._table_rows(conn)), 1, "отредактированный пользователем шаблон не должен удаляться откатом")


if __name__ == "__main__":
    unittest.main()
