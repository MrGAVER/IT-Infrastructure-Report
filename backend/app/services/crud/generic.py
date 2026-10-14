"""Generic CRUD: список с фильтрами и пагинацией, создание и изменение записей любого ресурса."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from ...models import AuditLog, Connection, DeviceInterface, DeviceStackMember, InformationSystem, ISProtocol, OpenPort, PhysicalDevice, VirtualMachine, VLAN, VLANDomainDevice
from ...constants import AuditAction
from ..serialization import enrich_devices, enrich_interfaces, enrich_connections, enrich_information_systems, enrich_open_port, enrich_open_ports, serialize
from ..integrity import integrity_error_response
from .audit_log import _describe_update, audit
from .columns import allowed_columns, model_for
from .owned_rows import _validate_is_protocol_number_is_free, _validate_open_port_catalog, _validate_open_port_number_is_free
from .payload import ensure_writable, validate_payload_schema
from .stack_vlan_settings import apply_stack_settings_to_device
from .validators import _release_rack_slot, validate_resource
from .vlan_domains import _auto_assign_new_domain_vlan_to_domain_devices, _stale_group_subinterfaces_on_vlan, _stale_subinterfaces_on_vlan, _unassign_moved_vlan_from_former_domain_devices, assign_domain_vlans_to_device


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


def _apply_ordering(stmt, model):
    if model is AuditLog:
        # Without explicit ordering, "limit" returns whatever order the DB happens to store rows
        # in (insertion order for SQLite) — i.e. the OLDEST entries, not the most recent ones the
        # UI labels "Последние N действий". Audit log is the one resource where recency matters.
        return stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())  # id — чтобы записи с равным временем не «переезжали» между страницами
    # Без ORDER BY порядок строк при offset/limit не гарантирован (на PostgreSQL он может меняться
    # между запросами), и соседние страницы дублировали или пропускали записи. Старые — первыми;
    # id — детерминированный тай-брейк для строк с равным временем создания.
    return stmt.order_by(*[col for col in (getattr(model, 'created_at', None), getattr(model, 'id', None)) if col is not None])


def _apply_search(stmt, model, q: str | None):
    """Поиск q: подстрока без учёта регистра по всем текстовым колонкам модели."""
    if not q:
        return stmt
    text_cols = [c for c in inspect(model).columns if str(c.type).upper().startswith(('VARCHAR', 'TEXT', 'CHAR'))]
    if not text_cols:
        return stmt
    return stmt.where(or_(*[func.lower(c).contains(q.lower(), autoescape=True) for c in text_cols]))  # autoescape: «%» и «_» из поиска — обычные символы, а не шаблон LIKE


def _apply_filters(stmt, model, filters: dict[str, str] | None):
    """Фильтры «поле = значение»; пустое значение означает IS NULL; неизвестное поле — 422."""
    if not filters:
        return stmt
    column_names = {c.key for c in inspect(model).columns}
    for key, value in filters.items():
        if key not in column_names:
            raise HTTPException(422, f'Неизвестное поле фильтра: {key}')
        col = getattr(model, key)
        stmt = stmt.where(col.is_(None)) if value == '' else stmt.where(col == value)
    return stmt


def _apply_date_range(stmt, model, date_from: str | None, date_to: str | None):
    if date_from:
        stmt = stmt.where(model.created_at >= _parse_range_datetime(date_from, end_of_day=False))
    if date_to:
        stmt = stmt.where(model.created_at <= _parse_range_datetime(date_to, end_of_day=True))
    return stmt


# Ресурсы, строки которых перед отдачей обогащаются связанными данными; остальные просто сериализуются.
_ROW_ENRICHERS = {
    PhysicalDevice: enrich_devices,
    DeviceInterface: enrich_interfaces,
    Connection: enrich_connections,
    InformationSystem: enrich_information_systems,
    OpenPort: enrich_open_ports,
}


def _enrich_rows(model, rows, session: Session):
    enricher = _ROW_ENRICHERS.get(model)
    return enricher(rows, session) if enricher else [serialize(row) for row in rows]


def list_resource(resource: str, session: Session, q: str | None = None, offset: int = 0, limit: int = 100, filters: dict[str, str] | None = None, date_from: str | None = None, date_to: str | None = None):
    model = model_for(resource)
    stmt = _apply_ordering(select(model), model)
    stmt = _apply_search(stmt, model, q)
    stmt = _apply_filters(stmt, model, filters)
    stmt = _apply_date_range(stmt, model, date_from, date_to)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.offset(offset).limit(limit)).all()
    return {'items': _enrich_rows(model, rows, session), 'total': total, 'offset': offset, 'limit': limit}


def _set_vm_hypervisor_os(data: dict[str, Any], session: Session) -> None:
    """ВМ на физическом хосте: ОС гипервизора берётся из ОС хоста (или сбрасывается, если у хоста её нет)."""
    host_id = data.get('physical_device_id')
    if host_id:
        host = session.get(PhysicalDevice, host_id)
        data['hypervisor_os_id'] = host.operating_system_id if host and host.operating_system_id else None


def _validate_new_owned_row(model, data: dict[str, Any], session: Session) -> None:
    """Создание открытого порта / протокола ИС: ссылка на справочник и свободный номер порта у владельца."""
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


def _validate_changed_owned_row(model, proposed: dict[str, Any], before: dict[str, Any], session: Session, item_id: str) -> None:
    """Правка открытого порта / протокола ИС: уникальность номера проверяется, только если поменялся сам порт или владелец."""
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


def create_resource(resource: str, payload: dict[str, Any], session: Session):
    ensure_writable(resource)
    payload = validate_payload_schema(resource, payload, is_update=False)
    model = model_for(resource); allowed = allowed_columns(model)
    data = {k: v for k, v in payload.items() if k in allowed}
    if model is VirtualMachine:
        _set_vm_hypervisor_os(data, session)
    _validate_new_owned_row(model, data, session)
    validate_resource(model, data, session, confirm_duplicate=bool(payload.get('confirm_system_name_duplicate')), confirm_rack_reassign=bool(payload.get('confirm_rack_position_reassign')))
    _release_rack_slot(model, data, session)
    obj = model(**data); session.add(obj)
    try:
        session.flush()
        if model is VLAN:
            _auto_assign_new_domain_vlan_to_domain_devices(obj, session)
        if model is VLANDomainDevice:
            assign_domain_vlans_to_device(obj.domain_id, obj.physical_device_id, session)
        if model is DeviceStackMember:
            # Тот же результат, что у POST /device-stacks/{id}/members: общие настройки VLAN стека — новому участнику.
            member = session.get(PhysicalDevice, obj.physical_device_id)
            if member: apply_stack_settings_to_device(session, obj.stack_id, member)
        audit(session, resource, str(obj.id), AuditAction.CREATE, 'Создание записи'); session.commit()
        return enrich_open_port(obj, session) if model is OpenPort else serialize(obj)
    except IntegrityError as exc:
        session.rollback(); raise integrity_error_response(resource, exc) from exc


def _follow_vlan_domain_move(model, obj, payload: dict[str, Any], before: dict[str, Any], session: Session) -> int:
    """Согласует назначения VLAN с устройствами доменов, если VLAN перенесён в другой домен; возвращает, у скольких устройств он снят."""
    # Пункт 2 правки "создание физического устройства": только когда domain_id реально
    # менялся в этом запросе — иначе безобидное редактирование ДРУГОГО поля VLAN (например,
    # описания) на каждый сохранение заново бы проверяло/дублировало привязку к
    # устройствам домена, в котором этот VLAN и так уже давно значится.
    # Перенос VLAN в другой домен: сначала снимаем его с устройств прежнего домена, которых нет в
    # новом, потом назначаем устройствам нового (_unassign_moved_vlan_from_former_domain_devices).
    if model is not VLAN or 'domain_id' not in payload:
        return 0
    unassigned_devices = _unassign_moved_vlan_from_former_domain_devices(obj, before.get('domain_id'), session)
    _auto_assign_new_domain_vlan_to_domain_devices(obj, session)
    return unassigned_devices


def _audit_vlan_domain_move(resource: str, obj, unassigned_devices: int, session: Session) -> None:
    if not unassigned_devices:
        return
    audit(session, resource, str(obj.id), AuditAction.UPDATE, f'VLAN снят с устройств прежнего домена: {unassigned_devices}')
    # Подинтерфейсы на этом VLAN при снятии не удаляются (у них свои IP и открытые порты) — фиксируем, какие
    # остались без разрешённого VLAN: в форме устройства их придётся перенести на другой VLAN или удалить.
    stale = _stale_subinterfaces_on_vlan(str(obj.id), session)
    if stale:
        audit(session, resource, str(obj.id), AuditAction.UPDATE, f'Подинтерфейсы остались на VLAN, не разрешённом устройству ({len(stale)}): ' + '; '.join(stale[:20]) + ('…' if len(stale) > 20 else ''))
    # То же для шаблонов подинтерфейсов групп портов: связи VLAN с группами сняты, а шаблоны на этом VLAN остались.
    stale_groups = _stale_group_subinterfaces_on_vlan(str(obj.id), session)
    if stale_groups:
        audit(session, resource, str(obj.id), AuditAction.UPDATE, f'Подинтерфейсы групп портов остались на VLAN, которого у группы больше нет ({len(stale_groups)}): ' + '; '.join(stale_groups[:20]) + ('…' if len(stale_groups) > 20 else ''))


def update_resource(resource: str, item_id: str, payload: dict[str, Any], session: Session):
    ensure_writable(resource)
    payload = validate_payload_schema(resource, payload, is_update=True)
    model = model_for(resource); obj = session.get(model, item_id)
    if not obj: raise HTTPException(404, 'Запись не найдена')
    allowed = allowed_columns(model); before = {k: getattr(obj, k) for k in allowed}
    proposed = dict(before); proposed.update({k: v for k, v in payload.items() if k in allowed})
    if model is VirtualMachine:
        _set_vm_hypervisor_os(proposed, session)
    _validate_changed_owned_row(model, proposed, before, session, item_id)
    validate_resource(model, proposed, session, item_id, bool(payload.get('confirm_system_name_duplicate')), bool(payload.get('confirm_rack_position_reassign')))
    _release_rack_slot(model, proposed, session, item_id)
    for key, value in payload.items():
        if key in allowed: setattr(obj, key, value)
    if model is VirtualMachine and 'physical_device_id' in proposed:
        obj.hypervisor_os_id = proposed.get('hypervisor_os_id')
    try:
        session.flush()
        unassigned_devices = _follow_vlan_domain_move(model, obj, payload, before, session)
        audit(session, resource, str(obj.id), AuditAction.UPDATE, _describe_update(before, proposed))
        _audit_vlan_domain_move(resource, obj, unassigned_devices, session)
        session.commit()
        return enrich_open_port(obj, session) if model is OpenPort else serialize(obj)
    except IntegrityError as exc:
        session.rollback(); raise integrity_error_response(resource, exc) from exc
