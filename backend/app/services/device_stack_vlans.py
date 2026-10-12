"""Общие IP-адрес и маска VLAN для всех устройств стека (кластера).

Участники стека/кластера делят один адрес на VLAN (общий управляющий адрес стека коммутаторов, виртуальный адрес
пары межсетевых экранов). Отдельной сущности «общий адрес» нет: источник истины остаётся прежним — IP и префикс
в PhysicalDeviceVLAN каждого участника (на них уже опираются отчёты, управляющие адреса и диаграмма). Сервис лишь
- показывает, как этот VLAN настроен на участниках (общий адрес, «не у всех», «различается»);
- одной транзакцией записывает один и тот же адрес и префикс всем участникам, создавая недостающие назначения VLAN.

Такой подход не может рассинхронизироваться с формой устройства: правка адреса на отдельном устройстве просто
отобразится в стеке как расхождение. Флаг «Управление» и описание существующих назначений не меняются.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..models import DeviceStack, DeviceStackMember, PhysicalDevice, PhysicalDeviceVLAN, VLAN, VLANDomainDevice
from .crud import audit
from .integrity import integrity_error_response
from .validation import validate_ipv4_field

IpPrefix = tuple[str | None, int | None]


def _get_stack(session: Session, stack_id: str) -> DeviceStack:
    stack = session.get(DeviceStack, stack_id)
    if not stack:
        raise HTTPException(404, 'Стек не найден')
    return stack


def _member_devices(session: Session, stack_id: str) -> list[PhysicalDevice]:
    """Участники стека по позиции (при равных позициях — по id, чтобы порядок был стабильным)."""
    return list(session.scalars(
        select(PhysicalDevice)
        .join(DeviceStackMember, DeviceStackMember.physical_device_id == PhysicalDevice.id)
        .where(DeviceStackMember.stack_id == stack_id)
        .order_by(DeviceStackMember.position, PhysicalDevice.id)
    ).all())


def _device_label(device: PhysicalDevice) -> str:
    return device.system_name or device.serial_number


def _domain_members(session: Session, device_ids: list[str]) -> dict[str, set[str]]:
    """domain_id -> id участников стека, входящих в этот домен VLAN (один запрос на весь стек)."""
    result: dict[str, set[str]] = {}
    if not device_ids:
        return result
    rows = session.execute(
        select(VLANDomainDevice.domain_id, VLANDomainDevice.physical_device_id).where(VLANDomainDevice.physical_device_id.in_(device_ids))
    ).all()
    for domain_id, device_id in rows:
        result.setdefault(domain_id, set()).add(device_id)
    return result


def _outside_domain(vlan: VLAN, members: list[PhysicalDevice], domain_members: dict[str, set[str]]) -> list[PhysicalDevice]:
    """Участники, которым VLAN назначить нельзя: VLAN доменный, а устройство в домен не входит.

    То же правило, что в crud/validators.py:_validate_physical_device_vlan, но для всех участников за раз."""
    if not vlan.domain_id:
        return []
    inside = domain_members.get(vlan.domain_id, set())
    return [d for d in members if d.id not in inside]


def _normalize_ip(value: str | None) -> str | None:
    return value or None


def _vlan_row(vlan: VLAN, members: list[PhysicalDevice], links: dict[str, PhysicalDeviceVLAN]) -> dict[str, Any]:
    """Состояние одного VLAN на участниках стека.

    ip_address/prefix_length — значение, на котором сошлись ВСЕ участники, у которых VLAN назначен (даже если он
    назначен не у всех: форма подставляет его, чтобы «Применить ко всем» достроило остальных); при разногласии — None.
    is_uniform — VLAN назначен каждому участнику и адрес с префиксом у всех одинаковые."""
    states = []
    for device in members:
        link = links.get(device.id)
        states.append({
            'physical_device_id': device.id,
            'device_name': _device_label(device),
            'assigned': link is not None,
            'ip_address': _normalize_ip(link.ip_address) if link else None,
            'prefix_length': link.prefix_length if link else None,
        })
    assigned_values: set[IpPrefix] = {(s['ip_address'], s['prefix_length']) for s in states if s['assigned']}
    common: IpPrefix = next(iter(assigned_values)) if len(assigned_values) == 1 else (None, None)
    assigned_count = sum(1 for s in states if s['assigned'])
    return {
        'vlan_id': vlan.id,
        'vlan_number': vlan.vlan_id,
        'vlan_name': vlan.name,
        'domain_id': vlan.domain_id,
        'ip_address': common[0],
        'prefix_length': common[1],
        'is_uniform': assigned_count == len(members) and len(assigned_values) == 1,
        'assigned_count': assigned_count,
        'member_count': len(members),
        'members': states,
    }


def _sort_key(vlan: VLAN) -> tuple[int, str, str]:
    return (vlan.vlan_id, vlan.name, vlan.id)


def stack_vlans(session: Session, stack_id: str) -> dict[str, Any]:
    """VLAN стека и их адреса на участниках.

    items — VLAN, назначенные хотя бы одному участнику (по номеру VLAN); available — остальные VLAN справочника,
    которые можно назначить КАЖДОМУ участнику (без домена либо из домена, куда входят все участники). Запросов
    фиксированное число, не зависящее от размера стека."""
    _get_stack(session, stack_id)
    members = _member_devices(session, stack_id)
    if not members:
        return {'items': [], 'available': []}
    member_ids = [d.id for d in members]
    links_by_vlan: dict[str, dict[str, PhysicalDeviceVLAN]] = {}
    for link in session.scalars(select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id.in_(member_ids))).all():
        links_by_vlan.setdefault(link.vlan_id, {})[link.physical_device_id] = link

    catalog = sorted(session.scalars(select(VLAN)).all(), key=_sort_key)
    domain_members = _domain_members(session, member_ids)
    items = [_vlan_row(v, members, links_by_vlan[v.id]) for v in catalog if v.id in links_by_vlan]
    available = [
        {'vlan_id': v.id, 'vlan_number': v.vlan_id, 'vlan_name': v.name}
        for v in catalog
        if v.id not in links_by_vlan and not _outside_domain(v, members, domain_members)
    ]
    return {'items': items, 'available': available}


def _validated_ip_prefix(ip_address: str | None, prefix_length: int | None) -> IpPrefix:
    """Адрес и префикс — только вместе: «общий IP без маски» не описывает сеть, а маска без адреса бессмысленна.
    Оба пустые — осознанная очистка адреса у всех участников."""
    validate_ipv4_field(ip_address, 'IP-адрес VLAN стека')
    ip = _normalize_ip(ip_address)
    if (ip is None) != (prefix_length is None):
        raise HTTPException(422, 'Укажите IP-адрес и префикс вместе либо оставьте оба поля пустыми, чтобы очистить адрес')
    return ip, prefix_length


def apply_stack_vlan_ip(session: Session, stack_id: str, vlan_id: str, ip_address: str | None, prefix_length: int | None) -> dict[str, Any]:
    """Записывает один адрес и префикс VLAN всем участникам стека; возвращает свежее состояние (как stack_vlans).

    Недостающие назначения VLAN создаются (описание — из VLAN, как при массовом назначении), существующие
    обновляются на месте, а уже совпадающие не трогаются (нет лишнего UPDATE). Все проверки идут ДО записи:
    если VLAN доменный и хотя бы один участник в домен не входит, не меняется никто. Операция идемпотентна."""
    ip, prefix = _validated_ip_prefix(ip_address, prefix_length)
    stack = _get_stack(session, stack_id)
    members = _member_devices(session, stack_id)
    if not members:
        raise HTTPException(409, 'В стеке нет устройств: добавьте участников, чтобы задать общий IP-адрес VLAN')
    vlan = session.get(VLAN, vlan_id)
    if not vlan:
        raise HTTPException(404, 'VLAN не найден')
    outside = _outside_domain(vlan, members, _domain_members(session, [d.id for d in members]))
    if outside:
        names = ', '.join(_device_label(d) for d in outside)
        raise HTTPException(422, f'VLAN {vlan.vlan_id} «{vlan.name}» принадлежит домену, в который не входят устройства стека: {names}. Включите их в домен или выберите другой VLAN')

    existing = {
        link.physical_device_id: link
        for link in session.scalars(select(PhysicalDeviceVLAN).where(
            PhysicalDeviceVLAN.vlan_id == vlan.id, PhysicalDeviceVLAN.physical_device_id.in_([d.id for d in members]))).all()
    }
    created = updated = 0
    for device in members:
        link = existing.get(device.id)
        if link is None:
            session.add(PhysicalDeviceVLAN(physical_device_id=device.id, vlan_id=vlan.id, ip_address=ip, prefix_length=prefix, description=vlan.description))
            created += 1
        elif (_normalize_ip(link.ip_address), link.prefix_length) != (ip, prefix):
            link.ip_address, link.prefix_length = ip, prefix
            updated += 1
    address = f'{ip}/{prefix}' if ip else 'адрес очищен'
    audit(session, 'device-stacks', stack.id, AuditAction.SYNC,
          f'Общий IP VLAN {vlan.vlan_id} «{vlan.name}» для стека «{stack.name}»: {address}; назначено устройствам {created}, изменено {updated}, без изменений {len(members) - created - updated}')
    try:
        session.commit()
    except IntegrityError as exc:  # параллельный запрос успел создать то же назначение (uq_physical_device_vlan)
        session.rollback()
        raise integrity_error_response('device-vlans', exc) from exc
    return stack_vlans(session, stack_id)
