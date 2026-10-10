"""Generic CRUD: список с фильтрами и пагинацией, создание и изменение записей любого ресурса."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from ...models import AuditLog, Connection, DeviceInterface, InformationSystem, ISProtocol, OpenPort, PhysicalDevice, VirtualMachine, VLAN, VLANDomainDevice
from ...constants import AuditAction
from ..serialization import enrich_devices, enrich_interfaces, enrich_connections, enrich_information_systems, enrich_open_port, enrich_open_ports, serialize
from ..integrity import integrity_error_response
from .audit_log import _describe_update, audit
from .columns import allowed_columns, model_for
from .owned_rows import _validate_is_protocol_number_is_free, _validate_open_port_catalog, _validate_open_port_number_is_free
from .payload import ensure_writable, validate_payload_schema
from .validators import _release_rack_slot, validate_resource
from .vlan_domains import _auto_assign_new_domain_vlan_to_domain_devices, _unassign_moved_vlan_from_former_domain_devices, assign_domain_vlans_to_device


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


def list_resource(resource: str, session: Session, q: str | None = None, offset: int = 0, limit: int = 100, filters: dict[str, str] | None = None, date_from: str | None = None, date_to: str | None = None):
    model = model_for(resource); stmt = select(model)
    if model is AuditLog:
        # Without explicit ordering, "limit" returns whatever order the DB happens to store rows
        # in (insertion order for SQLite) — i.e. the OLDEST entries, not the most recent ones the
        # UI labels "Последние N действий". Audit log is the one resource where recency matters.
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())  # id — чтобы записи с равным временем не «переезжали» между страницами
    else:
        # Без ORDER BY порядок строк при offset/limit не гарантирован (на PostgreSQL он может меняться
        # между запросами), и соседние страницы дублировали или пропускали записи. Старые — первыми;
        # id — детерминированный тай-брейк для строк с равным временем создания.
        stmt = stmt.order_by(*[col for col in (getattr(model, 'created_at', None), getattr(model, 'id', None)) if col is not None])
    if q:
        text_cols = [c for c in inspect(model).columns if str(c.type).upper().startswith(('VARCHAR', 'TEXT', 'CHAR'))]
        if text_cols: stmt = stmt.where(or_(*[func.lower(c).contains(q.lower(), autoescape=True) for c in text_cols]))  # autoescape: «%» и «_» из поиска — обычные символы, а не шаблон LIKE
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
    elif model is OpenPort:
        items = enrich_open_ports(rows, session)
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
    # Правка "убрать текстовые поля Порт/Протокол": новая запись open-ports создаётся ТОЛЬКО через
    # generic-ресурс (ВМ, VMFormModal.vue) — в отличие от интерфейсов устройства, где свой путь
    # синхронизации (_sync_interface_open_ports). port/protocol — больше не колонки этой модели
    # вовсе (см. models.OpenPort); единственное, что здесь ещё нужно — проверить, что
    # protocol_catalog_id ссылается на существующую запись справочника.
    if model is OpenPort:
        _validate_open_port_catalog(data, session)
        _validate_open_port_number_is_free(data, session)
    # Протоколы передачи данных ИС — те же открытые порты, только владелец одна ИС: номер порта в её
    # пределах не повторяется (см. _validate_is_protocol_number_is_free).
    if model is ISProtocol:
        _validate_open_port_catalog(data, session)
        _validate_is_protocol_number_is_free(data, session)
    validate_resource(model, data, session, confirm_duplicate=bool(payload.get('confirm_system_name_duplicate')), confirm_rack_reassign=bool(payload.get('confirm_rack_position_reassign')))
    _release_rack_slot(model, data, session)
    obj = model(**data); session.add(obj)
    try:
        session.flush()
        if model is VLAN:
            _auto_assign_new_domain_vlan_to_domain_devices(obj, session)
        if model is VLANDomainDevice:
            assign_domain_vlans_to_device(obj.domain_id, obj.physical_device_id, session)
        audit(session, resource, str(obj.id), AuditAction.CREATE, 'Создание записи'); session.commit()
        return enrich_open_port(obj, session) if model is OpenPort else serialize(obj)
    except IntegrityError as exc:
        session.rollback(); raise integrity_error_response(resource, exc) from exc


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
    # protocol_catalog_id — NOT NULL в БД с миграции a1b7c9d3e502; port/protocol не колонки этой
    # модели вовсе (см. create_resource выше) — здесь только валидация ссылки на справочник.
    if model is OpenPort:
        _validate_open_port_catalog(proposed, session)
        # Только когда меняется сам порт или владелец: правка описания/транспорта строки, у которой
        # дубликат появился ещё до этого правила, не должна блокироваться (дубли чинят отдельно —
        # GET /integrity/open-port-duplicates показывает, где они есть).
        if any(proposed.get(k) != before.get(k) for k in ('protocol_catalog_id', 'owner_type', 'owner_id')):
            _validate_open_port_number_is_free(proposed, session, item_id)
    if model is ISProtocol:
        _validate_open_port_catalog(proposed, session)
        # Как у открытых портов: правка только описания записи с уже существующим дублем не блокируется.
        if any(proposed.get(k) != before.get(k) for k in ('protocol_catalog_id', 'information_system_id')):
            _validate_is_protocol_number_is_free(proposed, session, item_id)
    validate_resource(model, proposed, session, item_id, bool(payload.get('confirm_system_name_duplicate')), bool(payload.get('confirm_rack_position_reassign')))
    _release_rack_slot(model, proposed, session, item_id)
    for key, value in payload.items():
        if key in allowed: setattr(obj, key, value)
    if model is VirtualMachine and 'physical_device_id' in proposed:
        obj.hypervisor_os_id = proposed.get('hypervisor_os_id')
    try:
        session.flush()
        # Пункт 2 правки "создание физического устройства": только когда domain_id реально
        # менялся в этом запросе — иначе безобидное редактирование ДРУГОГО поля VLAN (например,
        # описания) на каждый сохранение заново бы проверяло/дублировало привязку к
        # устройствам домена, в котором этот VLAN и так уже давно значится.
        # Перенос VLAN в другой домен: сначала снимаем его с устройств прежнего домена, которых нет в
        # новом, потом назначаем устройствам нового (_unassign_moved_vlan_from_former_domain_devices).
        unassigned_devices = 0
        if model is VLAN and 'domain_id' in payload:
            unassigned_devices = _unassign_moved_vlan_from_former_domain_devices(obj, before.get('domain_id'), session)
            _auto_assign_new_domain_vlan_to_domain_devices(obj, session)
        audit(session, resource, str(obj.id), AuditAction.UPDATE, _describe_update(before, proposed))
        if unassigned_devices:
            audit(session, resource, str(obj.id), AuditAction.UPDATE, f'VLAN снят с устройств прежнего домена: {unassigned_devices}')
        session.commit()
        return enrich_open_port(obj, session) if model is OpenPort else serialize(obj)
    except IntegrityError as exc:
        session.rollback(); raise integrity_error_response(resource, exc) from exc
