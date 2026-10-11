"""Группы портов устройства: чтение, синхронизация (payload['groups']) и применение значений группы к её портам.

Вынесено из interfaces.py (тест test_modules_are_small_enough_to_review): sync_interfaces вызывает отсюда
разбор групп и _apply_group_to_interface, зависимость направлена в одну сторону (interfaces -> interface_groups).

«Все VLAN» группы (models.InterfaceGroup.all_vlans) хранится одним признаком, без строк interface_group_vlans:
набор VLAN вычисляется из VLAN устройства при чтении (services/port_vlans.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from ...models import DeviceInterface, IPAddress, OpenPort, PhysicalDevice, InterfaceVLAN, InterfaceGroup, InterfaceGroupOpenPort, InterfaceGroupVLAN
from ...constants import OwnerType
from ..serialization import enrich_interface_groups
from ..validation import validate_ipv4_field, validate_prefix_length_field, validate_unique_open_port_numbers
from .owned_rows import _IP_PURPOSE_MAX_LENGTH, _validate_open_port_catalog


_VLAN_MODES = frozenset({"access", "trunk"})


def list_interface_groups(device_id: str, session: Session) -> list[dict[str, Any]]:
    """Группы портов устройства с их VLAN и открытыми портами (GET /devices/{id}/interface-groups и
    поле groups ответа PUT /devices/{id}/interfaces). Порядок — по наименованию."""
    groups = session.scalars(select(InterfaceGroup).where(InterfaceGroup.physical_device_id == device_id).order_by(InterfaceGroup.name)).all()
    return enrich_interface_groups(groups, session)


def get_interface_groups(device_id: str, session: Session) -> dict[str, Any]:
    if not session.get(PhysicalDevice, device_id): raise HTTPException(404, 'Физическое устройство не найдено')
    return {'items': list_interface_groups(device_id, session)}


@dataclass
class _GroupState:
    """Разобранная группа из payload['groups']: объект в сессии и нормализованные значения,
    которые применяются к каждому порту группы (см. _apply_group_to_interface)."""
    obj: InterfaceGroup
    vlan_ids: list[str]
    open_ports: list[dict[str, Any]]


def _normalize_group_item(item: Any, allowed_vlans: set[str], session: Session) -> dict[str, Any]:
    """Валидирует один элемент payload['groups'] и приводит к значениям колонок. Заданность
    параметра (vlan_mode / ip_address / manage_open_ports) определяет, управляет ли им группа —
    см. models.InterfaceGroup. Проверки те же, что для отдельного порта (_sync_single_interface)."""
    if not isinstance(item, dict): raise HTTPException(422, 'Каждая группа портов должна быть объектом')
    name = str(item.get('name') or '').strip()
    if not name: raise HTTPException(422, 'У группы портов должно быть наименование')
    if len(name) > 100: raise HTTPException(422, 'Наименование группы портов не должно превышать 100 символов')
    vlan_mode = item.get('vlan_mode') or None
    if vlan_mode is not None and vlan_mode not in _VLAN_MODES:
        raise HTTPException(422, "Поле vlan_mode группы портов должно быть 'access', 'trunk' или пустым")
    vlan_ids = item.get('vlan_ids') or []
    if not isinstance(vlan_ids, list): raise HTTPException(422, 'Поле vlan_ids группы портов должно быть массивом')
    all_vlans = item.get('all_vlans', False)
    if not isinstance(all_vlans, bool): raise HTTPException(422, 'Поле all_vlans группы портов должно быть true или false')
    # «Все VLAN» группы: как у порта, хранится только признак (а vlan_ids игнорируется), набор VLAN — все VLAN устройства.
    if all_vlans and vlan_mode != 'trunk': raise HTTPException(422, "«Все VLAN» у группы портов возможно только в режиме trunk")
    if all_vlans: vlan_ids = []
    if vlan_ids and vlan_mode is None: raise HTTPException(422, 'VLAN группы портов можно задать только вместе с режимом порта')
    if any(v not in allowed_vlans for v in vlan_ids): raise HTTPException(422, 'Один или несколько VLAN не разрешены для типа данного устройства')
    unique_vlan_ids = list(dict.fromkeys(vlan_ids))
    if vlan_mode == 'access' and len(unique_vlan_ids) > 1: raise HTTPException(422, 'В режиме access у группы портов может быть не более одного VLAN')
    ip_address = str(item.get('ip_address') or '').strip() or None
    prefix = item.get('prefix_length')
    validate_ipv4_field(ip_address, 'IP-адрес группы портов')
    validate_prefix_length_field(prefix, 'Префикс IP-адреса группы портов')
    prefix_length = int(prefix) if ip_address and prefix not in (None, '') else None
    # Назначение — часть общего IP: без адреса не хранится (как и префикс). Колонка IPAddress.purpose — 255 символов.
    ip_purpose = (str(item.get('ip_purpose') or '').strip() or None) if ip_address else None
    if ip_purpose is not None and len(ip_purpose) > _IP_PURPOSE_MAX_LENGTH:
        raise HTTPException(422, f'Назначение IP-адреса группы портов не должно превышать {_IP_PURPOSE_MAX_LENGTH} символов')
    manage_open_ports = bool(item.get('manage_open_ports'))
    raw_ports = item.get('open_ports') or []
    if not isinstance(raw_ports, list): raise HTTPException(422, 'Поле open_ports группы портов должно быть массивом')
    open_ports: list[dict[str, Any]] = []
    for port_data in raw_ports:
        # Строка-плейсхолдер без выбранной записи справочника пропускается, как у порта (см.
        # _sync_interface_open_ports). Без manage_open_ports список открытых портов не хранится.
        if not manage_open_ports or not isinstance(port_data, dict) or not port_data.get('protocol_catalog_id'): continue
        _validate_open_port_catalog(port_data, session)
        open_ports.append({'id': port_data.get('id'), 'protocol_catalog_id': port_data['protocol_catalog_id'], 'transport_protocol': port_data.get('transport_protocol') or 'TCP', 'description': port_data.get('description') or None})
    validate_unique_open_port_numbers((p['protocol_catalog_id'] for p in open_ports), session, f'Группа портов «{name}»')
    return {'name': name, 'vlan_mode': vlan_mode, 'all_vlans': all_vlans, 'vlan_ids': unique_vlan_ids, 'ip_address': ip_address, 'prefix_length': prefix_length, 'ip_purpose': ip_purpose, 'manage_open_ports': manage_open_ports, 'open_ports': open_ports}


def _sync_interface_groups(device_id: str, groups_payload: list[Any], allowed_vlans: set[str], session: Session) -> dict[str, _GroupState]:
    """Создаёт/обновляет группы устройства по payload['groups'] (diff с БД). Возвращает
    {key -> состояние группы}: key — для существующей группы её id, для новой — временный ключ
    клиента, по которому порты в payload['interfaces'][i]['group_key'] на неё ссылаются (у новой
    группы id ещё нет). Удаление отсутствующих в payload групп — _delete_stale_groups() после
    обработки портов."""
    existing = {g.id: g for g in session.scalars(select(InterfaceGroup).where(InterfaceGroup.physical_device_id == device_id)).all()}
    states: dict[str, _GroupState] = {}
    names: set[str] = set()
    for item in groups_payload:
        norm = _normalize_group_item(item, allowed_vlans, session)
        key = item.get('key') or item.get('id')
        if not key: raise HTTPException(422, 'У группы портов должен быть key (id существующей группы или временный ключ новой)')
        if key in states: raise HTTPException(422, 'Ключи групп портов должны быть уникальны')
        if norm['name'].casefold() in names: raise HTTPException(422, 'Наименования групп портов на устройстве должны быть уникальны')
        names.add(norm['name'].casefold())
        group_id = item.get('id')
        if group_id:
            obj = existing.get(group_id)
            if not obj: raise HTTPException(422, 'Группа портов не принадлежит выбранному физическому устройству')
        else:
            obj = InterfaceGroup(physical_device_id=device_id); session.add(obj)
        obj.name = norm['name']; obj.vlan_mode = norm['vlan_mode']; obj.all_vlans = norm['all_vlans']; obj.ip_address = norm['ip_address']
        obj.prefix_length = norm['prefix_length']; obj.ip_purpose = norm['ip_purpose']; obj.manage_open_ports = norm['manage_open_ports']
        session.flush()
        _sync_group_vlans(obj, norm['vlan_ids'], session)
        _sync_group_open_ports(obj, norm['open_ports'], session)
        states[key] = _GroupState(obj, norm['vlan_ids'], norm['open_ports'])
    return states


def _sync_group_vlans(group: InterfaceGroup, vlan_ids: list[str], session: Session) -> None:
    current = session.scalars(select(InterfaceGroupVLAN).where(InterfaceGroupVLAN.group_id == group.id)).all()
    wanted = set(vlan_ids)
    for row in current:
        if row.vlan_id not in wanted: session.delete(row)
    have = {row.vlan_id for row in current}
    for vlan_id in vlan_ids:
        if vlan_id not in have: session.add(InterfaceGroupVLAN(group_id=group.id, vlan_id=vlan_id))


def _sync_group_open_ports(group: InterfaceGroup, open_ports: list[dict[str, Any]], session: Session) -> None:
    old_rows = session.scalars(select(InterfaceGroupOpenPort).where(InterfaceGroupOpenPort.group_id == group.id)).all()
    old_map = {row.id: row for row in old_rows}; seen: set[str] = set()
    for data in open_ports:
        port_id = data.get('id')
        if port_id:
            row = old_map.get(port_id)
            if not row: raise HTTPException(422, 'Открытый порт не принадлежит выбранной группе портов')
            seen.add(port_id)
        else:
            row = InterfaceGroupOpenPort(group_id=group.id); session.add(row)
        row.protocol_catalog_id = data['protocol_catalog_id']; row.transport_protocol = data['transport_protocol']; row.description = data['description']
    for row in old_rows:
        if row.id not in seen: session.delete(row)


def _resolve_interface_group(item: dict[str, Any], states: dict[str, _GroupState]) -> _GroupState | None:
    group_key = item.get('group_key')
    if not group_key: return None
    state = states.get(group_key)
    if not state: raise HTTPException(422, 'Порт ссылается на группу портов, которой нет в payload["groups"]')
    return state


def _apply_group_to_interface(iface: DeviceInterface, state: _GroupState, session: Session) -> None:
    """Записывает в порт значения тех параметров, которыми управляет его группа (заданы в группе):
    режим порта + VLAN, единственный общий IP (адрес, префикс и назначение), полный список
    открытых портов. Повторный вызов с теми
    же значениями ничего не меняет (строки порта обновляются на месте, лишние удаляются, id не
    пересоздаются). Незаданные группой параметры порта не трогаются."""
    group = state.obj
    # autoflush отключён (db.py): без flush() запросы ниже не увидели бы VLAN/IP/порты, только что
    # добавленные _sync_single_interface() в этой же сессии, и продублировали бы их.
    session.flush()
    if group.vlan_mode:
        iface.vlan_mode = group.vlan_mode
        # «Все VLAN» группы: порт получает тот же признак и не хранит связей — набор вычисляется из VLAN устройства.
        iface.all_vlans = bool(group.all_vlans)
        links = session.scalars(select(InterfaceVLAN).where(InterfaceVLAN.interface_id == iface.id)).all()
        wanted = set() if group.all_vlans else set(state.vlan_ids); kept: set[str] = set()
        for link in links:
            if link.vlan_id in wanted and link.vlan_id not in kept: link.mode = group.vlan_mode; kept.add(link.vlan_id)
            else: session.delete(link)
        for vlan_id in ([] if group.all_vlans else state.vlan_ids):
            if vlan_id not in kept: session.add(InterfaceVLAN(interface_id=iface.id, vlan_id=vlan_id, mode=group.vlan_mode))
    if group.ip_address:
        ips = session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == iface.id).order_by(IPAddress.created_at, IPAddress.id)).all()
        ip_obj = ips[0] if ips else IPAddress(owner_type=OwnerType.DEVICE_INTERFACE, owner_id=iface.id)
        if not ips: session.add(ip_obj)
        ip_obj.ip_address = group.ip_address; ip_obj.prefix_length = group.prefix_length; ip_obj.is_management = bool(iface.is_management)
        # Назначение — часть общего IP, как адрес и префикс: группа записывает его безусловно
        # (пустое значение очищает назначение, которое стояло у порта).
        ip_obj.purpose = group.ip_purpose
        for extra in ips[1:]: session.delete(extra)
    if group.manage_open_ports:
        _apply_group_open_ports(iface, state.open_ports, session)


def _apply_group_open_ports(iface: DeviceInterface, group_ports: list[dict[str, Any]], session: Session) -> None:
    """Приводит открытые порты интерфейса в точное соответствие списку группы, не пересоздавая записи:
    строка с тем же (запись справочника, транспорт) остаётся как есть (обновляется только описание);
    оставшиеся лишние строки порта переиспользуются под ещё не размещённые порты группы — меняется
    запись справочника/транспорт, id и дата создания сохраняются (как при правке порта вручную и у ВМ);
    удаляются только строки, которым не хватило пары, создаются только порты группы без пары."""
    rows = session.scalars(
        select(OpenPort).where(OpenPort.owner_type == OwnerType.DEVICE_INTERFACE, OpenPort.owner_id == iface.id).order_by(OpenPort.created_at, OpenPort.id)
    ).all()
    wanted = {(p['protocol_catalog_id'], p['transport_protocol']): p for p in group_ports}
    kept: set[tuple[str, str]] = set()
    spare: list[OpenPort] = []
    for row in rows:
        key = (row.protocol_catalog_id, row.transport_protocol)
        if key in wanted and key not in kept:
            row.description = wanted[key]['description']; kept.add(key)
        else:
            spare.append(row)
    for key, data in wanted.items():
        if key in kept: continue
        if spare:
            row = spare.pop(0)
            row.protocol_catalog_id = data['protocol_catalog_id']; row.transport_protocol = data['transport_protocol']; row.description = data['description']
        else:
            session.add(OpenPort(owner_type=OwnerType.DEVICE_INTERFACE, owner_id=iface.id, protocol_catalog_id=data['protocol_catalog_id'], transport_protocol=data['transport_protocol'], description=data['description']))
    for row in spare: session.delete(row)


def _delete_stale_groups(device_id: str, kept_group_ids: set[str], session: Session) -> None:
    """Удаляет группы устройства, которых нет в payload['groups'], вместе с их VLAN и открытыми
    портами. Порты уже отвязаны (group_id выставлен по payload выше). Сам бэкенд значения портов при
    этом не стирает: PUT передаёт полное состояние порта, и в БД остаётся ровно то, что прислал
    клиент — форма шлёт значения, ранее записанные из группы («оставить»), либо пустые («стереть»,
    выбор пользователя при удалении группы)."""
    stale = [g for g in session.scalars(select(InterfaceGroup).where(InterfaceGroup.physical_device_id == device_id)).all() if g.id not in kept_group_ids]
    for group in stale:
        session.execute(update(DeviceInterface).where(DeviceInterface.group_id == group.id).values(group_id=None))
        session.execute(delete(InterfaceGroupVLAN).where(InterfaceGroupVLAN.group_id == group.id))
        session.execute(delete(InterfaceGroupOpenPort).where(InterfaceGroupOpenPort.group_id == group.id))
        session.delete(group)
    session.flush()
