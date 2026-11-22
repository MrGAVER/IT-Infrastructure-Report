"""Хуки ресурсов generic CRUD: особое поведение отдельных моделей вынесено из универсального пути записи.

generic.py (список, создание, правка) ничего не знает о конкретных моделях: он берёт `hooks_for(model)` и вызывает
хуки в фиксированных точках. Новому ресурсу с особым поведением достаточно записи в `HOOKS` — общий код не правится
(принцип открытости/закрытости). Модели без записи получают `ResourceHooks()` — все хуки по умолчанию ничего не делают.

Точки вызова (порядок закреплён tests/test_crud_hooks.py):

    создание:  prepare → validate_create → [проверки реестра] → flush → after_create → аудит → commit → to_dict
    правка:    prepare → validate_update → [проверки реестра] → запись полей → apply_derived → flush
               → after_update → аудит (+ строки из after_update) → commit → to_dict
    список:    ordering (порядок строк) → enrich_rows (обогащение строк связанными данными)
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from ...models import (
    AuditLog,
    Connection,
    DeviceInterface,
    DeviceStackMember,
    InformationSystem,
    ISProtocol,
    OpenPort,
    PhysicalDevice,
    VirtualMachine,
    VLAN,
    VLANDomainDevice,
)
from ..serialization import enrich_connections, enrich_devices, enrich_information_systems, enrich_interfaces, enrich_open_port, enrich_open_ports, serialize
from .owned_rows import _validate_is_protocol_number_is_free, _validate_open_port_catalog, _validate_open_port_number_is_free
from .stack_vlan_settings import apply_stack_settings_to_device
from .vlan_domains import (
    _auto_assign_new_domain_vlan_to_domain_devices,
    _stale_group_subinterfaces_on_vlan,
    _stale_subinterfaces_on_vlan,
    _unassign_moved_vlan_from_former_domain_devices,
    assign_domain_vlans_to_device,
)

_Data = dict[str, Any]

_AUDIT_LIST_LIMIT = 20  # сколько элементов перечисляется в строке аудита; остальные — «…»


# --- значения по умолчанию ------------------------------------------------------------------------


def _default_ordering(model: type) -> tuple[Any, ...]:
    """Без ORDER BY порядок строк при offset/limit не гарантирован (на PostgreSQL он может меняться между запросами),
    и соседние страницы дублировали или пропускали записи. Старые — первыми; id — детерминированный тай-брейк для
    строк с равным временем создания."""
    return tuple(col for col in (getattr(model, "created_at", None), getattr(model, "id", None)) if col is not None)


def _serialize_rows(rows: Sequence[Any], session: Session) -> list[_Data]:
    return [serialize(row) for row in rows]


def _serialize_one(obj: Any, session: Session) -> _Data:
    return serialize(obj)


def _do_nothing(*_args: Any) -> None:
    return None


def _no_audit_notes(*_args: Any) -> list[str]:
    return []


@dataclass(frozen=True)
class ResourceHooks:
    """Особое поведение одного ресурса. Все поля необязательны: незаданный хук ничего не делает (или даёт общий вариант).

    ordering(model)                              — столбцы ORDER BY списка (по умолчанию: время создания, затем id)
    enrich_rows(rows, session)                   — словари для списка; общий вариант — просто serialize
    prepare(data, session)                       — правит данные перед проверками; при создании `data` — новая запись,
                                                   при правке — итоговое состояние записи (текущие значения + изменения)
    validate_create(data, session)               — проверки новой записи сверх общих
    validate_update(proposed, before, session, item_id) — проверки правки; `before` — значения до изменения
    apply_derived(obj, proposed)                 — переносит в объект вычисленные поля, которых не было в payload
    after_create(obj, session)                   — побочные действия после flush (запись уже имеет id)
    after_update(obj, payload, before, session)  — побочные действия после flush; возвращает строки для журнала аудита
                                                   (пишутся сразу за основной записью о правке)
    to_dict(obj, session)                        — ответ API для одной записи
    """

    ordering: Callable[[type], tuple[Any, ...]] = _default_ordering
    enrich_rows: Callable[[Sequence[Any], Session], list[_Data]] = _serialize_rows
    prepare: Callable[[_Data, Session], None] = _do_nothing
    validate_create: Callable[[_Data, Session], None] = _do_nothing
    validate_update: Callable[[_Data, _Data, Session, str], None] = _do_nothing
    apply_derived: Callable[[Any, _Data], None] = _do_nothing
    after_create: Callable[[Any, Session], None] = _do_nothing
    after_update: Callable[[Any, _Data, _Data, Session], list[str]] = _no_audit_notes
    to_dict: Callable[[Any, Session], _Data] = _serialize_one


# --- порядок строк списка -------------------------------------------------------------------------


def _audit_log_ordering(model: type) -> tuple[Any, ...]:
    # Без явной сортировки limit отдаёт то, что БД хранит первым — самые СТАРЫЕ записи, а экран «Последние N действий»
    # ждёт свежие. id — чтобы записи с равным временем не «переезжали» между страницами.
    return (AuditLog.created_at.desc(), AuditLog.id.desc())


def _interface_ordering(model: type) -> tuple[Any, ...]:
    # Порты — в порядке, заданном пользователем в форме устройства (стрелки), а не в порядке создания; created_at и id —
    # тай-брейк для портов с одинаковой позицией (созданных не через форму).
    return (DeviceInterface.sort_order, DeviceInterface.created_at, DeviceInterface.id)


# --- виртуальные машины ---------------------------------------------------------------------------


def _set_vm_hypervisor_os(data: _Data, session: Session) -> None:
    """ВМ на физическом хосте: ОС гипервизора берётся из ОС хоста (или сбрасывается, если у хоста её нет)."""
    host_id = data.get("physical_device_id")
    if host_id:
        host = session.get(PhysicalDevice, host_id)
        data["hypervisor_os_id"] = host.operating_system_id if host and host.operating_system_id else None


def _copy_vm_hypervisor_os(obj: VirtualMachine, proposed: _Data) -> None:
    # hypervisor_os_id вычисляется в prepare и в payload не приходит — в объект его переносим отдельно.
    if "physical_device_id" in proposed:
        obj.hypervisor_os_id = proposed.get("hypervisor_os_id")


# --- открытые порты и протоколы ИС ----------------------------------------------------------------


def _changed(proposed: _Data, before: _Data, keys: tuple[str, ...]) -> bool:
    return any(proposed.get(key) != before.get(key) for key in keys)


def _validate_new_open_port(data: _Data, session: Session) -> None:
    # port/protocol — не колонки OpenPort: единственное, что проверяем, — что protocol_catalog_id ссылается на запись
    # справочника, а номер порта свободен у владельца.
    _validate_open_port_catalog(data, session)
    _validate_open_port_number_is_free(data, session)


def _validate_changed_open_port(proposed: _Data, before: _Data, session: Session, item_id: str) -> None:
    _validate_open_port_catalog(proposed, session)
    # Уникальность номера — только когда меняется сам порт или владелец: правка описания строки, у которой дубль появился
    # раньше этого правила, не должна блокироваться (дубли чинят отдельно — GET /integrity/open-port-duplicates).
    if _changed(proposed, before, ("protocol_catalog_id", "owner_type", "owner_id")):
        _validate_open_port_number_is_free(proposed, session, item_id)


def _validate_new_is_protocol(data: _Data, session: Session) -> None:
    # Протоколы передачи данных ИС — те же открытые порты, только владелец одна ИС: номер порта в её пределах не повторяется.
    _validate_open_port_catalog(data, session)
    _validate_is_protocol_number_is_free(data, session)


def _validate_changed_is_protocol(proposed: _Data, before: _Data, session: Session, item_id: str) -> None:
    _validate_open_port_catalog(proposed, session)
    # Как у открытых портов: правка только описания записи с уже существующим дублем не блокируется.
    if _changed(proposed, before, ("protocol_catalog_id", "information_system_id")):
        _validate_is_protocol_number_is_free(proposed, session, item_id)


# --- VLAN, домены VLAN, стеки ---------------------------------------------------------------------


def _vlan_after_create(obj: VLAN, session: Session) -> None:
    _auto_assign_new_domain_vlan_to_domain_devices(obj, session)


def _domain_device_after_create(obj: VLANDomainDevice, session: Session) -> None:
    assign_domain_vlans_to_device(obj.domain_id, obj.physical_device_id, session)


def _stack_member_after_create(obj: DeviceStackMember, session: Session) -> None:
    # Тот же результат, что у POST /device-stacks/{id}/members: общие настройки VLAN стека — новому участнику.
    member = session.get(PhysicalDevice, obj.physical_device_id)
    if member:
        apply_stack_settings_to_device(session, obj.stack_id, member)


def _listed(items: list[str]) -> str:
    return "; ".join(items[:_AUDIT_LIST_LIMIT]) + ("…" if len(items) > _AUDIT_LIST_LIMIT else "")


def _vlan_move_audit_notes(vlan: VLAN, unassigned_devices: int, session: Session) -> list[str]:
    """Строки аудита о последствиях переноса VLAN в другой домен; пусто, если ни с одного устройства VLAN не снят."""
    if not unassigned_devices:
        return []
    notes = [f"VLAN снят с устройств прежнего домена: {unassigned_devices}"]
    # Подинтерфейсы на этом VLAN при снятии не удаляются (у них свои IP и открытые порты) — фиксируем, какие остались без
    # разрешённого VLAN: в форме устройства их придётся перенести на другой VLAN или удалить.
    stale = _stale_subinterfaces_on_vlan(str(vlan.id), session)
    if stale:
        notes.append(f"Подинтерфейсы остались на VLAN, не разрешённом устройству ({len(stale)}): " + _listed(stale))
    # То же для шаблонов подинтерфейсов групп портов: связи VLAN с группами сняты, а шаблоны на этом VLAN остались.
    stale_groups = _stale_group_subinterfaces_on_vlan(str(vlan.id), session)
    if stale_groups:
        notes.append(f"Подинтерфейсы групп портов остались на VLAN, которого у группы больше нет ({len(stale_groups)}): " + _listed(stale_groups))
    return notes


def _vlan_after_update(vlan: VLAN, payload: _Data, before: _Data, session: Session) -> list[str]:
    """Перенос VLAN в другой домен: снимает его с устройств прежнего домена, которых нет в новом, и назначает устройствам нового."""
    # Только когда domain_id реально менялся в этом запросе: правка другого поля (например, описания) не должна при каждом
    # сохранении заново проверять привязку к устройствам домена, в котором VLAN и так давно значится.
    if "domain_id" not in payload:
        return []
    unassigned_devices = _unassign_moved_vlan_from_former_domain_devices(vlan, before.get("domain_id"), session)
    _auto_assign_new_domain_vlan_to_domain_devices(vlan, session)
    return _vlan_move_audit_notes(vlan, unassigned_devices, session)


# --- реестр ---------------------------------------------------------------------------------------

HOOKS: dict[type, ResourceHooks] = {
    AuditLog: ResourceHooks(ordering=_audit_log_ordering),
    DeviceInterface: ResourceHooks(ordering=_interface_ordering, enrich_rows=enrich_interfaces),
    PhysicalDevice: ResourceHooks(enrich_rows=enrich_devices),
    Connection: ResourceHooks(enrich_rows=enrich_connections),
    InformationSystem: ResourceHooks(enrich_rows=enrich_information_systems),
    OpenPort: ResourceHooks(
        enrich_rows=enrich_open_ports, validate_create=_validate_new_open_port, validate_update=_validate_changed_open_port, to_dict=enrich_open_port
    ),
    ISProtocol: ResourceHooks(validate_create=_validate_new_is_protocol, validate_update=_validate_changed_is_protocol),
    VirtualMachine: ResourceHooks(prepare=_set_vm_hypervisor_os, apply_derived=_copy_vm_hypervisor_os),
    VLAN: ResourceHooks(after_create=_vlan_after_create, after_update=_vlan_after_update),
    VLANDomainDevice: ResourceHooks(after_create=_domain_device_after_create),
    DeviceStackMember: ResourceHooks(after_create=_stack_member_after_create),
}

_DEFAULT_HOOKS = ResourceHooks()


def hooks_for(model: type) -> ResourceHooks:
    """Хуки модели; для модели без особого поведения — набор по умолчанию (ничего не делает)."""
    return HOOKS.get(model, _DEFAULT_HOOKS)
