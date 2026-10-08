"""Детали информационной системы: связанные таблицы и источники."""
from __future__ import annotations

from typing import Any
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from ...models import IPAddress, InformationSystem, ISDepartment, ISProtocol, InformationSystemSource, ISPlacementAsset, ProtocolPortCatalog
from ...constants import AuditAction, SourceType, OwnerType
from ..serialization import serialize
from ..integrity import integrity_error_response
from ..validation import validate_ipv4_field, validate_unique_open_port_numbers
from .audit_log import audit


def _load_protocols(system_id: str, session: Session) -> list[ISProtocol]:
    """Протоколы ИС по возрастанию номера порта (как открытые порты ВМ): форма показывает их в этом
    порядке без собственной сортировки. Равные номера — по id, чтобы порядок был стабильным."""
    return list(session.scalars(
        select(ISProtocol)
        .join(ProtocolPortCatalog, ProtocolPortCatalog.id == ISProtocol.protocol_catalog_id)
        .where(ISProtocol.information_system_id == system_id)
        .order_by(ProtocolPortCatalog.port, ISProtocol.id)
    ).all())


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
        'protocols': [serialize(x) for x in _load_protocols(system_id, session)],
        'sources': [{**serialize(x), 'ips': ips_by_source.get(x.id, [])} for x in sources],
        'placement_assets': [serialize(x) for x in session.scalars(select(ISPlacementAsset).where(ISPlacementAsset.information_system_id == system_id)).all()],
    }


_LINKED_TABLE_SPECS = [('departments', ISDepartment), ('protocols', ISProtocol), ('placement_assets', ISPlacementAsset)]


def _sync_linked_table(key: str, model, items: Any, system_id: str, session: Session) -> None:
    """Синхронизирует одну из простых связанных таблиц ИС (ISDepartment/ISProtocol/
    ISPlacementAsset — все три остаются актуальными наравне с information_system_sources, просто
    описывают другой аспект ИС). Вынесено из sync_information_system_details(), чтобы снизить
    цикломатическую сложность внешней функции (была 25) — сама логика не изменена.

    Протоколы ИС до записи проходят _prepare_protocol_items (пропуск пустых строк, проверка записи
    справочника и уникальности номеров портов) — остальные таблицы пишутся как есть."""
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


def _prepare_protocol_items(items: Any, system: InformationSystem, session: Session) -> list[dict[str, Any]]:
    """Протоколы ИС перед записью — те же правила, что у открытых портов ВМ (sync_owner_open_ports):
    строка без выбранной записи справочника (пустой плейсхолдер формы) пропускается, остальные
    должны ссылаться на существующую запись справочника «Протоколы и порты» (понятная 422 вместо
    IntegrityError), а номера портов в пределах ИС не повторяются (по списку целиком, поэтому обмен
    номерами между двумя строками за один запрос допустим). Три запроса независимо от числа строк."""
    if not isinstance(items, list): raise HTTPException(422, 'Поле protocols должно быть массивом')
    rows = [item for item in items if isinstance(item, dict) and item.get('protocol_catalog_id')]
    catalog_ids = {row['protocol_catalog_id'] for row in rows}
    known = set(session.scalars(select(ProtocolPortCatalog.id).where(ProtocolPortCatalog.id.in_(catalog_ids))).all()) if catalog_ids else set()
    if catalog_ids - known: raise HTTPException(422, 'Не выбрана существующая запись справочника «Протоколы и порты»')
    validate_unique_open_port_numbers((row['protocol_catalog_id'] for row in rows), session, f'ИС «{system.name}»')
    return rows


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
    system = session.get(InformationSystem, system_id)
    if not system:
        raise HTTPException(404, 'Информационная система не найдена')
    try:
        for key, model in _LINKED_TABLE_SPECS:
            items = payload.get(key, [])
            if key == 'protocols': items = _prepare_protocol_items(items, system, session)
            _sync_linked_table(key, model, items, system_id, session)
        _sync_information_system_sources(system_id, payload.get('sources', []), session)
        audit(session, 'information-systems', system_id, AuditAction.UPDATE, 'Обновлены связанные данные ИС (подразделения/протоколы/источники/размещение)')
        session.commit()
        return get_information_system_details(system_id, session)
    except HTTPException:
        session.rollback(); raise
    except IntegrityError as exc:
        session.rollback(); raise integrity_error_response('information-systems', exc) from exc
