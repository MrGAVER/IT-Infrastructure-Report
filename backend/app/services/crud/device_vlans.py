"""Синхронизация VLAN физического устройства."""
from __future__ import annotations

from typing import Any
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ...models import PhysicalDevice, PhysicalDeviceVLAN
from ...constants import AuditAction
from ..serialization import serialize
from ..integrity import integrity_error_response
from ..validation import validate_ipv4_field, validate_prefix_length_field
from .audit_log import audit
from .validators import _validate_physical_device_vlan


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


def _incoming_vlan_id(item: Any, incoming: set[str]) -> str:
    """Проверяет одну запись payload['vlans'] и возвращает её vlan_id (повтор в одном запросе — ошибка)."""
    if not isinstance(item, dict): raise HTTPException(422, 'Каждая запись VLAN устройства должна быть объектом')
    vlan_id = item.get('vlan_id')
    if not vlan_id: raise HTTPException(422, 'Для каждой записи VLAN устройства необходимо указать vlan_id')
    if vlan_id in incoming: raise HTTPException(422, 'Один и тот же VLAN указан для устройства несколько раз')
    return vlan_id


def _apply_device_vlan_item(device_id: str, vlan_id: str, item: dict[str, Any], existing: dict[str, PhysicalDeviceVLAN], session: Session) -> str | None:
    """Создаёт или обновляет назначение VLAN; возвращает 'added', 'updated' или None, если запись не изменилась."""
    values = _normalize_device_vlan_item(item)
    _validate_physical_device_vlan({'physical_device_id': device_id, 'vlan_id': vlan_id}, session)
    obj = existing.get(vlan_id)
    if obj is None:
        session.add(PhysicalDeviceVLAN(physical_device_id=device_id, vlan_id=vlan_id, **values))
        return 'added'
    if any(getattr(obj, k) != v for k, v in values.items()):
        for k, v in values.items(): setattr(obj, k, v)
        return 'updated'
    return None


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
            vlan_id = _incoming_vlan_id(item, incoming)
            incoming.add(vlan_id)
            outcome = _apply_device_vlan_item(device_id, vlan_id, item, existing, session)
            added += outcome == 'added'; updated += outcome == 'updated'
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
        session.rollback(); raise integrity_error_response('device-vlans', exc) from exc
