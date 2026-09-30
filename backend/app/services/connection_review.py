"""Операции проверки конфигураций портов-соседей подключений (дашборд «Подключения»).

Правила определения статуса — в services/port_config.py; здесь только изменяющие данные
операции: задать роль порта, одобрить расхождение, отозвать одобрение. Каждая операция — одна
транзакция с записью в журнал аудита.
"""
from __future__ import annotations

from typing import Any, Sequence

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..constants import AuditAction, OwnerType
from ..models import Connection, DeviceInterface, IPAddress
from .crud import audit
from .port_config import PORT_ROLE_LABELS, PortConfigStatus, approval_signature, evaluate_port_config, port_role, role_from_flags
from .serialization import enrich_connections, enrich_interfaces

MAX_APPROVE_BATCH = 500


def _require_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise HTTPException(422, f"Поле {key} должно быть true или false")
    return value


def set_port_role(interface_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """Точечно меняет роль порта (управление / передача данных), не трогая остальные его
    настройки — в отличие от PUT /devices/{id}/interfaces, который синхронизирует устройство
    целиком. Возвращает интерфейс в том же виде, что и GET /resources/interfaces, чтобы клиент
    мог заменить запись в своём кэше.

    IP-адреса порта зеркалируют его is_management (тот же инвариант, что поддерживает
    sync_interfaces), поэтому флаг на адресах обновляется вместе с портом."""
    is_management = _require_bool(payload, "is_management")
    is_data_transfer = _require_bool(payload, "is_data_transfer")
    iface = session.get(DeviceInterface, interface_id)
    if not iface:
        raise HTTPException(404, "Порт не найден")
    before = port_role(iface)
    iface.is_management = is_management
    iface.is_data_transfer = is_data_transfer
    session.execute(
        update(IPAddress)
        .where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == iface.id)
        .values(is_management=is_management)
    )
    after = role_from_flags(is_management, is_data_transfer)
    audit(session, "interfaces", iface.id, AuditAction.UPDATE, f"Роль порта «{iface.name}»: {PORT_ROLE_LABELS[before]} → {PORT_ROLE_LABELS[after]}")
    session.commit()
    session.refresh(iface)
    return enrich_interfaces([iface], session)[0]


def _load_connection_pair(connection: Connection, session: Session) -> tuple[DeviceInterface, DeviceInterface]:
    source = session.get(DeviceInterface, connection.source_interface_id)
    destination = session.get(DeviceInterface, connection.destination_interface_id)
    if not source or not destination:
        raise HTTPException(422, "У подключения отсутствует один из портов")
    return source, destination


def approve_port_config(payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """Одобряет текущее расхождение ролей у перечисленных подключений.

    Идемпотентно и безопасно к гонкам: подключение, у которого расхождения уже нет (роль порта
    успели выровнять) или которое неактивно, пропускается и попадает в skipped_ids — одобрять
    там нечего. Неизвестный id — 404 без каких-либо изменений."""
    ids = payload.get("connection_ids")
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids):
        raise HTTPException(422, "Поле connection_ids должно быть непустым массивом идентификаторов подключений")
    if len(ids) > MAX_APPROVE_BATCH:
        raise HTTPException(422, f"За один запрос можно одобрить не более {MAX_APPROVE_BATCH} подключений")
    unique_ids = list(dict.fromkeys(ids))
    connections = {c.id: c for c in session.scalars(select(Connection).where(Connection.id.in_(unique_ids))).all()}
    missing = [i for i in unique_ids if i not in connections]
    if missing:
        raise HTTPException(404, f"Подключение не найдено: {missing[0]}")

    approved: list[Connection] = []
    skipped: list[str] = []
    for conn_id in unique_ids:
        conn = connections[conn_id]
        source, destination = _load_connection_pair(conn, session)
        status = evaluate_port_config(source, destination, conn.port_config_approved_signature, is_active=conn.is_active is not False)
        if status is PortConfigStatus.MISMATCH:
            conn.port_config_approved_signature = approval_signature(source, destination)
            audit(
                session, "connections", conn.id, AuditAction.UPDATE,
                f"Одобрено расхождение ролей портов: «{source.name}» — {PORT_ROLE_LABELS[port_role(source)]}, «{destination.name}» — {PORT_ROLE_LABELS[port_role(destination)]}",
            )
            approved.append(conn)
        elif status is PortConfigStatus.OK:
            skipped.append(conn_id)
        else:  # уже одобрено — состояние не меняем, но клиенту вернём актуальную запись
            approved.append(conn)
    session.commit()
    return {"items": enrich_connections(approved, session), "skipped_ids": skipped}


def revoke_port_config_approval(connection_id: str, session: Session) -> dict[str, Any]:
    conn = session.get(Connection, connection_id)
    if not conn:
        raise HTTPException(404, "Подключение не найдено")
    if conn.port_config_approved_signature:
        conn.port_config_approved_signature = None
        audit(session, "connections", conn.id, AuditAction.UPDATE, "Отозвано одобрение расхождения ролей портов")
        session.commit()
    return enrich_connections([conn], session)[0]


def find_port_config_mismatches(session: Session, *, statuses: Sequence[PortConfigStatus] = (PortConfigStatus.MISMATCH,)) -> list[dict[str, Any]]:
    """Все подключения с указанным статусом сверки (по умолчанию — неодобренные расхождения).
    Нужна не дашборду (он получает статус в каждой строке списка), а внешним потребителям, которым
    достаточно одного запроса «что требует проверки»."""
    rows = session.scalars(select(Connection).order_by(Connection.created_at)).all()
    enriched = enrich_connections(rows, session)
    wanted = {s.value for s in statuses}
    return [c for c in enriched if c["port_config_status"] in wanted]
