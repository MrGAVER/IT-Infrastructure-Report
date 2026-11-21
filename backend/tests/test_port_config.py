"""Юнит-тесты чистой логики сверки конфигурации портов-соседей (app/services/port_config.py):
роль, режим порта (access / trunk) и набор VLAN — без БД.

Запуск: pytest backend/tests/test_port_config.py -v
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.port_config import (
    ConfigFacet,
    PortConfig,
    PortConfigStatus,
    PortRole,
    approval_signature,
    config_differences,
    evaluate_port_config,
    port_config_of,
    port_role,
    role_from_flags,
    vlan_fingerprint,
    vlan_hash,
)


def _cfg(role: PortRole = PortRole.NONE, mode: str = "trunk", vlans: set[int] | frozenset[int] = frozenset()) -> PortConfig:
    return PortConfig(role, mode, frozenset(vlans))


@pytest.mark.parametrize(
    ("management", "data", "expected"),
    [
        (False, False, PortRole.NONE),
        (True, False, PortRole.MANAGEMENT),
        (False, True, PortRole.DATA),
        (True, True, PortRole.MANAGEMENT_DATA),
    ],
)
def test_role_from_flags_covers_all_four_combinations(management, data, expected):
    assert role_from_flags(management, data) is expected
    assert port_role(SimpleNamespace(is_management=management, is_data_transfer=data)) is expected


def test_port_role_treats_none_flags_as_false():
    """Колонки NOT NULL, но объект может прийти недозаполненным (например, из мока/черновика)."""
    assert port_role(SimpleNamespace(is_management=None, is_data_transfer=None)) is PortRole.NONE


def test_port_config_of_builds_snapshot_and_defaults_empty_mode_to_trunk():
    port = SimpleNamespace(is_management=False, is_data_transfer=True, vlan_mode="access")
    assert port_config_of(port, [10, 10, 20]) == _cfg(PortRole.DATA, "access", {10, 20})
    assert port_config_of(SimpleNamespace(is_management=False, is_data_transfer=False, vlan_mode=None)).mode == "trunk"
    assert port_config_of(SimpleNamespace(is_management=False, is_data_transfer=False, vlan_mode="")).mode == "trunk"


# --- отпечаток набора VLAN ---------------------------------------------------------------


def test_vlan_fingerprint_ignores_order_and_duplicates():
    assert vlan_fingerprint([10, 20, 30]) == vlan_fingerprint([30, 10, 20]) == vlan_fingerprint([10, 20, 20, 30, 10])


def test_vlan_hash_is_injective_on_the_whole_valid_vlan_range():
    """SQL схлопывает дубликаты через SUM(DISTINCT хеш) — это корректно, только пока разные номера
    не дают одинакового хеша; для допустимых VLAN (1..4094) проверяем это полностью."""
    assert len({vlan_hash(n) for n in range(1, 4095)}) == 4094


def test_vlan_fingerprint_distinguishes_sets_including_empty():
    sets = [(), (10,), (20,), (10, 20), (10, 20, 30), (10, 30), tuple(range(1, 4095))]
    assert len({vlan_fingerprint(s) for s in sets}) == len(sets)
    assert vlan_fingerprint(()) == 0


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ((1, 5, 6), (2, 3, 7)),  # одинаковые сумма и сумма квадратов
        ((10, 14, 17, 21), (11, 12, 19, 20)),  # одинаковые три степенные суммы
        ((10, 20, 30), (15, 20, 25)),  # одинаковые сумма и количество
        ((100, 200), (150,)),  # та же сумма номеров, другой размер
    ],
)
def test_vlan_fingerprint_separates_sets_a_linear_hash_would_confuse(first, second):
    assert vlan_fingerprint(first) != vlan_fingerprint(second)


def test_vlan_fingerprint_fits_a_signed_64_bit_integer_for_the_largest_set():
    assert vlan_fingerprint(range(1, 4095)) < 2**63


# --- различающиеся грани -----------------------------------------------------------------


def test_identical_configs_have_no_differences():
    config = _cfg(PortRole.DATA, "trunk", {10, 20})
    assert config_differences(config, _cfg(PortRole.DATA, "trunk", {20, 10})) == []


def test_differences_report_each_facet_in_fixed_order():
    src, dst = _cfg(PortRole.MANAGEMENT, "trunk", set()), _cfg(PortRole.DATA, "access", {10})
    assert config_differences(src, dst) == [ConfigFacet.ROLE, ConfigFacet.MODE, ConfigFacet.VLANS]
    assert config_differences(_cfg(PortRole.DATA), _cfg(PortRole.DATA, "access")) == [ConfigFacet.MODE]
    assert config_differences(_cfg(PortRole.DATA, vlans={10}), _cfg(PortRole.DATA, vlans={10, 20})) == [ConfigFacet.VLANS]


# --- статус ------------------------------------------------------------------------------


def test_matching_configs_are_ok():
    assert evaluate_port_config(_cfg(PortRole.DATA), _cfg(PortRole.DATA), None) is PortConfigStatus.OK
    assert evaluate_port_config(_cfg(), _cfg(), None) is PortConfigStatus.OK


def test_server_management_port_vs_switch_data_port_is_mismatch():
    """Пример из задачи: порт сервера — управление, порт коммутатора — передача данных."""
    assert evaluate_port_config(_cfg(PortRole.MANAGEMENT), _cfg(PortRole.DATA), None) is PortConfigStatus.MISMATCH


def test_unconfigured_port_against_configured_one_is_mismatch():
    assert evaluate_port_config(_cfg(), _cfg(PortRole.DATA), None) is PortConfigStatus.MISMATCH


def test_trunk_against_access_is_mismatch_even_when_roles_and_vlans_match():
    assert evaluate_port_config(_cfg(PortRole.DATA, "trunk", {10}), _cfg(PortRole.DATA, "access", {10}), None) is PortConfigStatus.MISMATCH


def test_different_vlan_sets_are_mismatch_even_when_roles_and_modes_match():
    assert evaluate_port_config(_cfg(PortRole.DATA, "trunk", {10, 20}), _cfg(PortRole.DATA, "trunk", {10, 30}), None) is PortConfigStatus.MISMATCH


def test_inactive_connection_is_never_a_mismatch():
    assert evaluate_port_config(_cfg(PortRole.MANAGEMENT, "access"), _cfg(PortRole.DATA, "trunk", {10}), None, is_active=False) is PortConfigStatus.OK


# --- подпись и одобрение -----------------------------------------------------------------


def test_signature_for_role_only_difference_keeps_the_legacy_format():
    """Подписи, записанные до появления проверки режима и VLAN, остаются валидными."""
    assert approval_signature(_cfg(PortRole.MANAGEMENT), _cfg(PortRole.DATA)) == "management>data"


def test_signature_lists_only_differing_facets():
    assert approval_signature(_cfg(PortRole.DATA, "trunk"), _cfg(PortRole.DATA, "access")) == "|mode:trunk>access"
    assert approval_signature(_cfg(PortRole.DATA, vlans={10}), _cfg(PortRole.DATA)) == f"|vlan:{vlan_fingerprint({10})}>{vlan_fingerprint(())}"
    full = approval_signature(_cfg(PortRole.MANAGEMENT, "trunk", {10}), _cfg(PortRole.DATA, "access", {20}))
    assert full == f"management>data|mode:trunk>access|vlan:{vlan_fingerprint({10})}>{vlan_fingerprint({20})}"
    assert approval_signature(_cfg(PortRole.DATA), _cfg(PortRole.DATA)) == ""


def test_signature_fits_the_column_even_for_widest_values():
    widest = approval_signature(
        _cfg(PortRole.MANAGEMENT_DATA, "trunk", set(range(1, 4095))),
        _cfg(PortRole.NONE, "access", {4094}),
    )
    assert len(widest) <= 255


@pytest.mark.parametrize(
    ("src", "dst"),
    [
        (_cfg(PortRole.MANAGEMENT), _cfg(PortRole.DATA)),
        (_cfg(PortRole.DATA, "trunk"), _cfg(PortRole.DATA, "access")),
        (_cfg(PortRole.DATA, vlans={10}), _cfg(PortRole.DATA, vlans={20})),
    ],
)
def test_approved_signature_turns_mismatch_into_approved(src, dst):
    assert evaluate_port_config(src, dst, approval_signature(src, dst)) is PortConfigStatus.APPROVED


@pytest.mark.parametrize(
    ("changed_dst"),
    [
        _cfg(PortRole.MANAGEMENT_DATA, "trunk", {10}),  # роль
        _cfg(PortRole.DATA, "access", {10}),  # режим
        _cfg(PortRole.DATA, "trunk", {10, 20}),  # VLAN
    ],
)
def test_approval_is_invalidated_when_any_facet_changes(changed_dst):
    src, dst = _cfg(PortRole.MANAGEMENT, "trunk", {10}), _cfg(PortRole.DATA, "trunk", {10})
    signature = approval_signature(src, dst)
    assert evaluate_port_config(src, changed_dst, signature) is PortConfigStatus.MISMATCH


def test_approval_is_directional():
    """Одобрение пары «управление>данные» не распространяется на «данные>управление»."""
    signature = approval_signature(_cfg(PortRole.MANAGEMENT), _cfg(PortRole.DATA))
    assert evaluate_port_config(_cfg(PortRole.DATA), _cfg(PortRole.MANAGEMENT), signature) is PortConfigStatus.MISMATCH


def test_legacy_role_approval_does_not_cover_a_new_mode_or_vlan_difference():
    """Роли одобрили давно; позже выяснилось, что режимы тоже различаются — этого пользователь не видел."""
    src, dst = _cfg(PortRole.MANAGEMENT, "trunk"), _cfg(PortRole.DATA, "access")
    assert evaluate_port_config(src, dst, "management>data") is PortConfigStatus.MISMATCH
    src, dst = _cfg(PortRole.MANAGEMENT, vlans={10}), _cfg(PortRole.DATA)
    assert evaluate_port_config(src, dst, "management>data") is PortConfigStatus.MISMATCH


def test_stale_approval_on_matching_configs_stays_ok():
    """Порты выровняли уже после одобрения — расхождения нет, статус ok, а не approved."""
    assert evaluate_port_config(_cfg(PortRole.DATA), _cfg(PortRole.DATA), "management>data") is PortConfigStatus.OK
