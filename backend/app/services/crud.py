from __future__ import annotations
from datetime import datetime
from typing import Any
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from ..models import AuditLog, Connection, DeviceInterface, DeviceModel, InterfaceIP, InformationSystem, PhysicalDevice, VirtualMachine, ISDepartment, ISIP, ISProtocol, ISDevice, ISVM, ISContainer, InformationSystemSource, ISPlacementAsset, DeviceTypeVLAN, PhysicalDeviceVLAN, InterfaceVLAN, VLAN, VLANDomainDevice
from ..registry import MODEL_MAP, DISPLAY_NAMES, READONLY_RESOURCES
from ..schemas import RESOURCE_SCHEMAS
from ..constants import ErrorCode, AuditAction, SourceType
from .serialization import enrich_devices, enrich_interfaces, enrich_connections, enrich_information_systems, serialize
from .validation import duplicate_system_name, validate_connection, validate_device_location_hierarchy, validate_device_model_relation, validate_hypervisor, validate_operating_system, validate_vm_host, validate_embedded_os

def model_for(resource: str):
    try: return MODEL_MAP[resource]
    except KeyError as exc: raise HTTPException(404, f"Ресурс '{resource}' не найден") from exc

def ensure_writable(resource: str) -> None:
    """Запрещает запись через generic CRUD для ресурсов из READONLY_RESOURCES (сейчас — только
    audit-log). Вызывается из create_resource/update_resource/delete_resource, а не только на
    уровне роутера (api/resources.py), чтобы гарантия действовала для любого текущего и
    будущего вызывающего кода, а не только для одного набора HTTP-эндпоинтов."""
    if resource in READONLY_RESOURCES:
        raise HTTPException(403, f"Ресурс '{resource}' доступен только для чтения")

def validate_payload_schema(resource: str, payload: dict[str, Any], *, is_update: bool) -> dict[str, Any]:
    """Валидирует и приводит типы payload по Pydantic-схеме, если она зарегистрирована для
    этого ресурса (см. schemas.RESOURCE_SCHEMAS: пока только devices/information-systems/vlans
    — код-ревью п.2). Для остальных ресурсов возвращает payload без изменений — они по-прежнему
    проходят через generic CRUD как сырой dict, это осознанное инкрементальное покрытие.

    Возвращает НОВЫЙ dict — исходный payload с наложенными сверху провалидированными полями,
    а не просто dump схемы: так ключи вне схемы (confirm_system_name_duplicate,
    confirm_rack_position_reassign), которые читаются из payload напрямую в create_resource/
    update_resource, не теряются."""
    schemas = RESOURCE_SCHEMAS.get(resource)
    if schemas is None:
        return payload
    schema = schemas[1] if is_update else schemas[0]
    try:
        validated = schema.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, _format_schema_validation_error(exc)) from exc
    return {**payload, **validated.model_dump(exclude_unset=True)}

def _format_schema_validation_error(exc: ValidationError) -> str:
    """Сводит структурированный Pydantic ValidationError к одной строке — в стиле остальных
    422-ошибок этого модуля (см. validate_resource в services/validation.py), чтобы формат
    ошибки был единообразным независимо от того, какой слой её обнаружил."""
    parts = [f"{'.'.join(str(p) for p in err['loc']) or '(payload)'}: {err['msg']}" for err in exc.errors()]
    return 'Ошибка валидации: ' + '; '.join(parts)

def columns_for(model):
    return [{'name': c.key, 'type': str(c.type), 'nullable': c.nullable, 'primary_key': c.primary_key, 'default': None if c.default is None else str(c.default.arg), 'foreign_key': next(iter(c.foreign_keys)).target_fullname if c.foreign_keys else None} for c in inspect(model).columns]

def allowed_columns(model) -> set[str]:
    allowed = {c.key for c in inspect(model).columns if c.key not in {'id', 'created_at', 'updated_at'}}
    if model is InformationSystem: allowed.discard('number')
    return allowed

def audit(session: Session, entity_type: str, entity_id: str, action: str, details: str = '') -> None:
    if entity_type != 'audit-log': session.add(AuditLog(entity_type=entity_type, entity_id=entity_id, action=action, details=details))

def _fmt_audit_value(value: Any) -> str:
    """Короткое читаемое представление значения поля для diff'а в audit-log — не сериализация
    для API (см. serialize()), только текст в одну строку. None и '' показываются одинаково
    ('—') — иначе None → '' выглядело бы как изменение, хотя по сути и то, и то "не заполнено".
    Длинные значения (например, текст описания ИС) обрезаются — иначе правка одного длинного
    текстового поля раздувала бы запись журнала на весь текст целиком."""
    if value is None or value == '':
        return '—'
    if isinstance(value, bool):
        return 'да' if value else 'нет'
    text = str(value)
    return text if len(text) <= 60 else text[:57] + '…'

def _describe_update(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Человекочитаемый diff изменённых полей для audit-log: 'поле: старое → новое', через '; '.
    Раньше update_resource писал в audit-log одну и ту же строку 'Изменение записи' на любое
    изменение ЛЮБОЙ из ~40 сущностей реестра — колонка "Детали" в журнале аудита дублировала
    колонку "Действие" (там уже был бейдж "Изменено"), не добавляя ни одного факта о том, что
    именно изменилось (найдено при ревизии фронтенда на предмет неинформативных технических
    записей, показываемых пользователю). Сравнение по allowed_columns() модели — единый
    механизм для всех ресурсов без хардкода полей под конкретную модель, в отличие от ручного
    списка changes в services/auth.py:update_user (там модель всегда одна — User).
    Сортировка по строке diff'а, а не порядок allowed_columns() (это set(), не гарантированно
    стабильный порядок) — для детерминированного и читаемого результата."""
    changes = sorted(
        f'{key}: {_fmt_audit_value(before[key])} → {_fmt_audit_value(after[key])}'
        for key in after if before.get(key) != after.get(key)
    )
    return '; '.join(changes) if changes else 'Изменение записи (переданные значения совпадают с текущими)'

def _parse_range_datetime(value: str, *, end_of_day: bool) -> datetime:
    """Парсит date_from/date_to для list_resource(). Принимает как чистую дату
    (input[type=date] с фронтенда, 'YYYY-MM-DD'), так и полный ISO datetime.
    Чистая дата в end_of_day-позиции трактуется как конец дня (включительно),
    иначе фильтр 'по 15.08.2026' исключал бы записи, сделанные в течение этого дня."""
    text = value
    if end_of_day and 'T' not in value:
        text = f'{value}T23:59:59.999999'
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(422, f'Некорректная дата: {value}') from exc

def _validate_physical_device(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
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


def _validate_physical_device_vlan(data: dict[str, Any], session: Session) -> None:
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


def _validate_device_model(data: dict[str, Any], session: Session, item_id: str | None) -> None:
    if not data.get('manufacturer_id') or not data.get('device_type_id'): raise HTTPException(422, 'Для модели необходимо указать производителя и тип устройства')
    if data.get('model'):
        stmt = select(DeviceModel).where(DeviceModel.manufacturer_id == data['manufacturer_id'], DeviceModel.device_type_id == data['device_type_id'], DeviceModel.model == data['model'])
        if item_id: stmt = stmt.where(DeviceModel.id != item_id)
        if session.scalar(stmt): raise HTTPException(409, 'Такая модель уже существует для выбранных производителя и типа устройства')


def validate_resource(model, data: dict[str, Any], session: Session, item_id: str | None = None, confirm_duplicate: bool = False, confirm_rack_reassign: bool = False) -> None:
    """Диспетчеризация по типу модели на per-модель валидаторы выше. Вынесено из одной функции
    (была сложностью 18) — сама логика проверок не изменена."""
    if model is PhysicalDevice:
        _validate_physical_device(data, session, item_id, confirm_duplicate, confirm_rack_reassign)
    elif model is VirtualMachine:
        validate_operating_system(data, session); validate_hypervisor(data, session); validate_vm_host(data, session)
    elif model.__name__ == 'PhysicalDeviceVLAN':
        _validate_physical_device_vlan(data, session)
    elif model is DeviceModel:
        _validate_device_model(data, session, item_id)
    elif model is Connection: validate_connection(data, session, item_id)

def list_resource(resource: str, session: Session, q: str | None = None, offset: int = 0, limit: int = 100, filters: dict[str, str] | None = None, date_from: str | None = None, date_to: str | None = None):
    model = model_for(resource); stmt = select(model)
    if model is AuditLog:
        # Without explicit ordering, "limit" returns whatever order the DB happens to store rows
        # in (insertion order for SQLite) — i.e. the OLDEST entries, not the most recent ones the
        # UI labels "Последние N действий". Audit log is the one resource where recency matters.
        stmt = stmt.order_by(AuditLog.created_at.desc())
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
    if date_from:
        stmt = stmt.where(model.created_at >= _parse_range_datetime(date_from, end_of_day=False))
    if date_to:
        stmt = stmt.where(model.created_at <= _parse_range_datetime(date_to, end_of_day=True))
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
    ensure_writable(resource)
    payload = validate_payload_schema(resource, payload, is_update=False)
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
        session.rollback(); raise HTTPException(409, f'Нарушение целостности данных: {str(exc.orig)[:300]}') from exc

def update_resource(resource: str, item_id: str, payload: dict[str, Any], session: Session):
    ensure_writable(resource)
    payload = validate_payload_schema(resource, payload, is_update=True)
    model = model_for(resource); obj = session.get(model, item_id)
    if not obj: raise HTTPException(404, 'Запись не найдена')
    allowed = allowed_columns(model); before = {k: getattr(obj, k) for k in allowed}
    proposed = dict(before); proposed.update({k: v for k, v in payload.items() if k in allowed})
    if model is VirtualMachine and proposed.get('physical_device_id'):
        host = session.get(PhysicalDevice, proposed['physical_device_id'])
        proposed['hypervisor_os_id'] = host.operating_system_id if host and host.operating_system_id else None
    validate_resource(model, proposed, session, item_id, bool(payload.get('confirm_system_name_duplicate')), bool(payload.get('confirm_rack_position_reassign')))
    for key, value in payload.items():
        if key in allowed: setattr(obj, key, value)
    if model is VirtualMachine and 'physical_device_id' in proposed:
        obj.hypervisor_os_id = proposed.get('hypervisor_os_id')
    try:
        session.flush(); audit(session, resource, str(obj.id), AuditAction.UPDATE, _describe_update(before, proposed)); session.commit(); return serialize(obj)
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(409, f'Нарушение целостности данных: {str(exc.orig)[:300]}') from exc

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
    ensure_writable(resource)
    model = model_for(resource); obj = session.get(model, item_id)
    if not obj: raise HTTPException(404, 'Запись не найдена')
    refs = _find_referencing_counts(model, item_id, session)
    if refs:
        details = ', '.join(f'{name}: {count}' for name, count in refs)
        raise HTTPException(409, detail={'code': ErrorCode.REFERENCED_BY_OTHER_RECORDS, 'message': f'Нельзя удалить: запись используется в других данных ({details}).'})
    try:
        session.delete(obj); session.flush(); audit(session, resource, item_id, AuditAction.DELETE, 'Удаление записи'); session.commit(); return {'status': 'deleted', 'id': item_id}
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(409, 'Запись нельзя удалить: на неё ссылаются другие объекты') from exc

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


def sync_interfaces(device_id: str, payload: dict[str, Any], session: Session):
    device = session.get(PhysicalDevice, device_id)
    if not device: raise HTTPException(404, 'Физическое устройство не найдено')
    items = payload.get('interfaces', [])
    if not isinstance(items, list): raise HTTPException(422, 'Поле interfaces должно быть массивом')
    existing = session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id == device_id)).all(); existing_map = {x.id: x for x in existing}; incoming_ids: set[str] = set()
    # Allowed VLANs depend only on the device (its type and its own local VLANs), not on the
    # interface, so they're resolved once here instead of once per interface inside the loop below.
    allowed_type = set(session.scalars(select(DeviceTypeVLAN.vlan_id).where(DeviceTypeVLAN.device_type_id == device.device_type_id)).all())
    allowed_device = set(session.scalars(select(PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id == device.id)).all())
    allowed_vlans = allowed_type | allowed_device
    try:
        for item in items:
            if not isinstance(item, dict): raise HTTPException(422, 'Каждый интерфейс должен быть объектом')
            iid = item.get('id')
            if iid:
                obj = existing_map.get(iid)
                if not obj: raise HTTPException(422, 'Интерфейс не принадлежит выбранному физическому устройству')
                incoming_ids.add(iid)
            else: obj = DeviceInterface(physical_device_id=device_id); session.add(obj)
            _sync_single_interface(obj, item, device, session, allowed_vlans)
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
        session.rollback(); raise HTTPException(409, f'Нарушение целостности данных: {str(exc.orig)[:300]}') from exc


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

_LINKED_TABLE_SPECS = [('departments', ISDepartment), ('ips', ISIP), ('protocols', ISProtocol), ('devices', ISDevice), ('vms', ISVM), ('containers', ISContainer), ('placement_assets', ISPlacementAsset)]


def _sync_linked_table(key: str, model, items: Any, system_id: str, session: Session) -> None:
    """Синхронизирует одну из устаревших связанных таблиц (ISDepartment/ISIP/...), которые
    по-прежнему поддерживаются ради совместимости отчёта Excel. Вынесено из
    sync_information_system_details(), чтобы снизить цикломатическую сложность внешней функции
    (была 25) — сама логика не изменена."""
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
        # obj.id is only needed below to tell which *existing* rows are still referenced — for
        # existing rows it's already known from the query above, so a single flush() after the
        # loop (not one per item) is enough; id generation for new rows isn't needed here.
        if obj.id: seen.add(obj.id)
    session.flush()
    for obj in existing:
        if obj.id not in seen: session.delete(obj)


def _sync_information_system_sources(system_id: str, source_items: Any, session: Session) -> None:
    """Синхронизирует унифицированные записи InformationSystemSource. Вынесено из
    sync_information_system_details() по той же причине, что и _sync_linked_table()."""
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
        # Same reasoning as _sync_linked_table(): a single flush() after the loop is enough.
        if obj.id: seen.add(obj.id)
    session.flush()
    for obj in existing_sources:
        if obj.id not in seen: session.delete(obj)


def sync_information_system_details(system_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    if not session.get(InformationSystem, system_id):
        raise HTTPException(404, 'Информационная система не найдена')
    # Legacy linked tables are still synchronized for Excel/report compatibility.
    try:
        for key, model in _LINKED_TABLE_SPECS:
            _sync_linked_table(key, model, payload.get(key, []), system_id, session)
        _sync_information_system_sources(system_id, payload.get('sources', []), session)
        audit(session, 'information-systems', system_id, AuditAction.UPDATE, 'Обновлены связанные данные ИС (подразделения/протоколы/источники/устройства/ВМ/размещение)')
        session.commit()
        return get_information_system_details(system_id, session)
    except HTTPException:
        session.rollback(); raise
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(409, f'Нарушение целостности данных: {str(exc.orig)[:300]}') from exc

