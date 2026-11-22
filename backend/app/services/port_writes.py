"""Запись конфигурации ОДНОГО порта (роль, режим и VLAN) — общая для всех операций, которые меняют порт
точечно, в обход синхронизации устройства целиком (PUT /devices/{id}/interfaces):

  * согласование по правилам (services/port_sync_reconcile.py);
  * правка порта на дашборде «Подключения» (services/port_edit.py);
  * смена роли порта (services/connection_review.set_port_role).

Здесь только запись: проверки (допустимые VLAN, «в access не более одного VLAN», группа портов,
которая задаёт режим и VLAN) делает вызывающий — у каждой операции своё сообщение об ошибке и свой
способ её показать. Функции не делают commit и не пишут аудит — это тоже на вызывающем: операция
может менять несколько портов одной транзакцией.

Пакетная запись. Согласование по правилам может менять тысячи портов за раз, а запрос на каждый порт
(SELECT связей, UPDATE IP-адресов) вместе с flush на каждом порту превращал применение плана в минуты.
Поэтому для массовых операций есть `load_vlan_links` (связи порт–VLAN всех портов несколькими запросами)
и `write_port_roles` (признак на IP-адресах несколькими UPDATE): одиночные функции остаются для правок
одного порта и работают через те же примитивы.
"""

from __future__ import annotations

from typing import Sequence

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..constants import OwnerType
from ..models import DeviceInterface, IPAddress, InterfaceVLAN
from .port_config import VLAN_MODE_ACCESS, PortRole
from .port_sync_rules import flags_from_role

# Число id в одном IN-запросе (у SQLite/psycopg число параметров ограничено).
_CHUNK = 400


def _chunks(values: Sequence[str]):
    for start in range(0, len(values), _CHUNK):
        yield values[start : start + _CHUNK]


def write_port_roles(items: Sequence[tuple[DeviceInterface, PortRole]], session: Session) -> None:
    """Роль каждого порта (управление / передача данных) вместе с признаком на его IP-адресах.

    IP-адреса порта зеркалируют его is_management — тот же инвариант, что у sync_interfaces. Адреса
    обновляются одним UPDATE на каждое значение признака (на порцию портов), а не по запросу на порт."""
    by_flag: dict[bool, list[str]] = {True: [], False: []}
    for port, role in items:
        is_management, is_data = flags_from_role(role)
        port.is_management, port.is_data_transfer = is_management, is_data
        by_flag[is_management].append(port.id)
    for is_management, port_ids in by_flag.items():
        for chunk in _chunks(port_ids):
            session.execute(
                update(IPAddress)
                .where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id.in_(chunk))
                .values(is_management=is_management)
            )


def write_port_role(port: DeviceInterface, role: PortRole, session: Session) -> None:
    """Роль одного порта вместе с признаком на его IP-адресах (см. write_port_roles)."""
    write_port_roles([(port, role)], session)


def load_vlan_links(port_ids: Sequence[str], session: Session) -> dict[str, list[InterfaceVLAN]]:
    """Связи порт–VLAN всех данных портов несколькими запросами (порциями) — для `write_port_vlans(links=…)`
    при массовой записи. У порта без VLAN — пустой список."""
    ids = list(dict.fromkeys(port_ids))
    links: dict[str, list[InterfaceVLAN]] = {port_id: [] for port_id in ids}
    for chunk in _chunks(ids):
        for link in session.scalars(select(InterfaceVLAN).where(InterfaceVLAN.interface_id.in_(chunk))).all():
            links[link.interface_id].append(link)
    return links


def write_port_vlans(
    port: DeviceInterface,
    mode: str,
    vlan_ids: Sequence[str],
    session: Session,
    *,
    links: Sequence[InterfaceVLAN] | None = None,
    all_vlans: bool = False,
) -> None:
    """Режим порта и ровно этот набор VLAN (id записей справочника): лишние связи удаляются, недостающие
    добавляются, у остающихся выставляется режим. Дубликаты в `vlan_ids` игнорируются.

    `all_vlans` — «Все VLAN» (models.DeviceInterface.all_vlans): порт хранит только признак, а набор VLAN
    вычисляется из VLAN устройства при чтении (services/port_vlans.py), поэтому `vlan_ids` игнорируются, а
    все связи порта удаляются. В режиме access признак невозможен и всегда снимается. Явно заданный набор
    («выбраны вручную») пишется с all_vlans=False — признак не выводится из числа VLAN.

    `links` — текущие связи этого порта, уже загруженные `load_vlan_links` (массовая запись): тогда запроса
    по порту нет. Без него связи читаются здесь. Изменения уходят в БД при ближайшем flush сессии."""
    port.vlan_mode = mode
    port.all_vlans = bool(all_vlans) and mode != VLAN_MODE_ACCESS
    current = links if links is not None else session.scalars(select(InterfaceVLAN).where(InterfaceVLAN.interface_id == port.id)).all()
    keep = [] if port.all_vlans else list(dict.fromkeys(vlan_ids))
    kept: set[str] = set()
    for link in current:
        if link.vlan_id in keep and link.vlan_id not in kept:
            link.mode = mode
            kept.add(link.vlan_id)
        else:
            session.delete(link)
    for vlan_id in keep:
        if vlan_id not in kept:
            session.add(InterfaceVLAN(interface_id=port.id, vlan_id=vlan_id, mode=mode))
