"""Проверки согласованности и полноты данных: GET /api/v1/integrity/consistency (только чтение, без LLM).

Что защищают тесты: каждое правило находит дефект и НЕ срабатывает на законных случаях (порты одного устройства, участники одного
стека, внешние адреса ИС); фильтры, сводка и постраничная выдача; число запросов к БД не растёт с числом строк. Запуск:
pytest backend/tests/test_consistency_checks.py -v
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import pytest

from app.constants import OwnerType
from app.models import (
    Building,
    Container,
    DeviceCategory,
    DeviceInterface,
    DeviceModel,
    DeviceStack,
    DeviceStackMember,
    DeviceSubinterface,
    DeviceType,
    InformationSystem,
    InformationSystemSource,
    IPAddress,
    Manufacturer,
    PhysicalDevice,
    Rack,
    Room,
    VirtualMachine,
    VLAN,
)
from app.services.consistency import RULES, run_checks
from app.services.consistency.engine import rule
from app.services.consistency.model import Category, Severity

URL = "/api/v1/integrity/consistency"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _save(session, *objects):
    session.add_all(objects)
    session.commit()
    return objects[0] if len(objects) == 1 else objects


def _device(session, **fields) -> PhysicalDevice:
    """Устройство с полным паспортом (производитель, модель, встроенная ОС не нужна — ОС задаётся отдельно), если не сказано иное."""
    category = _save(session, DeviceCategory(name=f"cat-{_uid()}"))
    kind = _save(session, DeviceType(name=f"type-{_uid()}", category_id=category.id))
    maker = _save(session, Manufacturer(name=f"maker-{_uid()}"))
    model = _save(session, DeviceModel(manufacturer_id=maker.id, device_type_id=kind.id, model=f"m-{_uid()}"))
    values = {"device_type_id": kind.id, "manufacturer_id": maker.id, "model_id": model.id, "serial_number": f"SN-{_uid()}"}
    values.update(fields)
    return _save(session, PhysicalDevice(**values))


def _port(session, device, name="Gi0/1", **fields) -> DeviceInterface:
    return _save(session, DeviceInterface(physical_device_id=device.id, name=name, **fields))


def _ip(session, owner_type, owner_id, address, **fields) -> IPAddress:
    return _save(session, IPAddress(owner_type=owner_type, owner_id=owner_id, ip_address=address, **fields))


def _findings(client, **params) -> list[dict]:
    response = client.get(URL, params={"limit": 5000, **params})
    assert response.status_code == 200, response.text
    return response.json()["findings"]


def _of_rule(client, code: str) -> list[dict]:
    return _findings(client, rule=code)


def test_empty_registry_has_no_findings(client):
    body = client.get(URL).json()
    assert body["ok"] is True and body["total"] == 0 and body["findings"] == []


class TestAddressing:
    def test_same_ip_on_two_devices_is_reported_once_with_both_holders(self, client, db_session):
        first = _device(db_session, system_name="srv-1")
        second = _device(db_session, system_name="srv-2")
        _ip(db_session, OwnerType.DEVICE_INTERFACE, _port(db_session, first).id, "10.0.0.5")
        _ip(db_session, OwnerType.DEVICE_INTERFACE, _port(db_session, second).id, "10.0.0.5")

        (found,) = _of_rule(client, "duplicate_ip")

        assert found["entity_id"] == "10.0.0.5" and found["severity"] == "warning"
        assert {holder["name"] for holder in found["details"]["holders"]} == {"srv-1", "srv-2"}

    def test_ip_on_two_ports_of_one_device_is_not_a_duplicate(self, client, db_session):
        device = _device(db_session, system_name="srv-1")
        for name in ("Gi0/1", "Gi0/2"):
            _ip(db_session, OwnerType.DEVICE_INTERFACE, _port(db_session, device, name).id, "10.0.0.5")

        assert _of_rule(client, "duplicate_ip") == []

    def test_ip_shared_by_stack_members_is_not_a_duplicate(self, client, db_session):
        stack = _save(db_session, DeviceStack(name=f"stack-{_uid()}"))
        for position in (1, 2):
            member = _device(db_session, system_name=f"sw-{position}")
            _save(db_session, DeviceStackMember(stack_id=stack.id, physical_device_id=member.id, position=position))
            _ip(db_session, OwnerType.DEVICE_INTERFACE, _port(db_session, member).id, "10.0.0.2")

        assert _of_rule(client, "duplicate_ip") == []

    def test_vm_and_subinterface_addresses_are_compared_with_device_addresses(self, client, db_session):
        device = _device(db_session, system_name="fw-1")
        vlan = _save(db_session, VLAN(vlan_id=10, name="v10"))
        sub = _save(db_session, DeviceSubinterface(parent_interface_id=_port(db_session, device).id, name="Gi0/1.10", vlan_id=vlan.id))
        vm = _save(db_session, VirtualMachine(name="vm-1"))
        _ip(db_session, OwnerType.DEVICE_SUBINTERFACE, sub.id, "172.16.0.1")
        _ip(db_session, OwnerType.VIRTUAL_MACHINE, vm.id, "172.16.0.1")

        (found,) = _of_rule(client, "duplicate_ip")

        assert {holder["name"] for holder in found["details"]["holders"]} == {"fw-1", "vm-1"}

    def test_addresses_of_manual_is_sources_may_repeat(self, client, db_session):
        sources = []
        for number in (1, 2):
            system = _save(db_session, InformationSystem(name=f"ИС {number}"))
            sources.append(_save(db_session, InformationSystemSource(information_system_id=system.id, source_type="manual")))
        for source in sources:
            _ip(db_session, OwnerType.INFORMATION_SYSTEM_SOURCE, source.id, "203.0.113.7")

        assert _of_rule(client, "duplicate_ip") == []

    def test_address_with_mask_is_an_invalid_ip(self, client, db_session):
        vm = _save(db_session, VirtualMachine(name="vm-1"))
        _ip(db_session, OwnerType.VIRTUAL_MACHINE, vm.id, "192.168.1.10/24")
        _ip(db_session, OwnerType.VIRTUAL_MACHINE, vm.id, "192.168.1.11")

        (found,) = _of_rule(client, "invalid_ip")

        assert found["severity"] == "error" and found["entity_name"] == "vm-1" and found["details"]["ip_address"] == "192.168.1.10/24"

    def test_same_system_name_in_different_case_is_reported_but_not_inside_a_stack(self, client, db_session):
        _device(db_session, system_name="SW-Core")
        _device(db_session, system_name=" sw-core ")
        stack = _save(db_session, DeviceStack(name=f"stack-{_uid()}"))
        for position in (1, 2):
            member = _device(db_session, system_name="sw-stack")
            _save(db_session, DeviceStackMember(stack_id=stack.id, physical_device_id=member.id, position=position))

        (found,) = _of_rule(client, "duplicate_system_name")

        assert found["entity_name"].strip().casefold() == "sw-core" and len(found["details"]["devices"]) == 2


class TestInventory:
    def test_room_in_another_building_and_rack_in_another_room_are_errors(self, client, db_session):
        main, annex = _save(db_session, Building(name="Главное"), Building(name="Пристройка"))
        hall, lab = _save(db_session, Room(building_id=main.id, name="Зал"), Room(building_id=main.id, name="Лаборатория"))
        rack = _save(db_session, Rack(room_id=lab.id, name="R1"))
        wrong_building = _device(db_session, system_name="a", building_id=annex.id, room_id=hall.id)
        wrong_room = _device(db_session, system_name="b", building_id=main.id, room_id=hall.id, rack_id=rack.id)
        _device(db_session, system_name="ok", building_id=main.id, room_id=lab.id, rack_id=rack.id)

        found = {item["entity_id"]: item for item in _of_rule(client, "device_location_mismatch")}

        assert set(found) == {wrong_building.id, wrong_room.id}
        assert found[wrong_building.id]["severity"] == "error"

    def test_location_is_taken_from_the_rack_when_the_device_has_none(self, client, db_session):
        building = _save(db_session, Building(name="Главное"))
        room = _save(db_session, Room(building_id=building.id, name="Серверная"))
        rack = _save(db_session, Rack(room_id=room.id, name="R1"))
        _device(db_session, system_name="in-rack", rack_id=rack.id)
        bare = _device(db_session, system_name="bare")
        half = _device(db_session, system_name="half", building_id=building.id)

        found = {item["entity_id"]: item for item in _of_rule(client, "device_location_incomplete")}

        assert set(found) == {bare.id, half.id}
        assert found[bare.id]["details"]["missing"] == ["здание", "помещение"]
        assert found[half.id]["details"]["missing"] == ["помещение"]

    def test_identity_needs_maker_model_and_an_operating_system(self, client, db_session):
        complete = _device(db_session, system_name="complete", embedded_os_id=None)
        bare = _save(db_session, PhysicalDevice(device_type_id=complete.device_type_id, serial_number=f"SN-{_uid()}"))

        found = _of_rule(client, "device_identity_incomplete")

        by_id = {item["entity_id"]: item["details"]["missing"] for item in found}
        assert by_id[bare.id] == ["производитель", "модель", "операционная система"]
        assert by_id[complete.id] == ["операционная система"]

    def test_managed_device_needs_a_management_address_unless_its_stack_has_one(self, client, db_session):
        naked = _device(db_session, system_name="naked")
        _device(db_session, serial_number="unmanaged-serial")  # без системного имени — не управляемое
        managed = _device(db_session, system_name="managed")
        _ip(db_session, OwnerType.DEVICE_INTERFACE, _port(db_session, managed).id, "10.0.0.9", is_management=True)
        stack = _save(db_session, DeviceStack(name=f"stack-{_uid()}"))
        head, tail = _device(db_session, system_name="stack-head"), _device(db_session, system_name="stack-tail")
        for position, member in enumerate((head, tail), 1):
            _save(db_session, DeviceStackMember(stack_id=stack.id, physical_device_id=member.id, position=position))
        _ip(db_session, OwnerType.DEVICE_INTERFACE, _port(db_session, head).id, "10.0.0.10", is_management=True)

        found = _of_rule(client, "managed_device_without_mgmt_ip")

        assert [item["entity_id"] for item in found] == [naked.id]


class TestVirtualization:
    def test_vm_without_host_and_incomplete_card(self, client, db_session):
        host = _device(db_session, system_name="esxi-1")
        orphan = _save(db_session, VirtualMachine(name="orphan"))
        full = _save(db_session, VirtualMachine(name="full", physical_device_id=host.id, purpose="АРМ"))
        _ip(db_session, OwnerType.VIRTUAL_MACHINE, full.id, "10.1.1.1")

        assert [item["entity_id"] for item in _of_rule(client, "vm_without_host")] == [orphan.id]
        incomplete = {item["entity_id"]: item["details"]["missing"] for item in _of_rule(client, "vm_incomplete")}
        assert incomplete[orphan.id] == ["операционная система", "назначение", "IP-адрес"]
        assert incomplete[full.id] == ["операционная система"]

    def test_container_needs_a_vm_or_a_device(self, client, db_session):
        vm = _save(db_session, VirtualMachine(name="vm-1"))
        lost = _save(db_session, Container(name="lost"))
        _save(db_session, Container(name="placed", virtual_machine_id=vm.id))

        assert [item["entity_id"] for item in _of_rule(client, "container_without_host")] == [lost.id]


class TestInformationSystems:
    def test_placement_text_support_and_protocol_gaps(self, client, db_session):
        bare = _save(db_session, InformationSystem(name="Пустая ИС", description="  "))
        placed = _save(
            db_session, InformationSystem(name="Размещённая", description="d", purpose="p", localization="l", process_description="x")
        )
        _save(db_session, InformationSystemSource(information_system_id=placed.id, source_type="manual"))

        assert [item["entity_id"] for item in _of_rule(client, "is_without_placement")] == [bare.id]
        (text,) = _of_rule(client, "is_text_incomplete")
        assert text["entity_id"] == bare.id and len(text["details"]["missing"]) == 4  # пробелы вместо описания тоже пусто
        assert {item["entity_id"] for item in _of_rule(client, "is_without_support")} == {bare.id, placed.id}
        assert {item["entity_id"] for item in _of_rule(client, "is_without_protocols")} == {bare.id, placed.id}

    def test_crypto_flag_and_chosen_means_must_agree(self, client, db_session):
        from app.models import CryptoProtectionMeans

        means = _save(db_session, CryptoProtectionMeans(name=f"СКЗИ-{_uid()}"))
        flag_only = _save(db_session, InformationSystem(name="Флаг без средства", crypto_protection_enabled=True))
        means_only = _save(db_session, InformationSystem(name="Средство без флага", crypto_protection_description_id=means.id))
        _save(db_session, InformationSystem(name="Согласовано", crypto_protection_enabled=True, crypto_protection_description_id=means.id))

        found = {item["entity_id"]: item["severity"] for item in _of_rule(client, "is_crypto_mismatch")}

        assert found == {flag_only.id: "error", means_only.id: "warning"}

    def test_external_interaction_requires_crypto(self, client, db_session):
        exposed = _save(db_session, InformationSystem(name="Открытая"))
        protected = _save(db_session, InformationSystem(name="Защищённая", crypto_protection_enabled=True))
        internal = _save(db_session, InformationSystem(name="Внутренняя"))
        for system in (exposed, protected):
            _save(db_session, InformationSystemSource(information_system_id=system.id, source_type="manual", external_interaction=True))
        _save(db_session, InformationSystemSource(information_system_id=internal.id, source_type="manual"))

        assert [item["entity_id"] for item in _of_rule(client, "is_external_without_crypto")] == [exposed.id]


class TestApi:
    @pytest.fixture()
    def mixed(self, db_session):
        _save(db_session, InformationSystem(name="ИС", crypto_protection_enabled=True))  # ошибка + предупреждения + info
        _save(db_session, VirtualMachine(name="vm-1"))

    def test_filters_narrow_findings_by_category_severity_and_sheet(self, client, mixed):
        everything = _findings(client)
        assert {item["category"] for item in everything} == {"consistency", "completeness"}

        errors = _findings(client, severity="error")
        assert errors and all(item["severity"] == "error" for item in errors)
        sheet4 = _findings(client, sheet=4)
        assert sheet4 and all(item["sheet"] == 4 for item in sheet4)
        consistency = _findings(client, category="consistency")
        assert consistency and all(item["category"] == "consistency" for item in consistency)

    def test_results_are_sorted_with_errors_first(self, client, mixed):
        order = {"error": 0, "warning": 1, "info": 2}
        severities = [order[item["severity"]] for item in _findings(client)]
        assert severities == sorted(severities)

    def test_summary_counts_the_whole_selection_and_pages_are_cut(self, client, mixed):
        full = client.get(URL, params={"limit": 5000}).json()
        page = client.get(URL, params={"limit": 2, "offset": 1}).json()

        assert page["total"] == full["total"] and page["summary"] == full["summary"]
        assert page["returned"] == 2 and page["truncated"] is True
        assert page["findings"] == full["findings"][1:3]
        assert sum(full["summary"]["by_severity"].values()) == full["total"]

    @pytest.mark.parametrize("params", [{"rule": "no_such_rule"}, {"sheet": 9}, {"severity": "fatal"}, {"category": "x"}, {"limit": 0}])
    def test_bad_filters_are_rejected_with_422(self, client, params):
        assert client.get(URL, params=params).status_code == 422

    def test_rule_catalog_lists_every_registered_rule(self, client):
        catalog = client.get(f"{URL}/rules").json()["rules"]

        assert {item["code"] for item in catalog} == set(RULES)
        assert all(item["title"] and item["severity"] in {"error", "warning", "info"} for item in catalog)


def test_registering_a_rule_code_twice_fails_loudly():
    with pytest.raises(ValueError, match="уже зарегистрировано"):

        @rule("invalid_ip", "дубль", Severity.INFO, Category.CONSISTENCY)
        def duplicate(session, spec):  # pragma: no cover - регистрация падает до вызова
            return []


def test_a_crashing_rule_fails_the_whole_run_instead_of_looking_like_a_clean_registry(db_session, monkeypatch):
    def boom(session, spec):
        raise RuntimeError("сломанное правило")

    monkeypatch.setitem(RULES, "invalid_ip", replace(RULES["invalid_ip"], check=boom))

    with pytest.raises(RuntimeError, match="сломанное правило"):
        run_checks(db_session, rules=["invalid_ip"])


def test_number_of_queries_does_not_grow_with_the_number_of_rows(db_session, sql_log):
    def populate(count: int) -> None:
        for _ in range(count):
            device = _device(db_session, system_name=f"srv-{_uid()}")
            _ip(db_session, OwnerType.DEVICE_INTERFACE, _port(db_session, device).id, "10.9.9.9")
            _save(db_session, InformationSystem(name=f"ИС {_uid()}"), VirtualMachine(name=f"vm-{_uid()}"))

    def measure() -> int:
        before = len(sql_log)
        run_checks(db_session)
        return len(sql_log) - before

    populate(3)
    small = measure()
    populate(30)
    large = measure()

    assert large == small
