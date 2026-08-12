"""
Тесты на backend/app/reporting.py (генерация Excel-отчета).

Запуск:  python3 -m unittest discover -s backend/tests -v
Не требует установленных fastapi/sqlalchemy — использует mock_sqlalchemy.py.

Каждый тест соответствует конкретному дефекту, который был найден и исправлен в ходе разработки
(см. историю правок), чтобы такие регрессии больше не проходили незамеченными.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mock_sqlalchemy import FakeSession, empty_table, load_reporting_module

import openpyxl


class ReportingTestCase(unittest.TestCase):
    def setUp(self):
        self.build_report, self.C = load_reporting_module()
        self.table = empty_table()

    def build(self, tmp_path: Path):
        session = FakeSession(self.table)
        out = self.build_report(session, tmp_path)
        return openpyxl.load_workbook(out)

    def sheet_rows(self, wb, name):
        return list(wb[name].iter_rows(values_only=True))

    def col_index(self, header, substring):
        for i, h in enumerate(header):
            if h and substring in h:
                return i
        raise AssertionError(f"колонка с подстрокой {substring!r} не найдена среди заголовков: {header}")


class Sheet1InformationSystems(ReportingTestCase):
    """Лист 'Перечень ИС'."""

    def test_departments_column_is_filled_from_isdepartment(self):
        C = self.C
        dep = C["Department"](id="dep1", name="Бухгалтерия")
        isys = C["InformationSystem"](id="is1", name="ИС", crypto_protection_enabled=False)
        isdep = C["ISDepartment"](id="isd1", information_system_id="is1", department_id="dep1")
        self.table.update({
            "InformationSystem": [isys], "Department": [dep], "ISDepartment": [isdep],
        })
        wb = self.build(Path("/tmp/test_reports_1"))
        rows = self.sheet_rows(wb, "Перечень ИС")
        self.assertEqual(rows[1][4], "Бухгалтерия")

    def test_interaction_ip_excludes_physical_server_ip_but_includes_vm_ip(self):
        """Регрессия: раньше IP физического сервера ошибочно попадал в столбец IP ИС."""
        C = self.C
        dev = C["PhysicalDevice"](id="d1", serial_number="SN1")
        iface = C["DeviceInterface"](id="if1", physical_device_id="d1", is_management=True)
        dev_ip = C["InterfaceIP"](id="ip1", interface_id="if1", ip_address="10.0.0.5", prefix_length=24)
        vm = C["VirtualMachine"](id="v1", name="VM1", physical_device_id="d1", purpose="")
        vm_ip = C["VMIP"](id="vip1", virtual_machine_id="v1", ip_address="10.0.1.5", prefix_length=24, is_management=True)
        isys = C["InformationSystem"](id="is1", name="ИС", crypto_protection_enabled=False)
        isdev = C["ISDevice"](id="isd1", information_system_id="is1", physical_device_id="d1")
        isvm = C["ISVM"](id="isv1", information_system_id="is1", virtual_machine_id="v1")
        self.table.update({
            "InformationSystem": [isys], "PhysicalDevice": [dev], "DeviceInterface": [iface],
            "InterfaceIP": [dev_ip], "VirtualMachine": [vm], "VMIP": [vm_ip],
            "ISDevice": [isdev], "ISVM": [isvm],
        })
        wb = self.build(Path("/tmp/test_reports_2"))
        rows = self.sheet_rows(wb, "Перечень ИС")
        ip_col = rows[1][8]
        self.assertNotIn("10.0.0.5", ip_col or "")
        self.assertIn("10.0.1.5", ip_col or "")

    def test_legacy_tables_used_as_fallback_when_no_unified_sources(self):
        """ИС, ни разу не пересохранённая через новую форму (unified-источники пусты), должна
        по-прежнему показывать оборудование из старых таблиц ISDevice/ISVM/ISContainer."""
        C = self.C
        dev = C["PhysicalDevice"](id="d1", serial_number="SN1", system_name="LEGACY-SRV")
        isys = C["InformationSystem"](id="is1", name="ИС", crypto_protection_enabled=False)
        isdev = C["ISDevice"](id="isd1", information_system_id="is1", physical_device_id="d1")
        self.table.update({
            "InformationSystem": [isys], "PhysicalDevice": [dev], "ISDevice": [isdev],
            "InformationSystemSource": [],  # явно пусто — имитация немигрированной записи
        })
        wb = self.build(Path("/tmp/test_reports_11"))
        rows = self.sheet_rows(wb, "Перечень ИС")
        header = rows[0]
        equipment_idx = self.col_index(header, "Оборудование ООО")
        self.assertIn("LEGACY-SRV", rows[1][equipment_idx])

    def test_unified_sources_take_priority_and_no_duplication(self):
        """Как только у ИС есть unified-источники, легаси-таблицы игнорируются полностью (даже
        если в них есть устаревшие данные) — оборудование не должно задваиваться."""
        C = self.C
        dev = C["PhysicalDevice"](id="d1", serial_number="SN1", system_name="NEW-SRV")
        stale_dev = C["PhysicalDevice"](id="d2", serial_number="SN2", system_name="STALE-SRV")
        isys = C["InformationSystem"](id="is1", name="ИС", crypto_protection_enabled=False)
        src = C["InformationSystemSource"](id="src1", information_system_id="is1", source_type="device", physical_device_id="d1", role="server")
        stale_isdev = C["ISDevice"](id="isd1", information_system_id="is1", physical_device_id="d2")
        self.table.update({
            "InformationSystem": [isys], "PhysicalDevice": [dev, stale_dev],
            "InformationSystemSource": [src], "ISDevice": [stale_isdev],
        })
        wb = self.build(Path("/tmp/test_reports_12"))
        rows = self.sheet_rows(wb, "Перечень ИС")
        header = rows[0]
        equipment_idx = self.col_index(header, "Оборудование ООО")
        equipment_cell = rows[1][equipment_idx]
        self.assertIn("NEW-SRV", equipment_cell)
        self.assertNotIn("STALE-SRV", equipment_cell)
        self.assertEqual(equipment_cell.count("NEW-SRV"), 1)


class Sheet2PhysicalDevices(ReportingTestCase):
    """Лист 'Инвентаризац. физ. устройств ИС'."""

    def test_no_device_kind_column(self):
        wb = self.build(Path("/tmp/test_reports_3"))
        headers = self.sheet_rows(wb, "Инвентаризац. физ. устройств ИС")[0]
        self.assertNotIn("Вид физического устройства", " ".join(h for h in headers if h))

    def test_os_version_uses_embedded_os(self):
        C = self.C
        emb = C["EmbeddedOperatingSystem"](id="eos1", name="iLO", version="2.44")
        dev = C["PhysicalDevice"](id="d1", serial_number="SN1", embedded_os_id="eos1")
        self.table.update({"PhysicalDevice": [dev], "EmbeddedOperatingSystem": [emb]})
        wb = self.build(Path("/tmp/test_reports_4"))
        rows = self.sheet_rows(wb, "Инвентаризац. физ. устройств ИС")
        header = rows[0]
        os_col_idx = header.index("Версия операционной системы физического устройства")
        self.assertIn("iLO", rows[1][os_col_idx])

    def test_management_port_shows_vlan(self):
        """Регрессия: раньше VLAN-порт управления не попадал в столбец номера порта управления."""
        C = self.C
        dev = C["PhysicalDevice"](id="d1", serial_number="SN1")
        vlan = C["VLAN"](id="vl1", vlan_id=100, name="Mgmt")
        dev_vlan = C["PhysicalDeviceVLAN"](id="dv1", physical_device_id="d1", vlan_id="vl1", is_management=True, ip_address="10.10.10.5", prefix_length=24)
        self.table.update({"PhysicalDevice": [dev], "VLAN": [vlan], "PhysicalDeviceVLAN": [dev_vlan]})
        wb = self.build(Path("/tmp/test_reports_5"))
        rows = self.sheet_rows(wb, "Инвентаризац. физ. устройств ИС")
        header = rows[0]
        port_col_idx = header.index("Номер порта управления устройством, если устройство является управлемым")
        self.assertIn("VLAN 100", rows[1][port_col_idx])


class Sheet3Connections(ReportingTestCase):
    """Лист 'Организация подключений'."""

    def _two_devices_two_connections(self):
        C = self.C
        dt_server = C["DeviceType"](id="dt1", name="Сервер")
        dt_switch = C["DeviceType"](id="dt2", name="Коммутатор")
        dev1 = C["PhysicalDevice"](id="d1", device_type_id="dt1", serial_number="123", system_name="srv-204")
        dev2 = C["PhysicalDevice"](id="d2", device_type_id="dt2", serial_number="321", system_name="C2960X_210")
        if1 = C["DeviceInterface"](id="if1", physical_device_id="d1", name="eth0", is_management=False, is_data_transfer=True)
        if2 = C["DeviceInterface"](id="if2", physical_device_id="d2", name="Gi0/1", is_management=False, is_data_transfer=False)
        if3 = C["DeviceInterface"](id="if3", physical_device_id="d1", name="eth1", is_management=True, is_data_transfer=False)
        if4 = C["DeviceInterface"](id="if4", physical_device_id="d2", name="Gi0/2", is_management=True, is_data_transfer=True)
        ct = C["ConnectionType"](id="ct1", name="Ethernet")
        # Намеренно разный порядок src/dst между двумя связями — раньше это приводило
        # к чередованию строк устройств в отчете вместо группировки.
        conn1 = C["Connection"](id="c1", source_interface_id="if1", destination_interface_id="if2", connection_type_id="ct1")
        conn2 = C["Connection"](id="c2", source_interface_id="if4", destination_interface_id="if3", connection_type_id="ct1")
        self.table.update({
            "DeviceType": [dt_server, dt_switch], "PhysicalDevice": [dev1, dev2],
            "DeviceInterface": [if1, if2, if3, if4], "ConnectionType": [ct],
            "Connection": [conn1, conn2],
        })
        return dev1, dev2

    def test_rows_are_grouped_by_device_not_interleaved(self):
        self._two_devices_two_connections()
        wb = self.build(Path("/tmp/test_reports_6"))
        rows = self.sheet_rows(wb, "Организация подключений")[1:]
        serials = [r[2] for r in rows]
        # Все строки одного serial_number должны идти подряд, без чередования.
        seen = []
        for s in serials:
            if not seen or seen[-1] != s:
                seen.append(s)
        self.assertEqual(len(seen), len(set(serials)), f"строки чередуются: {serials}")

    def test_purpose_mapping_from_checkboxes(self):
        self._two_devices_two_connections()
        wb = self.build(Path("/tmp/test_reports_7"))
        rows = self.sheet_rows(wb, "Организация подключений")[1:]
        header = self.sheet_rows(wb, "Организация подключений")[0]
        port_idx = header.index("Номер физического или логического порта")
        purpose_idx = header.index("Сведения о назначении линий связи (передача данных или управление активами информационной системы, средствами защиты информации)")
        by_port = {r[port_idx]: r[purpose_idx] for r in rows}
        self.assertEqual(by_port["eth0"], "Передача данных")
        self.assertEqual(by_port["eth1"], "Управление активами")
        self.assertEqual(by_port["Gi0/2"], "Управление активами, передача данных")
        self.assertEqual(by_port["Gi0/1"], "-")

    def test_disconnected_ports_are_included_and_grouped_by_ip_signature(self):
        C = self.C
        dev1, _ = self._two_devices_two_connections()
        # Два порта без подключения и без IP — должны сгруппироваться в одну строку.
        if5 = C["DeviceInterface"](id="if5", physical_device_id="d1", name="eth2", is_management=False, is_data_transfer=False)
        if6 = C["DeviceInterface"](id="if6", physical_device_id="d1", name="eth3", is_management=False, is_data_transfer=False)
        self.table["DeviceInterface"].extend([if5, if6])
        wb = self.build(Path("/tmp/test_reports_8"))
        rows = self.sheet_rows(wb, "Организация подключений")[1:]
        header = self.sheet_rows(wb, "Организация подключений")[0]
        port_idx = header.index("Номер физического или логического порта")
        grouped = [r[port_idx] for r in rows if "eth2" in (r[port_idx] or "") or "eth3" in (r[port_idx] or "")]
        self.assertEqual(len(grouped), 1, "отключенные порты без IP должны объединиться в одну строку")
        self.assertIn("eth2", grouped[0])
        self.assertIn("eth3", grouped[0])

    def test_empty_cells_are_dash_not_blank(self):
        self._two_devices_two_connections()
        wb = self.build(Path("/tmp/test_reports_9"))
        rows = self.sheet_rows(wb, "Организация подключений")[1:]
        for row in rows:
            for cell in row:
                self.assertNotEqual(cell, "", "пустая ячейка должна быть заполнена '-'")

    def test_neighbor_ip_uses_management_ips_including_vlan(self):
        """Регрессия: IP соседнего порта должен быть IP управления устройства (включая VLAN), а не
        обязательно IP конкретного физического порта."""
        C = self.C
        dev1, dev2 = self._two_devices_two_connections()
        vlan = C["VLAN"](id="vl1", vlan_id=100, name="Mgmt")
        dev_vlan = C["PhysicalDeviceVLAN"](id="dv1", physical_device_id="d1", vlan_id="vl1", is_management=True, ip_address="10.10.10.5", prefix_length=24)
        self.table.update({"VLAN": [vlan], "PhysicalDeviceVLAN": [dev_vlan]})
        wb = self.build(Path("/tmp/test_reports_10"))
        rows = self.sheet_rows(wb, "Организация подключений")[1:]
        header = self.sheet_rows(wb, "Организация подключений")[0]
        neighbor_ip_idx = header.index("IP-адрес порта соседнего физического устройства ХХХ.ХХХ.ХХХ.ХХХ/24")
        neighbor_serial_idx = header.index("Серийный номер соседнего физического устройства, в том числе ПК пользователей")
        switch_rows = [r for r in rows if r[neighbor_serial_idx] == "123"]  # смотрим со стороны коммутатора на сервер
        self.assertTrue(any("10.10.10.5" in (r[neighbor_ip_idx] or "") for r in switch_rows))


if __name__ == "__main__":
    unittest.main()
