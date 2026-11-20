"""VLAN порта и группы портов с учётом признака «Все VLAN» (models.DeviceInterface.all_vlans / InterfaceGroup.all_vlans).

Хранение. Порт (группа) с признаком «Все VLAN» хранит ТОЛЬКО сам признак: строк interface_vlans
(interface_group_vlans) у него нет. Набор VLAN вычисляется при чтении как «все VLAN, доступные устройству» —
VLAN типа устройства (DeviceTypeVLAN) ∪ VLAN самого устройства (PhysicalDeviceVLAN). Поэтому VLAN,
добавленный устройству позже, у такого порта появляется сам, а снятый — пропадает, без пересчёта связей.
Порт без признака, как и раньше, хранит выбранные VLAN связями interface_vlans.

Признак значим только в режиме trunk: порт в access «все VLAN» нести не может, и его признак игнорируется.

Чтение. Всё, что читает VLAN порта, должно идти через этот модуль, а не напрямую из interface_vlans:

    * `effective_vlan_ids`          — id записей справочника VLAN по id портов (отчёты, схема сети, согласование,
                                      каскад режима, правка порта);
    * `effective_group_vlan_ids`    — то же для групп портов;
    * `allowed_vlan_ids_by_device`  — набор «всех» VLAN устройств.

SQL-аналог для сверки подключений — services/connection_query.py:_vlan_fingerprint_sql (ту же логику «Все VLAN» держит
она сама, чтобы считать отпечаток одним запросом на страницу, а не в Python).

Запись — services/port_writes.py (write_port_vlans) и services/crud/interfaces.py: у порта с признаком
связи удаляются, у порта без признака — пишутся выбранные.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import DeviceInterface, DeviceTypeVLAN, InterfaceGroup, InterfaceGroupVLAN, InterfaceVLAN, PhysicalDevice, PhysicalDeviceVLAN
from .port_config import VLAN_MODE_TRUNK

# Число id в одном IN-запросе (у SQLite/psycopg число параметров ограничено).
_CHUNK = 400


def _chunks(values: Sequence[str]):
    for start in range(0, len(values), _CHUNK):
        yield values[start : start + _CHUNK]


def carries_all_vlans(obj: Any) -> bool:
    """Несёт ли порт (группа) «все VLAN устройства»: признак установлен и режим trunk. Режим пустой — trunk."""
    return bool(getattr(obj, "all_vlans", False)) and (getattr(obj, "vlan_mode", None) or VLAN_MODE_TRUNK) == VLAN_MODE_TRUNK


def allowed_vlan_ids_by_device(device_ids: Iterable[str], session: Session) -> dict[str, set[str]]:
    """Для каждого устройства — id записей справочника VLAN, доступных ему: VLAN типа ∪ VLAN устройства.
    Несколько запросов на весь набор устройств (порциями), а не по запросу на устройство. Устройства, которого
    нет в БД, в результате нет."""
    ids = list(dict.fromkeys(device_ids))
    type_of: dict[str, str] = {}
    own: dict[str, set[str]] = {}
    for chunk in _chunks(ids):
        for device_id, type_id in session.execute(select(PhysicalDevice.id, PhysicalDevice.device_type_id).where(PhysicalDevice.id.in_(chunk))).all():
            type_of[device_id] = type_id
        for device_id, vlan_id in session.execute(select(PhysicalDeviceVLAN.physical_device_id, PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id.in_(chunk))).all():
            own.setdefault(device_id, set()).add(vlan_id)
    by_type: dict[str, set[str]] = {}
    for chunk in _chunks(list({t for t in type_of.values() if t})):
        for type_id, vlan_id in session.execute(select(DeviceTypeVLAN.device_type_id, DeviceTypeVLAN.vlan_id).where(DeviceTypeVLAN.device_type_id.in_(chunk))).all():
            by_type.setdefault(type_id, set()).add(vlan_id)
    return {device_id: by_type.get(type_id, set()) | own.get(device_id, set()) for device_id, type_id in type_of.items()}


def effective_vlan_ids(session: Session, port_ids: Iterable[str] | None = None) -> dict[str, set[str]]:
    """id записей справочника VLAN каждого порта: у порта с «Все VLAN» — все VLAN его устройства, у остальных —
    выбранные (interface_vlans). Порты без VLAN в результате отсутствуют. `port_ids=None` — все порты реестра
    (отчёты, схема сети), иначе только указанные. Запросов — константа от числа порций, не от числа портов."""
    if port_ids is None:
        chunks: list[list[str] | None] = [None]
    else:
        ids = list(dict.fromkeys(port_ids))
        if not ids:
            return {}
        chunks = list(_chunks(ids))

    result: dict[str, set[str]] = {}
    flagged: dict[str, str] = {}  # id порта с «Все VLAN» -> id его устройства
    for chunk in chunks:
        ports = select(DeviceInterface.id, DeviceInterface.physical_device_id).where(DeviceInterface.all_vlans.is_(True), DeviceInterface.vlan_mode == VLAN_MODE_TRUNK)
        links = select(InterfaceVLAN.interface_id, InterfaceVLAN.vlan_id)
        if chunk is not None:
            ports = ports.where(DeviceInterface.id.in_(chunk))
            links = links.where(InterfaceVLAN.interface_id.in_(chunk))
        flagged.update({port_id: device_id for port_id, device_id in session.execute(ports).all()})
        for port_id, vlan_id in session.execute(links).all():
            result.setdefault(port_id, set()).add(vlan_id)
    if flagged:
        allowed = allowed_vlan_ids_by_device(set(flagged.values()), session)
        for port_id, device_id in flagged.items():
            # Признак — единственный источник истины: остаточные связи такого порта (например, записанные
            # до миграции или в обход приложения) игнорируются, а не смешиваются с набором устройства.
            vlans = allowed.get(device_id, set())
            if vlans:
                result[port_id] = set(vlans)
            else:
                result.pop(port_id, None)
    return result


def effective_group_vlan_ids(groups: Sequence[InterfaceGroup], session: Session) -> dict[str, set[str]]:
    """То же для групп портов: у группы с «Все VLAN» — все VLAN её устройства, у остальных — interface_group_vlans.
    Группы без VLAN в результате отсутствуют."""
    result: dict[str, set[str]] = {}
    plain = [g.id for g in groups if not carries_all_vlans(g)]
    for chunk in _chunks(plain):
        for group_id, vlan_id in session.execute(select(InterfaceGroupVLAN.group_id, InterfaceGroupVLAN.vlan_id).where(InterfaceGroupVLAN.group_id.in_(chunk))).all():
            result.setdefault(group_id, set()).add(vlan_id)
    flagged = [g for g in groups if carries_all_vlans(g)]
    if flagged:
        allowed = allowed_vlan_ids_by_device({g.physical_device_id for g in flagged}, session)
        for group in flagged:
            vlans = allowed.get(group.physical_device_id, set())
            if vlans:
                result[group.id] = set(vlans)
    return result
