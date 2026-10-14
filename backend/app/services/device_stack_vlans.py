"""Общие IP-адрес, префикс и «Управление» VLAN для всех устройств стека (кластера).

Участники стека/кластера делят один адрес на VLAN (общий управляющий адрес стека коммутаторов, виртуальный адрес пары
межсетевых экранов). Настройка пары «стек — VLAN» хранится в models.DeviceStackVLAN и копируется каждому участнику
(PhysicalDeviceVLAN) одной транзакцией. Пока настройка задана:
- IP-адрес, префикс и «Управление» этого VLAN у участников не редактируются по отдельности (409 из
  crud/stack_vlan_settings.py:assert_device_vlan_editable);
- новый участник стека получает значения при добавлении, а окно подтверждения в интерфейсе заранее показывает, что
  будет добавлено и заменено (preview_member_addition);
- снять настройку можно отдельно (значения на устройствах остаются, поля снова редактируются) или вместе с VLAN у
  всех устройств стека (remove_stack_vlan).
Устройства, у которых значения разошлись с настройкой (например, VLAN убрали при выходе из домена), стек показывает
как «не у всех»/«различаются» — «Применить ко всем» приводит их обратно.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..models import (
    DeviceInterface, DeviceStack, DeviceStackMember, DeviceStackVLAN, DeviceSubinterface, InterfaceGroup, InterfaceGroupVLAN, InterfaceVLAN,
    PhysicalDevice, PhysicalDeviceVLAN, VLAN,
)
from .crud import audit, validate_resource
from .crud.stack_vlan_settings import (
    Values, device_label, domain_members, link_values, member_devices, normalize_ip, outside_domain, plan_member_settings, setting_values,
    stack_settings, vlan_sort_key, write_link,
)
from .integrity import integrity_error_response
from .validation import validate_ipv4_field


def _get_stack(session: Session, stack_id: str) -> DeviceStack:
    stack = session.get(DeviceStack, stack_id)
    if not stack:
        raise HTTPException(404, 'Стек не найден')
    return stack


def _member_state(device: PhysicalDevice, link: PhysicalDeviceVLAN | None) -> dict[str, Any]:
    return {
        'physical_device_id': device.id,
        'device_name': device_label(device),
        'assigned': link is not None,
        'ip_address': normalize_ip(link.ip_address) if link else None,
        'prefix_length': link.prefix_length if link else None,
        'is_management': bool(link.is_management) if link else False,
        'description': link.description if link else None,
    }


def _shared_row(vlan: VLAN, setting: DeviceStackVLAN, members: list[PhysicalDevice], links: dict[str, PhysicalDeviceVLAN]) -> dict[str, Any]:
    """Заданная настройка и то, как она применена к участникам. is_uniform — у каждого участника VLAN назначен и
    значения равны настройке; иначе стек показывает расхождение, а «Применить ко всем» его устраняет."""
    want = setting_values(setting)
    states = [_member_state(d, links.get(d.id)) for d in members]
    matching = sum(1 for d in members if d.id in links and link_values(links[d.id]) == want)
    return {
        'vlan_id': vlan.id,
        'vlan_number': vlan.vlan_id,
        'vlan_name': vlan.name,
        'domain_id': vlan.domain_id,
        'is_shared': True,
        'ip_address': want[0],
        'prefix_length': want[1],
        'is_management': want[2],
        'is_uniform': bool(members) and matching == len(members),
        'assigned_count': sum(1 for s in states if s['assigned']),
        'member_count': len(members),
        'members': states,
    }


def _candidate(vlan: VLAN, members: list[PhysicalDevice], links: dict[str, PhysicalDeviceVLAN]) -> dict[str, Any]:
    """VLAN, который ещё можно сделать общим: подсказка для формы — адрес с префиксом, на которых сошлись участники с
    этим VLAN (иначе пусто), и «Управление», если оно включено хотя бы у одного: флаг у одного устройства означает
    флаг у всех, при применении он выставляется каждому участнику."""
    assigned = [links[d.id] for d in members if d.id in links]
    pairs = {(normalize_ip(l.ip_address), l.prefix_length) for l in assigned}
    ip, prefix = next(iter(pairs)) if len(pairs) == 1 else (None, None)
    return {
        'vlan_id': vlan.id,
        'vlan_number': vlan.vlan_id,
        'vlan_name': vlan.name,
        'ip_address': ip,
        'prefix_length': prefix,
        'is_management': any(l.is_management for l in assigned),
        'assigned_count': len(assigned),
    }


def stack_vlans(session: Session, stack_id: str) -> dict[str, Any]:
    """Общие настройки VLAN стека и состояние их применения.

    items — заданные настройки (по номеру VLAN); available — остальные VLAN, которые можно сделать общими: добавленные
    хотя бы одному устройству стека (VLAN, которого нет ни у одного участника, в список не попадает — стек не «открывает»
    новые VLAN, а выравнивает уже используемые) и при этом без домена либо из домена, куда входят все участники; с
    подсказкой значений. Запросов фиксированное число, не зависящее от размера стека."""
    stack = _get_stack(session, stack_id)
    members = member_devices(session, stack_id)
    settings = stack_settings(session, stack_id)
    member_ids = [d.id for d in members]
    links_by_vlan: dict[str, dict[str, PhysicalDeviceVLAN]] = {}
    if member_ids:
        for link in session.scalars(select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id.in_(member_ids))).all():
            links_by_vlan.setdefault(link.vlan_id, {})[link.physical_device_id] = link
    result: dict[str, Any] = {'stack_name': stack.name, 'member_count': len(members), 'items': [], 'available': []}
    if not settings and not members:
        return result
    catalog = sorted(session.scalars(select(VLAN)).all(), key=vlan_sort_key)
    result['items'] = [_shared_row(v, settings[v.id], members, links_by_vlan.get(v.id, {})) for v in catalog if v.id in settings]
    if members:
        members_by_domain = domain_members(session, member_ids)
        result['available'] = [
            _candidate(v, members, links_by_vlan.get(v.id, {}))
            for v in catalog
            if v.id not in settings and v.id in links_by_vlan and not outside_domain(v, members, members_by_domain)
        ]
    return result


def _validated_values(ip_address: str | None, prefix_length: int | None, is_management: bool) -> Values:
    """Адрес и префикс — только вместе: «общий IP без маски» не описывает сеть, а маска без адреса бессмысленна.
    Оба пустые — адреса нет (VLAN всё равно назначается, можно задать только «Управление»)."""
    validate_ipv4_field(ip_address, 'IP-адрес VLAN стека')
    ip = normalize_ip(ip_address)
    if (ip is None) != (prefix_length is None):
        raise HTTPException(422, 'Укажите IP-адрес и префикс вместе либо оставьте оба поля пустыми')
    return ip, prefix_length, bool(is_management)


def apply_stack_vlan(session: Session, stack_id: str, vlan_id: str, ip_address: str | None, prefix_length: int | None, is_management: bool = False) -> dict[str, Any]:
    """Задаёт (или меняет) общую настройку VLAN стека и записывает её всем участникам; возвращает stack_vlans().

    Недостающие назначения VLAN создаются, существующие обновляются на месте (IP, префикс и «Управление»; описание не
    меняется), совпадающие не трогаются. Все проверки идут ДО записи: если VLAN доменный и хотя бы один участник в
    домен не входит, не меняется ничего. Операция идемпотентна — повтор «чинит» устройства, у которых значения разошлись."""
    values = _validated_values(ip_address, prefix_length, is_management)
    stack = _get_stack(session, stack_id)
    members = member_devices(session, stack_id)
    if not members:
        raise HTTPException(409, 'В стеке нет устройств: добавьте участников, чтобы задать общие настройки VLAN')
    vlan = session.get(VLAN, vlan_id)
    if not vlan:
        raise HTTPException(404, 'VLAN не найден')
    outside = outside_domain(vlan, members, domain_members(session, [d.id for d in members]))
    if outside:
        names = ', '.join(device_label(d) for d in outside)
        raise HTTPException(422, f'VLAN {vlan.vlan_id} «{vlan.name}» принадлежит домену, в который не входят устройства стека: {names}. Включите их в домен или выберите другой VLAN')

    setting = session.scalar(select(DeviceStackVLAN).where(DeviceStackVLAN.stack_id == stack.id, DeviceStackVLAN.vlan_id == vlan.id))
    if setting is None:
        setting = DeviceStackVLAN(stack_id=stack.id, vlan_id=vlan.id)
        session.add(setting)
    setting.ip_address, setting.prefix_length, setting.is_management = values
    links = {l.physical_device_id: l for l in session.scalars(
        select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.vlan_id == vlan.id, PhysicalDeviceVLAN.physical_device_id.in_([d.id for d in members]))).all()}
    outcomes = Counter(write_link(session, d.id, vlan, links.get(d.id), values) for d in members)
    address = f'{values[0]}/{values[1]}' if values[0] else 'адрес не задан'
    flag = ', «Управление»' if values[2] else ''
    audit(session, 'device-stacks', stack.id, AuditAction.SYNC,
          f'Общая настройка VLAN {vlan.vlan_id} «{vlan.name}» для стека «{stack.name}»: {address}{flag}; назначено устройствам {outcomes["added"]}, изменено {outcomes["updated"]}, без изменений {outcomes[None]}')
    try:
        session.commit()
    except IntegrityError as exc:  # параллельный запрос успел создать то же назначение или настройку
        session.rollback()
        raise integrity_error_response('device-stack-vlans', exc) from exc
    return stack_vlans(session, stack_id)


def _vlan_usage_by_device(session: Session, device_ids: list[str], vlan_id: str) -> Counter:
    """Сколько связей портов, групп портов и подинтерфейсов каждого устройства используют VLAN."""
    usage: Counter = Counter()
    queries = (
        select(DeviceInterface.physical_device_id).join(InterfaceVLAN, InterfaceVLAN.interface_id == DeviceInterface.id)
        .where(InterfaceVLAN.vlan_id == vlan_id, DeviceInterface.physical_device_id.in_(device_ids)),
        select(InterfaceGroup.physical_device_id).join(InterfaceGroupVLAN, InterfaceGroupVLAN.group_id == InterfaceGroup.id)
        .where(InterfaceGroupVLAN.vlan_id == vlan_id, InterfaceGroup.physical_device_id.in_(device_ids)),
        select(DeviceInterface.physical_device_id).join(DeviceSubinterface, DeviceSubinterface.parent_interface_id == DeviceInterface.id)
        .where(DeviceSubinterface.vlan_id == vlan_id, DeviceInterface.physical_device_id.in_(device_ids)),
    )
    for query in queries:
        usage.update(session.scalars(query).all())
    return usage


def remove_stack_vlan(session: Session, stack_id: str, vlan_id: str, remove_from_devices: bool = False) -> dict[str, Any]:
    """Снимает общую настройку VLAN со стека; возвращает stack_vlans().

    remove_from_devices=False (по умолчанию): значения на устройствах остаются, поля у них снова редактируются.
    remove_from_devices=True: VLAN убирается и у всех участников стека — но только если ни порт, ни группа портов, ни
    подинтерфейс участника его не используют (иначе 409 со списком устройств: сначала снимите VLAN с портов)."""
    stack = _get_stack(session, stack_id)
    setting = session.scalar(select(DeviceStackVLAN).where(DeviceStackVLAN.stack_id == stack.id, DeviceStackVLAN.vlan_id == vlan_id))
    if not setting:
        raise HTTPException(404, 'Общая настройка этого VLAN для стека не задана')
    vlan = session.get(VLAN, vlan_id)
    label = f'{vlan.vlan_id} «{vlan.name}»' if vlan else vlan_id
    removed = 0
    if remove_from_devices:
        members = member_devices(session, stack_id)
        names = {d.id: device_label(d) for d in members}
        busy = _vlan_usage_by_device(session, list(names), vlan_id)
        if busy:
            listing = ', '.join(f'{names[device_id]} ({count})' for device_id, count in sorted(busy.items(), key=lambda item: names[item[0]]))
            raise HTTPException(409, f'VLAN {label} нельзя убрать с устройств стека: он используется на портах, в группах портов или подинтерфейсах ({listing}). Сначала снимите VLAN с них или снимите настройку без удаления VLAN с устройств')
        for link in session.scalars(select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.vlan_id == vlan_id, PhysicalDeviceVLAN.physical_device_id.in_(list(names)))).all():
            session.delete(link)
            removed += 1
    session.delete(setting)
    outcome = f'VLAN убран у устройств: {removed}' if remove_from_devices else 'значения на устройствах сохранены'
    audit(session, 'device-stacks', stack.id, AuditAction.SYNC, f'Снята общая настройка VLAN {label} со стека «{stack.name}»: {outcome}')
    session.commit()
    return stack_vlans(session, stack_id)


def preview_member_addition(session: Session, stack_id: str, physical_device_id: str, position: int = 1) -> dict[str, Any]:
    """Что произойдёт с данными устройства при добавлении в стек — для окна подтверждения.

    changes — только изменяющие данные строки по общим настройкам стека: 'add' (VLAN будет назначен) и 'update'
    (значения устройства заменятся: before → after); unchanged_count — сколько настроек у устройства уже совпадает.
    Те же проверки, что у самого добавления (устройство в другом стеке — 409, VLAN вне домена устройства — 422)."""
    stack = _get_stack(session, stack_id)
    device = session.get(PhysicalDevice, physical_device_id)
    if not device:
        raise HTTPException(404, 'Физическое устройство не найдено')
    base = {'stack_name': stack.name, 'device_name': device_label(device)}
    existing = session.scalar(select(DeviceStackMember).where(DeviceStackMember.physical_device_id == device.id))
    if existing and existing.stack_id == stack_id:
        return {**base, 'already_member': True, 'changes': [], 'unchanged_count': 0}
    validate_resource(DeviceStackMember, {'stack_id': stack_id, 'physical_device_id': device.id, 'position': position}, session, item_id=None)
    plan = plan_member_settings(session, stack_id, device)
    return {
        **base,
        'already_member': False,
        'changes': [item for item in plan if item['action'] != 'keep'],
        'unchanged_count': sum(1 for item in plan if item['action'] == 'keep'),
    }
