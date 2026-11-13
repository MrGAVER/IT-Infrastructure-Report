"""Общие настройки VLAN стека (кластера): запись копий на устройства, план для нового участника, защита правки.

Лежит внутри пакета crud намеренно: его зовут и generic CRUD (создание участника стека), и синхронизация VLAN
устройства, а наверху (services/device_stack_vlans.py) — HTTP-операции со стеком. Модуль зависит только от моделей и
валидации, поэтому циклических импортов нет.

Настройка (models.DeviceStackVLAN) — источник значений; PhysicalDeviceVLAN каждого участника хранит их копию, на
которую опираются отчёты, управляющие адреса и диаграмма. Пока настройка задана, IP-адрес, префикс и «Управление»
этого VLAN у участников не редактируются по отдельности (assert_device_vlan_editable).
"""
from __future__ import annotations

from typing import Any, NamedTuple

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import DeviceStack, DeviceStackMember, DeviceStackVLAN, PhysicalDevice, PhysicalDeviceVLAN, VLAN, VLANDomainDevice
from ..device_label import device_label

class Values(NamedTuple):
    """То, что общая настройка задаёт каждому участнику: IP-адрес, префикс, «Управление». Это обычный кортеж по
    сравнению и распаковке (запрос формы устройства собирает значения кортежем), класс нужен ради читаемых имён полей."""
    ip_address: str | None
    prefix_length: int | None
    is_management: bool


def normalize_ip(value: str | None) -> str | None:
    return value or None


def setting_values(setting: DeviceStackVLAN) -> Values:
    return Values(normalize_ip(setting.ip_address), setting.prefix_length, bool(setting.is_management))


def link_values(link: PhysicalDeviceVLAN) -> Values:
    return Values(normalize_ip(link.ip_address), link.prefix_length, bool(link.is_management))


def vlan_sort_key(vlan: VLAN) -> tuple[int, str, str]:
    return (vlan.vlan_id, vlan.name, vlan.id)


def member_devices(session: Session, stack_id: str) -> list[PhysicalDevice]:
    """Участники стека по позиции (при равных позициях — по id, чтобы порядок был стабильным)."""
    return list(session.scalars(
        select(PhysicalDevice)
        .join(DeviceStackMember, DeviceStackMember.physical_device_id == PhysicalDevice.id)
        .where(DeviceStackMember.stack_id == stack_id)
        .order_by(DeviceStackMember.position, PhysicalDevice.id)
    ).all())


def stack_settings(session: Session, stack_id: str) -> dict[str, DeviceStackVLAN]:
    """Заданные настройки стека: id VLAN -> настройка."""
    return {s.vlan_id: s for s in session.scalars(select(DeviceStackVLAN).where(DeviceStackVLAN.stack_id == stack_id)).all()}


def domain_members(session: Session, device_ids: list[str]) -> dict[str, set[str]]:
    """domain_id -> id переданных устройств, входящих в этот домен VLAN (один запрос на всех)."""
    result: dict[str, set[str]] = {}
    if not device_ids:
        return result
    rows = session.execute(
        select(VLANDomainDevice.domain_id, VLANDomainDevice.physical_device_id).where(VLANDomainDevice.physical_device_id.in_(device_ids))
    ).all()
    for domain_id, device_id in rows:
        result.setdefault(domain_id, set()).add(device_id)
    return result


def outside_domain(vlan: VLAN, devices: list[PhysicalDevice], members_by_domain: dict[str, set[str]]) -> list[PhysicalDevice]:
    """Устройства, которым VLAN назначить нельзя: VLAN доменный, а устройство в домен не входит.

    То же правило, что в crud/validators.py:_validate_physical_device_vlan, но сразу для нескольких устройств."""
    if not vlan.domain_id:
        return []
    inside = members_by_domain.get(vlan.domain_id, set())
    return [d for d in devices if d.id not in inside]


def write_link(session: Session, device_id: str, vlan: VLAN, link: PhysicalDeviceVLAN | None, values: Values) -> str | None:
    """Приводит назначение VLAN устройству к значениям настройки: создаёт недостающее (описание — из VLAN, как при
    массовом назначении), обновляет отличающееся на месте, совпадающее не трогает. Возвращает 'added'/'updated'/None."""
    ip, prefix, management = values
    if link is None:
        session.add(PhysicalDeviceVLAN(physical_device_id=device_id, vlan_id=vlan.id, ip_address=ip, prefix_length=prefix, is_management=management, description=vlan.description))
        return 'added'
    if link_values(link) != values:
        link.ip_address, link.prefix_length, link.is_management = ip, prefix, management
        return 'updated'
    return None


def _values_dict(values: Values) -> dict[str, Any]:
    return {'ip_address': values[0], 'prefix_length': values[1], 'is_management': values[2]}


def plan_member_settings(session: Session, stack_id: str, device: PhysicalDevice) -> list[dict[str, Any]]:
    """Что произойдёт с VLAN устройства, когда оно станет участником стека: по строке на каждую заданную настройку.

    action: 'add' — VLAN будет назначен устройству; 'update' — назначение есть, но значения заменятся (before — то,
    что будет перезаписано); 'keep' — уже совпадает. Если VLAN доменный, а устройство в домен не входит, поднимает
    422 — так же, как отказала бы сама запись, поэтому план и применение не расходятся."""
    settings = stack_settings(session, stack_id)
    if not settings:
        return []
    vlans = {v.id: v for v in session.scalars(select(VLAN).where(VLAN.id.in_(list(settings)))).all()}
    members_by_domain = domain_members(session, [device.id])
    blocked = [v for v in vlans.values() if outside_domain(v, [device], members_by_domain)]
    if blocked:
        names = ', '.join(f'{v.vlan_id} «{v.name}»' for v in sorted(blocked, key=vlan_sort_key))
        raise HTTPException(422, f'Устройство «{device_label(device)}» не входит в домен VLAN: {names}. Включите его в домен или снимите общую настройку этих VLAN у стека')
    links = {l.vlan_id: l for l in session.scalars(
        select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id == device.id, PhysicalDeviceVLAN.vlan_id.in_(list(settings)))).all()}
    plan = []
    for vlan in sorted(vlans.values(), key=vlan_sort_key):
        after = setting_values(settings[vlan.id])
        link = links.get(vlan.id)
        if link is None:
            action, before = 'add', None
        elif link_values(link) != after:
            action, before = 'update', _values_dict(link_values(link))
        else:
            action, before = 'keep', _values_dict(after)
        plan.append({'vlan_id': vlan.id, 'vlan_number': vlan.vlan_id, 'vlan_name': vlan.name, 'action': action, 'before': before, 'after': _values_dict(after)})
    return plan


def apply_stack_settings_to_device(session: Session, stack_id: str, device: PhysicalDevice) -> dict[str, int]:
    """Записывает устройству значения всех заданных настроек стека (не коммитит — вызывающий добавляет участника и
    коммитит одной транзакцией). Возвращает счётчики {'added', 'updated'} для журнала аудита."""
    plan = plan_member_settings(session, stack_id, device)
    counts = {'added': 0, 'updated': 0}
    if not any(item['action'] != 'keep' for item in plan):
        return counts
    settings = stack_settings(session, stack_id)
    vlans = {v.id: v for v in session.scalars(select(VLAN).where(VLAN.id.in_(list(settings)))).all()}
    links = {l.vlan_id: l for l in session.scalars(
        select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id == device.id, PhysicalDeviceVLAN.vlan_id.in_(list(settings)))).all()}
    for vlan_id, setting in settings.items():
        outcome = write_link(session, device.id, vlans[vlan_id], links.get(vlan_id), setting_values(setting))
        if outcome:
            counts[outcome] += 1
    return counts


def _locking_stack(session: Session, device_id: str) -> tuple[DeviceStack | None, dict[str, DeviceStackVLAN]]:
    member = session.scalar(select(DeviceStackMember).where(DeviceStackMember.physical_device_id == device_id))
    if not member:
        return None, {}
    return session.get(DeviceStack, member.stack_id), stack_settings(session, member.stack_id)


def locked_vlan_ids(session: Session, device_id: str) -> set[str]:
    """VLAN устройства, значения которых заданы стеком, где оно состоит (пусто, если устройство вне стека)."""
    return set(_locking_stack(session, device_id)[1])


def assert_device_vlan_editable(session: Session, device_id: str, incoming: dict[str, Values], existing_ids: set[str]) -> None:
    """409, если сохранение «VLAN устройства» меняет то, что задано общей настройкой стека.

    incoming — vlan_id -> значения из запроса; existing_ids — VLAN, уже назначенные устройству. Для VLAN с настройкой
    стека значения в запросе обязаны совпадать с настройкой (форма устройства присылает их неизменными, пока поля
    заблокированы), а уже назначенный VLAN нельзя убрать с устройства отдельно: иначе у стека остался бы участник без
    общего адреса. Меняются они в настройках стека (PUT /device-stacks/{id}/vlans/{vlan_id})."""
    stack, settings = _locking_stack(session, device_id)
    if not settings:
        return
    vlans = {v.id: v for v in session.scalars(select(VLAN).where(VLAN.id.in_(list(settings)))).all()}
    for vlan_id, setting in settings.items():
        label = f'{vlans[vlan_id].vlan_id} «{vlans[vlan_id].name}»' if vlan_id in vlans else vlan_id
        stack_name = stack.name if stack else ''
        if vlan_id in incoming and incoming[vlan_id] != setting_values(setting):
            raise HTTPException(409, f'VLAN {label} задан для стека «{stack_name}»: IP-адрес, префикс и «Управление» меняются в общих настройках стека, а не на отдельном устройстве')
        if vlan_id in existing_ids and vlan_id not in incoming:
            raise HTTPException(409, f'VLAN {label} задан для стека «{stack_name}» и не может быть убран с отдельного устройства: снимите общую настройку у стека')
