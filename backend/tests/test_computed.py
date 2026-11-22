"""
Тесты на backend/app/services/computed.py — общую логику "IP/порт управления устройства с учётом
VLAN", которая раньше была независимо продублирована в serialization.py (дашборд) и дважды в
reporting.py (Лист 2 и Лист 3). Модуль не имеет зависимостей от SQLAlchemy, поэтому тестируется
напрямую, без моков и без in-memory БД.

Запуск: python3 -m unittest discover -s backend/tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services.computed import ip_label, device_management_ports_and_ips, port_label_with_subinterfaces, subinterface_ip_values


def iface(name, id_="if1"):
    return SimpleNamespace(id=id_, name=name)


def ip(interface_id, address, prefix=None):
    return SimpleNamespace(interface_id=interface_id, ip_address=address, prefix_length=prefix)


def vlan_link(vlan_id, ip_address=None, prefix=None):
    return SimpleNamespace(vlan_id=vlan_id, ip_address=ip_address, prefix_length=prefix)


def vlan(number, name):
    return SimpleNamespace(vlan_id=number, name=name)


class IpLabelTestCase(unittest.TestCase):
    def test_with_prefix(self):
        self.assertEqual(ip_label(ip("if1", "10.0.0.1", 24)), "10.0.0.1/24")

    def test_without_prefix(self):
        self.assertEqual(ip_label(ip("if1", "10.0.0.1")), "10.0.0.1")

    def test_zero_prefix_is_not_treated_as_missing(self):
        # prefix_length=0 технически валиден и не должен путаться с "не задан" (None).
        self.assertEqual(ip_label(ip("if1", "10.0.0.1", 0)), "10.0.0.1/0")


class DeviceManagementPortsAndIpsTestCase(unittest.TestCase):
    def test_physical_interface_only(self):
        names, ips = device_management_ports_and_ips([iface("eth0")], {"if1": [ip("if1", "10.0.0.5", 24)]}, [], {})
        self.assertEqual(names, ["eth0"])
        self.assertEqual(ips, ["10.0.0.5/24"])

    def test_vlan_only_with_name(self):
        names, ips = device_management_ports_and_ips(
            [],
            {},
            [vlan_link("v1", "10.10.10.5", 24)],
            {"v1": vlan(100, "Mgmt")},
            vlan_label_with_name=True,
        )
        self.assertEqual(names, ["VLAN 100 — Mgmt"])
        self.assertEqual(ips, ["10.10.10.5/24"])

    def test_vlan_only_without_name_for_strict_port_field(self):
        """Лист 2 отчета — строгое поле 'номер порта', имя VLAN туда не идёт."""
        names, _ = device_management_ports_and_ips(
            [],
            {},
            [vlan_link("v1", "10.10.10.5", 24)],
            {"v1": vlan(100, "Mgmt")},
            vlan_label_with_name=False,
        )
        self.assertEqual(names, ["VLAN 100"])

    def test_both_interface_and_vlan_combined(self):
        names, ips = device_management_ports_and_ips(
            [iface("eth0")],
            {"if1": [ip("if1", "10.0.0.5", 24)]},
            [vlan_link("v1", "10.10.10.5", 24)],
            {"v1": vlan(100, "Mgmt")},
        )
        self.assertEqual(names, ["eth0", "VLAN 100 — Mgmt"])
        self.assertEqual(ips, ["10.0.0.5/24", "10.10.10.5/24"])

    def test_vlan_without_ip_address_contributes_no_ip(self):
        names, ips = device_management_ports_and_ips(
            [],
            {},
            [vlan_link("v1", ip_address=None)],
            {"v1": vlan(100, "Mgmt")},
        )
        self.assertEqual(names, ["VLAN 100 — Mgmt"])
        self.assertEqual(ips, [])

    def test_unknown_vlan_id_is_skipped_not_crashed(self):
        """vlan_map не содержит записи — не должно падать, просто пропускается."""
        names, ips = device_management_ports_and_ips(
            [],
            {},
            [vlan_link("missing-vlan", "10.10.10.5")],
            {},
        )
        self.assertEqual(names, [])
        self.assertEqual(ips, [])

    def test_deduplicates_while_preserving_order(self):
        names, ips = device_management_ports_and_ips(
            [iface("eth0"), iface("eth0")],  # одноимённый порт дважды
            {"if1": [ip("if1", "10.0.0.5", 24), ip("if1", "10.0.0.5", 24)]},
            [],
            {},
        )
        self.assertEqual(names, ["eth0"])
        self.assertEqual(ips, ["10.0.0.5/24"])

    def test_nothing_management_returns_empty(self):
        names, ips = device_management_ports_and_ips([], {}, [], {})
        self.assertEqual(names, [])
        self.assertEqual(ips, [])


def sub(id_, name, vlan_id="v10", parent="if1"):
    return SimpleNamespace(id=id_, name=name, vlan_id=vlan_id, parent_interface_id=parent)


class SubinterfaceTestCase(unittest.TestCase):
    """Подинтерфейсы порта в общих вычислениях (отчёты; дашборд пока их не передаёт)."""

    def test_port_label_without_subinterfaces_is_the_port_name(self):
        self.assertEqual(port_label_with_subinterfaces("Gi0/0", [], {}), "Gi0/0")

    def test_port_label_lists_subinterfaces_with_their_vlan_numbers(self):
        vlans = {"v10": vlan(10, "Серверы"), "v20": vlan(20, "Гости")}
        label = port_label_with_subinterfaces("Gi0/0", [sub("s1", "Gi0/0.10"), sub("s2", "Gi0/0.20", "v20")], vlans)
        self.assertEqual(label, "Gi0/0 (подинтерфейсы: Gi0/0.10 [VLAN 10], Gi0/0.20 [VLAN 20])")

    def test_port_label_with_unknown_vlan_keeps_the_name_without_number(self):
        self.assertEqual(port_label_with_subinterfaces("Gi0/0", [sub("s1", "Gi0/0.99", "gone")], {}), "Gi0/0 (подинтерфейсы: Gi0/0.99)")

    def test_subinterface_ip_values_are_labeled_with_the_subinterface_name(self):
        ips = {"s1": [ip("s1", "10.0.10.1", 24), ip("s1", "10.0.10.2")], "s2": []}
        self.assertEqual(
            subinterface_ip_values([sub("s1", "Gi0/0.10"), sub("s2", "Gi0/0.20")], ips), ["Gi0/0.10: 10.0.10.1/24", "Gi0/0.10: 10.0.10.2"]
        )

    def test_management_subinterface_adds_port_label_and_ip_to_device_management(self):
        ports, ips = device_management_ports_and_ips(
            [iface("Gi0/1", "if2")],
            {"if2": [ip("if2", "192.168.1.1", 24)]},
            [],
            {},
            management_subinterfaces=[sub("s1", "Gi0/0.99", parent="if1")],
            ips_by_subinterface={"s1": [ip("s1", "10.0.99.1", 24)]},
            port_name_by_id={"if1": "Gi0/0"},
        )
        self.assertEqual(ports, ["Gi0/1", "Gi0/0 (подинтерфейс Gi0/0.99)"])
        self.assertEqual(ips, ["192.168.1.1/24", "10.0.99.1/24"])

    def test_management_subinterface_with_unknown_parent_falls_back_to_its_own_name(self):
        ports, _ = device_management_ports_and_ips([], {}, [], {}, management_subinterfaces=[sub("s1", "Gi0/0.99")], ips_by_subinterface={})
        self.assertEqual(ports, ["Gi0/0.99"])

    def test_without_subinterface_arguments_the_result_is_unchanged(self):
        ports, ips = device_management_ports_and_ips([iface("Gi0/1", "if2")], {"if2": [ip("if2", "192.168.1.1", 24)]}, [], {})
        self.assertEqual((ports, ips), (["Gi0/1"], ["192.168.1.1/24"]))


if __name__ == "__main__":
    unittest.main()
