"""Синхронизация портов (интерфейсов) устройства и их групп."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ...models import DeviceInterface, IPAddress, OpenPort, PhysicalDevice, ProtocolPortCatalog, DeviceTypeVLAN, PhysicalDeviceVLAN, InterfaceVLAN, InterfaceGroup, InterfaceGroupOpenPort, InterfaceGroupVLAN
from ...constants import AuditAction, OwnerType
from ..serialization import enrich_interface_groups, enrich_open_ports, serialize
from ..integrity import integrity_error_response
from ..interface_connections import assert_interfaces_not_connected, sync_interface_connections
from ..validation import validate_ipv4_field, validate_prefix_length_field, validate_unique_open_port_numbers
from .audit_log import audit
from .owned_rows import _IP_PURPOSE_MAX_LENGTH, _validate_open_port_catalog, sync_owner_open_ports


_VLAN_MODES = frozenset({"access", "trunk"})


def _sync_single_interface(obj: DeviceInterface, item: dict[str, Any], device: PhysicalDevice, session: Session, allowed_vlans: set[str]) -> None:
    """Применяет данные одного элемента payload['interfaces'] к объекту DeviceInterface:
    простые поля, VLAN-привязки и вложенные IP. Вынесено из sync_interfaces(), чтобы снизить
    цикломатическую сложность внешней функции (была 24) — сама логика не изменена.

    allowed_vlans приходит готовым от вызывающей стороны: набор допустимых VLAN одинаков для всех
    интерфейсов одного device, поэтому вычисляется один раз в sync_interfaces(), а не запросом на
    каждый интерфейс здесь (было N+1 при синхронизации устройства с несколькими портами)."""
    for key in ('name', 'interface_type_id', 'mac_address', 'speed_id', 'is_management', 'is_data_transfer', 'description'):
        if key in item: setattr(obj, key, item[key])
    # vlan_mode хранится на самом интерфейсе (фикс п.1.3.9 — см. миграцию 5b5ea0e81d32), а не
    # только выводится из InterfaceVLAN.mode: иначе access-порт без единого VLAN нечем было бы
    # запомнить между сохранением и следующей загрузкой. 'trunk', если поле не прислано вовсе, —
    # тот же дефолт, что и у колонки в БД (совместимо со старыми клиентами API).
    vlan_mode = item.get('vlan_mode') or 'trunk'
    if vlan_mode not in _VLAN_MODES:
        raise HTTPException(422, "Поле vlan_mode интерфейса должно быть 'access' или 'trunk'")
    # Аудит fix/usability-batch4 (находка №2): присваиваем ДО flush() — простые поля выше по
    # функции попадут в тот же autoflush-UPDATE, вместо отдельного второго UPDATE на этот же
    # интерфейс при следующем autoflush (session.execute(delete(...)) ниже). При синхронизации
    # устройства с десятками портов это лишний десяток write-запросов на каждый PUT.
    obj.vlan_mode = vlan_mode
    session.flush()
    vlan_ids=item.get('vlan_ids') or []
    if not isinstance(vlan_ids,list): raise HTTPException(422, 'Поле vlan_ids интерфейса должно быть массивом')
    bad=[v for v in vlan_ids if v not in allowed_vlans]
    if bad: raise HTTPException(422, 'Один или несколько VLAN не разрешены для типа данного устройства')
    unique_vlan_ids = list(dict.fromkeys(vlan_ids))
    # Защита на бэкенде того же инварианта, что и validateInterfaceDraftRows() на фронтенде —
    # там это только UI-проверка перед отправкой запроса, здесь гарантия для любого вызывающего
    # API-код напрямую (или старого кэшированного фронтенд-бандла). Читает локальную переменную
    # vlan_mode, а не obj.vlan_mode — та уже присвоена выше и не меняется дальше по функции.
    if vlan_mode == 'access' and len(unique_vlan_ids) > 1:
        raise HTTPException(422, 'В режиме access у порта может быть не более одного VLAN')
    session.execute(delete(InterfaceVLAN).where(InterfaceVLAN.interface_id==obj.id))
    for vlan_id in unique_vlan_ids: session.add(InterfaceVLAN(interface_id=obj.id,vlan_id=vlan_id,mode=vlan_mode))
    ips = item.get('ips') or []
    if not isinstance(ips, list): raise HTTPException(422, 'Поле ips интерфейса должно быть массивом')
    old_ips = session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == obj.id)).all(); old_map = {x.id: x for x in old_ips}; seen: set[str] = set()
    for ip_data in ips:
        if not isinstance(ip_data, dict) or not ip_data.get('ip_address'): continue
        # Код-ревью п.3.4: формат проверялся только на фронтенде (ipValidation.ts) — прямой
        # запрос к API мог записать в IPAddress произвольную строку вместо IPv4-адреса.
        validate_ipv4_field(ip_data.get('ip_address'), 'IP-адрес интерфейса')
        validate_prefix_length_field(ip_data.get('prefix_length'), 'Префикс IP-адреса интерфейса')
        ip_id = ip_data.get('id')
        if ip_id:
            ip_obj = old_map.get(ip_id)
            if not ip_obj: raise HTTPException(422, 'IP не принадлежит выбранному интерфейсу')
            seen.add(ip_id)
        else: ip_obj = IPAddress(owner_type=OwnerType.DEVICE_INTERFACE, owner_id=obj.id); session.add(ip_obj)
        ip_obj.ip_address = ip_data['ip_address']; ip_obj.prefix_length = ip_data.get('prefix_length'); ip_obj.purpose = ip_data.get('purpose'); ip_obj.is_management = bool(obj.is_management)
    for old_ip in old_ips:
        if old_ip.id not in seen: session.delete(old_ip)
    _sync_interface_open_ports(obj, item.get('open_ports') or [], session)


def _sync_interface_open_ports(obj: DeviceInterface, open_ports: Any, session: Session) -> None:
    """п.1.4 (батч4): "Открытые порты" — теперь свойство конкретного интерфейса, а не всего
    устройства (полиморфный OpenPort.owner_type=DEVICE_INTERFACE, owner_id=интерфейс), той же
    diff-схемой по id, что и IP интерфейса чуть выше (см. sync_owner_open_ports). Раньше один
    список открытых портов относился ко всему устройству разом (owner_type=PHYSICAL_DEVICE) —
    это не позволяло корректно заполнить Лист 3 отчёта, где колонка "Перечень открытых портов"
    относится к КОНКРЕТНОМУ физическому/логическому порту (см. reporting.py:_port_open_info)."""
    sync_owner_open_ports(
        OwnerType.DEVICE_INTERFACE, obj.id, open_ports, session,
        owner_label=f"Порт «{obj.name or 'без имени'}»",
        array_error='Поле open_ports интерфейса должно быть массивом',
        foreign_id_error='Открытый порт не принадлежит выбранному интерфейсу',
    )


def sync_interfaces(device_id: str, payload: dict[str, Any], session: Session):
    device = session.get(PhysicalDevice, device_id)
    if not device: raise HTTPException(404, 'Физическое устройство не найдено')
    items = payload.get('interfaces', [])
    if not isinstance(items, list): raise HTTPException(422, 'Поле interfaces должно быть массивом')
    # Группы портов: payload['groups'] — полный список групп устройства (как и interfaces — diff с
    # БД). Ключа нет вовсе (старый клиент API) — группы и group_id портов не трогаем; ключ есть —
    # он единственный источник истины о группах и о принадлежности к ним каждого порта.
    groups_payload = payload.get('groups')
    manage_groups = groups_payload is not None
    if manage_groups and not isinstance(groups_payload, list): raise HTTPException(422, 'Поле groups должно быть массивом')
    existing = session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id == device_id)).all(); existing_map = {x.id: x for x in existing}; incoming_ids: set[str] = set()
    # Allowed VLANs depend only on the device (its type and its own local VLANs), not on the
    # interface, so they're resolved once here instead of once per interface inside the loop below.
    allowed_type = set(session.scalars(select(DeviceTypeVLAN.vlan_id).where(DeviceTypeVLAN.device_type_id == device.device_type_id)).all())
    allowed_device = set(session.scalars(select(PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id == device.id)).all())
    allowed_vlans = allowed_type | allowed_device
    # Подключения портов (необязательный ключ connection в элементе interfaces, см.
    # services/interface_connections.py): применяются после записи всех портов — у новых уже есть id.
    connection_requests: list[tuple[DeviceInterface, Any]] = []
    row_objects: list[DeviceInterface] = []  # порты всех элементов payload по порядку — на них ссылается connection.peer_row
    try:
        group_states = _sync_interface_groups(device_id, groups_payload, allowed_vlans, session) if manage_groups else {}
        for item in items:
            if not isinstance(item, dict): raise HTTPException(422, 'Каждый интерфейс должен быть объектом')
            iid = item.get('id')
            if iid:
                obj = existing_map.get(iid)
                if not obj: raise HTTPException(422, 'Интерфейс не принадлежит выбранному физическому устройству')
                incoming_ids.add(iid)
            else: obj = DeviceInterface(physical_device_id=device_id); session.add(obj)
            group_state = _resolve_interface_group(item, group_states) if manage_groups else None
            if manage_groups: obj.group_id = group_state.obj.id if group_state else None
            _sync_single_interface(obj, item, device, session, allowed_vlans)
            # Параметры группы применяются ПОСЛЕ значений из payload и перекрывают их: группа —
            # источник истины для заданных ею параметров, что бы ни прислал клиент.
            if group_state: _apply_group_to_interface(obj, group_state, session)
            row_objects.append(obj)
            if 'connection' in item: connection_requests.append((obj, item['connection']))
        stale = [obj for obj in existing if obj.id not in incoming_ids]
        assert_interfaces_not_connected(stale, session)
        for obj in existing:
            if obj.id not in incoming_ids:
                session.execute(delete(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == obj.id))
                # Открытые порты полиморфны (нет FK/каскада на уровне БД, см. models.OpenPort) —
                # без явного удаления здесь они осиротели бы при удалении своего интерфейса.
                session.execute(delete(OpenPort).where(OpenPort.owner_type == OwnerType.DEVICE_INTERFACE, OpenPort.owner_id == obj.id))
                session.delete(obj)
        session.flush()
        if manage_groups: _delete_stale_groups(device_id, {state.obj.id for state in group_states.values()}, session)
        connections_changed = sync_interface_connections(connection_requests, session, row_objects) if connection_requests else 0
        all_ifaces = session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id == device_id)).all()
        for iface in all_ifaces: session.execute(update(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == iface.id).values(is_management=bool(iface.is_management)))
        audit(session, 'interfaces', device_id, AuditAction.SYNC, f'Синхронизация интерфейсов: {len(items)}' + (f', групп: {len(groups_payload)}' if manage_groups else '') + (f', подключений изменено: {connections_changed}' if connections_changed else '')); session.commit()
        result = session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id == device_id).order_by(DeviceInterface.name)).all()
        return {'groups': list_interface_groups(device_id, session), 'items': [{
            **serialize(iface),
            'ips': [serialize(ip) for ip in session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == iface.id).order_by(IPAddress.ip_address)).all()],
            # port больше не колонка OpenPort (см. models.py) — сортируем по номеру порта из
            # справочника через join, а не по несуществующей больше колонке.
            'open_ports': enrich_open_ports(
                session.scalars(
                    select(OpenPort)
                    .join(ProtocolPortCatalog, OpenPort.protocol_catalog_id == ProtocolPortCatalog.id)
                    .where(OpenPort.owner_type == OwnerType.DEVICE_INTERFACE, OpenPort.owner_id == iface.id)
                    .order_by(ProtocolPortCatalog.port)
                ).all(),
                session,
            ),
        } for iface in result]}
    except HTTPException:
        session.rollback(); raise
    except IntegrityError as exc:
        session.rollback(); raise integrity_error_response('device-interfaces', exc) from exc


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
    return {'name': name, 'vlan_mode': vlan_mode, 'vlan_ids': unique_vlan_ids, 'ip_address': ip_address, 'prefix_length': prefix_length, 'ip_purpose': ip_purpose, 'manage_open_ports': manage_open_ports, 'open_ports': open_ports}


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
        obj.name = norm['name']; obj.vlan_mode = norm['vlan_mode']; obj.ip_address = norm['ip_address']
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
        links = session.scalars(select(InterfaceVLAN).where(InterfaceVLAN.interface_id == iface.id)).all()
        wanted = set(state.vlan_ids); kept: set[str] = set()
        for link in links:
            if link.vlan_id in wanted and link.vlan_id not in kept: link.mode = group.vlan_mode; kept.add(link.vlan_id)
            else: session.delete(link)
        for vlan_id in state.vlan_ids:
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
        rows = session.scalars(select(OpenPort).where(OpenPort.owner_type == OwnerType.DEVICE_INTERFACE, OpenPort.owner_id == iface.id)).all()
        wanted_ports = {(p['protocol_catalog_id'], p['transport_protocol']): p for p in state.open_ports}
        kept_ports: set[tuple[str, str]] = set()
        for row in rows:
            key = (row.protocol_catalog_id, row.transport_protocol)
            if key in wanted_ports and key not in kept_ports: row.description = wanted_ports[key]['description']; kept_ports.add(key)
            else: session.delete(row)
        for key, data in wanted_ports.items():
            if key not in kept_ports:
                session.add(OpenPort(owner_type=OwnerType.DEVICE_INTERFACE, owner_id=iface.id, protocol_catalog_id=data['protocol_catalog_id'], transport_protocol=data['transport_protocol'], description=data['description']))


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
