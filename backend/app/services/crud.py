from __future__ import annotations
from typing import Any
from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from ..models import AuditLog, Connection, DeviceInterface, DeviceModel, InterfaceIP, InformationSystem, PhysicalDevice, VirtualMachine, ISDepartment, ISIP, ISProtocol, ISDevice, ISVM, ISContainer, InformationSystemSource, ISPlacementAsset, DeviceTypeVLAN, PhysicalDeviceVLAN, InterfaceVLAN, VLAN, VLANDomainDevice
from ..registry import MODEL_MAP, DISPLAY_NAMES
from ..constants import ErrorCode, AuditAction, SourceType
from .serialization import enrich_devices, enrich_interfaces, enrich_connections, enrich_information_systems, serialize
from .validation import duplicate_system_name, validate_connection, validate_device_location_hierarchy, validate_device_model_relation, validate_hypervisor, validate_operating_system, validate_vm_host, validate_embedded_os

def model_for(resource: str):
    try: return MODEL_MAP[resource]
    except KeyError: raise HTTPException(404, f"Ресурс '{resource}' не найден")

def columns_for(model):
    return [{'name': c.key, 'type': str(c.type), 'nullable': c.nullable, 'primary_key': c.primary_key, 'default': None if c.default is None else str(c.default.arg), 'foreign_key': next(iter(c.foreign_keys)).target_fullname if c.foreign_keys else None} for c in inspect(model).columns]

def allowed_columns(model) -> set[str]:
    allowed = {c.key for c in inspect(model).columns if c.key not in {'id', 'created_at', 'updated_at'}}
    if model is InformationSystem: allowed.discard('number')
    return allowed

def audit(session: Session, entity_type: str, entity_id: str, action: str, details: str = '') -> None:
    if entity_type != 'audit-log': session.add(AuditLog(entity_type=entity_type, entity_id=entity_id, action=action, details=details))

def validate_resource(model, data: dict[str, Any], session: Session, item_id: str | None = None, confirm_duplicate: bool = False, confirm_rack_reassign: bool = False) -> None:
    if model is PhysicalDevice:
        validate_device_model_relation(data, session, item_id); validate_operating_system(data, session); validate_embedded_os(data, session); validate_device_location_hierarchy(data, session)
        if data.get('system_name') and duplicate_system_name(session, data['system_name'], item_id) and not confirm_duplicate:
            raise HTTPException(409, detail={'code': ErrorCode.DUPLICATE_SYSTEM_NAME, 'message': 'Системное имя уже используется другим устройством. Сохранить дубликат?'})
        rack_id = data.get('rack_id'); rack_position = data.get('rack_position')
        if rack_id and rack_position:
            stmt = select(PhysicalDevice).where(PhysicalDevice.rack_id == rack_id, PhysicalDevice.rack_position == rack_position)
            if item_id: stmt = stmt.where(PhysicalDevice.id != item_id)
            occupant = session.scalar(stmt)
            if occupant:
                if not confirm_rack_reassign:
                    raise HTTPException(409, detail={'code': ErrorCode.RACK_POSITION_OCCUPIED, 'message': f'Позиция "{rack_position}" в этой стойке уже занята устройством "{occupant.system_name or occupant.serial_number}". Переназначить позицию на текущее устройство?'})
                occupant.rack_position = None
    elif model is VirtualMachine:
        validate_operating_system(data, session); validate_hypervisor(data, session); validate_vm_host(data, session)
    elif model.__name__ == 'PhysicalDeviceVLAN':
        device=session.get(PhysicalDevice, data.get('physical_device_id')) if data.get('physical_device_id') else None
        vlan=session.get(VLAN, data.get('vlan_id')) if data.get('vlan_id') else None
        if not device or not vlan: raise HTTPException(422, 'Необходимо указать физическое устройство и VLAN')
        # A device may define a local VLAN, or use a VLAN from a shared domain.
        # The old device-type VLAN catalog remains compatible, but is no longer
        # required for a newly created device-local VLAN.
        if vlan.domain_id:
            member=session.scalar(select(VLANDomainDevice.id).where(
                VLANDomainDevice.domain_id==vlan.domain_id,
                VLANDomainDevice.physical_device_id==device.id))
            if not member:
                raise HTTPException(422, 'Устройство не включено в домен этого VLAN')
    elif model is DeviceModel:
        if not data.get('manufacturer_id') or not data.get('device_type_id'): raise HTTPException(422, 'Для модели необходимо указать производителя и тип устройства')
        if data.get('model'):
            stmt = select(DeviceModel).where(DeviceModel.manufacturer_id == data['manufacturer_id'], DeviceModel.device_type_id == data['device_type_id'], DeviceModel.model == data['model'])
            if item_id: stmt = stmt.where(DeviceModel.id != item_id)
            if session.scalar(stmt): raise HTTPException(409, 'Такая модель уже существует для выбранных производителя и типа устройства')
    elif model is Connection: validate_connection(data, session, item_id)

def list_resource(resource: str, session: Session, q: str | None = None, offset: int = 0, limit: int = 100, filters: dict[str, str] | None = None):
    model = model_for(resource); stmt = select(model)
    if q:
        text_cols = [c for c in inspect(model).columns if str(c.type).upper().startswith(('VARCHAR', 'TEXT', 'CHAR'))]
        if text_cols: stmt = stmt.where(or_(*[func.lower(c).contains(q.lower()) for c in text_cols]))
    if filters:
        column_names = {c.key for c in inspect(model).columns}
        for key, value in filters.items():
            if key not in column_names:
                raise HTTPException(422, f'Неизвестное поле фильтра: {key}')
            col = getattr(model, key)
            if value == '':
                stmt = stmt.where(col.is_(None))
            else:
                stmt = stmt.where(col == value)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.offset(offset).limit(limit)).all()
    if model is PhysicalDevice:
        items = enrich_devices(rows, session)
    elif model is DeviceInterface:
        items = enrich_interfaces(rows, session)
    elif model is Connection:
        items = enrich_connections(rows, session)
    elif model is InformationSystem:
        items = enrich_information_systems(rows, session)
    else:
        items = [serialize(row) for row in rows]
    return {'items': items, 'total': total, 'offset': offset, 'limit': limit}

def create_resource(resource: str, payload: dict[str, Any], session: Session):
    model = model_for(resource); allowed = allowed_columns(model)
    data = {k: v for k, v in payload.items() if k in allowed}
    if model is VirtualMachine and data.get('physical_device_id'):
        host = session.get(PhysicalDevice, data['physical_device_id'])
        data['hypervisor_os_id'] = host.operating_system_id if host and host.operating_system_id else None
    validate_resource(model, data, session, confirm_duplicate=bool(payload.get('confirm_system_name_duplicate')), confirm_rack_reassign=bool(payload.get('confirm_rack_position_reassign')))
    obj = model(**data); session.add(obj)
    try:
        session.flush(); audit(session, resource, str(obj.id), AuditAction.CREATE, 'Создание записи'); session.commit(); return serialize(obj)
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(409, f'Нарушение целостности данных: {str(exc.orig)[:300]}')

def update_resource(resource: str, item_id: str, payload: dict[str, Any], session: Session):
    model = model_for(resource); obj = session.get(model, item_id)
    if not obj: raise HTTPException(404, 'Запись не найдена')
    allowed = allowed_columns(model); proposed = {k: getattr(obj, k) for k in allowed}; proposed.update({k: v for k, v in payload.items() if k in allowed})
    if model is VirtualMachine and proposed.get('physical_device_id'):
        host = session.get(PhysicalDevice, proposed['physical_device_id'])
        proposed['hypervisor_os_id'] = host.operating_system_id if host and host.operating_system_id else None
    validate_resource(model, proposed, session, item_id, bool(payload.get('confirm_system_name_duplicate')), bool(payload.get('confirm_rack_position_reassign')))
    for key, value in payload.items():
        if key in allowed: setattr(obj, key, value)
    if model is VirtualMachine and 'physical_device_id' in proposed:
        obj.hypervisor_os_id = proposed.get('hypervisor_os_id')
    try:
        session.flush(); audit(session, resource, str(obj.id), AuditAction.UPDATE, 'Изменение записи'); session.commit(); return serialize(obj)
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(409, f'Нарушение целостности данных: {str(exc.orig)[:300]}')

def _find_referencing_counts(model, item_id: str, session: Session) -> list[tuple[str, int]]:
    """Для каждого другого зарегистрированного ресурса считает, сколько его записей ссылаются
    (через FK) на удаляемую запись. Используется, чтобы дать конкретное предупреждение перед
    удалением, а не полагаться только на то, что БД сама остановит операцию через FK-констрейнт."""
    target_table = model.__tablename__
    results: list[tuple[str, int]] = []
    for resource_key, other_model in MODEL_MAP.items():
        if other_model is model:
            continue
        for c in inspect(other_model).columns:
            if not c.foreign_keys:
                continue
            target = next(iter(c.foreign_keys)).target_fullname
            if target.split('.')[0] != target_table:
                continue
            count = session.scalar(select(func.count()).select_from(other_model).where(c == item_id)) or 0
            if count:
                results.append((DISPLAY_NAMES.get(resource_key, resource_key), count))
    return results

def delete_resource(resource: str, item_id: str, session: Session):
    model = model_for(resource); obj = session.get(model, item_id)
    if not obj: raise HTTPException(404, 'Запись не найдена')
    refs = _find_referencing_counts(model, item_id, session)
    if refs:
        details = ', '.join(f'{name}: {count}' for name, count in refs)
        raise HTTPException(409, detail={'code': ErrorCode.REFERENCED_BY_OTHER_RECORDS, 'message': f'Нельзя удалить: запись используется в других данных ({details}).'})
    try:
        session.delete(obj); session.flush(); audit(session, resource, item_id, AuditAction.DELETE, 'Удаление записи'); session.commit(); return {'status': 'deleted', 'id': item_id}
    except IntegrityError:
        session.rollback(); raise HTTPException(409, 'Запись нельзя удалить: на неё ссылаются другие объекты')

def sync_interfaces(device_id: str, payload: dict[str, Any], session: Session):
    device = session.get(PhysicalDevice, device_id)
    if not device: raise HTTPException(404, 'Физическое устройство не найдено')
    items = payload.get('interfaces', [])
    if not isinstance(items, list): raise HTTPException(422, 'Поле interfaces должно быть массивом')
    existing = session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id == device_id)).all(); existing_map = {x.id: x for x in existing}; incoming_ids: set[str] = set()
    try:
        for item in items:
            if not isinstance(item, dict): raise HTTPException(422, 'Каждый интерфейс должен быть объектом')
            iid = item.get('id')
            if iid:
                obj = existing_map.get(iid)
                if not obj: raise HTTPException(422, 'Интерфейс не принадлежит выбранному физическому устройству')
                incoming_ids.add(iid)
            else: obj = DeviceInterface(physical_device_id=device_id); session.add(obj)
            for key in ('name', 'interface_type_id', 'mac_address', 'speed_id', 'is_management', 'is_data_transfer', 'description'):
                if key in item: setattr(obj, key, item[key])
            session.flush()
            vlan_ids=item.get('vlan_ids') or []
            if not isinstance(vlan_ids,list): raise HTTPException(422, 'Поле vlan_ids интерфейса должно быть массивом')
            allowed_type=set(session.scalars(select(DeviceTypeVLAN.vlan_id).where(DeviceTypeVLAN.device_type_id==device.device_type_id)).all())
            allowed_device=set(session.scalars(select(PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id==device.id)).all())
            allowed=set(allowed_type)|set(allowed_device)
            bad=[v for v in vlan_ids if v not in allowed]
            if bad: raise HTTPException(422, 'Один или несколько VLAN не разрешены для типа данного устройства')
            session.execute(delete(InterfaceVLAN).where(InterfaceVLAN.interface_id==obj.id))
            for vlan_id in dict.fromkeys(vlan_ids): session.add(InterfaceVLAN(interface_id=obj.id,vlan_id=vlan_id,mode=item.get('vlan_mode')))
            ips = item.get('ips') or []
            if not isinstance(ips, list): raise HTTPException(422, 'Поле ips интерфейса должно быть массивом')
            old_ips = session.scalars(select(InterfaceIP).where(InterfaceIP.interface_id == obj.id)).all(); old_map = {x.id: x for x in old_ips}; seen: set[str] = set()
            for ip_data in ips:
                if not isinstance(ip_data, dict) or not ip_data.get('ip_address'): continue
                ip_id = ip_data.get('id')
                if ip_id:
                    ip_obj = old_map.get(ip_id)
                    if not ip_obj: raise HTTPException(422, 'IP не принадлежит выбранному интерфейсу')
                    seen.add(ip_id)
                else: ip_obj = InterfaceIP(interface_id=obj.id); session.add(ip_obj)
                ip_obj.ip_address = ip_data['ip_address']; ip_obj.prefix_length = ip_data.get('prefix_length'); ip_obj.purpose = ip_data.get('purpose'); ip_obj.is_management = bool(obj.is_management)
            for old_ip in old_ips:
                if old_ip.id not in seen: session.delete(old_ip)
        for obj in existing:
            if obj.id not in incoming_ids: session.execute(delete(InterfaceIP).where(InterfaceIP.interface_id == obj.id)); session.delete(obj)
        session.flush()
        all_ifaces = session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id == device_id)).all()
        for iface in all_ifaces: session.execute(update(InterfaceIP).where(InterfaceIP.interface_id == iface.id).values(is_management=bool(iface.is_management)))
        audit(session, 'interfaces', device_id, AuditAction.SYNC, f'Синхронизация интерфейсов: {len(items)}'); session.commit()
        result = session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id == device_id).order_by(DeviceInterface.name)).all()
        return {'items': [{**serialize(iface), 'ips': [serialize(ip) for ip in session.scalars(select(InterfaceIP).where(InterfaceIP.interface_id == iface.id).order_by(InterfaceIP.ip_address)).all()]} for iface in result]}
    except HTTPException:
        session.rollback(); raise
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(409, f'Нарушение целостности данных: {str(exc.orig)[:300]}')


def get_information_system_details(system_id: str, session: Session) -> dict[str, Any]:
    if not session.get(InformationSystem, system_id):
        raise HTTPException(404, 'Информационная система не найдена')
    return {
        'departments': [serialize(x) for x in session.scalars(select(ISDepartment).where(ISDepartment.information_system_id == system_id)).all()],
        'ips': [serialize(x) for x in session.scalars(select(ISIP).where(ISIP.information_system_id == system_id)).all()],
        'protocols': [serialize(x) for x in session.scalars(select(ISProtocol).where(ISProtocol.information_system_id == system_id)).all()],
        'devices': [serialize(x) for x in session.scalars(select(ISDevice).where(ISDevice.information_system_id == system_id)).all()],
        'vms': [serialize(x) for x in session.scalars(select(ISVM).where(ISVM.information_system_id == system_id)).all()],
        'containers': [serialize(x) for x in session.scalars(select(ISContainer).where(ISContainer.information_system_id == system_id)).all()],
        'sources': [serialize(x) for x in session.scalars(select(InformationSystemSource).where(InformationSystemSource.information_system_id == system_id)).all()],
        'placement_assets': [serialize(x) for x in session.scalars(select(ISPlacementAsset).where(ISPlacementAsset.information_system_id == system_id)).all()],
    }

def sync_information_system_details(system_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    if not session.get(InformationSystem, system_id):
        raise HTTPException(404, 'Информационная система не найдена')
    # Legacy linked tables are still synchronized for Excel/report compatibility.
    specs = [('departments', ISDepartment), ('ips', ISIP), ('protocols', ISProtocol), ('devices', ISDevice), ('vms', ISVM), ('containers', ISContainer), ('placement_assets', ISPlacementAsset)]
    try:
        for key, model in specs:
            items = payload.get(key, [])
            if not isinstance(items, list): raise HTTPException(422, f'Поле {key} должно быть массивом')
            existing = session.scalars(select(model).where(model.information_system_id == system_id)).all()
            existing_map = {x.id: x for x in existing}; seen=set()
            for item in items:
                if not isinstance(item, dict): continue
                obj = existing_map.get(item.get('id')) if item.get('id') else model(information_system_id=system_id)
                if obj is None: raise HTTPException(422, f'Запись {key} не принадлежит выбранной ИС')
                if not getattr(obj, 'id', None): session.add(obj)
                for col in inspect(model).columns:
                    if col.key not in {'id','created_at','updated_at','information_system_id'} and col.key in item:
                        value = item[col.key]
                        # An empty string from a disabled/unselected <select> must not be written into a
                        # foreign-key column: it is not NULL, so SQLite/Postgres reject it with a FK violation
                        # instead of treating it as "no value". Normalize to NULL for FK columns only.
                        if value == '' and col.foreign_keys: value = None
                        setattr(obj, col.key, value)
                session.flush(); seen.add(obj.id)
            for obj in existing:
                if obj.id not in seen: session.delete(obj)
        # Unified source rows
        source_items = payload.get('sources', [])
        if not isinstance(source_items, list): raise HTTPException(422, 'Поле sources должно быть массивом')
        existing_sources = session.scalars(select(InformationSystemSource).where(InformationSystemSource.information_system_id == system_id)).all()
        source_map = {x.id: x for x in existing_sources}; seen=set()
        for item in source_items:
            if not isinstance(item, dict): continue
            source_type = item.get('source_type') or SourceType.MANUAL
            if source_type not in SourceType.ALL: raise HTTPException(422, 'Недопустимый тип источника')
            obj = source_map.get(item.get('id')) if item.get('id') else InformationSystemSource(information_system_id=system_id)
            if obj is None: raise HTTPException(422, 'Источник не принадлежит выбранной ИС')
            if not getattr(obj, 'id', None): session.add(obj)
            for k in ('source_type','physical_device_id','virtual_machine_id','container_id','ip_address','purpose','role','external_interaction'):
                value = item.get(k)
                # Same empty-string-vs-NULL issue as above: disabled selects for the fields that don't
                # apply to the chosen source_type still submit '' rather than null.
                if value == '' and k in ('physical_device_id','virtual_machine_id','container_id'): value = None
                setattr(obj, k, value)
            session.flush(); seen.add(obj.id)
        for obj in existing_sources:
            if obj.id not in seen: session.delete(obj)
        session.commit()
        return get_information_system_details(system_id, session)
    except HTTPException:
        session.rollback(); raise
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(409, f'Нарушение целостности данных: {str(exc.orig)[:300]}')

