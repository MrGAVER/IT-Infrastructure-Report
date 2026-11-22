"""Загрузка данных для отчётов — app/reporting.py: _load_report_data (контейнер `d`).

Фиксирует поведение до снижения сложности функции (код-ревью, п. 10; сложность 22). `d` — общий контракт: его
читают листы Excel (reporting.py), конструктор отчётов (services/report_registry_rows.py) и структурное
приложение (services/structural_appendix.py), поэтому проверяется состав и содержимое каждого значимого
атрибута, а не только итоговый файл. Раньше эти ветви (порт «Все VLAN», контейнеры в фильтре по структурной
единице) покрывались только через мок SQLAlchemy, который игнорирует `where`; здесь — настоящая БД и набор
данных tests/report_seed.py. Тесты написаны на прежнем коде и проходят без правок после рефакторинга.

Запуск: pytest backend/tests/test_report_data_behaviour.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_seed import seed_registry  # noqa: E402

from app.reporting import _load_report_data  # noqa: E402


@pytest.fixture()
def registry(db_session):
    seed_registry(db_session)
    return db_session


def _ids(value):
    """Объекты ORM → их id, словари и списки — рекурсивно; пары (тип владельца, id) в ключах — как есть."""
    if value is None:
        return None
    if hasattr(value, "id") and not isinstance(value, (str, bytes)):
        return value.id
    if isinstance(value, (list, tuple)):
        return [_ids(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(_ids(item) for item in value)
    if isinstance(value, dict):
        return {key: _ids(item) for key, item in value.items()}
    return value


def _load(session, only_is=None, units=None) -> SimpleNamespace:
    return _load_report_data(session, only_is, units)


ATTRIBUTES = {
    "allowed_device_ids",
    "buildings",
    "connection_types",
    "conns",
    "container_map",
    "containers",
    "crypto_means",
    "dep_by_is",
    "dep_map",
    "departments",
    "deployed_software",
    "device_map",
    "device_types",
    "device_vlan_by_device",
    "device_vlan_rows",
    "devices",
    "embedded_os",
    "iface_map",
    "iface_vlans",
    "ifaces_by_device",
    "interface_ips",
    "interface_types",
    "interfaces",
    "ips_by_iface",
    "ips_by_source",
    "ips_by_sub",
    "is_deps",
    "is_protocols",
    "is_sources",
    "manufacturers",
    "models",
    "open_ports",
    "open_ports_by_owner",
    "operating_systems",
    "placement_assets",
    "placement_by_is",
    "protocol_by_is",
    "protocol_catalog",
    "protocols",
    "rooms",
    "software",
    "software_by_device",
    "software_by_vm",
    "source_by_is",
    "source_ips",
    "structural_units",
    "subinterfaces",
    "subs_by_device",
    "subs_by_iface",
    "support_map",
    "support_methods",
    "support_orgs",
    "systems",
    "vlan_by_iface",
    "vlan_map",
    "vlans",
    "vm_map",
    "vmips",
    "vmips_by_vm",
    "vms",
}


class TestContract:
    def test_namespace_has_exactly_the_attributes_the_consumers_rely_on(self, registry):
        assert set(vars(_load(registry))) == ATTRIBUTES

    def test_attributes_are_present_even_for_an_empty_registry(self, db_session):
        d = _load(db_session)
        assert set(vars(d)) == ATTRIBUTES
        assert d.allowed_device_ids is None and d.systems == [] and d.devices == []
        assert dict(d.ips_by_iface) == {} and dict(d.vlan_by_iface) == {} and dict(d.subs_by_device) == {}


class TestOrderingAndMaps:
    def test_lists_come_in_the_order_the_sheets_expect(self, registry):
        d = _load(registry)
        assert _ids(d.systems) == ["is1", "is2", "is3", "is4", "is5", "is7", "is6"]  # по названию
        assert _ids(d.devices) == ["rt1", "srv0", "srv1", "sw1", "sw2"]  # по системному имени (пустое — первым), затем по серийному
        assert _ids(d.interfaces) == ["r1", "q1", "q2", "q3", "p1", "p2", "p3", "p4", "p5", "p6", "n1"]  # по имени порта
        assert _ids(d.vms) == ["vm1", "vm3", "vm2"]  # по названию
        assert _ids(d.conns) == ["c1", "c2", "c3"]  # по времени создания
        assert [ip.ip_address for ip in d.interface_ips] == ["10.0.0.2", "10.0.0.2", "192.168.1.1", "192.168.1.2"]
        assert [ip.ip_address for ip in d.vmips] == ["10.1.1.10", "10.1.1.20"]

    @pytest.mark.parametrize(
        ("mapping", "listing"),
        [
            ("dep_map", "departments"),
            ("support_map", "support_orgs"),
            ("device_map", "devices"),
            ("iface_map", "interfaces"),
            ("vm_map", "vms"),
            ("container_map", "containers"),
            ("vlan_map", "vlans"),
            ("protocol_catalog", "protocols"),
        ],
    )
    def test_maps_are_keyed_by_id_and_hold_the_same_records_as_the_lists(self, registry, mapping, listing):
        d = _load(registry)
        assert {key: value.id for key, value in getattr(d, mapping).items()} == {item.id: item.id for item in getattr(d, listing)}
        assert getattr(d, mapping)

    def test_reference_catalogs_are_loaded_in_full_by_id(self, registry):
        d = _load(registry)
        assert {
            name: sorted(getattr(d, name))
            for name in (
                "device_types",
                "manufacturers",
                "models",
                "buildings",
                "rooms",
                "structural_units",
                "operating_systems",
                "embedded_os",
                "support_methods",
                "crypto_means",
                "placement_assets",
                "interface_types",
                "connection_types",
                "software",
            )
        } == {
            "device_types": ["dt-rt", "dt-srv", "dt-sw"],
            "manufacturers": ["m1"],
            "models": ["mod1"],
            "buildings": ["b1", "b2", "b3"],
            "rooms": ["rm1"],
            "structural_units": ["u-child", "u-other", "u-root"],
            "operating_systems": ["os1"],
            "embedded_os": ["eos1"],
            "support_methods": ["sm1"],
            "crypto_means": ["cp1"],
            "placement_assets": ["pa1"],
            "interface_types": ["it1"],
            "connection_types": ["ct1"],
            "software": ["sa1", "sa2"],
        }

    def test_plain_lists_hold_every_row_of_their_tables(self, registry):
        d = _load(registry)
        assert sorted(_ids(d.containers)) == ["ct-a", "ct-b", "ct-c", "ct-d", "ct-e"]
        assert sorted(_ids(d.deployed_software)) == ["ds1", "ds2", "ds3"]
        assert sorted(_ids(d.is_deps)) == ["isd1"] and sorted(_ids(d.is_protocols)) == ["isp1"]
        assert sorted(_ids(d.is_sources)) == ["src-ct", "src-ct2", "src-ct3", "src-ct4", "src-dev", "src-dup", "src-gone", "src-lost", "src-vm", "src-vm3"]
        assert sorted(_ids(d.protocols)) == ["cat-22", "cat-443", "cat-80"] and sorted(_ids(d.open_ports)) == ["op1", "op2", "op3", "op4"]
        assert sorted(_ids(d.iface_vlans)) == ["iv1", "iv2", "iv3", "iv4", "iv5", "iv6"] and sorted(_ids(d.device_vlan_rows)) == ["pdv1", "pdv2"]
        assert sorted(_ids(d.subinterfaces)) == ["s-a", "s-b", "s-c"]


class TestGroupings:
    def test_interface_vm_subinterface_and_source_addresses_go_to_their_own_owners_only(self, registry):
        d = _load(registry)
        assert _ids(d.ips_by_iface) == {"q2": ["ip3"], "q3": ["ip4"], "p1": ["ip2", "ip1"]}  # по адресу
        assert _ids(d.ips_by_sub) == {"s-a": ["ip5"], "s-c": ["ip6"]}
        assert _ids(d.vmips_by_vm) == {"vm1": ["ip8", "ip7"]}
        assert _ids(d.ips_by_source) == {"src-vm": ["ip9"]}
        every = [ip for group in (d.ips_by_iface, d.ips_by_sub, d.vmips_by_vm, d.ips_by_source) for ips in group.values() for ip in ips]
        assert "ip10" not in _ids(every)  # адрес с владельцем «physical_device» в отчёт не попадает

    def test_interfaces_open_ports_and_device_vlans_are_grouped_by_owner(self, registry):
        d = _load(registry)
        assert _ids(d.ifaces_by_device) == {"rt1": ["r1"], "sw2": ["q1", "q2", "q3"], "sw1": ["p1", "p2", "p3", "p4", "p5", "p6"], "srv1": ["n1"]}
        assert _ids(d.open_ports_by_owner) == {
            ("device_interface", "p1"): ["op1"],
            ("device_subinterface", "s-a"): ["op2"],
            ("virtual_machine", "vm1"): ["op3"],
            ("physical_device", "sw1"): ["op4"],
        }
        assert _ids(d.device_vlan_by_device) == {"sw1": ["pdv1", "pdv2"]}

    def test_information_system_links_are_grouped_by_system_in_insertion_order(self, registry):
        d = _load(registry)
        assert _ids(d.dep_by_is) == {"is1": ["isd1"]} and _ids(d.protocol_by_is) == {"is1": ["isp1"]} and _ids(d.placement_by_is) == {"is1": ["isa1"]}
        assert _ids(d.source_by_is) == {
            "is1": ["src-dev", "src-vm", "src-ct", "src-dup", "src-gone"],
            "is2": ["src-ct2"],
            "is3": ["src-lost"],
            "is5": ["src-ct3"],
            "is6": ["src-ct4"],
            "is7": ["src-vm3"],
        }

    def test_software_is_split_by_owner_kind_and_everything_but_a_vm_lands_in_the_device_bucket(self, registry):
        d = _load(registry)
        assert _ids(d.software_by_vm) == {"vm1": ["sa1"]}
        assert _ids(d.software_by_device) == {"srv1": ["sa2"], "ct-a": ["sa2"]}  # ПО контейнера — тоже в «устройствах»


class TestPortVlans:
    def test_ports_keep_the_vlans_they_are_linked_to_in_link_order(self, registry):
        d = _load(registry)
        by_iface = _ids(d.vlan_by_iface)
        assert by_iface["p1"] == ["v10", "v20"] and by_iface["r1"] == ["v10"] and by_iface["q1"] == ["v20"] and by_iface["p3"] == ["v10"]
        assert "p4" not in d.vlan_by_iface  # у порта без связей ключа нет

    def test_all_vlans_port_gets_every_vlan_of_its_device_by_number_and_ignores_its_own_links(self, registry):
        d = _load(registry)
        # у SW-1: VLAN 10 и 20 заданы устройству, 30 — типу устройства; собственная связь порта с VLAN 40 игнорируется
        assert _ids(d.vlan_by_iface["p2"]) == ["v10", "v20", "a30"]  # по номеру: id «a30» в алфавите раньше, но номер у него 30
        assert [v.vlan_id for v in d.vlan_by_iface["p2"]] == [10, 20, 30]

    def test_all_vlans_derivation_is_skipped_when_no_port_carries_the_flag(self, registry):
        from app.models import DeviceInterface

        registry.query(DeviceInterface).filter_by(id="p2").update({"all_vlans": False})
        registry.commit()
        d = _load(registry)
        assert _ids(d.vlan_by_iface["p2"]) == ["v40"]  # теперь его собственная связь учитывается


class TestSubinterfaces:
    def test_subinterfaces_are_ordered_by_vlan_number_then_name_and_gathered_per_device(self, registry):
        d = _load(registry)
        assert _ids(d.subs_by_iface) == {"p5": ["s-b", "s-a"], "p1": ["s-c"]}  # у p5: сначала VLAN 10, потом VLAN 20
        assert _ids(d.subs_by_device) == {"rt1": [], "sw2": [], "sw1": ["s-c", "s-b", "s-a"], "srv1": []}  # устройства без подинтерфейсов — с пустым списком

    def test_name_decides_between_subinterfaces_of_the_same_vlan_ignoring_case(self, registry):
        from app.models import DeviceSubinterface

        registry.add_all(
            [DeviceSubinterface(id="s-d", parent_interface_id="p5", name="Gi1/0/5.dup-b", vlan_id="v10"), DeviceSubinterface(id="s-e", parent_interface_id="p5", name="gi1/0/5.dup-a", vlan_id="v10")]
        )
        registry.commit()
        d = _load(registry)
        assert _ids(d.subs_by_iface["p5"]) == ["s-b", "s-e", "s-d", "s-a"]  # VLAN 10: «Gi1/0/5.10» < «gi1/0/5.dup-a» < «Gi1/0/5.dup-b»; затем VLAN 20

    def test_vlan_number_outranks_the_name(self, registry):
        from app.models import DeviceSubinterface

        registry.add_all([DeviceSubinterface(id="s-f", parent_interface_id="p5", name="AAA-first-by-name", vlan_id="a30")])
        registry.commit()
        d = _load(registry)
        assert _ids(d.subs_by_iface["p5"]) == ["s-b", "s-a", "s-f"]  # по имени он был бы первым, но у него VLAN 30


class TestUnfiltered:
    def test_without_units_every_record_is_listed_and_no_device_filter_is_set(self, registry):
        d = _load(registry)
        assert d.allowed_device_ids is None
        assert _ids(d.devices) == ["rt1", "srv0", "srv1", "sw1", "sw2"] and _ids(d.vms) == ["vm1", "vm3", "vm2"]
        assert len(d.systems) == 7

    @pytest.mark.parametrize("units", [None, []])
    def test_empty_selection_means_no_filter(self, registry, units):
        d = _load(registry, units=units)
        assert d.allowed_device_ids is None and len(d.devices) == 5

    def test_single_information_system(self, registry):
        d = _load(registry, only_is="is2")
        assert _ids(d.systems) == ["is2"]
        assert sorted(d.source_by_is) == ["is1", "is2", "is3", "is5", "is6", "is7"]  # связи остальных ИС по-прежнему загружены
        assert _ids(_load(registry, only_is="нет-такой").systems) == []


class TestStructuralUnitFilter:
    def test_parent_unit_selects_devices_of_its_descendants(self, registry):
        d = _load(registry, units=["u-root"])
        assert _ids(d.allowed_device_ids) == ["rt1", "sw1"]  # здание Корпус 1 относится к «Отдел 1» — потомку «Управления»
        assert _ids(d.devices) == ["rt1", "sw1"]
        assert _ids(_load(registry, units=["u-child"]).devices) == ["rt1", "sw1"]

    def test_vms_are_narrowed_by_their_host_device(self, registry):
        d = _load(registry, units=["u-root"])
        assert _ids(d.vms) == ["vm3"]  # vm1 — на устройстве вне выбранных единиц, vm2 — без хоста

    def test_systems_are_kept_when_any_linked_object_sits_on_an_allowed_device(self, registry):
        d = _load(registry, units=["u-root"])
        # is1 — устройство SW-1; is5 — контейнер на ВМ, хост которой в выбранной единице; is7 — сама такая ВМ; is6 — контейнер прямо на устройстве.
        # Не попали: is2 (контейнер на ВМ с хостом вне единицы), is3 (ВМ без хоста), is4 (без источников).
        assert _ids(d.systems) == ["is1", "is5", "is7", "is6"]

    def test_lookup_maps_stay_complete_so_neighbors_and_hosts_can_still_be_found(self, registry):
        d = _load(registry, units=["u-root"])
        assert sorted(d.device_map) == ["rt1", "srv0", "srv1", "sw1", "sw2"]
        assert sorted(d.vm_map) == ["vm1", "vm2", "vm3"] and sorted(d.container_map) == ["ct-a", "ct-b", "ct-c", "ct-d", "ct-e"]
        # (при активном фильтре defaultdict дополняется пустыми записями ИС, которые просмотрели, — сравниваем только непустые)
        assert sorted(key for key, links in d.source_by_is.items() if links) == ["is1", "is2", "is3", "is5", "is6", "is7"]

    def test_other_unit_and_several_units(self, registry):
        other = _load(registry, units=["u-other"])
        assert _ids(other.allowed_device_ids) == ["sw2"] and _ids(other.devices) == ["sw2"] and other.vms == [] and other.systems == []
        both = _load(registry, units=["u-root", "u-other"])
        assert _ids(both.allowed_device_ids) == ["rt1", "sw1", "sw2"] and _ids(both.vms) == ["vm3"]

    def test_unknown_unit_selects_nothing_rather_than_everything(self, registry):
        d = _load(registry, units=["нет-такой"])
        assert d.allowed_device_ids == set() and d.devices == [] and d.vms == [] and d.systems == []

    def test_filters_combine(self, registry):
        assert _ids(_load(registry, only_is="is2", units=["u-root"]).systems) == []
        assert _ids(_load(registry, only_is="is5", units=["u-root"]).systems) == ["is5"]

    def test_building_without_a_unit_belongs_to_no_unit(self, registry):
        d = _load(registry, units=["u-root", "u-other", "u-child"])
        assert "srv1" not in d.allowed_device_ids and "srv0" not in d.allowed_device_ids  # здание «Склад» без единицы; srv0 — без здания
