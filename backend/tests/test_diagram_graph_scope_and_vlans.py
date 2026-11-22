"""
A-06 (код-ревью main @ b375f58): ветки diagram_graph.py, которых не касался ни один тест, — фильтр охвата диаграммы и работа с VLAN устройства.

Что проверяется: «Все VLAN» у порта (`carries_all_vlans` → `effective_vlan_ids`: порт несёт все VLAN устройства, выбранные вручную
игнорируются, access-порт «все VLAN» не несёт),
`device_vlan_ids` (VLAN устройства ∪ VLAN его портов), `management_vlan_id`, группировка по VLAN (управляющий VLAN важнее наименьшего
номера, устройство без VLAN — в «Без VLAN», неизвестное измерение — ошибка), подписи свёрнутых групп, фильтры охвата `structural_unit_ids`
(с вложенными единицами), `building_ids`,
`device_category_ids`, `vlan_ids` и их сочетание по AND.

Запуск: pytest backend/tests/test_diagram_graph_scope_and_vlans.py -v
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.models import (
    VLAN,
    Building,
    DeviceCategory,
    DeviceInterface,
    DeviceType,
    InterfaceVLAN,
    PhysicalDevice,
    PhysicalDeviceVLAN,
    SavedDiagram,
    StructuralUnit,
)
from app.services.diagram_graph import GraphContext, build_graph, group_key_for_device


@pytest.fixture()
def types(db_session):
    category_net, category_srv = DeviceCategory(name="Сеть"), DeviceCategory(name="Серверы")
    db_session.add_all([category_net, category_srv])
    db_session.flush()
    switch = DeviceType(name="Коммутатор", category_id=category_net.id)
    server = DeviceType(name="Сервер", category_id=category_srv.id)
    db_session.add_all([switch, server])
    db_session.flush()
    return {"switch": switch, "server": server, "net": category_net, "srv": category_srv}


def _device(session, device_type, serial, *, building=None, name=None) -> PhysicalDevice:
    device = PhysicalDevice(device_type_id=device_type.id, serial_number=serial, system_name=name or serial, building_id=building.id if building else None)
    session.add(device)
    session.flush()
    return device


def _graph_ids(session, scope: dict, group_by: str = "building", threshold: int = 50) -> set[str]:
    diagram = SavedDiagram(name=f"Д-{uuid.uuid4().hex[:8]}", scope_filter=json.dumps(scope), group_by=group_by, collapse_threshold=threshold)
    session.add(diagram)
    session.flush()
    return {node["id"] for node in build_graph(session, diagram, persist=False)["nodes"]}


class TestAllVlansPort:
    @pytest.fixture()
    def device(self, db_session, types):
        device = _device(db_session, types["switch"], "SN-SW")
        v20, v10, v30 = VLAN(vlan_id=20, name="Гости"), VLAN(vlan_id=10, name="Серверы"), VLAN(vlan_id=30, name="Чужой")
        db_session.add_all([v20, v10, v30])
        db_session.flush()
        db_session.add_all([PhysicalDeviceVLAN(physical_device_id=device.id, vlan_id=v20.id), PhysicalDeviceVLAN(physical_device_id=device.id, vlan_id=v10.id)])
        db_session.flush()
        return SimpleDevice(device, v10, v20, v30)

    def test_port_with_all_vlans_carries_every_vlan_of_its_device_sorted_by_number_and_ignores_manual_selection(self, db_session, device):
        port = DeviceInterface(physical_device_id=device.device.id, name="Gi0/1", all_vlans=True, vlan_mode="trunk")
        db_session.add(port)
        db_session.flush()
        db_session.add(
            InterfaceVLAN(interface_id=port.id, vlan_id=device.v30.id)
        )  # выбран вручную, но на устройстве его нет: при «Все VLAN» выбор не действует
        db_session.flush()

        ctx = GraphContext(db_session)

        assert ctx.interface_vlan_ids_by_interface[port.id] == [device.v10.id, device.v20.id], (
            "VLAN устройства по возрастанию номера (10, 20), а не по порядку добавления"
        )

    def test_access_port_does_not_carry_all_vlans_even_with_the_flag(self, db_session, device):
        port = DeviceInterface(physical_device_id=device.device.id, name="Gi0/2", all_vlans=True, vlan_mode="access")
        db_session.add(port)
        db_session.flush()
        db_session.add(InterfaceVLAN(interface_id=port.id, vlan_id=device.v30.id))
        db_session.flush()

        ctx = GraphContext(db_session)

        assert ctx.interface_vlan_ids_by_interface[port.id] == [device.v30.id], "у access-порта действует только то, что выбрано"

    def test_device_vlan_ids_join_the_device_vlans_and_the_vlans_of_its_ports(self, db_session, device):
        port = DeviceInterface(physical_device_id=device.device.id, name="Gi0/3")
        db_session.add(port)
        db_session.flush()
        db_session.add(InterfaceVLAN(interface_id=port.id, vlan_id=device.v30.id))
        db_session.flush()

        ctx = GraphContext(db_session)

        assert ctx.device_vlan_ids(device.device.id) == {device.v10.id, device.v20.id, device.v30.id}
        assert ctx.device_vlan_ids("no-such-device") == set()


class SimpleDevice:
    def __init__(self, device, v10, v20, v30):
        self.device, self.v10, self.v20, self.v30 = device, v10, v20, v30


class TestManagementVlanAndGroupingByVlan:
    def _link(self, session, device, vlan, *, management=False):
        session.add(PhysicalDeviceVLAN(physical_device_id=device.id, vlan_id=vlan.id, is_management=management))
        session.flush()

    def test_management_vlan_is_the_marked_one_or_none(self, db_session, types):
        managed, plain = _device(db_session, types["switch"], "SN-M"), _device(db_session, types["switch"], "SN-P")
        v10, v99 = VLAN(vlan_id=10, name="Данные"), VLAN(vlan_id=99, name="Управление")
        db_session.add_all([v10, v99])
        db_session.flush()
        self._link(db_session, managed, v10)
        self._link(db_session, managed, v99, management=True)
        self._link(db_session, plain, v10)

        ctx = GraphContext(db_session)

        assert ctx.management_vlan_id(managed.id) == v99.id
        assert ctx.management_vlan_id(plain.id) is None
        assert ctx.management_vlan_id("no-such-device") is None

    def test_vlan_grouping_prefers_the_management_vlan_then_the_lowest_number_then_the_unassigned_group(self, db_session, types):
        with_mgmt, without_mgmt, bare = (_device(db_session, types["switch"], serial) for serial in ("SN-1", "SN-2", "SN-3"))
        v5, v10, v99 = VLAN(vlan_id=5, name="Пять"), VLAN(vlan_id=10, name="Десять"), VLAN(vlan_id=99, name="Управление")
        db_session.add_all([v5, v10, v99])
        db_session.flush()
        self._link(db_session, with_mgmt, v5)
        self._link(db_session, with_mgmt, v99, management=True)  # управляющий важнее меньшего номера
        self._link(db_session, without_mgmt, v10)
        self._link(db_session, without_mgmt, v5)  # без управляющего — наименьший номер

        ctx = GraphContext(db_session)

        assert group_key_for_device(with_mgmt, "vlan", ctx) == f"vlan:{v99.id}"
        assert group_key_for_device(without_mgmt, "vlan", ctx) == f"vlan:{v5.id}"
        assert group_key_for_device(bare, "vlan", ctx) == "vlan:none"

    def test_unknown_grouping_dimension_is_an_error(self, db_session, types):
        device = _device(db_session, types["switch"], "SN-X")

        with pytest.raises(ValueError, match="Неизвестное измерение группировки: 'color'"):
            group_key_for_device(device, "color", GraphContext(db_session))

    def test_collapsed_vlan_group_gets_a_readable_label(self, db_session, types):
        vlan = VLAN(vlan_id=10, name="Серверы")
        db_session.add(vlan)
        first, second, lonely = (_device(db_session, types["server"], serial) for serial in ("SN-A", "SN-B", "SN-C"))
        db_session.flush()
        self._link(db_session, first, vlan)
        self._link(db_session, second, vlan)
        diagram = SavedDiagram(name="По VLAN", scope_filter="{}", group_by="vlan", collapse_threshold=2)
        db_session.add(diagram)
        db_session.flush()

        graph = build_graph(db_session, diagram, persist=False)

        labels = {node["id"]: node["label"] for node in graph["nodes"]}
        assert labels[f"group:vlan:{vlan.id}"] == "VLAN 10 Серверы (2)"
        assert lonely.id in labels, "устройство без VLAN — одиночное, ниже порога сворачивания"
        assert first.id not in labels and second.id not in labels, "свёрнутые устройства отдельными узлами не рисуются"


class TestScopeFilter:
    @pytest.fixture()
    def world(self, db_session, types):
        head, branch, other = StructuralUnit(name="Головной офис"), StructuralUnit(name="Филиал"), StructuralUnit(name="Сторонняя организация")
        db_session.add_all([head, other])
        db_session.flush()
        branch.parent_id = head.id  # филиал вложен в головной офис
        db_session.add(branch)
        db_session.flush()
        b_head, b_branch, b_other = (
            Building(name=name, structural_unit_id=unit.id) for name, unit in (("Здание ГО", head), ("Здание филиала", branch), ("Чужое здание", other))
        )
        db_session.add_all([b_head, b_branch, b_other])
        db_session.flush()
        vlan = VLAN(vlan_id=10, name="Серверы")
        db_session.add(vlan)
        devices = {
            "head_switch": _device(db_session, types["switch"], "SN-1", building=b_head),
            "branch_server": _device(db_session, types["server"], "SN-2", building=b_branch),
            "other_server": _device(db_session, types["server"], "SN-3", building=b_other),
            "homeless": _device(db_session, types["server"], "SN-4"),
        }
        db_session.flush()
        db_session.add(PhysicalDeviceVLAN(physical_device_id=devices["branch_server"].id, vlan_id=vlan.id))
        db_session.add(PhysicalDeviceVLAN(physical_device_id=devices["homeless"].id, vlan_id=vlan.id))
        db_session.flush()
        return {"head": head, "branch": branch, "b_head": b_head, "b_other": b_other, "vlan": vlan, "types": types, **devices}

    def _ids(self, session, world, *names: str) -> set[str]:
        return {world[name].id for name in names}

    def test_no_filter_shows_every_device(self, db_session, world):
        assert _graph_ids(db_session, {}) == self._ids(db_session, world, "head_switch", "branch_server", "other_server", "homeless")

    def test_structural_unit_includes_the_nested_units(self, db_session, world):
        shown = _graph_ids(db_session, {"structural_unit_ids": [world["head"].id]})

        assert shown == self._ids(db_session, world, "head_switch", "branch_server"), (
            "головной офис захватывает и вложенный филиал, но не чужую организацию и устройство без здания"
        )

    def test_building_filter(self, db_session, world):
        assert _graph_ids(db_session, {"building_ids": [world["b_other"].id]}) == self._ids(db_session, world, "other_server")

    def test_device_category_filter_uses_the_category_of_the_device_type(self, db_session, world):
        shown = _graph_ids(db_session, {"device_category_ids": [world["types"]["srv"].id]})

        assert shown == self._ids(db_session, world, "branch_server", "other_server", "homeless")

    def test_vlan_filter_matches_devices_that_have_the_vlan(self, db_session, world):
        assert _graph_ids(db_session, {"vlan_ids": [world["vlan"].id]}) == self._ids(db_session, world, "branch_server", "homeless")

    def test_dimensions_are_combined_with_and_and_values_within_a_dimension_with_or(self, db_session, world):
        scope = {"structural_unit_ids": [world["head"].id], "device_category_ids": [world["types"]["srv"].id], "vlan_ids": [world["vlan"].id, "no-such-vlan"]}

        assert _graph_ids(db_session, scope) == self._ids(db_session, world, "branch_server")

        either = {"building_ids": [world["b_head"].id, world["b_other"].id]}
        assert _graph_ids(db_session, either) == self._ids(db_session, world, "head_switch", "other_server")
