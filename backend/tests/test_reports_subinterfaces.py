"""Подинтерфейсы портов в отчётах Excel (Листы 1-3): выводятся ВНУТРИ строки своего порта, а не отдельными
строками. Порт и его подинтерфейсы — одна запись «Номер физического или логического порта»: подпись порта со
списком подинтерфейсов и их VLAN, IP/открытые порты/назначение подинтерфейса помечены его именем, VLAN
подинтерфейсов попадают в колонки VLAN. Если управление висит на подинтерфейсе, его порт и IP — это порт и IP
управления устройства (Лист 2, Лист 1, колонка IP соседа на Листе 3).

Использует тот же мок SQLAlchemy, что и test_reporting.py (tests/mock_sqlalchemy.py).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mock_sqlalchemy import FakeSession, empty_table, load_reporting_module
from xlsx_helpers import expanded_rows

import openpyxl

SHEET3 = "Организация подключений"
SHEET2 = "Инвентаризац. физ. устройств ИС"
PORT = "Номер физического или логического порта"


class SubinterfaceReportCase(unittest.TestCase):
    def setUp(self):
        self.build_report, self.C = load_reporting_module()
        self.table = empty_table()

    def build(self, name: str):
        out = self.build_report(FakeSession(self.table), Path(f"/tmp/test_reports_sub_{name}"), None, None)
        return openpyxl.load_workbook(out)

    @staticmethod
    def rows(wb, sheet):
        data = expanded_rows(wb[sheet])
        return data[0], data[1:]

    @staticmethod
    def col(header, substring):
        for i, h in enumerate(header):
            if h and substring in h:
                return i
        raise AssertionError(f"колонка {substring!r} не найдена")

    def seed_router_and_switch(self, *, router_port_flags=(False, True)):
        """Маршрутизатор r1 (порт Gi0/0 с двумя подинтерфейсами на VLAN 10 и 20) соединён с коммутатором s1."""
        C = self.C
        self.table.update(
            {
                "DeviceType": [C["DeviceType"](id="dt1", name="Маршрутизатор"), C["DeviceType"](id="dt2", name="Коммутатор")],
                "PhysicalDevice": [
                    C["PhysicalDevice"](id="r1", device_type_id="dt1", serial_number="R-1", system_name="rtr"),
                    C["PhysicalDevice"](id="s1", device_type_id="dt2", serial_number="S-1", system_name="sw"),
                ],
                "DeviceInterface": [
                    C["DeviceInterface"](id="r-if", physical_device_id="r1", name="Gi0/0", is_management=router_port_flags[0], is_data_transfer=router_port_flags[1]),
                    C["DeviceInterface"](id="s-if", physical_device_id="s1", name="Gi1/0/1", is_management=False, is_data_transfer=True),
                ],
                "ConnectionType": [C["ConnectionType"](id="ct1", name="Ethernet")],
                "Connection": [C["Connection"](id="c1", source_interface_id="r-if", destination_interface_id="s-if", connection_type_id="ct1")],
                "VLAN": [C["VLAN"](id="v10", vlan_id=10, name="Серверы"), C["VLAN"](id="v20", vlan_id=20, name="Гости")],
                # порядок в таблице нарочно «неправильный»: в отчёте подинтерфейсы идут по номеру VLAN
                "DeviceSubinterface": [
                    C["DeviceSubinterface"](id="sub20", parent_interface_id="r-if", name="Gi0/0.20", vlan_id="v20", is_management=False, is_data_transfer=False),
                    C["DeviceSubinterface"](id="sub10", parent_interface_id="r-if", name="Gi0/0.10", vlan_id="v10", is_management=False, is_data_transfer=True),
                ],
                "IPAddress": [
                    C["IPAddress"](id="ip-port", owner_type="device_interface", owner_id="r-if", ip_address="192.168.0.1", prefix_length=30),
                    C["IPAddress"](id="ip-s10", owner_type="device_subinterface", owner_id="sub10", ip_address="10.0.10.1", prefix_length=24),
                    C["IPAddress"](id="ip-s20", owner_type="device_subinterface", owner_id="sub20", ip_address="10.0.20.1", prefix_length=24),
                ],
            }
        )

    def router_row(self, wb):
        header, rows = self.rows(wb, SHEET3)
        port_idx = self.col(header, PORT)
        return header, next(r for r in rows if (r[port_idx] or "").startswith("Gi0/0"))


class Sheet3SubinterfacesInsidePort(SubinterfaceReportCase):
    def test_port_cell_lists_subinterfaces_with_vlans_and_no_extra_rows(self):
        self.seed_router_and_switch()
        header, row = self.router_row(self.build("port"))
        self.assertEqual(row[self.col(header, PORT)], "Gi0/0 (подинтерфейсы: Gi0/0.10 [VLAN 10], Gi0/0.20 [VLAN 20])")

        # строк по-прежнему по одной на каждую сторону подключения — подинтерфейсы отдельных строк не создают
        _, rows = self.rows(self.build("rows"), SHEET3)
        self.assertEqual(len(rows), 2)

    def test_ip_cell_has_port_ip_and_labeled_subinterface_ips(self):
        self.seed_router_and_switch()
        header, row = self.router_row(self.build("ip"))
        self.assertEqual(row[self.col(header, "IP-адрес порта физического устройства")], "192.168.0.1/30; Gi0/0.10: 10.0.10.1/24; Gi0/0.20: 10.0.20.1/24")

    def test_port_without_own_ip_shows_subinterface_ips_not_unassigned(self):
        self.seed_router_and_switch()
        self.table["IPAddress"] = [ip for ip in self.table["IPAddress"] if ip.id != "ip-port"]
        header, row = self.router_row(self.build("noip"))
        self.assertEqual(row[self.col(header, "IP-адрес порта физического устройства")], "Gi0/0.10: 10.0.10.1/24; Gi0/0.20: 10.0.20.1/24")

    def test_vlan_columns_include_subinterface_vlans_in_vlan_order(self):
        self.seed_router_and_switch()
        header, row = self.router_row(self.build("vlan"))
        self.assertEqual(row[self.col(header, "VLAN ID")], "10; 20")
        self.assertEqual(row[self.col(header, "VLAN Name")], "Серверы; Гости")

    def test_vlan_already_on_port_is_not_repeated_by_subinterface(self):
        C = self.C
        self.seed_router_and_switch()
        self.table["InterfaceVLAN"] = [C["InterfaceVLAN"](id="iv1", interface_id="r-if", vlan_id="v10")]
        header, row = self.router_row(self.build("vlan_dup"))
        self.assertEqual(row[self.col(header, "VLAN ID")], "10; 20")

    def test_open_ports_and_protocols_of_subinterface_are_labeled_with_its_name(self):
        C = self.C
        self.seed_router_and_switch()
        self.table.update(
            {
                "ProtocolPortCatalog": [C["ProtocolPortCatalog"](id="cat-ssh", port=22, protocol_type="SSH"), C["ProtocolPortCatalog"](id="cat-https", port=443, protocol_type="HTTPS")],
                "OpenPort": [
                    C["OpenPort"](id="op1", owner_type="device_interface", owner_id="r-if", protocol_catalog_id="cat-ssh", transport_protocol="TCP"),
                    C["OpenPort"](id="op2", owner_type="device_subinterface", owner_id="sub10", protocol_catalog_id="cat-https", transport_protocol="TCP"),
                ],
            }
        )
        header, row = self.router_row(self.build("ports"))
        # формат одного порта прежний («TCP/22; SSH» — транспорт/порт и протокол через «;»), у порта подинтерфейса
        # перед ним имя подинтерфейса
        self.assertEqual(row[self.col(header, "Перечень открытых портов")], "TCP/22; SSH; Gi0/0.10: TCP/443; HTTPS")
        self.assertEqual(row[self.col(header, "Протокол (технология)")], "SSH; HTTPS")

    def test_purpose_of_subinterface_is_labeled_and_port_purpose_kept(self):
        self.seed_router_and_switch(router_port_flags=(False, True))
        header, row = self.router_row(self.build("purpose"))
        # у Gi0/0 — «Передача данных», у Gi0/0.10 — тоже «Передача данных», у Gi0/0.20 ролей нет
        self.assertEqual(row[self.col(header, "Сведения о назначении линий связи")], "Передача данных; Gi0/0.10: Передача данных")

    def test_subinterface_role_shows_even_when_port_has_none(self):
        self.seed_router_and_switch(router_port_flags=(False, False))
        header, row = self.router_row(self.build("purpose2"))
        self.assertEqual(row[self.col(header, "Сведения о назначении линий связи")], "Gi0/0.10: Передача данных")

    def test_neighbor_ip_column_shows_labeled_subinterface_ips_of_the_neighbor_port(self):
        self.seed_router_and_switch()
        header, rows = self.rows(self.build("neighbor"), SHEET3)
        switch_row = next(r for r in rows if r[self.col(header, "Серийный номер устройства")] == "S-1")
        self.assertEqual(
            switch_row[self.col(header, "IP-адрес порта соседнего физического устройства")],
            "192.168.0.1/30; Gi0/0.10: 10.0.10.1/24; Gi0/0.20: 10.0.20.1/24",
        )

    def test_disconnected_port_with_subinterfaces_is_not_merged_with_other_ports(self):
        C = self.C
        self.seed_router_and_switch()
        self.table["DeviceInterface"] += [
            C["DeviceInterface"](id="r-if2", physical_device_id="r1", name="Gi0/1", is_management=False, is_data_transfer=False),
            C["DeviceInterface"](id="r-if3", physical_device_id="r1", name="Gi0/2", is_management=False, is_data_transfer=False),
            C["DeviceInterface"](id="r-if4", physical_device_id="r1", name="Gi0/3", is_management=False, is_data_transfer=False),
        ]
        self.table["DeviceSubinterface"].append(C["DeviceSubinterface"](id="sub-g1", parent_interface_id="r-if2", name="Gi0/1.10", vlan_id="v10"))
        header, rows = self.rows(self.build("grouping"), SHEET3)
        ports = [r[self.col(header, PORT)] for r in rows if r[self.col(header, "Серийный номер устройства")] == "R-1"]
        # Gi0/2 и Gi0/3 без IP и подинтерфейсов по-прежнему объединены в одну строку, Gi0/1 с подинтерфейсом — своя
        self.assertIn("Gi0/2; Gi0/3", ports)
        self.assertIn("Gi0/1 (подинтерфейсы: Gi0/1.10 [VLAN 10])", ports)
        self.assertEqual(len([p for p in ports if "Gi0/1" in p]), 1)

    def test_subinterface_with_vlan_missing_from_catalog_does_not_break_report(self):
        C = self.C
        self.seed_router_and_switch()
        self.table["DeviceSubinterface"].append(C["DeviceSubinterface"](id="sub-x", parent_interface_id="r-if", name="Gi0/0.99", vlan_id="v-gone"))
        header, row = self.router_row(self.build("orphan"))
        self.assertIn("Gi0/0.99", row[self.col(header, PORT)])
        self.assertNotIn("Gi0/0.99 [VLAN", row[self.col(header, PORT)])


class ManagementOnSubinterface(SubinterfaceReportCase):
    def seed_management_subinterface(self):
        C = self.C
        self.seed_router_and_switch()
        sub = next(s for s in self.table["DeviceSubinterface"] if s.id == "sub10")
        sub.is_management = True
        self.table["IPAddress"] = [
            C["IPAddress"](id="ip-mgmt", owner_type="device_subinterface", owner_id="sub10", ip_address="10.0.10.1", prefix_length=24, is_management=True),
        ]

    def test_sheet2_management_port_and_ip_come_from_the_management_subinterface(self):
        self.seed_management_subinterface()
        header, rows = self.rows(self.build("s2"), SHEET2)
        router = next(r for r in rows if r[self.col(header, "Серийный номер устройства")] == "R-1")
        self.assertEqual(router[self.col(header, "Номер порта управления")], "Gi0/0 (подинтерфейс Gi0/0.10)")
        self.assertEqual(router[self.col(header, "IP-адрес управления")], "10.0.10.1/24")

    def test_sheet2_port_count_counts_physical_ports_only(self):
        self.seed_management_subinterface()
        header, rows = self.rows(self.build("s2count"), SHEET2)
        router = next(r for r in rows if r[self.col(header, "Серийный номер устройства")] == "R-1")
        self.assertEqual(router[self.col(header, "Количество физических портов")], "1 Без типа")

    def test_sheet3_neighbor_ip_is_the_management_ip_on_the_subinterface(self):
        self.seed_management_subinterface()
        header, rows = self.rows(self.build("s3"), SHEET3)
        switch_row = next(r for r in rows if r[self.col(header, "Серийный номер устройства")] == "S-1")
        self.assertEqual(switch_row[self.col(header, "IP-адрес порта соседнего физического устройства")], "10.0.10.1/24")

    def test_sheet1_physical_server_ip_includes_management_subinterface_ip(self):
        C = self.C
        self.seed_management_subinterface()
        self.table.update(
            {
                "InformationSystem": [C["InformationSystem"](id="is1", name="ИС", crypto_protection_enabled=False)],
                "InformationSystemSource": [C["InformationSystemSource"](id="src1", information_system_id="is1", source_type="device", owner_id="r1")],
            }
        )
        header, rows = self.rows(self.build("s1"), "Перечень ИС")
        self.assertEqual(rows[0][self.col(header, "IP-адрес физического сервера")], "10.0.10.1/24")

    def test_non_management_subinterface_does_not_become_management_ip(self):
        self.seed_router_and_switch()
        header, rows = self.rows(self.build("s2none"), SHEET2)
        router = next(r for r in rows if r[self.col(header, "Серийный номер устройства")] == "R-1")
        self.assertIn(router[self.col(header, "IP-адрес управления")], (None, ""))  # пустая ячейка Excel читается как None


if __name__ == "__main__":
    unittest.main()
