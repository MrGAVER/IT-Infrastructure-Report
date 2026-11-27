"""Правила подключений (лист 3): назначение линии, повторное использование порта, петля на одном устройстве, подсети концов.

Что защищают тесты: каждое правило находит дефект и не срабатывает на законных случаях (L2-порты без адреса, неактивные подключения,
подинтерфейс с назначением, несколько адресов с общей сетью); отпечаток не зависит от переименования; число запросов постоянно.
Запуск: pytest backend/tests/test_consistency_connections.py -v
"""

from __future__ import annotations

import pytest

from app.constants import OwnerType
from app.models import Connection, ConnectionType, DeviceSubinterface, InterfaceVLAN, VLAN
from app.services.consistency import run_checks
from app.services.consistency.approvals import approve_finding
from test_consistency_checks import _device, _ip, _of_rule, _port, _save, _uid


def _connection_type(session) -> str:
    return _save(session, ConnectionType(name=f"витая пара {_uid()}")).id


def _link(session, source, destination, *, active: bool = True) -> Connection:
    return _save(
        session,
        Connection(
            source_interface_id=source.id,
            destination_interface_id=destination.id,
            connection_type_id=_connection_type(session),
            is_active=active,
        ),
    )


def _pair(session, *, purpose=True, names=("sw-a", "sw-b"), **port_fields):
    """Два новых устройства с портом Gi0/1 у каждого; purpose — отмечено ли назначение «передача данных» у обоих портов."""
    return [_port(session, _device(session, system_name=name), "Gi0/1", is_data_transfer=purpose, **port_fields) for name in names]


class TestWithoutPurpose:
    def test_a_port_without_purpose_is_reported_with_its_name(self, client, db_session):
        good, bad = (
            _port(db_session, _device(db_session, system_name="sw-a"), "Gi0/1", is_data_transfer=True),
            _port(db_session, _device(db_session, system_name="sw-b"), "Gi0/2"),
        )
        link = _link(db_session, good, bad)

        (found,) = _of_rule(client, "connection_without_purpose")

        assert found["entity_type"] == "connection" and found["entity_id"] == link.id and found["sheet"] == 3
        assert found["entity_name"] == "sw-a (Gi0/1) ↔ sw-b (Gi0/2)"
        assert [port["name"] for port in found["details"]["ports"]] == ["sw-b (Gi0/2)"]  # назван только порт без назначения

    def test_both_ports_are_named_when_both_lack_a_purpose(self, client, db_session):
        _link(db_session, *_pair(db_session, purpose=False))

        (found,) = _of_rule(client, "connection_without_purpose")

        assert len(found["details"]["ports"]) == 2

    def test_management_flag_and_subinterface_purpose_count_as_a_purpose(self, client, db_session):
        management = _port(db_session, _device(db_session, system_name="ilo"), "ilo", is_management=True)
        data = _port(db_session, _device(db_session, system_name="sw-b"), "Gi0/1", is_data_transfer=True)
        _link(db_session, management, data)
        trunk = _port(db_session, _device(db_session, system_name="rt"), "Gi0/0")
        vlan = _save(db_session, VLAN(vlan_id=20, name="v20"))
        _save(db_session, DeviceSubinterface(parent_interface_id=trunk.id, name="Gi0/0.20", vlan_id=vlan.id, is_data_transfer=True))
        _link(db_session, trunk, _port(db_session, _device(db_session, system_name="sw-c"), "Gi0/2", is_data_transfer=True))

        assert _of_rule(client, "connection_without_purpose") == []

    def test_an_inactive_connection_is_not_checked(self, client, db_session):
        _link(db_session, *_pair(db_session, purpose=False), active=False)

        assert _of_rule(client, "connection_without_purpose") == []


class TestSharedPort:
    def test_a_port_that_is_source_of_one_connection_and_destination_of_another_marks_both(self, client, db_session):
        a, b, c = (_port(db_session, _device(db_session, system_name=name), "Gi0/1", is_data_transfer=True) for name in ("a", "b", "c"))
        first, second = _link(db_session, a, b), _link(db_session, c, a)  # порт a — и источник, и назначение

        found = _of_rule(client, "connection_port_in_several_connections")

        assert {item["entity_id"] for item in found} == {first.id, second.id}
        assert all(item["severity"] == "error" for item in found)
        assert all([port["entity_id"] for port in item["details"]["ports"]] == [a.id] for item in found)

    def test_distinct_ports_and_an_inactive_second_cable_are_fine(self, client, db_session):
        a, b = _pair(db_session)
        _link(db_session, a, b)
        _link(db_session, *_pair(db_session, names=("x", "y")))
        _link(db_session, b, _port(db_session, _device(db_session, system_name="z"), "Gi0/1"), active=False)  # неактивный порт не занимает

        assert _of_rule(client, "connection_port_in_several_connections") == []


class TestSameDevice:
    def test_a_loop_between_two_ports_of_one_device_is_reported(self, client, db_session):
        device = _device(db_session, system_name="sw-a")
        link = _link(db_session, _port(db_session, device, "Gi0/1"), _port(db_session, device, "Gi0/2"))

        (found,) = _of_rule(client, "connection_ends_on_same_device")

        assert found["entity_id"] == link.id and "sw-a" in found["message"]

    def test_a_cable_between_two_devices_is_fine(self, client, db_session):
        _link(db_session, *_pair(db_session))

        assert _of_rule(client, "connection_ends_on_same_device") == []


class TestDifferentSubnets:
    def _addressed(self, session, source_ips, destination_ips):
        source, destination = _pair(session)
        for address, prefix in source_ips:
            _ip(session, OwnerType.DEVICE_INTERFACE, source.id, address, prefix_length=prefix)
        for address, prefix in destination_ips:
            _ip(session, OwnerType.DEVICE_INTERFACE, destination.id, address, prefix_length=prefix)
        return _link(session, source, destination)

    def test_addresses_in_different_networks_are_reported_with_both_sides(self, client, db_session):
        link = self._addressed(db_session, [("10.0.0.1", 24)], [("10.0.1.1", 24)])

        (found,) = _of_rule(client, "connection_ends_in_different_subnets")

        assert found["entity_id"] == link.id
        assert found["details"]["addresses"] == {"source": "10.0.0.1/24", "destination": "10.0.1.1/24"}

    def test_the_same_network_is_fine_whatever_the_host_part(self, client, db_session):
        self._addressed(db_session, [("10.0.0.1", 24)], [("10.0.0.200", 24)])

        assert _of_rule(client, "connection_ends_in_different_subnets") == []

    def test_a_mask_mismatch_is_a_different_network(self, client, db_session):
        self._addressed(db_session, [("10.0.0.1", 30)], [("10.0.0.2", 24)])

        assert len(_of_rule(client, "connection_ends_in_different_subnets")) == 1

    def test_one_shared_network_among_several_addresses_is_enough(self, client, db_session):
        self._addressed(db_session, [("10.0.0.1", 24), ("192.168.5.1", 24)], [("172.16.0.1", 24), ("192.168.5.2", 24)])

        assert _of_rule(client, "connection_ends_in_different_subnets") == []

    @pytest.mark.parametrize(
        ("source", "destination"),
        [
            ([], [("10.0.1.1", 24)]),  # L2-порт без адреса: сравнивать не с чем
            ([("10.0.0.1", None)], [("10.0.1.1", 24)]),  # у адреса нет маски: сеть неизвестна
            ([("10.0.0.1/24", 24)], [("10.0.1.1", 24)]),  # повреждённый адрес ловит invalid_ip, а не это правило
            ([("10.0.0.1", 24), ("10.0.5.1", None)], [("10.0.1.1", 24)]),  # один адрес без маски: судить нельзя
        ],
    )
    def test_when_a_side_cannot_be_judged_nothing_is_reported(self, client, db_session, source, destination):
        self._addressed(db_session, source, destination)

        assert _of_rule(client, "connection_ends_in_different_subnets") == []

    def test_ipv4_only_on_one_side_and_ipv6_only_on_the_other_is_reported(self, client, db_session):
        self._addressed(db_session, [("10.0.0.1", 24)], [("2001:db8::1", 64)])

        assert len(_of_rule(client, "connection_ends_in_different_subnets")) == 1

    def test_subinterface_addresses_are_not_compared(self, client, db_session):
        source, destination = _pair(db_session)
        vlan = _save(db_session, VLAN(vlan_id=30, name="v30"))
        sub = _save(db_session, DeviceSubinterface(parent_interface_id=source.id, name="Gi0/1.30", vlan_id=vlan.id))
        _ip(db_session, OwnerType.DEVICE_SUBINTERFACE, sub.id, "10.30.0.1", prefix_length=24)
        _ip(db_session, OwnerType.DEVICE_INTERFACE, destination.id, "10.99.0.1", prefix_length=24)
        _link(db_session, source, destination)

        assert _of_rule(client, "connection_ends_in_different_subnets") == []


class TestAccessPorts:
    """Правила VLAN: судят только по ЯВНО заданному режиму access — порт без режима считается trunk, а порты без VLAN бывают законными."""

    def _access_pair(self, session, *, vlans_a=0, vlans_b=0, mode_a="access", mode_b="access"):
        source = _port(session, _device(session, system_name=f"a-{_uid()}"), "Gi0/1", is_data_transfer=True, vlan_mode=mode_a)
        destination = _port(session, _device(session, system_name=f"b-{_uid()}"), "Gi0/2", is_data_transfer=True, vlan_mode=mode_b)
        for port, count in ((source, vlans_a), (destination, vlans_b)):
            for _ in range(count):
                vlan = _save(session, VLAN(vlan_id=100 + len(session.query(VLAN).all()), name=f"v-{_uid()}"))
                _save(session, InterfaceVLAN(interface_id=port.id, vlan_id=vlan.id, mode="access"))
        return _link(session, source, destination), source, destination

    def test_an_access_port_without_vlan_is_reported_and_one_with_a_vlan_is_not(self, client, db_session):
        link, bad, good = self._access_pair(db_session, vlans_a=0, vlans_b=1)

        (found,) = _of_rule(client, "connection_access_port_without_vlan")

        assert found["entity_id"] == link.id and found["sheet"] == 3 and found["severity"] == "warning"
        assert [port["entity_id"] for port in found["details"]["ports"]] == [bad.id]  # назван только порт без VLAN
        assert good.id not in found["message"]

    def test_trunk_and_unset_mode_without_vlan_are_not_judged(self, client, db_session):
        self._access_pair(db_session, mode_a="trunk", mode_b=None)

        assert _of_rule(client, "connection_access_port_without_vlan") == []

    def test_an_access_port_with_several_vlans_is_an_error_naming_the_count(self, client, db_session):
        link, overloaded, _ = self._access_pair(db_session, vlans_a=2, vlans_b=1)

        (found,) = _of_rule(client, "connection_access_port_with_several_vlans")

        assert found["entity_id"] == link.id and found["severity"] == "error" and found["category"] == "consistency"
        assert [port["entity_id"] for port in found["details"]["ports"]] == [overloaded.id]
        assert "2 VLAN" in found["message"]

    def test_one_vlan_per_access_port_and_several_on_a_trunk_are_fine(self, client, db_session):
        self._access_pair(db_session, vlans_a=1, vlans_b=1)
        self._access_pair(db_session, vlans_a=3, vlans_b=2, mode_a="trunk", mode_b="trunk")

        assert _of_rule(client, "connection_access_port_with_several_vlans") == []

    def test_inactive_connections_and_ports_outside_connections_are_not_checked(self, client, db_session):
        link, _, _ = self._access_pair(db_session)
        link.is_active = False
        db_session.commit()
        _port(db_session, _device(db_session, system_name="lonely"), "Gi0/9", vlan_mode="access")  # порт вне подключений

        assert _of_rule(client, "connection_access_port_without_vlan") == []

    def test_adding_one_more_vlan_makes_it_a_new_problem_but_a_rename_does_not(self, client, db_session):
        _, overloaded, _ = self._access_pair(db_session, vlans_a=2, vlans_b=1)
        before = _of_rule(client, "connection_access_port_with_several_vlans")[0]["fingerprint"]

        overloaded.name = "Gi0/9"
        db_session.commit()
        assert _of_rule(client, "connection_access_port_with_several_vlans")[0]["fingerprint"] == before

        vlan = _save(db_session, VLAN(vlan_id=900, name="extra"))
        _save(db_session, InterfaceVLAN(interface_id=overloaded.id, vlan_id=vlan.id, mode="access"))
        assert _of_rule(client, "connection_access_port_with_several_vlans")[0]["fingerprint"] != before


class TestFingerprintAndApproval:
    def test_renaming_a_device_or_port_does_not_change_the_fingerprint_but_a_new_problem_does(self, client, db_session):
        source, destination = _pair(db_session, purpose=False)
        _link(db_session, source, destination)
        before = _of_rule(client, "connection_without_purpose")[0]["fingerprint"]

        source.name = "Gi0/9"
        db_session.commit()
        assert _of_rule(client, "connection_without_purpose")[0]["fingerprint"] == before

        source.is_data_transfer = True  # у одного порта назначение появилось — проблема стала другой
        db_session.commit()
        assert _of_rule(client, "connection_without_purpose")[0]["fingerprint"] != before

    def test_a_connection_problem_can_be_approved(self, client, db_session):
        _link(db_session, *_pair(db_session, purpose=False))
        (problem,) = run_checks(db_session, rules=["connection_without_purpose"])

        result = approve_finding(db_session, problem.fingerprint, "служебная линия")

        assert result["created"] is True
        assert _of_rule(client, "connection_without_purpose")[0]["approved"] is True


def test_number_of_queries_does_not_grow_with_the_number_of_connections(db_session, sql_log):
    def populate(count: int) -> None:
        for number in range(count):
            source, destination = _pair(db_session, names=(f"a-{_uid()}", f"b-{_uid()}"), purpose=bool(number % 2))
            _ip(db_session, OwnerType.DEVICE_INTERFACE, source.id, f"10.{number % 200}.0.1", prefix_length=24)
            _ip(db_session, OwnerType.DEVICE_INTERFACE, destination.id, f"10.{number % 200}.1.1", prefix_length=24)
            _link(db_session, source, destination)

    def measure() -> int:
        before = len(sql_log)
        run_checks(db_session, sheets=[3])
        return len(sql_log) - before

    populate(3)
    small = measure()
    populate(20)

    assert measure() == small
