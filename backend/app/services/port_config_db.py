"""Загрузка из БД данных для сверки конфигурации портов (services/port_config.py).

Чистая логика сверки не знает про БД; здесь — пакетная загрузка номеров VLAN портов и сборка
снимков PortConfig. Один запрос на весь набор портов, а не по запросу на порт.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DeviceInterface, InterfaceVLAN, VLAN
from .port_config import PortConfig, port_config_of


def load_vlan_numbers(session: Session, interface_ids: Iterable[str]) -> dict[str, frozenset[int]]:
    """Номера VLAN (802.1Q-теги) по id порта; порты без VLAN в результате отсутствуют. Номера, а не
    id записей справочника: один тег в разных доменах VLAN — один и тот же VLAN на линии."""
    ids = list(dict.fromkeys(interface_ids))
    if not ids:
        return {}
    rows = session.execute(
        select(InterfaceVLAN.interface_id, VLAN.vlan_id)
        .join(VLAN, VLAN.id == InterfaceVLAN.vlan_id)
        .where(InterfaceVLAN.interface_id.in_(ids))
    ).all()
    numbers: dict[str, set[int]] = {}
    for interface_id, number in rows:
        numbers.setdefault(interface_id, set()).add(number)
    return {interface_id: frozenset(values) for interface_id, values in numbers.items()}


def load_port_configs(session: Session, interfaces: Sequence[DeviceInterface]) -> dict[str, PortConfig]:
    """Снимки конфигурации портов по id порта."""
    vlans = load_vlan_numbers(session, (i.id for i in interfaces))
    return {i.id: port_config_of(i, vlans.get(i.id, ())) for i in interfaces}
