"""
A-06 (код-ревью main @ b375f58): ветки validation.py, которые не вызывал ни один тест — проверки согласованности связей, которые API выполняет до записи.

Тикет называл «ранние 422-ветки validate_connection»; после тестов A-01 они покрыты (test_connection_invariants.py,
test_interface_connections.py), поэтому здесь — оставшиеся непокрытые проверки: модель устройства, встроенная ОС, ОС, хост ВМ, гипервизор,
иерархия «здание → помещение → стойка», способ
техподдержки и организация. Каждая ветка проверяется по тексту ответа 422: пользователь видит именно его.

Запуск: pytest backend/tests/test_validation_branches.py -v
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models import (
    Building,
    DeviceCategory,
    DeviceModel,
    DeviceType,
    EmbeddedOperatingSystem,
    Manufacturer,
    OperatingSystem,
    OperatingSystemCategory,
    PhysicalDevice,
    Rack,
    Room,
    SupportMethod,
    SupportOrganization,
)
from app.services.validation import (
    validate_device_location_hierarchy,
    validate_device_model_relation,
    validate_embedded_os,
    validate_hypervisor,
    validate_operating_system,
    validate_support_method_organization,
    validate_vm_host,
)


def _rejected(check, *args) -> str:
    with pytest.raises(HTTPException) as caught:
        check(*args)
    assert caught.value.status_code == 422
    return str(caught.value.detail)


def _add(session, *objects):
    session.add_all(objects)
    session.flush()
    return objects if len(objects) > 1 else objects[0]


@pytest.fixture()
def catalog(db_session):
    """Два производителя и два типа устройств; модель Cisco относится к типу «Коммутатор»."""
    category = _add(db_session, DeviceCategory(name="Оборудование"))
    switch, server = _add(
        db_session, DeviceType(name="Коммутатор", category_id=category.id), DeviceType(name="Сервер", category_id=category.id, allows_vm_hosting=True)
    )
    cisco, dell = _add(db_session, Manufacturer(name="Cisco"), Manufacturer(name="Dell"))
    model = _add(db_session, DeviceModel(manufacturer_id=cisco.id, device_type_id=switch.id, model="C9300"))
    return {"switch": switch, "server": server, "cisco": cisco, "dell": dell, "model": model}


class TestDeviceModelRelation:
    def test_unknown_model_is_rejected(self, db_session):
        assert _rejected(validate_device_model_relation, {"model_id": "no-such-model"}, db_session) == "Выбранная модель устройства не найдена"

    def test_model_of_another_manufacturer_is_rejected(self, db_session, catalog):
        data = {"model_id": catalog["model"].id, "manufacturer_id": catalog["dell"].id}

        assert _rejected(validate_device_model_relation, data, db_session) == "Выбранная модель не принадлежит указанному производителю"

    def test_model_of_another_device_type_is_rejected(self, db_session, catalog):
        data = {"model_id": catalog["model"].id, "device_type_id": catalog["server"].id}

        assert _rejected(validate_device_model_relation, data, db_session) == "Выбранная модель не соответствует выбранному типу устройства"

    def test_matching_model_passes(self, db_session, catalog):
        validate_device_model_relation(
            {"model_id": catalog["model"].id, "manufacturer_id": catalog["cisco"].id, "device_type_id": catalog["switch"].id}, db_session
        )

    def test_model_without_manufacturer_and_type_in_the_request_passes(self, db_session, catalog):
        validate_device_model_relation({"model_id": catalog["model"].id}, db_session)

    def test_missing_fields_are_taken_from_the_device_being_edited(self, db_session, catalog):
        """При правке устройства производитель и тип, которых нет в запросе, берутся из самого устройства: модель другого производителя отвергается и тогда."""
        device = _add(db_session, PhysicalDevice(device_type_id=catalog["switch"].id, manufacturer_id=catalog["dell"].id, serial_number="SN-1"))

        message = _rejected(validate_device_model_relation, {"model_id": catalog["model"].id}, db_session, device.id)

        assert message == "Выбранная модель не принадлежит указанному производителю"

    def test_request_values_win_over_the_edited_device(self, db_session, catalog):
        device = _add(db_session, PhysicalDevice(device_type_id=catalog["server"].id, manufacturer_id=catalog["dell"].id, serial_number="SN-2"))
        data = {"model_id": catalog["model"].id, "manufacturer_id": catalog["cisco"].id, "device_type_id": catalog["switch"].id}

        validate_device_model_relation(data, db_session, device.id)  # в запросе — Cisco и коммутатор, как у модели, хотя устройство сейчас Dell-сервер

    def test_unknown_edited_device_is_ignored(self, db_session, catalog):
        validate_device_model_relation({"model_id": catalog["model"].id}, db_session, "no-such-device")


class TestOperatingSystems:
    def test_unknown_embedded_os_is_rejected(self, db_session):
        assert _rejected(validate_embedded_os, {"embedded_os_id": "x"}, db_session) == "Выбранная встроенная ОС не найдена"

    def test_known_or_missing_embedded_os_passes(self, db_session):
        known = _add(db_session, EmbeddedOperatingSystem(name="IOS XE"))

        validate_embedded_os({"embedded_os_id": known.id}, db_session)
        validate_embedded_os({}, db_session)

    def test_unknown_operating_system_is_rejected(self, db_session):
        assert _rejected(validate_operating_system, {"operating_system_id": "x"}, db_session) == "Выбранная ОС не найдена"

    def test_known_or_missing_operating_system_passes(self, db_session):
        category = _add(db_session, OperatingSystemCategory(name="Серверные"))
        known = _add(db_session, OperatingSystem(category_id=category.id, name="Debian"))

        validate_operating_system({"operating_system_id": known.id}, db_session)
        validate_operating_system({}, db_session)


class TestVmHostAndHypervisor:
    def test_vm_host_is_optional(self, db_session):
        validate_vm_host({}, db_session)
        validate_vm_host({"physical_device_id": None}, db_session)

    def test_unknown_host_is_rejected(self, db_session):
        assert _rejected(validate_vm_host, {"physical_device_id": "x"}, db_session) == "Выбранное физическое устройство не найдено"

    def test_device_of_a_type_that_cannot_host_vms_is_rejected(self, db_session, catalog):
        switch = _add(db_session, PhysicalDevice(device_type_id=catalog["switch"].id, serial_number="SN-SW"))

        message = _rejected(validate_vm_host, {"physical_device_id": switch.id}, db_session)

        assert message == "Для размещения виртуальной машины можно выбрать только сервер или систему хранения"

    def test_server_can_host_vms(self, db_session, catalog):
        server = _add(db_session, PhysicalDevice(device_type_id=catalog["server"].id, serial_number="SN-SRV"))

        validate_vm_host({"physical_device_id": server.id}, db_session)

    def test_hypervisor_is_optional(self, db_session):
        validate_hypervisor({}, db_session)

    def test_unknown_hypervisor_is_rejected(self, db_session):
        assert _rejected(validate_hypervisor, {"hypervisor_os_id": "x"}, db_session) == "Выбранный гипервизор не найден"

    def test_os_outside_the_hypervisor_category_is_rejected(self, db_session):
        category = _add(db_session, OperatingSystemCategory(name="Серверные", is_hypervisor=False))
        debian = _add(db_session, OperatingSystem(category_id=category.id, name="Debian"))

        message = _rejected(validate_hypervisor, {"hypervisor_os_id": debian.id}, db_session)

        assert message == "В поле гипервизора можно выбрать только ОС из категории «Гипервизор»"

    def test_os_of_the_hypervisor_category_passes(self, db_session):
        category = _add(db_session, OperatingSystemCategory(name="Гипервизор", is_hypervisor=True))
        esxi = _add(db_session, OperatingSystem(category_id=category.id, name="ESXi"))

        validate_hypervisor({"hypervisor_os_id": esxi.id}, db_session)


class TestLocationHierarchy:
    @pytest.fixture()
    def places(self, db_session):
        main, annex = _add(db_session, Building(name="Главное здание"), Building(name="Пристройка"))
        hall, lab = _add(db_session, Room(building_id=main.id, name="Машзал"), Room(building_id=annex.id, name="Лаборатория"))
        rack = _add(db_session, Rack(room_id=hall.id, name="R1"))
        return {"main": main, "annex": annex, "hall": hall, "lab": lab, "rack": rack}

    def test_consistent_location_passes(self, db_session, places):
        validate_device_location_hierarchy({"building_id": places["main"].id, "room_id": places["hall"].id, "rack_id": places["rack"].id}, db_session)

    def test_empty_location_passes(self, db_session):
        validate_device_location_hierarchy({}, db_session)

    @pytest.mark.parametrize(
        ("build", "message"),
        [
            (lambda p: {"room_id": "no-room"}, "Выбранное помещение не найдено"),
            (lambda p: {"room_id": p["hall"].id, "rack_id": "no-rack"}, "Выбранная стойка не найдена"),
            (lambda p: {"building_id": p["annex"].id, "room_id": p["hall"].id}, "Выбранное помещение не принадлежит выбранному зданию"),
            (lambda p: {"rack_id": p["rack"].id}, "Для выбора стойки необходимо сначала выбрать помещение"),
            (lambda p: {"room_id": p["lab"].id, "rack_id": p["rack"].id}, "Выбранная стойка не принадлежит выбранному помещению"),
        ],
        ids=["unknown-room", "unknown-rack", "room-in-other-building", "rack-without-room", "rack-in-other-room"],
    )
    def test_inconsistent_location_is_rejected_with_a_readable_message(self, db_session, places, build, message):
        assert _rejected(validate_device_location_hierarchy, build(places), db_session) == message


class TestSupportMethodOrganization:
    @pytest.fixture()
    def support(self, db_session):
        mine, other = _add(db_session, SupportOrganization(name="Своя организация"), SupportOrganization(name="Чужая организация"))
        universal, bound = _add(db_session, SupportMethod(name="Телефон"), SupportMethod(name="Выезд", support_organization_id=mine.id))
        return {"mine": mine, "other": other, "universal": universal, "bound": bound}

    def test_method_is_optional(self, db_session):
        validate_support_method_organization({}, db_session)

    def test_unknown_method_is_rejected(self, db_session):
        message = _rejected(validate_support_method_organization, {"support_method_id": "x"}, db_session)

        assert message == "Выбранный способ оказания техподдержки не найден"

    def test_method_bound_to_another_organization_is_rejected(self, db_session, support):
        data = {"support_method_id": support["bound"].id, "support_organization_id": support["other"].id}

        message = _rejected(validate_support_method_organization, data, db_session)

        assert message == "Выбранный способ оказания техподдержки принадлежит другой организации технической поддержки"

    def test_method_bound_to_an_organization_needs_that_organization_to_be_given(self, db_session, support):
        _rejected(validate_support_method_organization, {"support_method_id": support["bound"].id}, db_session)

    def test_bound_method_with_its_own_organization_passes(self, db_session, support):
        validate_support_method_organization({"support_method_id": support["bound"].id, "support_organization_id": support["mine"].id}, db_session)

    def test_universal_method_suits_any_organization_or_none(self, db_session, support):
        validate_support_method_organization({"support_method_id": support["universal"].id, "support_organization_id": support["other"].id}, db_session)
        validate_support_method_organization({"support_method_id": support["universal"].id}, db_session)
