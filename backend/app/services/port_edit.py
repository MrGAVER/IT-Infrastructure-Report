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
  * в режиме access у порта не более одного VLAN, и «Все VLAN» невозможно;
  * порт, режим и VLAN которого задаёт группа портов, по VLAN не меняется (группа — источник истины,
    следующее сохранение устройства вернуло бы её набор): меняйте группу. Роль группа не задаёт, поэтому
    роль такого порта менять можно.

«Все VLAN». Вместо набора можно прислать `all_vlans: true` — порту ставится признак (хранится только он, набор
вычисляется из VLAN устройства, см. services/port_vlans.py), а `vlan_ids` игнорируется. Присланный набор VLAN
(`vlan_ids` без all_vlans, либо с `all_vlans: false`) — это выбор вручную: признак снимается. Набор, совпадающий с
текущим, у порта с признаком не меняет ничего (клиент присылает черновик целиком при правке одной лишь роли).

Операция — одна транзакция с записью в журнал аудита; если ничего не изменилось, не пишет ни данных,
ни аудита.

Вместе со сменой режима. Когда режим тоже меняется, роль и VLAN идут ТЕМ ЖЕ запросом, что и каскад
(services/vlan_mode_cascade.py: поле `port` в теле предпросмотра и применения) — в одной транзакции:
либо записано всё (режим со всей областью каскада, роль, VLAN), либо ничего. Для этого правка разбита
на три шага, которые каскад вызывает сам: `parse_port_change` (разбор тела), `prepare_port_change`
(вся проверка — ничего не пишет; набор VLAN проверяется под ЦЕЛЕВОЙ режим) и `write_port_change`
(запись и аудит без commit).

Пример:
    set_port_config(port_id, {"role": "data", "mode": "trunk", "vlan_ids": [vlan_10_id, vlan_20_id]}, session)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..models import DeviceInterface, DeviceTypeVLAN, InterfaceGroup, PhysicalDevice, PhysicalDeviceVLAN, VLAN
from .crud import audit
from .port_config import DEFAULT_VLAN_MODE, PORT_ROLE_LABELS, VLAN_MODE_ACCESS, PortRole, port_role
from .port_vlans import carries_all_vlans, effective_vlan_ids
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


@dataclass(frozen=True)
class PortChange:
    """Что просили изменить: роль и/или ПОЛНЫЙ набор VLAN (id записей справочника) и/или признак «Все VLAN».
    None — не менять."""

    role: PortRole | None
    vlan_ids: list[str] | None
    all_vlans: bool | None = None


@dataclass
class PreparedPortChange:
    """Проверенная правка порта: что именно записать. Получается из `prepare_port_change` и ничего не пишет."""

    iface: DeviceInterface
    mode: str  # режим, под который проверен набор VLAN (и в котором он будет записан)
    role: PortRole | None  # None — роль не меняется
    vlan_ids: list[str] | None  # None — набор не меняется; при all_vlans — все VLAN устройства (для аудита)
    current_vlan_ids: set[str]
    all_vlans: bool = False  # записать «Все VLAN» (хранится признак, а не набор)

    @property
    def changed(self) -> bool:
        return self.role is not None or self.vlan_ids is not None


def parse_port_change(raw: Any, *, allow_mode: bool = False) -> tuple[PortChange, str | None]:
    """Разбор тела правки: {role?, vlan_ids?, all_vlans?} (+ `mode` как проверка, если `allow_mode`). Хотя бы одно из
    role, vlan_ids и all_vlans. Возвращает правку и ожидаемый режим (None — не проверять)."""
    if not isinstance(raw, dict):
        raise HTTPException(422, "Тело запроса должно быть объектом")
    unknown = set(raw) - {"role", "vlan_ids", "all_vlans"} - ({"mode"} if allow_mode else set())
    if unknown:
        raise HTTPException(422, f"Неизвестные поля: {', '.join(sorted(unknown))}")
    if "role" not in raw and "vlan_ids" not in raw and "all_vlans" not in raw:
        raise HTTPException(422, "Укажите role, vlan_ids и/или all_vlans")
    role = _parse_role(raw["role"]) if "role" in raw else None
    all_vlans = raw["all_vlans"] if "all_vlans" in raw else None
    if all_vlans is not None and not isinstance(all_vlans, bool):
        raise HTTPException(422, "Поле all_vlans должно быть true или false")
    # С «Все VLAN» набор игнорируется (набор порта — все VLAN устройства), но формат поля проверяется как обычно.
    vlan_ids = _parse_vlan_ids(raw["vlan_ids"]) if "vlan_ids" in raw else None
    if all_vlans:
        vlan_ids = None
    expected_mode = raw.get("mode") if allow_mode else None
    if expected_mode is not None and expected_mode not in ("access", "trunk"):
        raise HTTPException(422, "Поле mode должно быть access или trunk")
    return PortChange(role, vlan_ids, all_vlans), expected_mode


@dataclass(frozen=True)
class PortConfigRequest:
    """Разобранное тело PUT /interfaces/{id}/port-config: правка и режим, под который выбран набор VLAN (None — не проверять)."""

    change: PortChange
    expected_mode: str | None = None


def parse_port_config_request(raw: Any) -> PortConfigRequest:
    """Разбор тела PUT /interfaces/{id}/port-config: {role?, vlan_ids?, all_vlans?, mode?} (см. `parse_port_change`).
    Модель тела (api/port_config_schemas.PortConfigUpdate) вызывает его ОДИН раз, а обработчик передаёт результат в
    `apply_port_config` — без повторного разбора того же словаря."""
    change, expected_mode = parse_port_change(raw, allow_mode=True)
    return PortConfigRequest(change, expected_mode)


def prepare_port_change(iface: DeviceInterface, mode: str, change: PortChange, session: Session) -> PreparedPortChange:
    """Вся проверка правки порта — ничего не пишет. `mode` — режим, в котором порт окажется после операции
    (для обычной правки — текущий, для правки вместе со сменой режима — целевой): под него проверяется
    «в access не более одного VLAN» и «Все VLAN только в trunk». Группа и допустимые VLAN от режима не зависят."""
    role = change.role if change.role is not None and change.role != port_role(iface) else None
    vlan_ids: list[str] | None = None
    current: set[str] = set()
    write_all = False
    if change.vlan_ids is not None or change.all_vlans is not None:
        current = effective_vlan_ids(session, [iface.id]).get(iface.id, set())
        was_all = carries_all_vlans(iface)
        if change.all_vlans:
            # «Все VLAN»: меняется, только если признака ещё нет (с признаком набор уже равен набору устройства).
            if mode == VLAN_MODE_ACCESS:
                raise HTTPException(422, "«Все VLAN» возможно только в режиме trunk")
            if not was_all:
                device = session.get(PhysicalDevice, iface.physical_device_id)
                if device is None:
                    raise HTTPException(404, "Устройство порта не найдено")
                allowed = _allowed_vlan_ids(device, session)
                if not allowed:
                    raise HTTPException(422, "У устройства порта нет VLAN, которые можно назначить, — добавьте их в «VLAN устройства»")
                _ensure_not_group_managed(iface, session)
                vlan_ids, write_all = sorted(allowed), True
        else:
            explicit = change.vlan_ids if change.vlan_ids is not None else sorted(current)
            # Набор не изменился: у порта с признаком его тоже не трогаем, если признак явно не снимают.
            unchanged = set(explicit) == current and not (was_all and change.all_vlans is False)
            if not unchanged:
                device = session.get(PhysicalDevice, iface.physical_device_id)
                if device is None:
                    raise HTTPException(404, "Устройство порта не найдено")
                if any(v not in _allowed_vlan_ids(device, session) for v in explicit):
                    raise HTTPException(422, "Один или несколько VLAN не разрешены для типа данного устройства")
                if mode == VLAN_MODE_ACCESS and len(explicit) > 1:
                    raise HTTPException(422, "В режиме access у порта может быть не более одного VLAN")
                _ensure_not_group_managed(iface, session)
                vlan_ids = explicit
    return PreparedPortChange(iface, mode, role, vlan_ids, current, write_all)


def _ensure_not_group_managed(iface: DeviceInterface, session: Session) -> None:
    group = session.get(InterfaceGroup, iface.group_id) if iface.group_id else None
    if group is not None and group.vlan_mode:
        raise HTTPException(409, f"Порт входит в группу «{group.name}», которая задаёт режим и VLAN, — измените группу")


def write_port_change(prepared: PreparedPortChange, session: Session, *, context: str = "") -> bool:
    """Записывает проверенную правку и пишет аудит — без commit (транзакцию закрывает вызывающий). `context`
    дописывается к тексту аудита («вместе со сменой режима → access»). True — что-то записано."""
    iface = prepared.iface
    parts: list[str] = []
    if prepared.role is not None:
        parts.append(f"роль {PORT_ROLE_LABELS[port_role(iface)]} → {PORT_ROLE_LABELS[prepared.role]}")
        write_port_role(iface, prepared.role, session)
    if prepared.vlan_ids is not None:
        after = _list(_numbers(prepared.vlan_ids, session))
        parts.append(f"VLAN {_list(_numbers(prepared.current_vlan_ids, session))} → {'все VLAN устройства: ' if prepared.all_vlans else ''}{after}")
        write_port_vlans(iface, prepared.mode, prepared.vlan_ids, session, all_vlans=prepared.all_vlans)
    if parts:
        audit(session, "interfaces", iface.id, AuditAction.UPDATE, f"Правка порта «{iface.name}» с дашборда подключений{context}: {'; '.join(parts)}")
    return bool(parts)


def apply_port_config(interface_id: str, request: PortConfigRequest, session: Session) -> dict[str, Any]:
    """Меняет роль и/или набор VLAN порта по уже разобранному телу (`parse_port_config_request`): `vlan_ids` — ПОЛНЫЙ набор
    (id записей справочника VLAN), не изменение; `all_vlans: true` — «Все VLAN» устройства порта (хранится признак).
    Возвращает порт в том же виде, что и GET /resources/interfaces (клиент заменяет им запись в кэше)."""
    iface = session.get(DeviceInterface, interface_id)
    if iface is None:
        raise HTTPException(404, "Порт не найден")
    mode = iface.vlan_mode or DEFAULT_VLAN_MODE
    if request.expected_mode is not None and request.expected_mode != mode:
        raise HTTPException(409, f"Режим порта «{iface.name}» изменился (сейчас {mode}) — обновите данные и повторите")
    # Сначала вся проверка, потом запись: ошибка валидации не должна оставить в сессии половину правки.
    prepared = prepare_port_change(iface, mode, request.change, session)
    if write_port_change(prepared, session):
        session.commit()
        session.refresh(iface)
    return enrich_interfaces([iface], session)[0]


def set_port_config(interface_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """То же, что `apply_port_config`, но из «сырого» тела {role?, vlan_ids?, all_vlans?, mode?} — хотя бы одно из role, vlan_ids и
    all_vlans. Для вызовов вне HTTP-обработчика (тесты, другие сервисы): тело разбирается здесь, один раз. Обработчик маршрута тело
    уже разобрал в модели запроса и зовёт `apply_port_config` напрямую."""
    return apply_port_config(interface_id, parse_port_config_request(payload), session)
