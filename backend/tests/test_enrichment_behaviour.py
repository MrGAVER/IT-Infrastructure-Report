"""Обогащение записей (services/serialization.py) и строки листа «Перечень ИС» (reporting._is_row_values).

Фиксирует вычисляемые поля до и после разбора самых сложных функций проекта на шаги (код-ревью, П-8: enrich_devices,
enrich_connections, загрузка и сборка ИС, _is_row_values — по 32–44 по radon). Ожидания сняты с прежнего кода на наборе
tests/report_seed.py; тесты проходят и на коде до рефакторинга, и после него. Проверяются только вычисляемые поля:
столбцы самих записей добавляются часто, и привязывать к ним этот тест незачем.
Запуск: pytest backend/tests/test_enrichment_behaviour.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_seed import seed_registry  # noqa: E402

from app import reporting  # noqa: E402
from app.models import Connection, DeviceInterface, DeviceStack, DeviceStackMember, EmbeddedOperatingSystem, InformationSystem, PhysicalDevice  # noqa: E402
from app.services.serialization import enrich_connections, enrich_devices, enrich_information_systems, enrich_interfaces  # noqa: E402

DEVICE_FIELDS = (
    "management_interface",
    "management_ips",
    "interface_count",
    "embedded_os_name",
    "embedded_os_version",
    "vlan_summary",
    "stack_id",
    "stack_name",
    "stack_position",
)
CONNECTION_FIELDS = (
    "source_device_name",
    "source_interface_name",
    "destination_device_name",
    "destination_interface_name",
    "connection_type_name",
    "source_port_role",
    "destination_port_role",
    "source_vlan_mode",
    "destination_vlan_mode",
    "source_vlans",
    "destination_vlans",
    "port_config_diff",
    "port_config_status",
)
SYSTEM_FIELDS = (
    "support_organization_name",
    "support_method_name",
    "placement_assets_summary",
    "departments_summary",
    "ip_addresses",
    "ip_addresses_summary",
    "protocols_summary",
    "physical_devices_summary",
    "vms_summary",
    "containers_summary",
)


@pytest.fixture()
def registry(db_session):
    seed_registry(db_session)
    db_session.add(DeviceStack(id="stk1", name="Стек SW"))
    db_session.flush()
    db_session.add_all(
        [
            DeviceStackMember(id="stm1", stack_id="stk1", physical_device_id="sw1", position=1),
            DeviceStackMember(id="stm2", stack_id="stk1", physical_device_id="sw2", position=2),
        ]
    )
    db_session.get(EmbeddedOperatingSystem, "eos1").version = "17.9"
    alpha = db_session.get(InformationSystem, "is1")
    alpha.crypto_protection_enabled, alpha.crypto_protection_description_id, alpha.siem_enabled = True, "cp1", True
    alpha.process_description, alpha.localization, alpha.purpose, alpha.description = "Процесс", "Серверная", "Назначение", "Описание"
    db_session.commit()
    return db_session


def _picked(rows: list[dict], fields: tuple[str, ...]) -> dict[str, dict]:
    return {row["id"]: {field: row[field] for field in fields} for row in rows}


def _all(session, model):
    return session.scalars(select(model).order_by(model.id)).all()


NO_STACK = {"stack_id": None, "stack_name": None, "stack_position": None}
EMPTY_DEVICE = {"management_interface": "", "management_ips": "", "embedded_os_name": "", "embedded_os_version": "", "vlan_summary": "", **NO_STACK}


class TestEnrichDevices:
    def test_computed_fields_of_every_device(self, registry):
        result = _picked(enrich_devices(_all(registry, PhysicalDevice), registry), DEVICE_FIELDS)
        assert result == {
            "rt1": {**EMPTY_DEVICE, "interface_count": 1},
            "srv0": {**EMPTY_DEVICE, "interface_count": 0},
            # порт управления без IP: порт перечисляется, адресов нет
            "srv1": {**EMPTY_DEVICE, "interface_count": 1, "management_interface": "Te0/0"},
            # управление на порту, на подинтерфейсе порта и на VLAN управления устройства; адреса — по возрастанию
            "sw1": {
                "management_interface": "Gi1/0/1; Gi1/0/1 (подинтерфейс Gi1/0/1.99); VLAN 20 — Управление",
                "management_ips": "192.168.1.1/24; 192.168.1.2/24; 172.16.99.1/24; 192.168.20.1/24",
                "interface_count": 6,
                "embedded_os_name": "IOS XE",
                "embedded_os_version": "17.9",
                "vlan_summary": "10 Данные; 20 Управление",
                "stack_id": "stk1",
                "stack_name": "Стек SW",
                "stack_position": 1,
            },
            "sw2": {**EMPTY_DEVICE, "interface_count": 3, "stack_id": "stk1", "stack_name": "Стек SW", "stack_position": 2},
        }

    def test_empty_input_runs_no_queries(self, registry, sql_log):
        assert enrich_devices([], registry) == []
        assert enrich_connections([], registry) == []
        assert enrich_interfaces([], registry) == []
        assert enrich_information_systems([], registry) == []
        assert sql_log == []


class TestEnrichInterfaces:
    def test_ip_fields_and_management_ips(self, registry):
        rows = {r["id"]: r for r in enrich_interfaces(_all(registry, DeviceInterface), registry)}
        assert rows["p1"]["ip_addresses"] == "192.168.1.1/24; 192.168.1.2/24"
        assert rows["p1"]["management_ips"] == "192.168.1.1/24; 192.168.1.2/24"  # порт управления
        assert rows["q2"]["ip_addresses"] == "10.0.0.2/24" and rows["q2"]["management_ips"] == ""  # не порт управления
        assert rows["p4"]["ip_addresses"] == "" and rows["p4"]["management_ips"] == ""


class TestEnrichConnections:
    def test_computed_fields_of_every_connection(self, registry):
        result = _picked(enrich_connections(_all(registry, Connection), registry), CONNECTION_FIELDS)
        assert result["c1"] == {
            "source_device_name": "SW-1",
            "source_interface_name": "Gi1/0/1",
            "destination_device_name": "SW-2",
            "destination_interface_name": "Gi0/1",
            "connection_type_name": "Витая пара",
            "source_port_role": "management_data",
            "destination_port_role": "data",
            "source_vlan_mode": "trunk",
            "destination_vlan_mode": "access",
            "source_vlans": [10, 20],
            "destination_vlans": [20],
            "port_config_diff": ["role", "mode", "vlans"],
            "port_config_status": "mismatch",
        }
        # устройство без системного имени подписывается серийным номером; у порта «Все VLAN» набор — все VLAN устройства
        assert result["c2"]["destination_device_name"] == "SN-RT1" and result["c2"]["source_vlans"] == [10, 20, 30]
        assert result["c2"]["port_config_diff"] == ["vlans"] and result["c2"]["port_config_status"] == "mismatch"
        # неактивное подключение расхождением не считается
        assert result["c3"]["port_config_diff"] == [] and result["c3"]["port_config_status"] == "ok"
        assert result["c3"]["destination_port_role"] == "management" and result["c3"]["destination_vlans"] == []

    def test_raw_approval_signature_is_not_exposed(self, registry):
        assert all("port_config_approved_signature" not in row for row in enrich_connections(_all(registry, Connection), registry))


class TestEnrichInformationSystems:
    def test_every_source_kind_contributes_to_the_summaries(self, registry):
        result = _picked(enrich_information_systems(_all(registry, InformationSystem), registry), SYSTEM_FIELDS)
        assert result["is1"] == {
            "support_organization_name": "Интегратор",
            "support_method_name": "Удалённо",
            "placement_assets_summary": "ЦОД",
            "departments_summary": "Бухгалтерия",
            # адреса ручных источников, затем адреса ВМ (с префиксом); повторный источник-устройство учтён один раз
            "ip_addresses": ["10.9.9.9", "10.1.1.10/24", "10.1.1.20/24"],
            "ip_addresses_summary": "10.9.9.9; 10.1.1.10/24; 10.1.1.20/24",
            "protocols_summary": "HTTPS/443",
            "physical_devices_summary": "SW-1",
            "vms_summary": "app-vm",
            "containers_summary": "db",
        }
        assert result["is2"]["containers_summary"] == "web" and result["is2"]["physical_devices_summary"] == ""
        assert result["is3"]["vms_summary"] == "orphan-vm"
        assert result["is7"]["vms_summary"] == "edge-vm"

    def test_system_without_links_has_empty_summaries(self, registry):
        empty = _picked(enrich_information_systems(_all(registry, InformationSystem), registry), SYSTEM_FIELDS)["is4"]
        assert empty == {field: ([] if field == "ip_addresses" else "") for field in SYSTEM_FIELDS}

    def test_result_does_not_depend_on_which_systems_are_on_the_page(self, registry):
        everything = {row["id"]: row for row in enrich_information_systems(_all(registry, InformationSystem), registry)}
        alone = enrich_information_systems([registry.get(InformationSystem, "is1")], registry)
        assert alone == [everything["is1"]]


class TestIsRowValues:
    @pytest.fixture()
    def rows(self, registry):
        data = reporting._load_report_data(registry, None)
        return {obj.id: reporting._is_row_values(obj, data) for obj in data.systems}

    def test_fully_filled_row(self, rows):
        assert rows["is1"] == [
            "ИС Альфа",
            "Описание",
            "Назначение",
            "Бухгалтерия",
            "Серверная",
            "SW-1; VM: app-vm; Контейнер: db; ЦОД",
            "HTTPS/443",
            "10.9.9.9; 10.1.1.10/24; 10.1.1.20/24",
            "Да; КриптоПро",
            "Да",
            "Интегратор",
            "Удалённо",
            "Процесс",
            # устройство ИС и хост её ВМ; IP управления — адреса порта и подинтерфейса управления SW-1
            "SW-1; SRV-1",
            "192.168.1.1/24; 192.168.1.2/24; 172.16.99.1/24",
            "app-vm; db",
            "10.1.1.10/24; 10.1.1.20/24",
        ]

    def test_container_vm_without_host_and_vm_on_a_device(self, rows):
        assert rows["is2"][5] == "Контейнер: web" and rows["is2"][15] == "web"
        assert rows["is3"][5] == "VM: orphan-vm" and rows["is3"][13] == ""  # ВМ без хоста: физических устройств нет
        assert rows["is7"][5] == "VM: edge-vm" and rows["is7"][13] == "SN-RT1"  # хост без системного имени — серийный номер

    def test_system_without_sources_is_all_defaults(self, rows):
        assert rows["is4"] == ["ИС Дельта", "", "", "", "", "", "", "", "Нет", "Нет", "", "", "", "", "", "", ""]

    def test_every_row_has_the_seventeen_columns_of_the_sheet(self, rows):
        assert len(rows) == 7 and {len(row) for row in rows.values()} == {17}
