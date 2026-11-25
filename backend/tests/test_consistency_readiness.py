"""«Готовность отчёта»: GET /api/v1/integrity/consistency/readiness — по каждому листу доля объектов без незакрытых проблем.

Что защищают тесты: объект с несколькими проблемами считается один раз; одобренные проблемы не мешают; 100 % только когда готовы все;
повтор имени задевает все одноимённые устройства; лист 3 не выдаёт отсутствие проверок за отсутствие проблем; проблемы без листа
считаются отдельно. Запуск: pytest backend/tests/test_consistency_readiness.py -v
"""

from __future__ import annotations

import pytest

from app.constants import OwnerType
from app.models import (
    Building,
    Connection,
    Container,
    InformationSystem,
    InformationSystemSource,
    EmbeddedOperatingSystem,
    PhysicalDevice,
    Room,
    VirtualMachine,
)
from app.services.consistency import run_checks
from app.services.consistency.approvals import approve_finding
from app.services.consistency.readiness import TOP_RULES, affected_objects
from test_consistency_checks import _device, _ip, _port, _save, _uid

URL = "/api/v1/integrity/consistency/readiness"


def _sheets(client) -> dict[int, dict]:
    response = client.get(URL)
    assert response.status_code == 200, response.text
    return {item["sheet"]: item for item in response.json()["sheets"]}


def _located_device(session, **fields) -> PhysicalDevice:
    """Устройство без пробелов в паспорте и размещении (здание, помещение, производитель, модель, встроенная ОС): на листе 2 у него нет
    проблем, кроме отсутствующего IP управления, если у устройства есть системное имя."""
    building = _save(session, Building(name=f"Здание {fields.get('system_name', '')}"))
    room = _save(session, Room(building_id=building.id, name="Серверная"))
    system = _save(session, EmbeddedOperatingSystem(name="Linux"))
    return _device(session, building_id=building.id, room_id=room.id, embedded_os_id=system.id, **fields)


def test_empty_registry_has_four_sheets_without_percentages(client):
    body = client.get(URL).json()

    assert [item["sheet"] for item in body["sheets"]] == [1, 2, 3, 4]
    assert all(item["total"] == 0 and item["percent"] is None for item in body["sheets"])
    assert body["unassigned"] == 0


def _connection_type(session) -> str:
    from app.models import ConnectionType

    return _save(session, ConnectionType(name=f"витая пара {_uid()}")).id


def _connect(session, name_a: str, name_b: str, *, active: bool = True, purpose: bool = True) -> Connection:
    """Подключение между портами двух новых устройств; purpose — отмечено ли назначение «передача данных» у обоих портов."""
    ports = [_port(session, _device(session, system_name=name), "Gi0/1", is_data_transfer=purpose) for name in (name_a, name_b)]
    return _save(
        session,
        Connection(
            source_interface_id=ports[0].id,
            destination_interface_id=ports[1].id,
            connection_type_id=_connection_type(session),
            is_active=active,
        ),
    )


class TestSheetThree:
    def test_sheet_three_is_checked_and_counts_only_active_connections(self, client, db_session):
        _connect(db_session, "a", "b")
        _connect(db_session, "c", "d", active=False)  # неактивное подключение в отчёт не попадает

        sheet = _sheets(client)[3]

        assert sheet["checked"] is True and sheet["total"] == 1

    def test_a_connection_without_purpose_lowers_the_sheet_and_a_complete_one_does_not(self, client, db_session):
        _connect(db_session, "a", "b")
        _connect(db_session, "c", "d", purpose=False)

        sheet = _sheets(client)[3]

        assert sheet["total"] == 2 and sheet["affected"] == 1 and sheet["percent"] == 50
        assert [item["rule"] for item in sheet["top_rules"]] == ["connection_without_purpose"]

    def test_a_clean_sheet_three_is_one_hundred_percent(self, client, db_session):
        _connect(db_session, "a", "b")

        sheet = _sheets(client)[3]

        assert sheet["affected"] == 0 and sheet["percent"] == 100


class TestSheetTwo:
    def test_an_object_with_several_problems_counts_once_but_all_problems_are_counted(self, client, db_session):
        _located_device(db_session, system_name="ok-1")
        _located_device(db_session, system_name="ok-2")
        bare = _save(
            db_session, PhysicalDevice(device_type_id=_device(db_session).device_type_id, serial_number="bare")
        )  # нет здания, помещения, паспорта

        sheet = _sheets(client)[2]

        assert sheet["total"] == 4  # + устройство, созданное ради типа
        assert bare.id and sheet["affected"] >= 1
        assert sheet["problems"] > sheet["affected"]  # у «голого» устройства их несколько, а объект один

    def test_percentage_rounds_down_so_one_hundred_means_everyone_is_ready(self, client, db_session):
        for _ in range(99):
            _located_device(db_session)  # без системного имени — не управляемое, адрес управления не нужен
        _device(db_session, serial_number="bad")  # без здания, помещения и ОС

        sheet = _sheets(client)[2]

        assert sheet["total"] == 100 and sheet["affected"] == 1 and sheet["ready"] == 99
        assert sheet["percent"] == 99  # не 100: округление вверх выдало бы «готово», пока есть проблемный объект

    def test_a_tiny_share_of_problems_never_rounds_up_to_ready(self, client, db_session):
        for _ in range(300):
            _located_device(db_session)
        _device(db_session, serial_number="bad")

        sheet = _sheets(client)[2]

        assert sheet["ready"] == 300 and sheet["total"] == 301
        assert sheet["percent"] == 99  # 99,67 % → 99, а не 100

    def test_everything_ready_gives_exactly_one_hundred(self, client, db_session):
        for number in range(3):
            _ip(
                db_session,
                OwnerType.DEVICE_INTERFACE,
                _port(db_session, _located_device(db_session, system_name=f"ok-{number}"), "mgmt", is_management=True).id,
                f"10.0.0.{number + 1}",
            )

        sheet = _sheets(client)[2]

        assert sheet["affected"] == 0 and sheet["percent"] == 100 and sheet["problems"] == 0

    def test_a_repeated_system_name_touches_every_device_that_bears_it(self, client, db_session):
        for _ in range(3):
            _located_device(db_session, system_name="SW-Core")
        _located_device(db_session, system_name="unique")

        sheet = _sheets(client)[2]

        assert sheet["affected"] >= 3  # все три одноимённых, а не одно из них

    def test_the_most_frequent_problems_come_first_and_there_are_at_most_three(self, client, db_session):
        for number in range(4):
            _device(db_session, system_name=f"d-{number}")  # у всех нет здания/помещения, и все управляемые без IP

        top = _sheets(client)[2]["top_rules"]

        assert 1 <= len(top) <= TOP_RULES
        assert [item["count"] for item in top] == sorted((item["count"] for item in top), reverse=True)
        assert all(item["title"] for item in top)


class TestApprovals:
    def test_an_approved_problem_no_longer_blocks_readiness_but_is_counted_separately(self, client, db_session):
        _device(db_session, system_name="d-1")
        before = _sheets(client)[2]
        problem = next(item for item in run_checks(db_session, sheets=[2]) if item.rule == "device_location_incomplete")

        approve_finding(db_session, problem.fingerprint, "допустимо")
        after = _sheets(client)[2]

        assert after["problems"] == before["problems"] - 1
        assert after["approved"] == before["approved"] + 1

    def test_if_the_only_problem_is_approved_the_object_is_ready(self, client, db_session):
        device = _located_device(db_session, system_name="d-1")
        # Единственная проблема — нет IP управления; одобряем её.
        problems = [item for item in run_checks(db_session, sheets=[2])]
        assert [item.rule for item in problems] == ["managed_device_without_mgmt_ip"]
        approve_finding(db_session, problems[0].fingerprint)

        sheet = _sheets(client)[2]

        assert device.id and sheet["affected"] == 0 and sheet["percent"] == 100 and sheet["approved"] == 1


class TestSheetsOneAndFour:
    def test_information_systems_without_placement_lower_sheet_one(self, client, db_session):
        full = _save(db_session, InformationSystem(name="Полная", description="d", purpose="p", localization="l", process_description="x"))
        _save(db_session, InformationSystemSource(information_system_id=full.id, source_type="manual"))
        _save(db_session, InformationSystem(name="Пустая"))

        sheet = _sheets(client)[1]

        assert sheet["total"] == 2 and sheet["affected"] == 2  # у «полной» нет поддержки и протоколов
        assert {item["rule"] for item in sheet["top_rules"]} <= {
            "is_without_support",
            "is_without_placement",
            "is_text_incomplete",
            "is_without_protocols",
        }

    def test_sheet_four_counts_virtual_machines_and_containers_together(self, client, db_session):
        vm = _save(db_session, VirtualMachine(name="vm-1"))
        _save(db_session, Container(name="lost"))
        _save(db_session, Container(name="placed", virtual_machine_id=vm.id))

        sheet = _sheets(client)[4]

        assert sheet["total"] == 3
        assert sheet["affected"] == 2  # вм без хоста и потерянный контейнер; размещённый контейнер проблем не имеет


def test_problems_without_a_sheet_are_reported_separately_and_do_not_touch_any_sheet(client, db_session):
    first, second = _located_device(db_session, system_name="a"), _located_device(db_session, system_name="b")
    for device in (first, second):
        _ip(
            db_session, OwnerType.DEVICE_INTERFACE, _port(db_session, device, "mgmt", is_management=True).id, "10.0.0.5"
        )  # повтор IP: листа нет

    body = client.get(URL).json()

    assert body["unassigned"] == 1
    assert next(item for item in body["sheets"] if item["sheet"] == 2)["affected"] == 0


def test_an_approved_problem_without_a_sheet_leaves_the_unassigned_count(client, db_session):
    for name in ("a", "b"):
        _ip(
            db_session,
            OwnerType.DEVICE_INTERFACE,
            _port(db_session, _located_device(db_session, system_name=name), "mgmt", is_management=True).id,
            "10.0.0.5",
        )
    (problem,) = [item for item in run_checks(db_session, rules=["duplicate_ip"])]
    assert client.get(URL).json()["unassigned"] == 1

    approve_finding(db_session, problem.fingerprint, "общий адрес VRRP")

    assert client.get(URL).json()["unassigned"] == 0


class TestAffectedObjects:
    def _finding(self, **details):
        from app.services.consistency.model import Category, Finding, Severity

        return Finding("r", Severity.WARNING, Category.CONSISTENCY, "ip_address", "10.0.0.5", "10.0.0.5", "m", details=details)

    def test_holders_and_devices_replace_the_pseudo_object(self):
        assert affected_objects(
            self._finding(
                holders=[{"entity_type": "virtual_machine", "entity_id": "v"}, {"entity_type": "physical_device", "entity_id": "d"}]
            )
        ) == {
            ("virtual_machine", "v"),
            ("physical_device", "d"),
        }
        assert affected_objects(self._finding(devices=[{"entity_id": "d1"}, {"entity_id": "d2"}])) == {
            ("physical_device", "d1"),
            ("physical_device", "d2"),
        }

    @pytest.mark.parametrize("details", [{}, {"holders": []}, {"holders": "мусор"}, {"holders": [{"name": "без id"}, None]}])
    def test_without_usable_nested_objects_the_finding_itself_is_the_object(self, details):
        assert affected_objects(self._finding(**details)) == {("ip_address", "10.0.0.5")}
