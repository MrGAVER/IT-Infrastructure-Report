"""Загрузка из БД данных для сверки конфигурации портов (services/port_config.py).

Чистая логика сверки не знает про БД; здесь — пакетная загрузка номеров VLAN портов и сборка
снимков PortConfig. Один запрос на весь набор портов, а не по запросу на порт.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DeviceInterface, VLAN
from .port_config import PortConfig, port_config_of
from .port_vlans import effective_vlan_ids

_CHUNK = 400  # число id в одном IN-запросе (у SQLite/psycopg число параметров ограничено)


def load_vlan_numbers(session: Session, interface_ids: Iterable[str]) -> dict[str, frozenset[int]]:
    """Номера VLAN (802.1Q-теги) по id порта; порты без VLAN в результате отсутствуют. Номера, а не
    id записей справочника: один тег в разных доменах VLAN — один и тот же VLAN на линии. У порта с «Все VLAN»
    набор — все VLAN его устройства (services/port_vlans.py), у остальных — выбранные."""
    ids = list(dict.fromkeys(interface_ids))
    if not ids:
        return {}
    by_port = effective_vlan_ids(session, ids)
    wanted = list(set().union(*by_port.values())) if by_port else []
    number_of: dict[str, int] = {}
    for start in range(0, len(wanted), _CHUNK):
        for vlan_id, number in session.execute(select(VLAN.id, VLAN.vlan_id).where(VLAN.id.in_(wanted[start:start + _CHUNK]))).all():
            number_of[vlan_id] = number
    numbers = {port_id: frozenset(number_of[v] for v in vlan_ids if v in number_of) for port_id, vlan_ids in by_port.items()}
    return {port_id: values for port_id, values in numbers.items() if values}


def load_port_configs(session: Session, interfaces: Sequence[DeviceInterface]) -> dict[str, PortConfig]:
    """Снимки конфигурации портов по id порта."""
    vlans = load_vlan_numbers(session, (i.id for i in interfaces))
    return {i.id: port_config_of(i, vlans.get(i.id, ())) for i in interfaces}
