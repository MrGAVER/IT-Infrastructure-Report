"""Юнит-тесты чистой логики сверки ролей портов-соседей (app/services/port_config.py) — без БД.

Запуск: pytest backend/tests/test_port_config.py -v
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.port_config import (
    PortConfigStatus,
    PortRole,
    approval_signature,
    evaluate_port_config,
    port_role,
    role_from_flags,
)


def _port(management: bool = False, data: bool = False):
    return SimpleNamespace(is_management=management, is_data_transfer=data)


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
    assert port_role(_port(management, data)) is expected


def test_port_role_treats_none_flags_as_false():
    """Колонки NOT NULL, но объект может прийти недозаполненным (например, из мока/черновика)."""
    assert port_role(SimpleNamespace(is_management=None, is_data_transfer=None)) is PortRole.NONE


def test_matching_roles_are_ok():
    assert evaluate_port_config(_port(data=True), _port(data=True), None) is PortConfigStatus.OK
    assert evaluate_port_config(_port(), _port(), None) is PortConfigStatus.OK


def test_server_management_port_vs_switch_data_port_is_mismatch():
    """Пример из задачи: порт сервера — управление, порт коммутатора — передача данных."""
    status = evaluate_port_config(_port(management=True), _port(data=True), None)
    assert status is PortConfigStatus.MISMATCH


def test_unconfigured_port_against_configured_one_is_mismatch():
    assert evaluate_port_config(_port(), _port(data=True), None) is PortConfigStatus.MISMATCH


def test_approved_signature_turns_mismatch_into_approved():
    src, dst = _port(management=True), _port(data=True)
    signature = approval_signature(src, dst)
    assert signature == "management>data"
    assert evaluate_port_config(src, dst, signature) is PortConfigStatus.APPROVED


def test_approval_is_invalidated_when_a_port_role_changes():
    src, dst = _port(management=True), _port(data=True)
    signature = approval_signature(src, dst)
    dst.is_management = True  # порт назначения стал «управление + данные»
    assert evaluate_port_config(src, dst, signature) is PortConfigStatus.MISMATCH


def test_approval_is_directional():
    """Одобрение пары «управление>данные» не распространяется на «данные>управление»."""
    signature = approval_signature(_port(management=True), _port(data=True))
    assert evaluate_port_config(_port(data=True), _port(management=True), signature) is PortConfigStatus.MISMATCH


def test_inactive_connection_is_never_a_mismatch():
    assert evaluate_port_config(_port(management=True), _port(data=True), None, is_active=False) is PortConfigStatus.OK


def test_stale_approval_on_matching_roles_stays_ok():
    """Роли выровняли уже после одобрения — расхождения нет, статус ok, а не approved."""
    assert evaluate_port_config(_port(data=True), _port(data=True), "management>data") is PortConfigStatus.OK
