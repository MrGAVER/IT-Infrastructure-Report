"""Строки листа «Организация подключений» — app/reporting.py: _connection_rows_by_device и _connection_row_values_list.

Фиксирует поведение до снижения сложности `_connection_rows_by_device` (код-ревью, п. 10; сложность 26) — «золотая»
таблица всех строк на наборе данных tests/report_seed.py, проверенная глазами на соответствие шапке листа, плюс
правила, которые из неё следуют: порядок и нумерация, группировка по устройству, склейка неподключённых портов с
одинаковой «подписью IP», порт с подинтерфейсами не склеивается, фильтр по структурным единицам оставляет соседа
вне выбора только как контекст. Тесты написаны на прежнем коде и проходят без правок после рефакторинга.

Колонки строки (после №): вид, серийный номер, системное имя и ОС устройства-владельца; порт; IP; открытые порты;
протоколы; VLAN ID; VLAN-имена; тип линии; назначение; вид, серийный, системное имя и ОС соседа; IP соседа.

Запуск: pytest backend/tests/test_report_connection_rows_behaviour.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_seed import seed_registry  # noqa: E402

from app.reporting import _connection_row_values_list, _connection_rows_by_device, _load_report_data  # noqa: E402

# Управление SW-1: IP его порта управления, подинтерфейса управления и VLAN управления — так выглядит IP соседа у всех его линий.
SW1_MGMT_IPS = "192.168.1.1/24; 192.168.1.2/24; 172.16.99.1/24; 192.168.20.1/24"

EXPECTED_ROWS = [
    ('rt1', [1, 'Маршрутизатор', 'SN-RT1', '-', '-', 'Gi0/0', 'не назначен', '-', '-', '10', 'Данные', 'Витая пара', 'Передача данных', 'Коммутатор', 'SN-SW1', 'SW-1', 'IOS XE', SW1_MGMT_IPS]),
    ('srv1', [2, 'Сервер', 'SN-SRV1', 'SRV-1', '-', 'eth0', 'не назначен', '-', '-', '-', '-', 'Витая пара', 'Управление активами', 'Коммутатор', 'SN-SW1', 'SW-1', 'IOS XE', SW1_MGMT_IPS]),
    ('sw1', [3, 'Коммутатор', 'SN-SW1', 'SW-1', 'IOS XE', 'Gi1/0/1 (подинтерфейсы: Gi1/0/1.99 [VLAN 20])', '192.168.1.1/24; 192.168.1.2/24; Gi1/0/1.99: 172.16.99.1/24', 'TCP/22; SSH', 'SSH', '10; 20', 'Данные; Управление', 'Витая пара', 'Управление активами, передача данных; Gi1/0/1.99: Управление активами', 'Коммутатор', 'SN-SW2', 'SW-2', '-', 'не назначен']),
    ('sw1', [4, 'Коммутатор', 'SN-SW1', 'SW-1', 'IOS XE', 'Gi1/0/2', 'не назначен', '-', '-', '10; 20; 30', 'Данные; Управление; Гости', 'Витая пара', 'Передача данных', 'Маршрутизатор', 'SN-RT1', '-', '-', 'не назначен']),
    ('sw1', [5, 'Коммутатор', 'SN-SW1', 'SW-1', 'IOS XE', 'Gi1/0/3', 'не назначен', '-', '-', '-', '-', 'Витая пара', 'Передача данных', 'Сервер', 'SN-SRV1', 'SRV-1', '-', 'не назначен']),
    ('sw1', [6, 'Коммутатор', 'SN-SW1', 'SW-1', 'IOS XE', 'Gi1/0/4; Gi1/0/6', 'не назначен', '-', '-', '-', '-', '-', 'Передача данных', '-', '-', '-', '-', '-']),
    ('sw1', [7, 'Коммутатор', 'SN-SW1', 'SW-1', 'IOS XE', 'Gi1/0/5 (подинтерфейсы: Gi1/0/5.10 [VLAN 10], Gi1/0/5.20 [VLAN 20])', 'Gi1/0/5.20: 172.16.0.1/30', 'Gi1/0/5.20: TCP/443; HTTPS', 'HTTPS', '10; 20', 'Данные; Управление', '-', 'Передача данных; Gi1/0/5.10: Передача данных; Gi1/0/5.20: Передача данных', '-', '-', '-', '-', '-']),
    ('sw2', [8, 'Коммутатор', 'SN-SW2', 'SW-2', '-', 'Gi0/1', 'не назначен', '-', '-', '20', 'Управление', 'Витая пара', 'Передача данных', 'Коммутатор', 'SN-SW1', 'SW-1', 'IOS XE', SW1_MGMT_IPS]),
    ('sw2', [9, 'Коммутатор', 'SN-SW2', 'SW-2', '-', 'Gi0/2; Gi0/3', '10.0.0.2/24', '-', '-', '-', '-', '-', 'Передача данных', '-', '-', '-', '-', '-']),
]

@pytest.fixture()
def registry(db_session):
    seed_registry(db_session)
    return db_session


@pytest.fixture()
def data(registry):
    return _load_report_data(registry, None)


@pytest.fixture()
def filtered_data(registry):
    return _load_report_data(registry, None, ["u-root"])


class TestAllRows:
    def test_every_row_matches_the_expected_table(self, data):
        assert _connection_rows_by_device(data) == EXPECTED_ROWS

    def test_rows_are_numbered_consecutively_from_one(self, data):
        assert [row[0] for _, row in _connection_rows_by_device(data)] == list(range(1, len(EXPECTED_ROWS) + 1))

    def test_rows_of_one_device_are_adjacent_and_devices_follow_the_device_list_order(self, data):
        owners = [device_id for device_id, _ in _connection_rows_by_device(data)]
        assert owners == ["rt1", "srv1", "sw1", "sw1", "sw1", "sw1", "sw1", "sw2", "sw2"]  # srv0 без портов — строк нет
        assert [d.id for d in data.devices] == ["rt1", "srv0", "srv1", "sw1", "sw2"]

    def test_no_cell_is_left_empty_and_widths_are_equal(self, data):
        for _, row in _connection_rows_by_device(data):
            assert len(row) == 18 and all(cell not in (None, "") for cell in row)

    def test_values_list_is_the_same_rows_without_device_ids(self, data):
        assert _connection_row_values_list(data) == [row for _, row in EXPECTED_ROWS]


class TestWhatGoesIntoARow:
    def test_connected_port_shows_both_ends_each_from_its_own_side(self, data):
        rows = {row[0]: row for _, row in _connection_rows_by_device(data)}
        own, neighbor = rows[3], rows[8]  # p1 ↔ q1: строка SW-1 и строка SW-2 по одному подключению
        assert (own[2], own[5][:7], own[14]) == ("SN-SW1", "Gi1/0/1", "SN-SW2")
        assert (neighbor[2], neighbor[5], neighbor[14]) == ("SN-SW2", "Gi0/1", "SN-SW1")

    def test_inactive_connection_is_listed_like_an_active_one(self, data):
        sw1_to_server = next(row for _, row in _connection_rows_by_device(data) if row[5] == "Gi1/0/3")
        assert sw1_to_server[11] == "Витая пара" and sw1_to_server[13] == "Сервер"

    def test_neighbor_ip_is_its_management_address_when_it_has_one_otherwise_its_port_address(self, data):
        rows = {row[5]: row for _, row in _connection_rows_by_device(data)}
        assert rows["Gi0/0"][17] == SW1_MGMT_IPS  # у соседа SW-1 есть адреса управления
        assert rows["Gi1/0/2"][17] == "не назначен"  # у соседа-маршрутизатора нет ни управления, ни адреса порта

    def test_unconnected_ports_with_the_same_ip_signature_share_one_row(self, data):
        unconnected = [row[5] for _, row in _connection_rows_by_device(data) if row[11] == "-"]  # без типа линии — порт не подключён
        assert unconnected == ["Gi1/0/4; Gi1/0/6", "Gi1/0/5 (подинтерфейсы: Gi1/0/5.10 [VLAN 10], Gi1/0/5.20 [VLAN 20])", "Gi0/2; Gi0/3"]

    def test_port_with_subinterfaces_is_never_merged_with_ports_that_have_the_same_ip_signature(self, data):
        ports = [row[5] for _, row in _connection_rows_by_device(data)]
        assert "Gi1/0/4; Gi1/0/6" in ports  # без IP
        assert any(p.startswith("Gi1/0/5 (подинтерфейсы") for p in ports)  # тоже без собственных IP, но отдельной строкой

    def test_all_vlans_port_lists_the_vlans_of_its_device_not_its_own_stale_links(self, data):
        row = next(row for _, row in _connection_rows_by_device(data) if row[5] == "Gi1/0/2")
        assert (row[9], row[10]) == ("10; 20; 30", "Данные; Управление; Гости")

    def test_subinterface_vlan_joins_the_port_vlans_once(self, data):
        row = next(row for _, row in _connection_rows_by_device(data) if row[5].startswith("Gi1/0/1 ("))
        assert row[9] == "10; 20"  # VLAN 20 порта и подинтерфейса — один раз

    def test_open_ports_of_the_legacy_device_owner_are_not_shown(self, data):
        # на SW-1 есть и устаревшая запись «открытый порт 80 у устройства целиком» — ни в одной строке портов SW-1 её нет
        sw1_rows = [row for device_id, row in _connection_rows_by_device(data) if device_id == "sw1"]
        assert not any("TCP/80" in row[7] or "HTTP" in row[8].split("; ") for row in sw1_rows)
        assert next(row for row in sw1_rows if row[5].startswith("Gi1/0/1 ("))[7:9] == ["TCP/22; SSH", "SSH"]


class TestStructuralUnitFilter:
    def test_only_devices_of_the_selected_units_get_rows_and_numbering_restarts(self, filtered_data):
        rows = _connection_rows_by_device(filtered_data)
        assert [device_id for device_id, _ in rows] == ["rt1", "sw1", "sw1", "sw1", "sw1", "sw1"]
        assert [row[0] for _, row in rows] == [1, 2, 3, 4, 5, 6]

    def test_rows_of_selected_devices_are_unchanged_apart_from_the_number(self, data, filtered_data):
        expected = [(device_id, row[1:]) for device_id, row in _connection_rows_by_device(data) if device_id in ("rt1", "sw1")]
        assert [(device_id, row[1:]) for device_id, row in _connection_rows_by_device(filtered_data)] == expected

    def test_neighbor_outside_the_selection_is_still_shown_as_context_but_has_no_row_of_its_own(self, filtered_data):
        rows = [row for _, row in _connection_rows_by_device(filtered_data)]
        assert not any(row[2] in ("SN-SW2", "SN-SRV1") for row in rows)  # SW-2 и сервер собственных строк не имеют
        assert any(row[14] == "SN-SW2" for row in rows) and any(row[14] == "SN-SRV1" for row in rows)  # но видны как соседи SW-1

    def test_empty_selection_result_gives_no_rows(self, registry):
        assert _connection_rows_by_device(_load_report_data(registry, None, ["нет-такой"])) == []

    def test_whole_unit_of_another_building_gets_only_its_own_rows(self, registry):
        rows = _connection_rows_by_device(_load_report_data(registry, None, ["u-other"]))
        assert [device_id for device_id, _ in rows] == ["sw2", "sw2"]
        assert [row[5] for _, row in rows] == ["Gi0/1", "Gi0/2; Gi0/3"]
