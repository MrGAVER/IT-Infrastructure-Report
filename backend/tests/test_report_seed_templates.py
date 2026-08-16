"""
Тесты на backend/app/services/report_seed_templates.py — конфигурацию шаблона конструктора
отчётов, построенную по структуре регламентированного 4-листового отчёта, и на data-миграцию
alembic/versions/b1f0a2265711_seed_report_builder_template.py, которая добавляет этот шаблон в
report_templates при обновлении.

Запуск: python3 -m unittest discover -s backend/tests -v
Требует sqlalchemy/openpyxl/alembic (как test_report_grid.py) — при их отсутствии тесты пропускаются.
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
    import openpyxl
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import (
        Base, Connection, ConnectionType, Department, DeviceInterface, DeviceType, EmbeddedOperatingSystem,
        InformationSystem, ISDepartment, Manufacturer, PhysicalDevice, VirtualMachine,
    )
    from app.services.report_engine import ReportBuilderError
    from app.services.report_grid import build_xlsx_grid
    from app.services.report_meta import build_entity_metadata
    from app.services.report_seed_templates import (
        TEMPLATE_DESCRIPTION, TEMPLATE_NAME, default_registry_template_config,
    )

    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False


def _load_migration_module():
    """Импортирует файл миграции по пути — у него нет package-имени (стандартный alembic-модуль
    версии), поэтому используем importlib вместо обычного import."""
    path = ALEMBIC_VERSIONS_DIR / "b1f0a2265711_seed_report_builder_template.py"
    spec = importlib.util.spec_from_file_location("seed_migration_b1f0a2265711", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/openpyxl не установлены в этом окружении")
class DefaultRegistryTemplateConfigTestCase(unittest.TestCase):
    """Структурная валидация — без обращения к БД (та же проверка, что при сохранении шаблона
    через API конструктора)."""

    def test_passes_validate_grid_config(self):
        from app.services.report_grid import validate_grid_config

        cfg = default_registry_template_config()
        try:
            validate_grid_config(build_entity_metadata(), cfg)
        except ReportBuilderError as e:
            self.fail(f"Конфигурация шаблона-заготовки не проходит validate_grid_config(): {e}")

    def test_four_sheets_in_original_order(self):
        cfg = default_registry_template_config()
        titles = [s["title"] for s in cfg["sheets"]]
        self.assertEqual(titles, [
            "Перечень ИС", "Инвентаризац. физ. устройств ИС",
            "Организация подключений", "Организация управления ВМ",
        ])

    def test_is_pure_function_no_shared_mutable_state(self):
        """Два вызова не должны возвращать общие вложенные списки/словари — иначе правка одного
        сгенерированного шаблона в памяти (например, в тесте на миграцию) исказила бы другой."""
        cfg1 = default_registry_template_config()
        cfg2 = default_registry_template_config()
        cfg1["sheets"][0]["rows"][0]["cells"][0]["text"] = "испорчено"
        self.assertNotEqual(cfg1["sheets"][0]["rows"][0]["cells"][0]["text"],
                             cfg2["sheets"][0]["rows"][0]["cells"][0]["text"])

    def test_description_mentions_original_report_is_unaffected(self):
        # Ключевое требование: пользователь не должен подумать, что этот шаблон заменяет собой
        # регламентированный отчёт (кнопка "Отчёт Excel" на дашборде) — см. описание задачи.
        self.assertIn("Отчёт Excel", TEMPLATE_DESCRIPTION)
        self.assertTrue(TEMPLATE_NAME)


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/openpyxl не установлены в этом окружении")
class BuildRegistryTemplateTestCase(unittest.TestCase):
    """Рендер шаблона на реальных (пусть и минимальных) данных реестра — проверяет, что все пути
    полей действительно резолвятся на настоящих ORM-объектах, а не только проходят структурную
    валидацию путей по именам."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        Session = sessionmaker(bind=self.engine)
        self.session = Session()

        dep = Department(name="ИТ-отдел")
        dtype = DeviceType(name="Сервер")
        manufacturer = Manufacturer(name="Dell")
        embedded_os = EmbeddedOperatingSystem(name="Ubuntu Server", version="22.04")
        self.session.add_all([dep, dtype, manufacturer, embedded_os])
        self.session.flush()

        self.dev1 = PhysicalDevice(device_type_id=dtype.id, manufacturer_id=manufacturer.id,
                                    serial_number="SN-001", system_name="srv-01", embedded_os_id=embedded_os.id)
        self.dev2 = PhysicalDevice(device_type_id=dtype.id, manufacturer_id=manufacturer.id,
                                    serial_number="SN-002", system_name="sw-01", embedded_os_id=embedded_os.id)
        self.session.add_all([self.dev1, self.dev2])
        self.session.flush()

        iface1 = DeviceInterface(physical_device_id=self.dev1.id, name="eth0", is_management=True)
        iface2 = DeviceInterface(physical_device_id=self.dev2.id, name="Gi0/1", is_management=False)
        self.session.add_all([iface1, iface2])
        self.session.flush()

        ctype = ConnectionType(name="Витая пара")
        self.session.add(ctype)
        self.session.flush()
        self.session.add(Connection(source_interface_id=iface1.id, destination_interface_id=iface2.id,
                                     connection_type_id=ctype.id, purpose="Передача данных"))

        isys = InformationSystem(name="ИС Бухгалтерия", description="Учётная система",
                                  purpose="Учёт", localization="ЦОД-1")
        self.session.add(isys)
        self.session.flush()
        self.session.add(ISDepartment(information_system_id=isys.id, department_id=dep.id))

        self.session.add(VirtualMachine(name="vm-buh-01", physical_device_id=self.dev1.id, purpose="1С сервер"))
        self.session.commit()

    def tearDown(self):
        self.session.close()

    def test_builds_real_xlsx_with_expected_content(self):
        cfg = default_registry_template_config()
        out_dir = Path(__file__).resolve().parent / "_tmp_report_seed_templates"
        out_dir.mkdir(exist_ok=True)
        try:
            path = build_xlsx_grid(self.session, cfg, out_dir, template_name=TEMPLATE_NAME, params={})
            wb = openpyxl.load_workbook(path)
            self.assertEqual(wb.sheetnames, [
                "Перечень ИС", "Инвентаризац. физ. устройств ИС",
                "Организация подключений", "Организация управления ВМ",
            ])

            ws1 = wb["Перечень ИС"]
            # Строка 1 — заголовок листа (объединённая), строка 2 — примечание об упрощениях,
            # строка 3 — заголовки колонок, строка 4 — первая (единственная) запись.
            self.assertEqual(ws1.cell(row=3, column=2).value, "Наименование ИС")
            data_row = [ws1.cell(row=4, column=c).value for c in range(1, ws1.max_column + 1)]
            self.assertEqual(data_row[1], "ИС Бухгалтерия")
            self.assertEqual(data_row[4], "ИТ-отдел")  # is_departments[].department.name
            self.assertEqual(data_row[11], "Нет")  # crypto_protection_enabled -> "Да"/"Нет"

            ws2 = wb["Инвентаризац. физ. устройств ИС"]
            dev_row = [ws2.cell(row=4, column=c).value for c in range(1, ws2.max_column + 1)]
            self.assertIn("Dell", dev_row)
            self.assertIn("SN-001", dev_row)
            self.assertIn("eth0", dev_row)  # interfaces[].name

            ws3 = wb["Организация подключений"]
            conn_row = [ws3.cell(row=4, column=c).value for c in range(1, ws3.max_column + 1)]
            self.assertIn("srv-01", conn_row)
            self.assertIn("sw-01", conn_row)
            self.assertIn("Да", conn_row)  # is_active -> "Да"

            ws4 = wb["Организация управления ВМ"]
            vm_row = [ws4.cell(row=4, column=c).value for c in range(1, ws4.max_column + 1)]
            self.assertIn("vm-buh-01", vm_row)
            self.assertIn("srv-01", vm_row)  # physical_device.system_name (хост)
        finally:
            for f in out_dir.glob("*"):
                f.unlink()
            out_dir.rmdir()


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/openpyxl не установлены в этом окружении")
class SeedMigrationTestCase(unittest.TestCase):
    """Data-миграция b1f0a2265711: идемпотентная вставка + осторожный откат (не удаляет строку,
    если пользователь успел отредактировать шаблон после апгрейда)."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.migration = _load_migration_module()

    def _table_rows(self, conn):
        return conn.execute(
            self.migration._report_templates.select()
        ).mappings().all()

    def test_upgrade_inserts_exactly_one_row_and_is_idempotent(self):
        with self.engine.begin() as conn:
            self.migration.op = _FakeOp(conn)
            self.migration.upgrade()
            rows = self._table_rows(conn)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], TEMPLATE_NAME)
            self.assertEqual(json.loads(rows[0]["config"]), default_registry_template_config())

            self.migration.upgrade()  # повторный прогон не должен дублировать строку
            rows_again = self._table_rows(conn)
            self.assertEqual(len(rows_again), 1)

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
            conn.execute(
                self.migration._report_templates.update().values(config=json.dumps({"sheets": [], "params": []}))
            )
            self.migration.downgrade()
            rows = self._table_rows(conn)
            self.assertEqual(len(rows), 1, "отредактированный пользователем шаблон не должен удаляться откатом")


class _FakeOp:
    """Минимальная замена alembic.op для юнит-теста миграции на голом sqlalchemy-соединении —
    настоящий alembic.op требует активный MigrationContext, который в проекте поднимается только
    через сам `alembic upgrade`/`downgrade` (уже проверено вручную при разработке, см. историю
    ветки); здесь достаточно только двух методов, которые использует эта конкретная миграция."""

    def __init__(self, conn):
        self._conn = conn

    def get_bind(self):
        return self._conn

    def bulk_insert(self, table, rows):
        self._conn.execute(table.insert(), rows)

    def execute(self, stmt):
        self._conn.execute(stmt)


if __name__ == "__main__":
    unittest.main()
