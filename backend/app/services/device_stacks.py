"""Стеки устройств: сводная карточка стека и добавление участника.

Вынесено из api/device_stacks.py. Тела функций перенесены из обработчиков без изменения логики;
описание контрактов — в docstring обработчиков api/device_stacks.py (они же попадают в /docs).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..models import Connection, DeviceInterface, DeviceStack, DeviceStackMember, PhysicalDevice
from .crud import audit, validate_resource
from .crud.stack_vlan_settings import apply_stack_settings_to_device
from .serialization import enrich_connections, enrich_devices, serialize


def stack_detail(session: Session, stack_id: str) -> dict[str, Any]:
    """Участники стека (полными карточками, по позиции) и подключения, оба конца которых принадлежат стеку."""

    stack = session.get(DeviceStack, stack_id)
    if not stack:
        raise HTTPException(404, "Стек не найден")

    member_rows = session.scalars(select(DeviceStackMember).where(DeviceStackMember.stack_id == stack_id).order_by(DeviceStackMember.position)).all()
    device_ids = [m.physical_device_id for m in member_rows]
    devices_by_id = {d.id: d for d in session.scalars(select(PhysicalDevice).where(PhysicalDevice.id.in_(device_ids))).all()} if device_ids else {}
    # Порядок — по DeviceStackMember.position (физический номер участника в стеке), а не по тому,
    # в каком порядке БД вернула бы PhysicalDevice — devices_by_id используется только для
    # словарного доступа, реальный порядок задаёт member_rows.
    ordered_devices = [devices_by_id[d_id] for d_id in device_ids if d_id in devices_by_id]
    members = enrich_devices(ordered_devices, session)
    # stack_position теперь приходит из enrich_devices() само по себе (см. п.2 правки
    # "инвентаризация физических устройств" в serialization.py) — здесь довешиваем только
    # stack_member_id: id самой строки членства (не самого устройства), нужный
    # DeviceStackFormModal.vue для DELETE /device-stack-members/{id} при исключении из стека.
    member_row_id_by_device = {m.physical_device_id: m.id for m in member_rows}
    for item in members:
        item["stack_member_id"] = member_row_id_by_device.get(item["id"])

    connections = []
    if device_ids:
        interface_ids = session.scalars(select(DeviceInterface.id).where(DeviceInterface.physical_device_id.in_(device_ids))).all()
        if interface_ids:
            connections = session.scalars(
                select(Connection).where(Connection.source_interface_id.in_(interface_ids), Connection.destination_interface_id.in_(interface_ids))
            ).all()

    return {"stack": serialize(stack), "members": members, "connections": enrich_connections(connections, session)}


def add_stack_member(session: Session, stack_id: str, physical_device_id: str | None, position: int) -> dict[str, Any]:
    """Добавляет устройство в стек (идемпотентно для того же стека); состояние в другом стеке — 409 из валидатора."""

    stack = session.get(DeviceStack, stack_id)
    device = session.get(PhysicalDevice, physical_device_id) if physical_device_id else None
    if not stack or not device:
        raise HTTPException(404, "Стек или физическое устройство не найдено")
    existing = session.scalar(select(DeviceStackMember).where(DeviceStackMember.physical_device_id == device.id))
    if existing and existing.stack_id == stack_id:
        return serialize(existing)
    data = {"stack_id": stack_id, "physical_device_id": device.id, "position": position}
    validate_resource(DeviceStackMember, data, session, item_id=None)
    # Общие настройки VLAN стека записываются устройству той же транзакцией (до добавления: VLAN вне домена устройства — 422,
    # и участник не создаётся). Окно подтверждения в интерфейсе перед этим показывает, что будет добавлено и заменено.
    applied = apply_stack_settings_to_device(session, stack_id, device)
    obj = DeviceStackMember(**data)
    session.add(obj)
    session.flush()
    details = f"Устройство добавлено в стек «{stack.name}»"
    if applied["added"] or applied["updated"]:
        details += f"; общие настройки VLAN: назначено {applied['added']}, заменено {applied['updated']}"
    audit(session, "device-stack-members", obj.id, AuditAction.CREATE, details)
    session.commit()
    session.refresh(obj)
    return serialize(obj)
