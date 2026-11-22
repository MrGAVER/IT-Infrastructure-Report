"""Поведение разбора групп портов (crud/interface_groups.py: _normalize_group_item и проверки ключей/имён в
_sync_interface_groups), зафиксированное до снижения сложности _normalize_group_item (код-ревью, п. 10; сложность 16).
Тесты написаны на прежнем коде и проходят без правок после рефакторинга.

Сервисные функции вызываются напрямую, а не только через HTTP: схема тела запроса отсекает часть значений, а сервис —
последний рубеж для любого вызывающего. Порядок проверок тоже часть поведения: при нескольких ошибках сразу клиент
видит ту, что выше по списку (см. TestCheckOrder). Запуск: pytest backend/tests/test_normalize_group_item_behaviour.py -v
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import InterfaceGroup
from app.services.crud import sync_interfaces
from app.services.crud.interface_groups import _normalize_group_item

API = "/api/v1"
ALLOWED = {"v10", "v20", "v30"}


def _normalize(db_session, item, allowed=ALLOWED):
    return _normalize_group_item(item, set(allowed), db_session)


def _rejected(db_session, item, allowed=ALLOWED) -> str:
    with pytest.raises(HTTPException) as exc_info:
        _normalize(db_session, item, allowed)
    assert exc_info.value.status_code == 422
    return exc_info.value.detail


def _catalog_entry(client, port: int, protocol_type: str = "TCP") -> dict:
    """Запись справочника «Протоколы и порты»: часть записей засеяна по умолчанию — ищем существующую."""
    existing = client.get(f"{API}/resources/protocol-port-catalog", params={"limit": 1000}).json()["items"]
    match = next((e for e in existing if e["port"] == port and e["protocol_type"] == protocol_type), None)
    return match or client.post(f"{API}/resources/protocol-port-catalog", json={"port": port, "protocol_type": protocol_type}).json()


def _device(client, serial: str = "NORM-G-1") -> dict:
    category_id = client.get(f"{API}/resources/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    device_type = client.post(f"{API}/resources/device-types", json={"name": f"Тип {serial}", "category_id": category_id}).json()
    return client.post(f"{API}/resources/devices", json={"device_type_id": device_type["id"], "serial_number": serial}).json()


class TestItemAndName:
    @pytest.mark.parametrize("item", ["группа", None, ["name"], 5])
    def test_item_must_be_an_object(self, db_session, item):
        assert _rejected(db_session, item) == "Каждая группа портов должна быть объектом"

    @pytest.mark.parametrize("name", [None, "", "   ", 0])
    def test_name_is_required(self, db_session, name):
        assert _rejected(db_session, {"name": name}) == "У группы портов должно быть наименование"

    def test_missing_name_key_is_required_too(self, db_session):
        assert _rejected(db_session, {}) == "У группы портов должно быть наименование"

    def test_name_is_stripped_and_limited_to_100_characters(self, db_session):
        assert _normalize(db_session, {"name": "  " + "а" * 100 + "  "})["name"] == "а" * 100
        assert _rejected(db_session, {"name": "а" * 101}) == "Наименование группы портов не должно превышать 100 символов"


class TestVlanMode:
    @pytest.mark.parametrize("mode", ["hybrid", "ACCESS", "Trunk", 1])
    def test_unknown_mode_is_rejected(self, db_session, mode):
        assert _rejected(db_session, {"name": "Г", "vlan_mode": mode}) == "Поле vlan_mode группы портов должно быть 'access', 'trunk' или пустым"

    @pytest.mark.parametrize("mode", [None, "", 0, False])
    def test_empty_mode_means_group_does_not_manage_it(self, db_session, mode):
        assert _normalize(db_session, {"name": "Г", "vlan_mode": mode})["vlan_mode"] is None

    @pytest.mark.parametrize("mode", ["access", "trunk"])
    def test_valid_modes_are_kept(self, db_session, mode):
        assert _normalize(db_session, {"name": "Г", "vlan_mode": mode})["vlan_mode"] == mode


class TestVlanIds:
    @pytest.mark.parametrize("value", ["10", {"a": 1}, 7])
    def test_vlan_ids_must_be_a_list(self, db_session, value):
        assert _rejected(db_session, {"name": "Г", "vlan_mode": "trunk", "vlan_ids": value}) == "Поле vlan_ids группы портов должно быть массивом"

    @pytest.mark.parametrize("value", [None, "", 0, {}])
    def test_falsy_vlan_ids_are_treated_as_empty(self, db_session, value):
        assert _normalize(db_session, {"name": "Г", "vlan_ids": value})["vlan_ids"] == []

    def test_vlan_ids_require_a_port_mode(self, db_session):
        assert _rejected(db_session, {"name": "Г", "vlan_ids": ["v10"]}) == "VLAN группы портов можно задать только вместе с режимом порта"

    def test_vlan_must_be_allowed_for_the_device_type(self, db_session):
        assert (
            _rejected(db_session, {"name": "Г", "vlan_mode": "trunk", "vlan_ids": ["v10", "чужой"]})
            == "Один или несколько VLAN не разрешены для типа данного устройства"
        )

    def test_access_allows_at_most_one_distinct_vlan(self, db_session):
        assert (
            _rejected(db_session, {"name": "Г", "vlan_mode": "access", "vlan_ids": ["v10", "v20"]})
            == "В режиме access у группы портов может быть не более одного VLAN"
        )

    def test_duplicates_are_removed_keeping_first_occurrence_order(self, db_session):
        assert _normalize(db_session, {"name": "Г", "vlan_mode": "trunk", "vlan_ids": ["v30", "v10", "v30", "v20", "v10"]})["vlan_ids"] == ["v30", "v10", "v20"]
        assert _normalize(db_session, {"name": "Г", "vlan_mode": "access", "vlan_ids": ["v10", "v10"]})["vlan_ids"] == ["v10"]


class TestAllVlans:
    @pytest.mark.parametrize("value", ["yes", 1, 0, None, []])
    def test_all_vlans_must_be_a_boolean(self, db_session, value):
        assert _rejected(db_session, {"name": "Г", "vlan_mode": "trunk", "all_vlans": value}) == "Поле all_vlans группы портов должно быть true или false"

    @pytest.mark.parametrize("mode", ["access", None])
    def test_all_vlans_is_only_possible_in_trunk_mode(self, db_session, mode):
        assert _rejected(db_session, {"name": "Г", "vlan_mode": mode, "all_vlans": True}) == "«Все VLAN» у группы портов возможно только в режиме trunk"

    def test_all_vlans_in_trunk_drops_vlan_ids_without_checking_them(self, db_session):
        result = _normalize(db_session, {"name": "Г", "vlan_mode": "trunk", "all_vlans": True, "vlan_ids": ["чужой", "v10"]})
        assert result["all_vlans"] is True and result["vlan_ids"] == []

    def test_all_vlans_false_keeps_vlan_ids(self, db_session):
        result = _normalize(db_session, {"name": "Г", "vlan_mode": "trunk", "all_vlans": False, "vlan_ids": ["v10"]})
        assert result["all_vlans"] is False and result["vlan_ids"] == ["v10"]


class TestIps:
    """Общие IP группы — список ips (адрес, префикс, назначение); проверки — services/crud/interface_groups.py:_group_ips."""

    @staticmethod
    def _ips(db_session, *ips, **extra):
        return _normalize(db_session, {"name": "Г", "ips": list(ips), **extra})["ips"]

    def test_invalid_address_and_prefix_are_rejected_with_group_name_in_message(self, db_session):
        assert "Группа портов «Г»: IP-адрес" in _rejected(db_session, {"name": "Г", "ips": [{"ip_address": "999.1.1.1"}]})
        assert "Группа портов «Г»: префикс IP-адреса" in _rejected(db_session, {"name": "Г", "ips": [{"ip_address": "10.0.0.1", "prefix_length": 33}]})
        assert "Группа портов «Г»: префикс IP-адреса" in _rejected(db_session, {"name": "Г", "ips": [{"ip_address": "10.0.0.1", "prefix_length": "abc"}]})

    def test_every_row_is_checked_not_only_the_first(self, db_session):
        assert "IP-адрес" in _rejected(db_session, {"name": "Г", "ips": [{"ip_address": "10.0.0.1"}, {"ip_address": "bad"}]})

    def test_ips_must_be_a_list_of_objects(self, db_session):
        assert "поле ips должно быть массивом" in _rejected(db_session, {"name": "Г", "ips": "10.0.0.1"})
        assert "каждый IP-адрес должен быть объектом" in _rejected(db_session, {"name": "Г", "ips": ["10.0.0.1"]})

    @pytest.mark.parametrize(("prefix", "expected"), [("24", 24), (0, 0), ("", None), (None, None), (32, 32)])
    def test_prefix_is_normalized_to_int_or_none(self, db_session, prefix, expected):
        assert self._ips(db_session, {"ip_address": "10.0.0.1", "prefix_length": prefix})[0]["prefix_length"] == expected

    def test_address_is_stripped_and_placeholder_rows_are_dropped(self, db_session):
        assert [
            ip["ip_address"] for ip in self._ips(db_session, {"ip_address": " 10.0.0.1 "}, {"ip_address": "  "}, {"prefix_length": 24, "purpose": "x"})
        ] == ["10.0.0.1"]

    def test_group_without_addresses_has_an_empty_list(self, db_session):
        assert self._ips(db_session, {"ip_address": "", "prefix_length": 99}) == []  # префикс без адреса — плейсхолдер, не проверяется
        assert _normalize(db_session, {"name": "Г"})["ips"] == []

    def test_several_addresses_keep_payload_order_and_row_ids(self, db_session):
        ips = self._ips(db_session, {"id": "r2", "ip_address": "10.0.0.9"}, {"ip_address": "10.0.0.1"})
        assert [(ip["id"], ip["ip_address"]) for ip in ips] == [("r2", "10.0.0.9"), (None, "10.0.0.1")]

    def test_repeated_address_is_rejected_even_with_different_prefix(self, db_session):
        assert (
            _rejected(db_session, {"name": "Г", "ips": [{"ip_address": "10.0.0.1", "prefix_length": 24}, {"ip_address": " 10.0.0.1 ", "prefix_length": 16}]})
            == "Группа портов «Г»: IP-адреса не должны повторяться"
        )

    def test_purpose_is_stripped_and_blank_becomes_none(self, db_session):
        ips = self._ips(db_session, {"ip_address": "10.0.0.1", "purpose": "  шлюз "}, {"ip_address": "10.0.0.2", "purpose": "  "}, {"ip_address": "10.0.0.3"})
        assert [ip["purpose"] for ip in ips] == ["шлюз", None, None]

    def test_purpose_is_limited_to_255_characters(self, db_session):
        assert len(self._ips(db_session, {"ip_address": "10.0.0.1", "purpose": "н" * 255})[0]["purpose"]) == 255
        assert (
            _rejected(db_session, {"name": "Г", "ips": [{"ip_address": "10.0.0.1", "purpose": "н" * 256}]})
            == "Группа портов «Г»: назначение IP-адреса не должно превышать 255 символов"
        )

    def test_overlong_purpose_is_ignored_without_an_address(self, db_session):
        assert self._ips(db_session, {"purpose": "н" * 300}) == []


class TestOpenPorts:
    def test_open_ports_must_be_a_list_even_when_group_does_not_manage_them(self, db_session):
        assert _rejected(db_session, {"name": "Г", "open_ports": "80"}) == "Поле open_ports группы портов должно быть массивом"
        assert _rejected(db_session, {"name": "Г", "manage_open_ports": True, "open_ports": {"a": 1}}) == "Поле open_ports группы портов должно быть массивом"

    def test_open_ports_are_not_stored_unless_the_group_manages_them(self, client, db_session):
        http = _catalog_entry(client, 80)
        result = _normalize(db_session, {"name": "Г", "open_ports": [{"protocol_catalog_id": http["id"]}]})
        assert result["manage_open_ports"] is False and result["open_ports"] == []

    def test_unmanaged_open_ports_are_not_validated(self, db_session):
        assert _normalize(db_session, {"name": "Г", "open_ports": [{"protocol_catalog_id": "нет-такой"}]})["open_ports"] == []

    def test_rows_are_normalized_with_defaults(self, client, db_session):
        http, ssh = _catalog_entry(client, 80), _catalog_entry(client, 22)
        result = _normalize(
            db_session,
            {
                "name": "Г",
                "manage_open_ports": True,
                "open_ports": [
                    {"id": "row-1", "protocol_catalog_id": http["id"], "transport_protocol": "UDP", "description": "веб", "лишнее": 1},
                    {"protocol_catalog_id": ssh["id"], "description": ""},
                ],
            },
        )
        assert result["manage_open_ports"] is True
        assert result["open_ports"] == [
            {"id": "row-1", "protocol_catalog_id": http["id"], "transport_protocol": "UDP", "description": "веб"},
            {"id": None, "protocol_catalog_id": ssh["id"], "transport_protocol": "TCP", "description": None},
        ]

    def test_placeholder_rows_are_skipped(self, client, db_session):
        http = _catalog_entry(client, 80)
        result = _normalize(
            db_session,
            {
                "name": "Г",
                "manage_open_ports": True,
                "open_ports": [
                    {"protocol_catalog_id": ""},
                    {"description": "без записи справочника"},
                    "строка",
                    None,
                    {"protocol_catalog_id": http["id"]},
                ],
            },
        )
        assert [p["protocol_catalog_id"] for p in result["open_ports"]] == [http["id"]]

    def test_unknown_catalog_entry_is_rejected(self, db_session):
        detail = _rejected(db_session, {"name": "Г", "manage_open_ports": True, "open_ports": [{"protocol_catalog_id": "нет-такой"}]})
        assert detail == "Не выбрана существующая запись справочника «Протоколы и порты»"

    def test_repeated_port_number_is_rejected_with_the_group_name(self, client, db_session):
        http, http_proxy = _catalog_entry(client, 80), _catalog_entry(client, 80, "UDP")
        detail = _rejected(
            db_session,
            {"name": "Веб", "manage_open_ports": True, "open_ports": [{"protocol_catalog_id": http["id"]}, {"protocol_catalog_id": http_proxy["id"]}]},
        )
        assert detail == "Группа портов «Веб»: номера открытых портов не должны повторяться — 80"


class TestSubinterfaces:
    def test_subinterfaces_are_not_stored_unless_the_group_manages_them(self, db_session):
        result = _normalize(db_session, {"name": "Г", "vlan_mode": "trunk", "vlan_ids": ["v10"], "subinterfaces": "мусор"})
        assert result["manage_subinterfaces"] is False and result["subinterfaces"] == []

    def test_managed_subinterfaces_must_be_a_list(self, db_session):
        detail = _rejected(db_session, {"name": "Г", "manage_subinterfaces": True, "subinterfaces": "мусор"})
        assert detail == "Поле subinterfaces группы портов должно быть массивом"

    @pytest.mark.parametrize("value", [None, [], 0])
    def test_managed_empty_subinterfaces_give_an_empty_list(self, db_session, value):
        result = _normalize(db_session, {"name": "Г", "manage_subinterfaces": True, "subinterfaces": value})
        assert result["manage_subinterfaces"] is True and result["subinterfaces"] == []

    @pytest.mark.parametrize(("all_vlans", "expected_allowed"), [(True, ALLOWED), (False, {"v10"})])
    def test_group_vlans_for_subinterfaces_follow_all_vlans(self, db_session, monkeypatch, all_vlans, expected_allowed):
        """При «Все VLAN» подинтерфейс может быть на любом VLAN устройства, иначе — только на VLAN группы."""
        from app.services.crud import interface_groups

        captured = {}

        def fake_normalize(raw, *, group_name, vlan_mode, group_vlans, session):
            captured.update(raw=raw, group_name=group_name, vlan_mode=vlan_mode, group_vlans=group_vlans)
            return [{"маркер": True}]

        monkeypatch.setattr(interface_groups, "normalize_group_subinterfaces", fake_normalize)
        item = {"name": "Г", "vlan_mode": "trunk", "all_vlans": all_vlans, "vlan_ids": ["v10"], "manage_subinterfaces": True, "subinterfaces": [{"x": 1}]}
        assert _normalize(db_session, item)["subinterfaces"] == [{"маркер": True}]
        assert captured == {"raw": [{"x": 1}], "group_name": "Г", "vlan_mode": "trunk", "group_vlans": expected_allowed}


class TestResultShape:
    def test_full_item_is_normalized_to_column_values(self, client, db_session):
        http = _catalog_entry(client, 80)
        result = _normalize(
            db_session,
            {
                "name": " Магистраль ",
                "vlan_mode": "trunk",
                "vlan_ids": ["v20", "v10", "v20"],
                "ips": [{"ip_address": "10.1.1.1", "prefix_length": "24", "purpose": "управление"}],
                "manage_open_ports": 1,
                "open_ports": [{"protocol_catalog_id": http["id"]}],
                "manage_subinterfaces": 0,
            },
        )
        assert result == {
            "name": "Магистраль",
            "vlan_mode": "trunk",
            "all_vlans": False,
            "vlan_ids": ["v20", "v10"],
            "ips": [{"id": None, "ip_address": "10.1.1.1", "prefix_length": 24, "purpose": "управление"}],
            "manage_open_ports": True,
            "open_ports": [{"id": None, "protocol_catalog_id": http["id"], "transport_protocol": "TCP", "description": None}],
            "manage_subinterfaces": False,
            "subinterfaces": [],
        }

    def test_minimal_item_leaves_every_parameter_unmanaged(self, db_session):
        assert _normalize(db_session, {"name": "Г"}) == {
            "name": "Г",
            "vlan_mode": None,
            "all_vlans": False,
            "vlan_ids": [],
            "ips": [],
            "manage_open_ports": False,
            "open_ports": [],
            "manage_subinterfaces": False,
            "subinterfaces": [],
        }


class TestCheckOrder:
    """Если нарушено сразу несколько правил, сообщение берётся у первого по порядку проверок."""

    @pytest.mark.parametrize(
        ("item", "fragment"),
        [
            ({"name": "", "vlan_mode": "hybrid"}, "наименование"),
            ({"name": "Г", "vlan_mode": "hybrid", "vlan_ids": "10"}, "vlan_mode"),
            ({"name": "Г", "vlan_ids": "10", "all_vlans": "yes"}, "vlan_ids группы портов должно быть массивом"),
            ({"name": "Г", "vlan_ids": ["v10"], "all_vlans": "yes"}, "all_vlans группы портов должно быть true или false"),
            ({"name": "Г", "vlan_ids": ["чужой"], "all_vlans": True}, "«Все VLAN»"),
            ({"name": "Г", "vlan_ids": ["чужой"]}, "только вместе с режимом порта"),
            ({"name": "Г", "vlan_mode": "access", "vlan_ids": ["чужой", "v10"], "ips": [{"ip_address": "bad"}]}, "не разрешены для типа данного устройства"),
            ({"name": "Г", "vlan_mode": "access", "vlan_ids": ["v10", "v20"], "ips": [{"ip_address": "bad"}]}, "не более одного VLAN"),
            ({"name": "Г", "ips": [{"ip_address": "bad", "prefix_length": 99}], "open_ports": "x"}, "IP-адрес"),
            ({"name": "Г", "ips": [{"ip_address": "10.0.0.1", "prefix_length": 99}], "open_ports": "x"}, "префикс IP-адреса"),
            ({"name": "Г", "ips": [{"ip_address": "10.0.0.1", "purpose": "н" * 256}], "open_ports": "x"}, "назначение IP-адреса"),
            ({"name": "Г", "open_ports": "x", "manage_subinterfaces": True, "subinterfaces": "y"}, "open_ports группы портов должно быть массивом"),
        ],
    )
    def test_first_violated_rule_wins(self, db_session, item, fragment):
        assert fragment in _rejected(db_session, item)


class TestGroupKeysAndNames:
    """Проверки уровня payload['groups'] в _sync_interface_groups (после разбора элемента)."""

    @staticmethod
    def _put(db_session, device_id: str, groups: list):
        with pytest.raises(HTTPException) as exc_info:
            sync_interfaces(device_id, {"interfaces": [], "groups": groups}, db_session)
        assert exc_info.value.status_code == 422
        return exc_info.value.detail

    @staticmethod
    def _stored_groups(db_session, device_id: str) -> list[InterfaceGroup]:
        db_session.expire_all()
        return list(db_session.scalars(select(InterfaceGroup).where(InterfaceGroup.physical_device_id == device_id)).all())

    def test_group_needs_a_key_or_an_id(self, client, db_session):
        device = _device(client)
        assert self._put(db_session, device["id"], [{"name": "Г"}]) == "У группы портов должен быть key (id существующей группы или временный ключ новой)"

    def test_keys_must_be_unique(self, client, db_session):
        device = _device(client)
        detail = self._put(db_session, device["id"], [{"key": "k", "name": "А"}, {"key": "k", "name": "Б"}])
        assert detail == "Ключи групп портов должны быть уникальны"

    @pytest.mark.parametrize("second", ["а", "А", "  а "])
    def test_names_must_be_unique_ignoring_case_and_spaces(self, client, db_session, second):
        device = _device(client)
        detail = self._put(db_session, device["id"], [{"key": "k1", "name": "А"}, {"key": "k2", "name": second}])
        assert detail == "Наименования групп портов на устройстве должны быть уникальны"

    def test_group_id_must_belong_to_the_device(self, client, db_session):
        device, other = _device(client, "NORM-G-A"), _device(client, "NORM-G-B")
        sync_interfaces(other["id"], {"interfaces": [], "groups": [{"key": "k", "name": "Чужая"}]}, db_session)
        foreign_id = self._stored_groups(db_session, other["id"])[0].id
        detail = self._put(db_session, device["id"], [{"id": foreign_id, "name": "Моя"}])
        assert detail == "Группа портов не принадлежит выбранному физическому устройству"

    def test_key_error_precedes_item_level_checks_only_after_normalization(self, client, db_session):
        """Элемент разбирается раньше проверки key: у группы без key и без имени сообщают про имя."""
        device = _device(client)
        assert self._put(db_session, device["id"], [{}]) == "У группы портов должно быть наименование"

    def test_failure_rolls_back_groups_created_earlier_in_the_same_payload(self, client, db_session):
        device = _device(client)
        self._put(db_session, device["id"], [{"key": "k1", "name": "Хорошая"}, {"key": "k2", "name": "Плохая", "vlan_mode": "hybrid"}])
        assert self._stored_groups(db_session, device["id"]) == []
