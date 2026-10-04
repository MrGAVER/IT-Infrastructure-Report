from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import delete, func, literal, or_, select, union_all, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from ..models import AuditLog, Connection, Container, DeployedSoftware, DeviceInterface, DeviceModel, DeviceStack, DeviceStackMember, DeviceType, DiagramIcon, IPAddress, InformationSystem, OpenPort, PhysicalDevice, ProtocolPortCatalog, VirtualMachine, ISDepartment, ISProtocol, InformationSystemSource, ISPlacementAsset, DeviceTypeVLAN, PhysicalDeviceVLAN, InterfaceVLAN, VLAN, VLANDomain, VLANDomainDevice, InterfaceGroup, InterfaceGroupOpenPort, InterfaceGroupVLAN, SoftwareAsset
from ..registry import MODEL_MAP, DISPLAY_NAMES, READONLY_RESOURCES
from ..schemas import RESOURCE_SCHEMAS
from ..constants import ErrorCode, AuditAction, SourceType, OwnerType
from .serialization import enrich_devices, enrich_interface_groups, enrich_interfaces, enrich_connections, enrich_information_systems, enrich_open_port, enrich_open_ports, serialize
from .diagram_icons import validate_svg_markup
from .integrity import format_referenced_message, source_reference_refs
from .validation import duplicate_system_name, validate_connection, validate_container_host, validate_device_location_hierarchy, validate_device_model_relation, validate_hypervisor, validate_ipv4_field, validate_operating_system, validate_prefix_length_field, validate_vm_host, validate_embedded_os, validate_support_method_organization, validate_unique_open_port_numbers

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
    # Одобрение расхождения ролей портов пишется только эндпоинтами services/connection_review.py:
    # иначе клиент мог бы «одобрить» подключение произвольной строкой в обход проверки статуса.
    if model is Connection: allowed.discard('port_config_approved_signature')
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


def _validate_virtual_machine_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    validate_operating_system(data, session); validate_hypervisor(data, session); validate_vm_host(data, session)

def _validate_container_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    validate_container_host(data)

def _validate_physical_device_vlan_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    _validate_physical_device_vlan(data, session)

def _validate_device_model_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    _validate_device_model(data, session, item_id)

def _validate_connection_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    validate_connection(data, session, item_id)

def _validate_device_type_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    # Интеграционный фикс (слияние feature/network-topology-diagram + fix/usability-batch4):
    # DeviceType.category_id стал обязательным NOT NULL FK в рамках фичи диаграммы топологии
    # сети (models.py, миграция 38e9b2624a53), но ни generic-валидатор здесь, ни
    # quickAdd/schema.ts не были обновлены под это требование — POST /resources/device-types
    # без category_id падал сырым 409 "NOT NULL constraint failed" вместо понятной ошибки.
    # Саму ссылочную целостность (существует ли такая категория) отдельно не проверяем —
    # некорректный category_id всё равно упадёт на FK при commit() и обработается уже
    # существующим общим обработчиком IntegrityError в create_resource/update_resource.
    if not data.get('category_id'):
        raise HTTPException(422, 'Поле category_id обязательно для типа устройства')

def _validate_diagram_icon_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    # Код-ревью п.3.1: без этой проверки svg_markup сохранялся бы в БД как есть и затем
    # выполнялся бы в браузере через v-html (фронтенд) и при экспорте .svg (бэкенд).
    validate_svg_markup(data.get('svg_markup'))

def _validate_ip_address_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    # Код-ревью п.3.4 + объединение InterfaceIP/VMIP в IPAddress (owner_type/owner_id, миграция
    # d8e35a1c7f60): владение интерфейсом синхронизируется отдельной функцией
    # (_sync_interface_ips, свой вызов validate_ipv4_field ниже по файлу), владение источником ИС —
    # тоже отдельной (_sync_information_system_sources). Этот валидатор покрывает оставшийся путь —
    # ПОЛНОСТЬЮ generic create_resource/update_resource (владение виртуальной машиной, как и было
    # у VMIP до объединения).
    validate_ipv4_field(data.get('ip_address'), 'IP-адрес')
    validate_prefix_length_field(data.get('prefix_length'), 'Префикс IP-адреса')

def _validate_information_system_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    validate_support_method_organization(data, session)

# Реестр валидаторов по модели (код-ревью п.3.5): раньше это была цепочка if/elif внутри
# validate_resource() — каждая новая модель, которой требуется своя проверка, была обязана
# трогать тело диспетчера (нарушение OCP; интеграция feature/network-topology-diagram и
# fix/usability-batch4 уже доказала риск на примере DeviceType). Теперь новая модель
# добавляется одной строкой сюда, без изменения самой функции validate_resource(). Все
# значения — вызываемые с единой сигнатурой (data, session, item_id, confirm_duplicate,
# confirm_rack_reassign) — там, где исходный валидатор её не использует, параметры просто
# игнорируются тонкой обёрткой-адаптером выше.
def _validate_device_stack_member_entry(data: dict[str, Any], session: Session, item_id: str | None, confirm_duplicate: bool, confirm_rack_reassign: bool) -> None:
    """Пункт 5 правки "создание физического устройства": устройство может состоять максимум в
    ОДНОМ стеке одновременно (см. UniqueConstraint('physical_device_id') на DeviceStackMember) —
    без этой проверки повторная попытка добавить уже состоящее в другом стеке устройство падала
    бы сырым 409 IntegrityError вместо понятного сообщения с названием стека, где оно уже состоит."""
    if not data.get('stack_id') or not data.get('physical_device_id'):
        raise HTTPException(422, 'Необходимо указать стек и устройство')
    existing = session.scalar(select(DeviceStackMember).where(DeviceStackMember.physical_device_id == data['physical_device_id']))
    if existing and existing.id != item_id:
        stack = session.get(DeviceStack, existing.stack_id)
        raise HTTPException(409, f'Устройство уже состоит в стеке «{stack.name if stack else existing.stack_id}»')

_RESOURCE_VALIDATORS: dict[type, Callable[[dict[str, Any], Session, str | None, bool, bool], None]] = {
    PhysicalDevice: _validate_physical_device,
    VirtualMachine: _validate_virtual_machine_entry,
    Container: _validate_container_entry,
    PhysicalDeviceVLAN: _validate_physical_device_vlan_entry,
    DeviceModel: _validate_device_model_entry,
    Connection: _validate_connection_entry,
    DeviceType: _validate_device_type_entry,
    DiagramIcon: _validate_diagram_icon_entry,
    IPAddress: _validate_ip_address_entry,
    InformationSystem: _validate_information_system_entry,
    DeviceStackMember: _validate_device_stack_member_entry,
}

def validate_resource(model, data: dict[str, Any], session: Session, item_id: str | None = None, confirm_duplicate: bool = False, confirm_rack_reassign: bool = False) -> None:
    """Диспетчеризация по типу модели на per-модель валидаторы в _RESOURCE_VALIDATORS.
    Модели без зарегистрированного валидатора (большинство ~40 ресурсов реестра) проходят без
    дополнительных проверок — как и раньше, это не бага, а осознанный дизайн: не для каждого
    ресурса нужна валидация сверх generic CRUD/FK-констрейнтов БД."""
    validator = _RESOURCE_VALIDATORS.get(model)
    if validator is not None:
        validator(data, session, item_id, confirm_duplicate, confirm_rack_reassign)

def list_resource(resource: str, session: Session, q: str | None = None, offset: int = 0, limit: int = 100, filters: dict[str, str] | None = None, date_from: str | None = None, date_to: str | None = None):
    model = model_for(resource); stmt = select(model)
    if model is AuditLog:
        # Without explicit ordering, "limit" returns whatever order the DB happens to store rows
        # in (insertion order for SQLite) — i.e. the OLDEST entries, not the most recent ones the
        # UI labels "Последние N действий". Audit log is the one resource where recency matters.
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())  # id — чтобы записи с равным временем не «переезжали» между страницами
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
    elif model is OpenPort:
        items = enrich_open_ports(rows, session)
    else:
        items = [serialize(row) for row in rows]
    return {'items': items, 'total': total, 'offset': offset, 'limit': limit}

def _auto_assign_new_domain_vlan_to_domain_devices(vlan: 'VLAN', session: Session) -> None:
    """Правка "VLAN домена": VLAN, заведённый в «справочник VLAN» (VLANFormModal.vue) сразу с
    привязкой к домену — или привязанный к домену позже обновлением domain_id — должен появиться в
    блоке «VLAN устройства» ВСЕХ физических устройств этого домена (участников VLANDomainDevice и
    устройства-источника) без ручного шага «Синхронизировать».

    Раньше (п.2 правки "создание физического устройства") VLAN назначался только устройству-
    источнику, а остальные участники получали его лишь при ручной синхронизации (sync_vlan_domain
    реплицирует набор VLAN источника на участников), из-за чего новый VLAN не появлялся на
    устройствах домена. Источник учитывается отдельно от участников: он может не числиться в
    VLANDomainDevice.

    Уже назначенное не дублируется (uq_physical_device_vlan), поэтому вызов безопасно повторять.
    Если VLAN не привязан к домену или у домена нет ни участников, ни источника — тихо выходим:
    это не ошибка, а обычный локальный или пока пустой домен. Два запроса на весь домен, а не по
    запросу на устройство."""
    if not vlan.domain_id:
        return
    domain = session.get(VLANDomain, vlan.domain_id)
    if not domain:
        return
    device_ids = set(session.scalars(select(VLANDomainDevice.physical_device_id).where(VLANDomainDevice.domain_id == domain.id)).all())
    if domain.source_device_id:
        device_ids.add(domain.source_device_id)
    if not device_ids:
        return
    already_assigned = set(session.scalars(
        select(PhysicalDeviceVLAN.physical_device_id).where(
            PhysicalDeviceVLAN.vlan_id == vlan.id,
            PhysicalDeviceVLAN.physical_device_id.in_(device_ids),
        )
    ).all())
    for device_id in sorted(device_ids - already_assigned):
        session.add(PhysicalDeviceVLAN(physical_device_id=device_id, vlan_id=vlan.id, description=vlan.description))


def assign_domain_vlans_to_device(domain_id: str | None, physical_device_id: str | None, session: Session) -> None:
    """Пункт 2 правки "домен VLAN": устройство, добавленное в домен, должно СРАЗУ получить набор
    VLAN, уже определённых для этого домена (VLAN.domain_id == domain_id) — до этой правки это
    происходило только при следующем ручном "Синхронизировать" (sync_vlan_domain), не при самом
    добавлении. Публичная (без "_", в отличие от большинства helper'ов рядом) — вызывается не
    только отсюда (хук ниже, для VLANDomainDevice, созданного через generic-ресурс — этим путём
    идёт, например, DeviceFormModal.vue:persistPendingDomainMemberships), но и напрямую из
    api/system.py:add_vlan_domain_member (тот строит VLANDomainDevice сам, в обход
    create_resource, ради собственной идемпотентности — см. её комментарий).

    Если у домена ещё нет ни одного своего VLAN (устройство-источник не задано или домен ни разу
    не синхронизировался) — присваивать нечего, это не ошибка, а обычное новое устройство в ещё
    пустом домене."""
    if not domain_id or not physical_device_id:
        return
    domain_vlans = session.scalars(select(VLAN).where(VLAN.domain_id == domain_id)).all()
    if not domain_vlans:
        return
    existing_ids = set(session.scalars(select(PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id == physical_device_id)).all())
    for v in domain_vlans:
        if v.id not in existing_ids:
            session.add(PhysicalDeviceVLAN(physical_device_id=physical_device_id, vlan_id=v.id, description=v.description))


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
    validate_resource(model, data, session, confirm_duplicate=bool(payload.get('confirm_system_name_duplicate')), confirm_rack_reassign=bool(payload.get('confirm_rack_position_reassign')))
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
    # protocol_catalog_id — NOT NULL в БД с миграции a1b7c9d3e502; port/protocol не колонки этой
    # модели вовсе (см. create_resource выше) — здесь только валидация ссылки на справочник.
    if model is OpenPort:
        _validate_open_port_catalog(proposed, session)
        # Только когда меняется сам порт или владелец: правка описания/транспорта строки, у которой
        # дубликат появился ещё до этого правила, не должна блокироваться (дубли чинят отдельно —
        # GET /integrity/open-port-duplicates показывает, где они есть).
        if any(proposed.get(k) != before.get(k) for k in ('protocol_catalog_id', 'owner_type', 'owner_id')):
            _validate_open_port_number_is_free(proposed, session, item_id)
    validate_resource(model, proposed, session, item_id, bool(payload.get('confirm_system_name_duplicate')), bool(payload.get('confirm_rack_position_reassign')))
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
        if model is VLAN and 'domain_id' in payload:
            _auto_assign_new_domain_vlan_to_domain_devices(obj, session)
        audit(session, resource, str(obj.id), AuditAction.UPDATE, _describe_update(before, proposed)); session.commit()
        return enrich_open_port(obj, session) if model is OpenPort else serialize(obj)
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(409, f'Нарушение целостности данных: {str(exc.orig)[:300]}') from exc

def _find_referencing_counts(model, item_id: str, session: Session) -> list[tuple[str, int]]:
    """Для каждого другого зарегистрированного ресурса считает, сколько его записей ссылаются
    (через FK) на удаляемую запись. Используется, чтобы дать конкретное предупреждение перед
    удалением, а не полагаться только на то, что БД сама остановит операцию через FK-констрейнт.

    Код-ревью п.3.7: раньше здесь был отдельный SELECT COUNT(*) на каждую FK-колонку каждой из
    ~40 моделей реестра (MODEL_MAP) — при удалении часто ссылаемой записи (например,
    производителя устройства) это десятки последовательных round-trip'ов к БД на одно
    удаление. Теперь все подзапросы объединяются в один через UNION ALL и выполняются ОДНИМ
    запросом; каждая ветка несёт свой порядковый номер (ord) как обычную колонку данных, а не
    полагается на порядок строк, в котором сервер БД решит вернуть результат UNION ALL (для
    SQLite и PostgreSQL это на практике совпадает с порядком объявления веток, но опираться на
    недокументированное поведение не стоит) — после выполнения строки сортируются по этому
    номеру в Python, что и восстанавливает исходный, стабильный порядок вывода."""
    target_table = model.__tablename__
    resource_keys: list[str] = []
    subqueries = []
    for resource_key, other_model in MODEL_MAP.items():
        if other_model is model:
            continue
        for c in inspect(other_model).columns:
            if not c.foreign_keys:
                continue
            target = next(iter(c.foreign_keys)).target_fullname
            if target.split('.')[0] != target_table:
                continue
            subqueries.append(
                select(literal(len(resource_keys)).label('ord'), func.count().label('cnt'))
                .select_from(other_model).where(c == item_id)
            )
            resource_keys.append(resource_key)
    if not subqueries:
        return []
    combined = union_all(*subqueries) if len(subqueries) > 1 else subqueries[0]
    rows = sorted(session.execute(combined).all(), key=lambda row: row.ord)
    return [
        (DISPLAY_NAMES.get(resource_keys[row.ord], resource_keys[row.ord]), row.cnt)
        for row in rows if row.cnt
    ]

# Код-ревью (отчёт по рефакторингу и безопасности, находка 1): открытые порты (OpenPort),
# развёрнутое ПО (DeployedSoftware) и IP-адреса (IPAddress) — три модели с полиморфным владельцем
# (owner_type/owner_id без настоящего FK), поэтому _find_referencing_counts() выше их структурно
# не видит. Значение словаря — СПИСОК (модель, owner_type), не один элемент: у одного resource_key
# может быть несколько таких моделей сразу (например, у устройства — и открытые порты, и ПО).
# Если правки из отчёта по анализу БД добавят owner_type/owner_id ещё куда-то — этот словарь и
# вызывающий его delete_resource() снова первое, что нужно будет расширить.
_POLYMORPHIC_OWNER_CLEANUP: dict[str, list[tuple[type, str]]] = {
    'interfaces': [(OpenPort, OwnerType.DEVICE_INTERFACE), (IPAddress, OwnerType.DEVICE_INTERFACE)],
    'vms': [(OpenPort, OwnerType.VIRTUAL_MACHINE), (DeployedSoftware, OwnerType.VIRTUAL_MACHINE), (IPAddress, OwnerType.VIRTUAL_MACHINE)],
    'devices': [(OpenPort, OwnerType.PHYSICAL_DEVICE), (DeployedSoftware, OwnerType.PHYSICAL_DEVICE)],
    'is-sources': [(IPAddress, OwnerType.INFORMATION_SYSTEM_SOURCE)],
}

def assert_deletable(resource: str, item_id: str, session: Session) -> None:
    """Единая точка проверки «можно ли удалить запись»: настоящие FK-ссылки (reflection-based
    _find_referencing_counts) + owner_id-ссылки источников ИС на устройство/ВМ/контейнер
    (InformationSystemSource.owner_id — не FK, см. services/integrity.py). Кидает 409 в едином
    формате. Любой новый путь удаления устройства/ВМ/контейнера ОБЯЗАН вызывать эту функцию
    (delete_resource() уже вызывает); сама защита на этом не заканчивается — см. before_delete и
    триггеры БД в integrity.py — но понятное сообщение пользователю даёт только этот уровень."""
    model = model_for(resource)
    refs = _find_referencing_counts(model, item_id, session) + source_reference_refs(resource, item_id, session)
    if refs:
        raise HTTPException(409, detail={'code': ErrorCode.REFERENCED_BY_OTHER_RECORDS, 'message': format_referenced_message(refs)})

def delete_resource(resource: str, item_id: str, session: Session):
    ensure_writable(resource)
    model = model_for(resource); obj = session.get(model, item_id)
    if not obj: raise HTTPException(404, 'Запись не найдена')
    assert_deletable(resource, item_id, session)
    try:
        # Подтверждено эмпирически: DELETE /resources/interfaces/{id} в обход sync_interfaces
        # удалял интерфейс, но оставлял открытые порты/IP в БД с owner_id, указывающим на уже не
        # существующую запись. Явно подчищаем перед удалением для каждой полиморфной модели,
        # зарегистрированной для этого resource_key выше.
        for cleanup_model, owner_type in _POLYMORPHIC_OWNER_CLEANUP.get(resource, []):
            session.execute(delete(cleanup_model).where(cleanup_model.owner_type == owner_type, cleanup_model.owner_id == item_id))
        session.delete(obj); session.flush(); audit(session, resource, item_id, AuditAction.DELETE, 'Удаление записи'); session.commit(); return {'status': 'deleted', 'id': item_id}
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(409, 'Запись нельзя удалить: на неё ссылаются другие объекты') from exc

_VLAN_MODES = frozenset({"access", "trunk"})
# Длина колонки ip_addresses.purpose (models.IPAddress): назначение общего IP группы копируется в неё.
_IP_PURPOSE_MAX_LENGTH = 255
# Длина колонки deployed_software.version (models.DeployedSoftware).
_SOFTWARE_VERSION_MAX_LENGTH = 100


def _resolve_protocol_catalog_entry(catalog_id: Any, session: Session) -> ProtocolPortCatalog:
    """Достаёт запись справочника «Протоколы и порты» по id или кидает понятную 422 — общая точка
    для _validate_open_port_catalog() ниже, чтобы формулировка ошибки не разъезжалась между
    интерфейсами устройства и generic create/update_resource('open-ports') (ВМ)."""
    entry = session.get(ProtocolPortCatalog, catalog_id) if catalog_id else None
    if not entry:
        raise HTTPException(422, 'Не выбрана существующая запись справочника «Протоколы и порты»')
    return entry


_OPEN_PORT_OWNER_LABELS = {OwnerType.VIRTUAL_MACHINE: 'Виртуальная машина', OwnerType.DEVICE_INTERFACE: 'Порт устройства', OwnerType.PHYSICAL_DEVICE: 'Устройство'}


def _validate_open_port_number_is_free(data: dict[str, Any], session: Session, current_id: str | None = None) -> None:
    """Номер порта новой/изменяемой записи open-ports не должен совпадать с номером другой записи
    ТОГО ЖЕ владельца (ВМ, порт устройства). Сверяется только эта запись с остальными, а не весь
    список владельца: уже существовавшие дубли не мешают добавить корректный порт. Вызывать после
    _validate_open_port_catalog() — он гарантирует, что запись справочника существует."""
    owner_type, owner_id = data.get('owner_type'), data.get('owner_id')
    if not owner_type or not owner_id: return
    port = _resolve_protocol_catalog_entry(data.get('protocol_catalog_id'), session).port
    stmt = (select(OpenPort.id).join(ProtocolPortCatalog, ProtocolPortCatalog.id == OpenPort.protocol_catalog_id)
            .where(OpenPort.owner_type == owner_type, OpenPort.owner_id == owner_id, ProtocolPortCatalog.port == port).limit(1))
    if current_id: stmt = stmt.where(OpenPort.id != current_id)
    if session.scalar(stmt) is not None:
        label = _OPEN_PORT_OWNER_LABELS.get(owner_type, 'Владелец')
        raise HTTPException(422, f'{label}: порт {port} уже добавлен — номера открытых портов не должны повторяться')


def _validate_open_port_catalog(data: dict[str, Any], session: Session) -> None:
    """Правка "справочник — единственный источник правды для порта/протокола": OpenPort.port/
    protocol больше не колонки этой модели вовсе (см. models.OpenPort) — значения читаются join'ом
    к protocol_port_catalogs при КАЖДОМ чтении (services/serialization.py:enrich_open_port(s)), а
    не подставляются один раз при записи, как было раньше (до миграции b7f2c1e5a904). Поэтому
    здесь больше нечего мутировать в data — остаётся только убедиться, что protocol_catalog_id
    ссылается на существующую запись справочника, иначе клиент получит понятную 422 вместо
    IntegrityError на NOT NULL при flush()."""
    _resolve_protocol_catalog_entry(data.get('protocol_catalog_id'), session)


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


def _sync_owned_rows(model: type, owner_type: str, owner_id: str, items: Any, session: Session, *, normalize: Callable[[dict[str, Any]], dict[str, Any] | None], array_error: str, foreign_id_error: str) -> tuple[int, int, int]:
    """Общая diff-синхронизация вложенных записей с полиморфным владельцем (OpenPort, IPAddress,
    DeployedSoftware: owner_type/owner_id) по присланному списку: элемент с id обновляет существующую
    запись владельца, без id создаёт новую, записи владельца, которых в списке нет, удаляются.

    normalize(item) приводит элемент к значениям колонок (и валидирует их — бросает HTTPException 422)
    либо возвращает None для пустой строки-плейсхолдера формы, которая тихо пропускается.

    Записи не пересоздаются: id и created_at сохраняются, а изменённой считается только запись, у
    которой реально поменялось значение колонки. Транзакцию функция не коммитит — это делает
    вызывающий. Список — полное желаемое состояние, поэтому повтор запроса идемпотентен: записи,
    созданные неудавшейся попыткой и не известные форме по id, при повторе удалятся как лишние.
    Возвращает (создано, изменено, удалено)."""
    if not isinstance(items, list): raise HTTPException(422, array_error)
    old_rows = session.scalars(select(model).where(model.owner_type == owner_type, model.owner_id == owner_id)).all()
    old_map = {x.id: x for x in old_rows}; seen: set[str] = set()
    created = updated = 0
    for item in items:
        if not isinstance(item, dict): continue
        new_values = normalize(item)
        if new_values is None: continue
        row_id = item.get('id')
        if row_id:
            row = old_map.get(row_id)
            if not row: raise HTTPException(422, foreign_id_error)
            if row_id in seen: raise HTTPException(422, 'Одна и та же запись указана в списке несколько раз')
            seen.add(row_id)
            if any(getattr(row, key) != value for key, value in new_values.items()): updated += 1
        else:
            row = model(owner_type=owner_type, owner_id=owner_id); session.add(row); created += 1
        for key, value in new_values.items(): setattr(row, key, value)
    stale_rows = [row for row in old_rows if row.id not in seen]
    for stale_row in stale_rows: session.delete(stale_row)
    return created, updated, len(stale_rows)


def sync_owner_open_ports(owner_type: str, owner_id: str, open_ports: Any, session: Session, *, owner_label: str, array_error: str, foreign_id_error: str) -> tuple[int, int, int]:
    """Открытые порты владельца (ВМ или порт устройства) по присланному списку, см. _sync_owned_rows.
    Уникальность номеров проверяется по списку целиком (validate_unique_open_port_numbers), а не по
    записям в БД поочерёдно, поэтому обмен номерами между двумя строками за один запрос допустим.
    Строка без выбранной записи справочника (пустой плейсхолдер формы) пропускается."""
    if not isinstance(open_ports, list): raise HTTPException(422, array_error)
    validate_unique_open_port_numbers((p.get('protocol_catalog_id') for p in open_ports if isinstance(p, dict)), session, owner_label)

    def normalize(port_data: dict[str, Any]) -> dict[str, Any] | None:
        # Пользователь нажал "+ Открытый порт", но ещё ничего не выбрал (см. addRow() в OpenPortListEditor.vue).
        if not port_data.get('protocol_catalog_id'): return None
        _validate_open_port_catalog(port_data, session)
        return {
            'protocol_catalog_id': port_data['protocol_catalog_id'],
            'transport_protocol': port_data.get('transport_protocol') or 'TCP',
            'description': port_data.get('description') or None,
        }

    return _sync_owned_rows(OpenPort, owner_type, owner_id, open_ports, session, normalize=normalize, array_error=array_error, foreign_id_error=foreign_id_error)


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


def sync_owner_ip_addresses(owner_type: str, owner_id: str, ip_addresses: Any, session: Session, *, array_error: str, foreign_id_error: str) -> tuple[int, int, int]:
    """IP-адреса владельца (ВМ) по присланному списку, см. _sync_owned_rows. Те же проверки, что у
    generic create/update ресурса ip-addresses (_validate_ip_address_entry): формат IPv4 и префикс
    0-32 — плюс длина назначения (колонка ограничена _IP_PURPOSE_MAX_LENGTH). Строка без адреса
    (пустой плейсхолдер формы) пропускается."""
    def normalize(ip_data: dict[str, Any]) -> dict[str, Any] | None:
        ip_address = str(ip_data.get('ip_address') or '').strip()
        if not ip_address: return None
        validate_ipv4_field(ip_address, 'IP-адрес')
        prefix_length = ip_data.get('prefix_length')
        validate_prefix_length_field(prefix_length, 'Префикс IP-адреса')
        purpose = ip_data.get('purpose') or None
        if purpose is not None and len(str(purpose)) > _IP_PURPOSE_MAX_LENGTH:
            raise HTTPException(422, f'Назначение IP-адреса не должно превышать {_IP_PURPOSE_MAX_LENGTH} символов')
        return {
            'ip_address': ip_address,
            'prefix_length': None if prefix_length in (None, '') else int(prefix_length),
            'purpose': purpose,
            'is_management': bool(ip_data.get('is_management')),
        }

    return _sync_owned_rows(IPAddress, owner_type, owner_id, ip_addresses, session, normalize=normalize, array_error=array_error, foreign_id_error=foreign_id_error)


def sync_owner_deployed_software(owner_type: str, owner_id: str, deployed_software: Any, session: Session, *, array_error: str, foreign_id_error: str) -> tuple[int, int, int]:
    """Развёрнутое ПО владельца (ВМ) по присланному списку, см. _sync_owned_rows. Записи каталога
    программных активов проверяются одним запросом на весь список: несуществующий актив — понятный
    422, а не IntegrityError по внешнему ключу. Строка без выбранного актива (пустой плейсхолдер
    формы) пропускается."""
    if not isinstance(deployed_software, list): raise HTTPException(422, array_error)
    asset_ids = {i['software_asset_id'] for i in deployed_software if isinstance(i, dict) and i.get('software_asset_id')}
    known_ids = set(session.scalars(select(SoftwareAsset.id).where(SoftwareAsset.id.in_(asset_ids))).all()) if asset_ids else set()
    if asset_ids - known_ids: raise HTTPException(422, 'Программный актив не найден в справочнике')

    def normalize(software_data: dict[str, Any]) -> dict[str, Any] | None:
        if not software_data.get('software_asset_id'): return None
        version = software_data.get('version') or None
        if version is not None and len(str(version)) > _SOFTWARE_VERSION_MAX_LENGTH:
            raise HTTPException(422, f'Версия ПО не должна превышать {_SOFTWARE_VERSION_MAX_LENGTH} символов')
        return {'software_asset_id': software_data['software_asset_id'], 'version': version}

    return _sync_owned_rows(DeployedSoftware, owner_type, owner_id, deployed_software, session, normalize=normalize, array_error=array_error, foreign_id_error=foreign_id_error)


def _sync_vm_collection(vm_id: str, session: Session, *, label: str, sync: Callable[[VirtualMachine], tuple[int, int, int]], load: Callable[[VirtualMachine], list[dict[str, Any]]]) -> dict[str, Any]:
    """Общий каркас атомарной синхронизации одного вложенного списка ВМ (порты, IP-адреса, ПО): ВМ
    существует (404), список применяется одной транзакцией (любая ошибка откатывает весь запрос),
    запись в журнал аудита пишется только если что-то реально изменилось. Ответ: {'items': [...]} —
    сохранённые записи списка."""
    vm = session.get(VirtualMachine, vm_id)
    if not vm: raise HTTPException(404, 'Виртуальная машина не найдена')
    try:
        created, updated, removed = sync(vm)
        if created or updated or removed:
            audit(session, 'vms', vm.id, AuditAction.UPDATE, f'{label}: добавлено {created}, изменено {updated}, удалено {removed}')
        session.commit()
    except HTTPException:
        session.rollback(); raise
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(409, f'Нарушение целостности данных: {str(exc.orig)[:300]}') from exc
    return {'items': load(vm)}


def sync_vm_open_ports(vm_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """PUT /api/v1/vms/{vm_id}/open-ports — атомарная синхронизация открытых портов ВМ (форма ВМ,
    VMFormModal.vue): порты с id обновляются, без id создаются, отсутствующие в списке удаляются (см.
    sync_owner_open_ports) — вместо прежнего «удалить все и создать заново» при каждом сохранении.
    Ключ open_ports обязателен: его отсутствие — 422, а не молчаливое удаление всех портов.

    Ответ: {'items': [...]} — порты ВМ по возрастанию номера порта."""
    def load(vm: VirtualMachine) -> list[dict[str, Any]]:
        rows = session.scalars(
            select(OpenPort)
            .join(ProtocolPortCatalog, OpenPort.protocol_catalog_id == ProtocolPortCatalog.id)
            .where(OpenPort.owner_type == OwnerType.VIRTUAL_MACHINE, OpenPort.owner_id == vm.id)
            .order_by(ProtocolPortCatalog.port, OpenPort.transport_protocol)
        ).all()
        return enrich_open_ports(rows, session)

    return _sync_vm_collection(
        vm_id, session, label='Открытые порты', load=load,
        sync=lambda vm: sync_owner_open_ports(
            OwnerType.VIRTUAL_MACHINE, vm.id, payload.get('open_ports'), session,
            owner_label=f'ВМ «{vm.name}»',
            array_error='Поле open_ports должно быть массивом',
            foreign_id_error='Открытый порт не принадлежит выбранной виртуальной машине',
        ),
    )


def sync_vm_ip_addresses(vm_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """PUT /api/v1/vms/{vm_id}/ip-addresses — то же для IP-адресов ВМ (ключ ip_addresses, см.
    sync_owner_ip_addresses). Ответ: {'items': [...]} — IP-адреса ВМ по возрастанию адреса."""
    def load(vm: VirtualMachine) -> list[dict[str, Any]]:
        rows = session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.VIRTUAL_MACHINE, IPAddress.owner_id == vm.id).order_by(IPAddress.ip_address, IPAddress.id)).all()
        return [serialize(row) for row in rows]

    return _sync_vm_collection(
        vm_id, session, label='IP-адреса', load=load,
        sync=lambda vm: sync_owner_ip_addresses(
            OwnerType.VIRTUAL_MACHINE, vm.id, payload.get('ip_addresses'), session,
            array_error='Поле ip_addresses должно быть массивом',
            foreign_id_error='IP-адрес не принадлежит выбранной виртуальной машине',
        ),
    )


def sync_vm_deployed_software(vm_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """PUT /api/v1/vms/{vm_id}/deployed-software — то же для программных активов ВМ (ключ
    deployed_software, см. sync_owner_deployed_software). Ответ: {'items': [...]} — записи ПО ВМ."""
    def load(vm: VirtualMachine) -> list[dict[str, Any]]:
        rows = session.scalars(select(DeployedSoftware).where(DeployedSoftware.owner_type == OwnerType.VIRTUAL_MACHINE, DeployedSoftware.owner_id == vm.id).order_by(DeployedSoftware.created_at, DeployedSoftware.id)).all()
        return [serialize(row) for row in rows]

    return _sync_vm_collection(
        vm_id, session, label='Программные активы', load=load,
        sync=lambda vm: sync_owner_deployed_software(
            OwnerType.VIRTUAL_MACHINE, vm.id, payload.get('deployed_software'), session,
            array_error='Поле deployed_software должно быть массивом',
            foreign_id_error='Запись о ПО не принадлежит выбранной виртуальной машине',
        ),
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
        for obj in existing:
            if obj.id not in incoming_ids:
                session.execute(delete(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == obj.id))
                # Открытые порты полиморфны (нет FK/каскада на уровне БД, см. models.OpenPort) —
                # без явного удаления здесь они осиротели бы при удалении своего интерфейса.
                session.execute(delete(OpenPort).where(OpenPort.owner_type == OwnerType.DEVICE_INTERFACE, OpenPort.owner_id == obj.id))
                session.delete(obj)
        session.flush()
        if manage_groups: _delete_stale_groups(device_id, {state.obj.id for state in group_states.values()}, session)
        all_ifaces = session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id == device_id)).all()
        for iface in all_ifaces: session.execute(update(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == iface.id).values(is_management=bool(iface.is_management)))
        audit(session, 'interfaces', device_id, AuditAction.SYNC, f'Синхронизация интерфейсов: {len(items)}' + (f', групп: {len(groups_payload)}' if manage_groups else '')); session.commit()
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
        session.rollback(); raise HTTPException(409, f'Нарушение целостности данных: {str(exc.orig)[:300]}') from exc


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


def _normalize_device_vlan_item(item: dict[str, Any]) -> dict[str, Any]:
    """Приводит одну запись payload['vlans'] к значениям колонок PhysicalDeviceVLAN: пустые
    строки — NULL (как отправляет форма устройства), prefix_length — int. Валидирует IPv4 и префикс:
    generic POST /resources/device-vlans этих проверок не делает (только членство в домене), а новый
    атомарный путь не должен быть слабее фронтенда, который их уже проверяет."""
    validate_ipv4_field(item.get('ip_address'), 'IP-адрес VLAN устройства')
    validate_prefix_length_field(item.get('prefix_length'), 'Префикс IP-адреса VLAN устройства')
    prefix = item.get('prefix_length')
    return {
        'ip_address': item.get('ip_address') or None,
        'prefix_length': None if prefix in (None, '') else int(prefix),
        'is_management': bool(item.get('is_management', False)),
        'description': item.get('description') or None,
    }


def sync_device_vlans(device_id: str, payload: dict[str, Any], session: Session):
    """Атомарная синхронизация блока «VLAN устройства» (PhysicalDeviceVLAN) с переданным списком
    payload['vlans'] — по образцу sync_interfaces(). Заменяет схему «удалить все записи, затем создать
    заново» на стороне клиента (несколько десятков отдельных запросов без транзакции): при ошибке на
    середине устройство оставалось без части VLAN, а параллельное сохранение другой вкладки могло
    затереть чужие изменения.

    Записи сопоставляются по vlan_id (пара «устройство — VLAN» уникальна, uq_physical_device_vlan), а
    не по id записи: смена VLAN в строке — это удаление старой и создание новой записи, и перестановка
    двух VLAN местами не упирается в unique-констрейнт посреди flush. Незатронутые записи не
    обновляются вовсе (нет лишнего UPDATE и сдвига updated_at). Всё в одной транзакции: любая ошибка
    валидации — полный rollback, в БД остаётся прежнее состояние.

    Пример: PUT /api/v1/devices/{id}/vlans  {"vlans": [{"vlan_id": "<uuid>", "ip_address": "10.0.0.1",
    "prefix_length": 24, "is_management": true, "description": "mgmt"}]}"""
    device = session.get(PhysicalDevice, device_id)
    if not device: raise HTTPException(404, 'Физическое устройство не найдено')
    items = payload.get('vlans', [])
    if not isinstance(items, list): raise HTTPException(422, 'Поле vlans должно быть массивом')
    existing = {x.vlan_id: x for x in session.scalars(select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id == device_id)).all()}
    incoming: set[str] = set(); added = updated = 0
    try:
        for item in items:
            if not isinstance(item, dict): raise HTTPException(422, 'Каждая запись VLAN устройства должна быть объектом')
            vlan_id = item.get('vlan_id')
            if not vlan_id: raise HTTPException(422, 'Для каждой записи VLAN устройства необходимо указать vlan_id')
            if vlan_id in incoming: raise HTTPException(422, 'Один и тот же VLAN указан для устройства несколько раз')
            incoming.add(vlan_id)
            values = _normalize_device_vlan_item(item)
            _validate_physical_device_vlan({'physical_device_id': device_id, 'vlan_id': vlan_id}, session)
            obj = existing.get(vlan_id)
            if obj is None:
                session.add(PhysicalDeviceVLAN(physical_device_id=device_id, vlan_id=vlan_id, **values)); added += 1
            elif any(getattr(obj, k) != v for k, v in values.items()):
                for k, v in values.items(): setattr(obj, k, v)
                updated += 1
        removed = 0
        for vlan_id, obj in existing.items():
            if vlan_id not in incoming: session.delete(obj); removed += 1
        session.flush()
        audit(session, 'device-vlans', device_id, AuditAction.SYNC, f'Синхронизация VLAN устройства: добавлено {added}, изменено {updated}, удалено {removed}'); session.commit()
        result = session.scalars(select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id == device_id)).all()
        return {'items': [serialize(x) for x in result]}
    except HTTPException:
        session.rollback(); raise
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(409, f'Нарушение целостности данных: {str(exc.orig)[:300]}') from exc


def get_information_system_details(system_id: str, session: Session) -> dict[str, Any]:
    if not session.get(InformationSystem, system_id):
        raise HTTPException(404, 'Информационная система не найдена')
    sources = session.scalars(select(InformationSystemSource).where(InformationSystemSource.information_system_id == system_id)).all()
    # Один batch-запрос на все source-строки сразу, а не по одному на строку (N+1) — тот же приём,
    # что и в enrich_open_ports/enrich_information_systems (services/serialization.py).
    ips_by_source: dict[str, list[Any]] = {}
    if sources:
        source_ids = [s.id for s in sources]
        for ip in session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.INFORMATION_SYSTEM_SOURCE, IPAddress.owner_id.in_(source_ids)).order_by(IPAddress.ip_address)).all():
            ips_by_source.setdefault(ip.owner_id, []).append(serialize(ip))
    return {
        'departments': [serialize(x) for x in session.scalars(select(ISDepartment).where(ISDepartment.information_system_id == system_id)).all()],
        'protocols': [serialize(x) for x in session.scalars(select(ISProtocol).where(ISProtocol.information_system_id == system_id)).all()],
        'sources': [{**serialize(x), 'ips': ips_by_source.get(x.id, [])} for x in sources],
        'placement_assets': [serialize(x) for x in session.scalars(select(ISPlacementAsset).where(ISPlacementAsset.information_system_id == system_id)).all()],
    }

_LINKED_TABLE_SPECS = [('departments', ISDepartment), ('protocols', ISProtocol), ('placement_assets', ISPlacementAsset)]


def _sync_linked_table(key: str, model, items: Any, system_id: str, session: Session) -> None:
    """Синхронизирует одну из простых связанных таблиц ИС (ISDepartment/ISProtocol/
    ISPlacementAsset — все три остаются актуальными наравне с information_system_sources, просто
    описывают другой аспект ИС). Вынесено из sync_information_system_details(), чтобы снизить
    цикломатическую сложность внешней функции (была 25) — сама логика не изменена.

    ISProtocol.protocol_catalog_id — обязательное поле (NOT NULL, миграция b7f2c1e5a904) и не
    проверяется здесь отдельно: generic-цикл ниже просто передаст его как есть, а его отсутствие
    или ссылка на несуществующую запись справочника упадёт при flush() понятной IntegrityError —
    информационных систем немного, а отдельная проверка ради чуть более дружелюбного сообщения
    здесь не стоит лишнего запроса на каждую строку протокола (в отличие от open-ports, где эта
    проверка уже даёт понятную 422 — см. _validate_open_port_catalog)."""
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


def _sync_source_ip_addresses(source_id: str, ip_items: Any, session: Session) -> None:
    """Вложенный список IP-адресов одной строки InformationSystemSource — по одному адресу на
    отдельное поле ввода (вопрос 3/5 отчёта по анализу БД, согласовано с заказчиком: "можно
    добавлять несколько полей IP вместо одного текстового поля"), а не через запятую в одном
    текстовом поле, как было раньше (до миграции d8e35a1c7f60). Тот же приём, что
    _sync_interface_ips (внутри sync_interfaces) для интерфейса, только без наследования
    is_management от владельца — у источника ИС такого родительского флага нет."""
    if not isinstance(ip_items, list): raise HTTPException(422, 'Поле ips источника должно быть массивом')
    existing_ips = session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.INFORMATION_SYSTEM_SOURCE, IPAddress.owner_id == source_id)).all()
    old_map = {x.id: x for x in existing_ips}; seen_ip_ids: set[str] = set()
    for ip_data in ip_items:
        if not isinstance(ip_data, dict) or not ip_data.get('ip_address'): continue
        validate_ipv4_field(ip_data.get('ip_address'), 'IP-адрес источника ИС')
        ip_id = ip_data.get('id')
        if ip_id:
            ip_obj = old_map.get(ip_id)
            if not ip_obj: raise HTTPException(422, 'IP не принадлежит выбранному источнику')
            seen_ip_ids.add(ip_id)
        else:
            ip_obj = IPAddress(owner_type=OwnerType.INFORMATION_SYSTEM_SOURCE, owner_id=source_id); session.add(ip_obj)
        ip_obj.ip_address = ip_data['ip_address']
    for old_ip in existing_ips:
        if old_ip.id not in seen_ip_ids: session.delete(old_ip)


def _sync_information_system_sources(system_id: str, source_items: Any, session: Session) -> None:
    """Синхронизирует унифицированные записи InformationSystemSource — единственный (с миграции
    b7f2c1e5a904) механизм связи ИС с оборудованием/ВМ/контейнером и IP-адресом источника, не
    относящегося ни к одному из них ('manual'). Вынесено из sync_information_system_details() по
    той же причине, что и _sync_linked_table()."""
    if not isinstance(source_items, list): raise HTTPException(422, 'Поле sources должно быть массивом')
    existing_sources = session.scalars(select(InformationSystemSource).where(InformationSystemSource.information_system_id == system_id)).all()
    source_map = {x.id: x for x in existing_sources}; seen=set()
    for item in source_items:
        if not isinstance(item, dict): continue
        source_type = item.get('source_type') or SourceType.MANUAL
        if source_type not in SourceType.ALL: raise HTTPException(422, 'Недопустимый тип источника')
        obj = source_map.get(item.get('id')) if item.get('id') else InformationSystemSource(information_system_id=system_id)
        if obj is None: raise HTTPException(422, 'Источник не принадлежит выбранной ИС')
        is_new = not getattr(obj, 'id', None)
        if is_new: session.add(obj)
        for k in ('source_type','owner_id','purpose','role','external_interaction'):
            value = item.get(k)
            # Same empty-string-vs-NULL issue as above: a disabled select (когда выбранному
            # source_type владелец не нужен, например 'manual') по-прежнему присылает '', а не null.
            if value == '' and k == 'owner_id': value = None
            setattr(obj, k, value)
        if is_new: session.flush()  # нужен obj.id ниже — для владения вложенными IP этой строки
        seen.add(obj.id)
        _sync_source_ip_addresses(obj.id, item.get('ips') or [], session)
    session.flush()
    for obj in existing_sources:
        if obj.id not in seen:
            session.execute(delete(IPAddress).where(IPAddress.owner_type == OwnerType.INFORMATION_SYSTEM_SOURCE, IPAddress.owner_id == obj.id))
            session.delete(obj)


def sync_information_system_details(system_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    if not session.get(InformationSystem, system_id):
        raise HTTPException(404, 'Информационная система не найдена')
    try:
        for key, model in _LINKED_TABLE_SPECS:
            _sync_linked_table(key, model, payload.get(key, []), system_id, session)
        _sync_information_system_sources(system_id, payload.get('sources', []), session)
        audit(session, 'information-systems', system_id, AuditAction.UPDATE, 'Обновлены связанные данные ИС (подразделения/протоколы/источники/размещение)')
        session.commit()
        return get_information_system_details(system_id, session)
    except HTTPException:
        session.rollback(); raise
    except IntegrityError as exc:
        session.rollback(); raise HTTPException(409, f'Нарушение целостности данных: {str(exc.orig)[:300]}') from exc

