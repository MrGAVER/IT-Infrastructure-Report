"""
Тесты на backend/app/services/report_registry_rows.py — "виртуальные" сущности конструктора
отчётов, переиспользующие логику reporting.py, и на саму точку интеграции с движком конструктора
(report_meta.build_entity_metadata() / report_engine.ReportContext.all_rows()).

Главный тест — ExactParityTestCase: строит регламентированный отчёт (reporting.build_report()) и
шаблон-заготовку конструктора (report_seed_templates.default_registry_template_config() через
report_grid.build_xlsx_grid()) на ОДНИХ и тех же данных и сравнивает содержимое ячеек лист-в-лист,
включая заголовки колонок. Это much сильнее структурной валидации путей по именам — подтверждает,
что вывод конструктора действительно совпадает с оригиналом на настоящих ORM-объектах, а не только
"похож по форме".

Запуск: python3 -m unittest discover -s backend/tests -v
Требует sqlalchemy/openpyxl (как test_report_grid.py) — при их отсутствии тесты пропускаются.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"

try:
    sys.path.insert(0, str(APP_DIR.parent))
    import openpyxl
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.models import (
        Base, Building, Connection, ConnectionType, Container, Department, DeviceInterface, DeviceType,
        EmbeddedOperatingSystem, InformationSystem, InformationSystemSource, InterfaceIP, InterfaceVLAN,
        ISContainer, ISDepartment, ISDevice, ISIP, ISVM, Manufacturer, OpenPort, OperatingSystem,
        OperatingSystemCategory, PhysicalDevice, Room, SoftwareAsset, StructuralUnit, VirtualMachine, VLAN, VMIP, VMSoftware,
    )
    from app.reporting import HEADERS1, HEADERS2, HEADERS3, HEADERS4, build_report
    from app.services.report_engine import ReportContext
    from app.services.report_grid import build_xlsx_grid
    from app.services.report_meta import build_entity_metadata
    from app.services.report_registry_rows import VIRTUAL_ENTITIES
    from app.services.report_seed_templates import TEMPLATE_NAME, default_registry_template_config

    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/openpyxl не установлены в этом окружении")
class VirtualEntityRegistrationTestCase(unittest.TestCase):
    """Проверка самой точки интеграции — виртуальные сущности видны в общих метаданных
    конструктора и их строки резолвятся через ReportContext, как и у обычных сущностей."""

    def test_all_four_virtual_entities_are_registered(self):
        meta = build_entity_metadata()
        for key in VIRTUAL_ENTITIES:
            self.assertIn(key, meta)
            self.assertIsNone(meta[key]["model"])
            self.assertTrue(callable(meta[key]["virtual_loader"]))
            self.assertEqual(meta[key]["to_one"], {})
            self.assertEqual(meta[key]["to_many"], {})

    def test_field_names_match_dataclass_definition(self):
        meta = build_entity_metadata()
        for key, ve in VIRTUAL_ENTITIES.items():
            names_in_meta = [f["name"] for f in meta[key]["fields"]]
            self.assertEqual(names_in_meta, [f.name for f in ve.fields])

    def test_report_context_all_rows_uses_loader_not_select(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        try:
            dep = Department(name="Отдел")
            session.add(dep)
            session.flush()
            isys = InformationSystem(name="ИС для теста")
            session.add(isys)
            session.flush()
            session.add(ISDepartment(information_system_id=isys.id, department_id=dep.id))
            session.commit()

            ctx = ReportContext(session)
            rows = ctx.all_rows("registry-is-rows")
            self.assertEqual(len(rows), 1)
            row = next(iter(rows.values()))
            self.assertEqual(row.name, "ИС для теста")
            self.assertEqual(row.departments, "Отдел")
        finally:
            session.close()

    def test_structural_unit_ids_filter_virtual_device_rows(self):
        """ReportContext(session, structural_unit_ids=[...]) сужает registry-device-rows тем же
        способом, что и лист 2 регламентированного отчёта (см. test_reporting.StructuralUnitFiltering) —
        runtime-фильтр конструктора должен работать на той же точке интеграции."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        try:
            unit = StructuralUnit(name="Филиал А")
            other_unit = StructuralUnit(name="Филиал Б")
            dtype = DeviceType(name="Сервер")
            session.add_all([unit, other_unit, dtype])
            session.flush()
            building_in = Building(name="Здание А", structural_unit_id=unit.id)
            building_out = Building(name="Здание Б", structural_unit_id=other_unit.id)
            session.add_all([building_in, building_out])
            session.flush()
            dev_in = PhysicalDevice(device_type_id=dtype.id, serial_number="SN-IN", system_name="dev-in", building_id=building_in.id)
            dev_out = PhysicalDevice(device_type_id=dtype.id, serial_number="SN-OUT", system_name="dev-out", building_id=building_out.id)
            session.add_all([dev_in, dev_out])
            session.commit()

            ctx_all = ReportContext(session)
            self.assertEqual(len(ctx_all.all_rows("registry-device-rows")), 2)

            ctx_filtered = ReportContext(session, structural_unit_ids=[unit.id])
            rows = ctx_filtered.all_rows("registry-device-rows")
            self.assertEqual([r.serial_number for r in rows.values()], ["SN-IN"])
        finally:
            session.close()


def _seed_rich_dataset(session, *, via_legacy_links: bool):
    """Наполняет БД данными, задействующими большинство ветвлений report_registry_rows.py:
    подключённые/неподключённые порты, VLAN, открытые порты у устройства и у ВМ, СКЗИ, SIEM,
    протокол с fallback (без записи в каталоге), подразделения. via_legacy_links=True привязывает
    ИС к оборудованию через устаревшие таблицы is_devices/is_vms/is_containers/is_ips (fallback-
    ветка _is_row_values при отсутствии InformationSystemSource), False — через актуальную модель
    InformationSystemSource."""
    dep = Department(name="ИТ-отдел")
    dtype = DeviceType(name="Сервер")
    manufacturer = Manufacturer(name="Dell")
    embedded_os = EmbeddedOperatingSystem(name="Ubuntu Server", version="22.04")
    os_category = OperatingSystemCategory(name="Linux-семейство")
    building = Building(name="Главный корпус", address="ул. Ленина, 1")
    session.add_all([dep, dtype, manufacturer, embedded_os, os_category, building])
    session.flush()
    operating_system = OperatingSystem(name="Linux", version="5.15", category_id=os_category.id)
    room = Room(name="214", building_id=building.id)
    session.add_all([operating_system, room])
    session.flush()

    dev1 = PhysicalDevice(device_type_id=dtype.id, manufacturer_id=manufacturer.id, serial_number="SN-001",
                           system_name="srv-01", embedded_os_id=embedded_os.id, building_id=building.id,
                           room_id=room.id, siem_enabled=True)
    dev2 = PhysicalDevice(device_type_id=dtype.id, manufacturer_id=manufacturer.id, serial_number="SN-002",
                           system_name="sw-01", embedded_os_id=embedded_os.id)
    session.add_all([dev1, dev2])
    session.flush()

    iface1 = DeviceInterface(physical_device_id=dev1.id, name="eth0", is_management=True)
    iface2 = DeviceInterface(physical_device_id=dev2.id, name="Gi0/1", is_management=False, is_data_transfer=True)
    iface3 = DeviceInterface(physical_device_id=dev2.id, name="Gi0/2", is_management=False)  # неподключённый
    session.add_all([iface1, iface2, iface3])
    session.flush()
    session.add(InterfaceIP(interface_id=iface1.id, ip_address="10.0.0.1"))
    session.flush()

    ctype = ConnectionType(name="Витая пара")
    session.add(ctype)
    session.flush()
    session.add(Connection(source_interface_id=iface1.id, destination_interface_id=iface2.id,
                            connection_type_id=ctype.id, purpose="Передача данных"))

    vlan = VLAN(vlan_id=100, name="Servers")
    session.add(vlan)
    session.flush()
    session.add(InterfaceVLAN(interface_id=iface1.id, vlan_id=vlan.id))
    session.add(OpenPort(owner_type="physical_device", owner_id=dev1.id,
                          transport_protocol="TCP", port=22, protocol="SSH"))

    isys = InformationSystem(name="ИС Бухгалтерия", description="Учётная система", purpose="Учёт",
                              localization="ЦОД-1", siem_enabled=True, crypto_protection_enabled=True)
    session.add(isys)
    session.flush()
    session.add(ISDepartment(information_system_id=isys.id, department_id=dep.id))
    from app.models import ISProtocol
    session.add(ISProtocol(information_system_id=isys.id, protocol="HTTPS", port=443, description="Веб-интерфейс"))

    vm1 = VirtualMachine(name="vm-buh-01", physical_device_id=dev1.id, purpose="1С сервер",
                          operating_system_id=operating_system.id)
    session.add(vm1)
    session.flush()
    session.add(VMIP(virtual_machine_id=vm1.id, ip_address="192.168.1.10", is_management=True))
    sw = SoftwareAsset(name="1С:Предприятие")
    session.add(sw)
    session.flush()
    session.add(VMSoftware(virtual_machine_id=vm1.id, software_asset_id=sw.id))
    session.add(OpenPort(owner_type="virtual_machine", owner_id=vm1.id,
                          transport_protocol="TCP", port=1540, protocol="1C"))
    container = Container(name="buh-container", virtual_machine_id=vm1.id)
    session.add(container)
    session.flush()

    if via_legacy_links:
        session.add(ISDevice(information_system_id=isys.id, physical_device_id=dev1.id))
        session.add(ISVM(information_system_id=isys.id, virtual_machine_id=vm1.id))
        session.add(ISContainer(information_system_id=isys.id, container_id=container.id))
        session.add(ISIP(information_system_id=isys.id, ip_address="203.0.113.5"))
    else:
        session.add(InformationSystemSource(information_system_id=isys.id, source_type="device",
                                             physical_device_id=dev1.id))
        session.add(InformationSystemSource(information_system_id=isys.id, source_type="vm",
                                             virtual_machine_id=vm1.id, ip_address="203.0.113.5"))

    session.commit()


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/openpyxl не установлены в этом окружении")
class ExactParityTestCase(unittest.TestCase):
    """Строит оба отчёта (регламентированный и шаблон-заготовку конструктора) на одних данных и
    построчно/поколоночно сравнивает содержимое, включая заголовки — не только структуру."""

    def _build_both_and_compare(self, tmp_path, *, via_legacy_links):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        try:
            _seed_rich_dataset(session, via_legacy_links=via_legacy_links)

            orig_path = build_report(session, tmp_path)
            wb_orig = openpyxl.load_workbook(orig_path)

            grid_path = build_xlsx_grid(session, default_registry_template_config(), tmp_path,
                                         template_name=TEMPLATE_NAME, params={})
            wb_grid = openpyxl.load_workbook(grid_path)

            self.assertEqual(wb_orig.sheetnames, wb_grid.sheetnames)
            for name, expected_headers in zip(
                wb_orig.sheetnames, [HEADERS1, HEADERS2, HEADERS3, HEADERS4]
            ):
                ws_o = wb_orig[name]
                ws_g = wb_grid[name]

                orig_headers = [c.value for c in next(ws_o.iter_rows(min_row=1, max_row=1))]
                grid_headers = [c.value for c in next(ws_g.iter_rows(min_row=1, max_row=1))]
                self.assertEqual(orig_headers, expected_headers, f"{name}: заголовки оригинала разошлись с HEADERSn")
                self.assertEqual(grid_headers, expected_headers, f"{name}: заголовки шаблона не совпадают с оригиналом")

                orig_rows = [[c.value for c in row] for row in ws_o.iter_rows(min_row=2)]
                grid_rows = [[c.value for c in row] for row in ws_g.iter_rows(min_row=2)]
                self.assertEqual(orig_rows, grid_rows, f"{name}: данные шаблона разошлись с оригиналом")
                self.assertGreater(len(orig_rows), 0, f"{name}: тестовые данные не дали ни одной строки")
        finally:
            session.close()

    def test_exact_parity_with_current_source_model(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._build_both_and_compare(Path(tmp), via_legacy_links=False)

    def test_exact_parity_with_legacy_link_tables(self):
        """Тот же сценарий, но ИС привязана к оборудованию через устаревшие таблицы
        (is_devices/is_vms/is_containers/is_ips), без InformationSystemSource — проверяет fallback-
        ветку _is_row_values, которую использует и оригинал, и шаблон конструктора (общая функция)."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._build_both_and_compare(Path(tmp), via_legacy_links=True)

    def test_exact_parity_with_structural_unit_filter(self):
        """Тот же сценарий, но с активным structural_unit_ids на обоих движках — подтверждает, что
        runtime-фильтр конструктора (ReportContext/report_registry_rows loaders) не расходится с
        регламентированным отчётом и на отфильтрованном, не только на полном выводе. dev1 (dataset)
        размещён в building без структурной единицы — привязываем её здесь, dev2 её не получает и
        должен выпасть из отфильтрованного вывода обоих движков одинаково."""
        import tempfile
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        try:
            _seed_rich_dataset(session, via_legacy_links=False)
            unit = StructuralUnit(name="Филиал А")
            session.add(unit)
            session.flush()
            building = session.query(Building).one()
            building.structural_unit_id = unit.id
            session.commit()

            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                orig_path = build_report(session, tmp_path, structural_unit_ids=[unit.id])
                wb_orig = openpyxl.load_workbook(orig_path)
                grid_path = build_xlsx_grid(session, default_registry_template_config(), tmp_path,
                                             template_name=TEMPLATE_NAME, params={}, structural_unit_ids=[unit.id])
                wb_grid = openpyxl.load_workbook(grid_path)

                for name in wb_orig.sheetnames:
                    orig_rows = list(wb_orig[name].iter_rows(min_row=2, values_only=True))
                    grid_rows = list(wb_grid[name].iter_rows(min_row=2, values_only=True))
                    self.assertEqual(orig_rows, grid_rows, f"{name}: расхождение при активном фильтре структурной единицы")

                # Устройство вне единицы (sw-01, без building_id) не должно попасть в отфильтрованный
                # вывод ни одного из движков — иначе тест мог бы пройти даже при полностью
                # игнорируемом фильтре (сравнение "пусто == пусто").
                device_rows = list(wb_orig["Инвентаризац. физ. устройств ИС"].iter_rows(min_row=2, values_only=True))
                self.assertEqual(len(device_rows), 1)
                self.assertNotIn("sw-01", device_rows[0])
        finally:
            session.close()

    def test_empty_registry_produces_matching_empty_sheets(self):
        """Пустой реестр — граничный случай (ни одной ИС/устройства/подключения/ВМ)."""
        import tempfile
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        session = sessionmaker(bind=engine)()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                orig_path = build_report(session, tmp_path)
                wb_orig = openpyxl.load_workbook(orig_path)
                grid_path = build_xlsx_grid(session, default_registry_template_config(), tmp_path,
                                             template_name=TEMPLATE_NAME, params={})
                wb_grid = openpyxl.load_workbook(grid_path)
                for name in wb_orig.sheetnames:
                    orig_rows = list(wb_orig[name].iter_rows(min_row=2, values_only=True))
                    grid_rows = list(wb_grid[name].iter_rows(min_row=2, values_only=True))
                    self.assertEqual(orig_rows, grid_rows, f"{name}: пустой реестр — расхождение")
        finally:
            session.close()


if __name__ == "__main__":
    unittest.main()
