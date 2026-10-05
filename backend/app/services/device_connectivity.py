"""Данные о подключаемости портов устройства для формы устройства (блок «Порты / интерфейсы»).

Форма раньше брала занятость портов и подключения из общих списков (справочник интерфейсов и список
подключений), которые клиент загружает целиком с потолком 1000 записей: в большом реестре порт, не
попавший в выборку, пропадал из списка соседей, а занятый порт выглядел свободным. Здесь то же самое
считает сервер — по одному устройству, с поиском и постраничной выдачей:

* ``list_free_interfaces`` — свободные порты устройства (без активного подключения), чтобы выбрать
  соседа для подключения;
* ``list_interface_connections`` — действующие подключения портов устройства вместе со сведениями о
  соседнем порте и устройстве, чтобы показать их в форме при редактировании.

«Активное» подключение — ``is_active IS NOT FALSE``, как в services/validation.py:validate_connection
(NULL считается активным): порт, который эти функции считают свободным, validate_connection тоже
примет.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..models import Connection, DeviceInterface, PhysicalDevice

_DIGITS = re.compile(r'(\d+)')


def natural_key(name: str) -> tuple[Any, ...]:
    """Ключ «естественной» сортировки имён портов: Gi0/2 раньше Gi0/10.

    re.split с группой даёт чередование «текст, число, текст, …», поэтому сравниваются только
    значения одного типа на одинаковых позициях.

    >>> sorted(['Gi0/10', 'Gi0/2', 'gi0/1'], key=natural_key)
    ['gi0/1', 'Gi0/2', 'Gi0/10']
    """
    return tuple(int(part) if part.isdigit() else part for part in _DIGITS.split(name.casefold()))


def _require_device(device_id: str, session: Session) -> PhysicalDevice:
    device = session.get(PhysicalDevice, device_id)
    if device is None:
        raise HTTPException(404, 'Физическое устройство не найдено')
    return device


def _device_label(device: PhysicalDevice) -> str:
    return device.system_name or device.serial_number


def _active_connections_of_device(device_id: str, session: Session) -> list[Connection]:
    """Активные подключения, в которых участвует хотя бы один порт устройства, в стабильном порядке.
    Порты выбираются подзапросом, а не списком id: у устройства их может быть много."""
    own_ids = select(DeviceInterface.id).where(DeviceInterface.physical_device_id == device_id)
    stmt = (
        select(Connection)
        .where(Connection.is_active.is_not(False), or_(Connection.source_interface_id.in_(own_ids), Connection.destination_interface_id.in_(own_ids)))
        .order_by(Connection.created_at, Connection.id)
    )
    return list(session.scalars(stmt).all())


def list_free_interfaces(device_id: str, session: Session, *, q: str | None = None, include: Iterable[str] = (), offset: int = 0, limit: int = 100) -> dict[str, Any]:
    """Свободные порты устройства в естественном порядке имён, одна страница.

    ``q`` — подстрока имени порта без учёта регистра. ``include`` — id портов ЭТОГО устройства, которые
    нужно вернуть, даже если они заняты (и независимо от ``q``): текущий сосед подключения, который
    форма должна показать выбранным, и порты, освобождаемые этой же формой; такие порты помечаются
    ``occupied: true``. Чужие id в ``include`` игнорируются. ``total`` — число портов во всей выборке
    (до разбиения на страницы).

    Пример: list_free_interfaces(device.id, session, q='gi0', include=[current_peer_id], limit=50)
    """
    _require_device(device_id, session)
    ports = list(session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id == device_id)).all())
    occupied: set[str] = set()
    for conn in _active_connections_of_device(device_id, session):
        occupied.update((conn.source_interface_id, conn.destination_interface_id))
    forced = set(include)
    needle = (q or '').strip().casefold()

    selected = [p for p in ports if p.id in forced or (p.id not in occupied and (not needle or needle in p.name.casefold()))]
    selected.sort(key=lambda p: (natural_key(p.name), p.id))
    page = selected[offset:offset + limit]
    return {
        'items': [
            {'id': p.id, 'name': p.name, 'is_management': p.is_management, 'is_data_transfer': p.is_data_transfer, 'vlan_mode': p.vlan_mode, 'occupied': p.id in occupied}
            for p in page
        ],
        'total': len(selected),
        'offset': offset,
        'limit': limit,
    }


def list_interface_connections(device_id: str, session: Session) -> dict[str, Any]:
    """Действующие подключения портов устройства: по записи на каждый подключённый порт устройства.

    Кабель между двумя портами одного устройства даёт две записи (по одной с каждой стороны), чтобы
    форма видела подключение у обоих портов. Поле ``peer_*`` описывает порт на другом конце, включая
    его роль и режим — для предупреждения о расхождении конфигураций до сохранения.
    """
    _require_device(device_id, session)
    own_ids = set(session.scalars(select(DeviceInterface.id).where(DeviceInterface.physical_device_id == device_id)).all())
    connections = _active_connections_of_device(device_id, session)
    peer_ids = {pid for c in connections for pid in (c.source_interface_id, c.destination_interface_id)}
    peers = {p.id: p for p in session.scalars(select(DeviceInterface).where(DeviceInterface.id.in_(peer_ids))).all()} if peer_ids else {}
    device_ids = {p.physical_device_id for p in peers.values()}
    devices = {d.id: d for d in session.scalars(select(PhysicalDevice).where(PhysicalDevice.id.in_(device_ids))).all()} if device_ids else {}

    items: list[dict[str, Any]] = []
    for conn in connections:
        for own_id, peer_id in ((conn.source_interface_id, conn.destination_interface_id), (conn.destination_interface_id, conn.source_interface_id)):
            if own_id not in own_ids:
                continue
            peer = peers.get(peer_id)
            if peer is None:  # внешний ключ гарантирует наличие; защита от рассинхронизации данных
                continue
            peer_device = devices.get(peer.physical_device_id)
            items.append({
                'interface_id': own_id,
                'connection_id': conn.id,
                'connection_type_id': conn.connection_type_id,
                'description': conn.description,
                'peer_interface_id': peer.id,
                'peer_interface_name': peer.name,
                'peer_device_id': peer.physical_device_id,
                'peer_device_name': _device_label(peer_device) if peer_device else '',
                'peer_is_management': peer.is_management,
                'peer_is_data_transfer': peer.is_data_transfer,
                'peer_vlan_mode': peer.vlan_mode,
            })
    return {'items': items}
