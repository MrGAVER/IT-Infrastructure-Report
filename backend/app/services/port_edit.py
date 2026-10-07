"""Правка конфигурации одного порта с дашборда «Подключения»: роль (тип использования порта —
управление / передача данных) и набор VLAN, одной атомарной операцией.

Режим порта (access / trunk) здесь НЕ меняется: его меняет каскад (services/vlan_mode_cascade.py) —
режим может задаваться группой портов и должен совпасть у связанных портов, поэтому сервер считает
всю область изменения и показывает последствия до применения. Дашборд меняет режим каскадом, а затем
вызывает эту операцию для роли и VLAN. Поле `mode` в запросе — не команда сменить режим, а проверка:
набор VLAN выбран для этого режима, и если у порта режим уже другой (его сменили между шагами), операция
отклоняется 409, а не записывает набор, который в «чужом» режиме мог бы нарушить «в access не более
одного VLAN».

Те же ограничения, что у остальных точечных записей порта (согласование по правилам, смена роли):
  * VLAN — только из доступных устройству (VLAN его типа и собственные VLAN устройства — те же, что
    принимает PUT /devices/{id}/interfaces);
  * в режиме access у порта не более одного VLAN;
  * порт, режим и VLAN которого задаёт группа портов, по VLAN не меняется (группа — источник истины,
    следующее сохранение устройства вернуло бы её набор): меняйте группу. Роль группа не задаёт, поэтому
    роль такого порта менять можно.

Операция — одна транзакция с записью в журнал аудита; если ничего не изменилось, не пишет ни данных,
ни аудита.

Пример:
    set_port_config(port_id, {"role": "data", "mode": "trunk", "vlan_ids": [vlan_10_id, vlan_20_id]}, session)
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..models import DeviceInterface, DeviceTypeVLAN, InterfaceGroup, InterfaceVLAN, PhysicalDevice, PhysicalDeviceVLAN, VLAN
from .crud import audit
from .port_config import DEFAULT_VLAN_MODE, PORT_ROLE_LABELS, VLAN_MODE_ACCESS, PortRole, port_role
from .port_writes import write_port_role, write_port_vlans
from .serialization import enrich_interfaces

# Потолок на длину списка VLAN: номеров 802.1Q не больше 4094, а справочник может хранить один номер в
# нескольких доменах — запас с тем же порядком величины защищает от заведомо неверного тела запроса.
MAX_VLAN_IDS = 5000


def _parse_role(raw: Any) -> PortRole:
    try:
        return PortRole(raw)
    except ValueError:
        allowed = ", ".join(r.value for r in PortRole)
        raise HTTPException(422, f"Поле role: допустимые значения — {allowed}") from None


def _parse_vlan_ids(raw: Any) -> list[str]:
    if not isinstance(raw, list) or not all(isinstance(v, str) and v for v in raw):
        raise HTTPException(422, "Поле vlan_ids должно быть массивом идентификаторов VLAN")
    if len(raw) > MAX_VLAN_IDS:
        raise HTTPException(422, f"В поле vlan_ids не больше {MAX_VLAN_IDS} VLAN")
    return list(dict.fromkeys(raw))


def _allowed_vlan_ids(device: PhysicalDevice, session: Session) -> set[str]:
    """VLAN, доступные устройству: VLAN его типа ∪ собственные VLAN устройства."""
    by_type = session.scalars(select(DeviceTypeVLAN.vlan_id).where(DeviceTypeVLAN.device_type_id == device.device_type_id)).all()
    own = session.scalars(select(PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id == device.id)).all()
    return set(by_type) | set(own)


def _numbers(vlan_ids: set[str] | list[str], session: Session) -> list[int]:
    if not vlan_ids:
        return []
    return sorted(set(session.scalars(select(VLAN.vlan_id).where(VLAN.id.in_(list(vlan_ids)))).all()))


def _list(numbers: list[int]) -> str:
    return ", ".join(map(str, numbers)) or "нет"


def set_port_config(interface_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """Меняет роль и/или набор VLAN порта. Тело: {role?, vlan_ids?, mode?} — хотя бы одно из role и
    vlan_ids; `vlan_ids` — ПОЛНЫЙ набор (id записей справочника VLAN), не изменение. Возвращает порт
    в том же виде, что и GET /resources/interfaces (клиент заменяет им запись в кэше)."""
    if not isinstance(payload, dict):
        raise HTTPException(422, "Тело запроса должно быть объектом")
    unknown = set(payload) - {"role", "vlan_ids", "mode"}
    if unknown:
        raise HTTPException(422, f"Неизвестные поля: {', '.join(sorted(unknown))}")
    if "role" not in payload and "vlan_ids" not in payload:
        raise HTTPException(422, "Укажите role и/или vlan_ids")
    role = _parse_role(payload["role"]) if "role" in payload else None
    vlan_ids = _parse_vlan_ids(payload["vlan_ids"]) if "vlan_ids" in payload else None
    expected_mode = payload.get("mode")
    if expected_mode is not None and expected_mode not in ("access", "trunk"):
        raise HTTPException(422, "Поле mode должно быть access или trunk")

    iface = session.get(DeviceInterface, interface_id)
    if iface is None:
        raise HTTPException(404, "Порт не найден")
    mode = iface.vlan_mode or DEFAULT_VLAN_MODE
    if expected_mode is not None and expected_mode != mode:
        raise HTTPException(409, f"Режим порта «{iface.name}» изменился (сейчас {mode}) — обновите данные и повторите")

    # Сначала вся проверка, потом запись: ошибка валидации не должна оставить в сессии половину правки.
    role_changed = role is not None and role != port_role(iface)
    vlans_changed = False
    current: set[str] = set()
    if vlan_ids is not None:
        current = set(session.scalars(select(InterfaceVLAN.vlan_id).where(InterfaceVLAN.interface_id == iface.id)).all())
        vlans_changed = set(vlan_ids) != current
    if vlans_changed:
        assert vlan_ids is not None
        device = session.get(PhysicalDevice, iface.physical_device_id)
        if device is None:
            raise HTTPException(404, "Устройство порта не найдено")
        if any(v not in _allowed_vlan_ids(device, session) for v in vlan_ids):
            raise HTTPException(422, "Один или несколько VLAN не разрешены для типа данного устройства")
        if mode == VLAN_MODE_ACCESS and len(vlan_ids) > 1:
            raise HTTPException(422, "В режиме access у порта может быть не более одного VLAN")
        group = session.get(InterfaceGroup, iface.group_id) if iface.group_id else None
        if group is not None and group.vlan_mode:
            raise HTTPException(409, f"Порт входит в группу «{group.name}», которая задаёт режим и VLAN, — измените группу")

    parts: list[str] = []
    if role_changed:
        assert role is not None
        parts.append(f"роль {PORT_ROLE_LABELS[port_role(iface)]} → {PORT_ROLE_LABELS[role]}")
        write_port_role(iface, role, session)
    if vlans_changed:
        assert vlan_ids is not None
        parts.append(f"VLAN {_list(_numbers(current, session))} → {_list(_numbers(vlan_ids, session))}")
        write_port_vlans(iface, mode, vlan_ids, session)

    if parts:
        audit(session, "interfaces", iface.id, AuditAction.UPDATE, f"Правка порта «{iface.name}» с дашборда подключений: {'; '.join(parts)}")
        session.commit()
        session.refresh(iface)
    return enrich_interfaces([iface], session)[0]
