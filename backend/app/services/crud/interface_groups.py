"""Группы портов устройства: чтение, синхронизация (payload['groups']) и применение значений группы к её портам.

Вынесено из interfaces.py (тест test_modules_are_small_enough_to_review): sync_interfaces вызывает отсюда
разбор групп и _apply_group_to_interface, зависимость направлена в одну сторону (interfaces -> interface_groups).

«Все VLAN» группы (models.InterfaceGroup.all_vlans) хранится одним признаком, без строк interface_group_vlans:
набор VLAN вычисляется из VLAN устройства при чтении (services/port_vlans.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session
from ...models import DeviceInterface, IPAddress, OpenPort, PhysicalDevice, InterfaceVLAN, InterfaceGroup, InterfaceGroupIP, InterfaceGroupOpenPort, InterfaceGroupVLAN
from ...constants import OwnerType
from ..serialization import enrich_interface_groups
from ..validation import validate_unique_open_port_numbers
from .interface_group_subinterfaces import apply_group_subinterfaces, group_subinterfaces_by_group, normalize_group_subinterfaces, normalize_ips, purge_subinterfaces_of_groups, sync_group_subinterfaces, with_reused_ids
from .owned_rows import _validate_open_port_catalog, sync_owner_ip_addresses


_VLAN_MODES = frozenset({"access", "trunk"})


def list_interface_groups(device_id: str, session: Session) -> list[dict[str, Any]]:
    """Группы портов устройства с их VLAN и открытыми портами (GET /devices/{id}/interface-groups и
    поле groups ответа PUT /devices/{id}/interfaces). Порядок — по наименованию."""
    groups = session.scalars(select(InterfaceGroup).where(InterfaceGroup.physical_device_id == device_id).order_by(InterfaceGroup.name)).all()
    subinterfaces = group_subinterfaces_by_group([g.id for g in groups], session)
    return [{**data, "subinterfaces": subinterfaces.get(data["id"], [])} for data in enrich_interface_groups(groups, session)]


def get_interface_groups(device_id: str, session: Session) -> dict[str, Any]:
    if not session.get(PhysicalDevice, device_id):
        raise HTTPException(404, "Физическое устройство не найдено")
    return {"items": list_interface_groups(device_id, session)}


@dataclass
class _GroupState:
    """Разобранная группа из payload['groups']: объект в сессии и нормализованные значения,
    которые применяются к каждому порту группы (см. _apply_group_to_interface)."""

    obj: InterfaceGroup
    vlan_ids: list[str]
    open_ports: list[dict[str, Any]]
    ips: list[dict[str, Any]] = field(default_factory=list)
    subinterfaces: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class _GroupVlans:
    """Режим порта и VLAN группы после проверок: vlan_ids без повторов, а при «Все VLAN» пуст."""

    mode: str | None
    all_vlans: bool
    vlan_ids: list[str]


def _group_name(item: dict[str, Any]) -> str:
    name = str(item.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "У группы портов должно быть наименование")
    if len(name) > 100:
        raise HTTPException(422, "Наименование группы портов не должно превышать 100 символов")
    return name


def _group_vlans(item: dict[str, Any], allowed_vlans: set[str]) -> _GroupVlans:
    """Режим порта, «Все VLAN» и список VLAN группы. Порядок проверок — часть поведения: при нескольких
    нарушениях клиент получает первое из них (закреплено tests/test_normalize_group_item_behaviour.py)."""
    mode = item.get("vlan_mode") or None
    if mode is not None and mode not in _VLAN_MODES:
        raise HTTPException(422, "Поле vlan_mode группы портов должно быть 'access', 'trunk' или пустым")
    vlan_ids = item.get("vlan_ids") or []
    if not isinstance(vlan_ids, list):
        raise HTTPException(422, "Поле vlan_ids группы портов должно быть массивом")
    all_vlans = item.get("all_vlans", False)
    if not isinstance(all_vlans, bool):
        raise HTTPException(422, "Поле all_vlans группы портов должно быть true или false")
    # «Все VLAN» группы: как у порта, хранится только признак (а vlan_ids игнорируется), набор VLAN — все VLAN устройства.
    if all_vlans and mode != "trunk":
        raise HTTPException(422, "«Все VLAN» у группы портов возможно только в режиме trunk")
    if all_vlans:
        vlan_ids = []
    if vlan_ids and mode is None:
        raise HTTPException(422, "VLAN группы портов можно задать только вместе с режимом порта")
    if any(v not in allowed_vlans for v in vlan_ids):
        raise HTTPException(422, "Один или несколько VLAN не разрешены для типа данного устройства")
    unique_vlan_ids = list(dict.fromkeys(vlan_ids))
    if mode == "access" and len(unique_vlan_ids) > 1:
        raise HTTPException(422, "В режиме access у группы портов может быть не более одного VLAN")
    return _GroupVlans(mode, all_vlans, unique_vlan_ids)


def _group_ips(item: dict[str, Any], group_name: str) -> list[dict[str, Any]]:
    """Общие IP-адреса группы: адрес, префикс и назначение каждого. Строка-плейсхолдер без адреса пропускается (как у
    IP порта), назначение обрезается по краям, пустое — NULL. Адрес в группе не повторяется: иначе порт получил бы
    два одинаковых IP. Группа без единого адреса IP портов не трогает."""
    label = f"Группа портов «{group_name}»"
    raw = item.get("ips") or []
    if isinstance(raw, list):
        raw = [{**ip, "purpose": str(ip.get("purpose") or "").strip() or None} if isinstance(ip, dict) else ip for ip in raw]
    ips = normalize_ips(raw, label)
    addresses = [ip["ip_address"] for ip in ips]
    if len(set(addresses)) != len(addresses):
        raise HTTPException(422, f"{label}: IP-адреса не должны повторяться")
    return ips


def _group_open_ports(item: dict[str, Any], group_name: str, session: Session) -> tuple[bool, list[dict[str, Any]]]:
    """(управляет ли группа открытыми портами, их нормализованный список). Строка-плейсхолдер без выбранной
    записи справочника пропускается, как у порта (см. _sync_interface_open_ports); без manage_open_ports
    список открытых портов не хранится и не проверяется (кроме того, что это массив)."""
    manage = bool(item.get("manage_open_ports"))
    raw_ports = item.get("open_ports") or []
    if not isinstance(raw_ports, list):
        raise HTTPException(422, "Поле open_ports группы портов должно быть массивом")
    open_ports: list[dict[str, Any]] = []
    for port_data in raw_ports:
        if not manage or not isinstance(port_data, dict) or not port_data.get("protocol_catalog_id"):
            continue
        _validate_open_port_catalog(port_data, session)
        open_ports.append({"id": port_data.get("id"), "protocol_catalog_id": port_data["protocol_catalog_id"], "transport_protocol": port_data.get("transport_protocol") or "TCP", "description": port_data.get("description") or None})
    validate_unique_open_port_numbers((p["protocol_catalog_id"] for p in open_ports), session, f"Группа портов «{group_name}»")
    return manage, open_ports


def _group_subinterfaces(item: dict[str, Any], group_name: str, vlans: _GroupVlans, allowed_vlans: set[str], session: Session) -> tuple[bool, list[dict[str, Any]]]:
    """(управляет ли группа подинтерфейсами, их нормализованный список). Как и открытые порты, подинтерфейсы
    хранятся только пока группа ими управляет. Допустимые VLAN подинтерфейса — те, что группа записывает
    портам (при «Все VLAN» — все VLAN устройства)."""
    if not item.get("manage_subinterfaces"):
        return False, []
    group_vlans = set(allowed_vlans) if vlans.all_vlans else set(vlans.vlan_ids)
    return True, normalize_group_subinterfaces(item.get("subinterfaces") or [], group_name=group_name, vlan_mode=vlans.mode, group_vlans=group_vlans, session=session)


def _normalize_group_item(item: Any, allowed_vlans: set[str], session: Session) -> dict[str, Any]:
    """Валидирует один элемент payload['groups'] и приводит к значениям колонок. Заданность
    параметра (vlan_mode / непустой список ips / manage_open_ports) определяет, управляет ли им группа —
    см. models.InterfaceGroup. Проверки те же, что для отдельного порта (_sync_single_interface).
    Шаги: имя → режим и VLAN → общие IP → открытые порты → подинтерфейсы."""
    if not isinstance(item, dict):
        raise HTTPException(422, "Каждая группа портов должна быть объектом")
    name = _group_name(item)
    vlans = _group_vlans(item, allowed_vlans)
    ips = _group_ips(item, name)
    manage_open_ports, open_ports = _group_open_ports(item, name, session)
    manage_subinterfaces, subinterfaces = _group_subinterfaces(item, name, vlans, allowed_vlans, session)
    return {
        "name": name,
        "vlan_mode": vlans.mode,
        "all_vlans": vlans.all_vlans,
        "vlan_ids": vlans.vlan_ids,
        "ips": ips,
        "manage_open_ports": manage_open_ports,
        "open_ports": open_ports,
        "manage_subinterfaces": manage_subinterfaces,
        "subinterfaces": subinterfaces,
    }


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
        key = item.get("key") or item.get("id")
        if not key:
            raise HTTPException(422, "У группы портов должен быть key (id существующей группы или временный ключ новой)")
        if key in states:
            raise HTTPException(422, "Ключи групп портов должны быть уникальны")
        if norm["name"].casefold() in names:
            raise HTTPException(422, "Наименования групп портов на устройстве должны быть уникальны")
        names.add(norm["name"].casefold())
        group_id = item.get("id")
        if group_id:
            obj = existing.get(group_id)
            if not obj:
                raise HTTPException(422, "Группа портов не принадлежит выбранному физическому устройству")
        else:
            obj = InterfaceGroup(physical_device_id=device_id)
            session.add(obj)
        obj.name = norm["name"]
        obj.vlan_mode = norm["vlan_mode"]
        obj.all_vlans = norm["all_vlans"]
        obj.manage_open_ports = norm["manage_open_ports"]
        obj.manage_subinterfaces = norm["manage_subinterfaces"]
        session.flush()
        _sync_group_vlans(obj, norm["vlan_ids"], session)
        _sync_group_ips(obj, norm["ips"], session)
        _sync_group_open_ports(obj, norm["open_ports"], session)
        sync_group_subinterfaces(obj.id, norm["subinterfaces"], session)
        states[key] = _GroupState(obj, norm["vlan_ids"], norm["open_ports"], norm["ips"], norm["subinterfaces"])
    return states


def _sync_group_vlans(group: InterfaceGroup, vlan_ids: list[str], session: Session) -> None:
    current = session.scalars(select(InterfaceGroupVLAN).where(InterfaceGroupVLAN.group_id == group.id)).all()
    wanted = set(vlan_ids)
    for row in current:
        if row.vlan_id not in wanted:
            session.delete(row)
    have = {row.vlan_id for row in current}
    for vlan_id in vlan_ids:
        if vlan_id not in have:
            session.add(InterfaceGroupVLAN(group_id=group.id, vlan_id=vlan_id))


def _sync_group_ips(group: InterfaceGroup, ips: list[dict[str, Any]], session: Session) -> None:
    """Приводит строки общих IP группы к нормализованному списку (diff по id): новые создаются, существующие обновляются
    на месте, отсутствующие удаляются. Чужой id или id, указанный дважды, — 422."""
    old_map = {row.id: row for row in session.scalars(select(InterfaceGroupIP).where(InterfaceGroupIP.group_id == group.id)).all()}
    seen: set[str] = set()
    for data in ips:
        row_id = data.get("id")
        if row_id:
            row = old_map.get(row_id)
            if not row or row_id in seen:
                raise HTTPException(422, "IP-адрес не принадлежит выбранной группе портов")
            seen.add(row_id)
        else:
            row = InterfaceGroupIP(group_id=group.id)
            session.add(row)
        row.ip_address = data["ip_address"]
        row.prefix_length = data["prefix_length"]
        row.purpose = data["purpose"]
    for row_id, row in old_map.items():
        if row_id not in seen:
            session.delete(row)


def _sync_group_open_ports(group: InterfaceGroup, open_ports: list[dict[str, Any]], session: Session) -> None:
    old_rows = session.scalars(select(InterfaceGroupOpenPort).where(InterfaceGroupOpenPort.group_id == group.id)).all()
    old_map = {row.id: row for row in old_rows}
    seen: set[str] = set()
    for data in open_ports:
        port_id = data.get("id")
        if port_id:
            row = old_map.get(port_id)
            if not row:
                raise HTTPException(422, "Открытый порт не принадлежит выбранной группе портов")
            seen.add(port_id)
        else:
            row = InterfaceGroupOpenPort(group_id=group.id)
            session.add(row)
        row.protocol_catalog_id = data["protocol_catalog_id"]
        row.transport_protocol = data["transport_protocol"]
        row.description = data["description"]
    for row in old_rows:
        if row.id not in seen:
            session.delete(row)


def _resolve_interface_group(item: dict[str, Any], states: dict[str, _GroupState]) -> _GroupState | None:
    group_key = item.get("group_key")
    if not group_key:
        return None
    state = states.get(group_key)
    if not state:
        raise HTTPException(422, 'Порт ссылается на группу портов, которой нет в payload["groups"]')
    return state


def _apply_group_to_interface(iface: DeviceInterface, state: _GroupState, session: Session) -> None:
    """Записывает в порт значения тех параметров, которыми управляет его группа (заданы в группе):
    режим порта + VLAN, полный список общих IP (адрес, префикс и назначение каждого), полный список
    открытых портов, полный список подинтерфейсов. Повторный вызов с теми
    же значениями ничего не меняет (строки порта обновляются на месте, лишние удаляются, id не
    пересоздаются). Незаданные группой параметры порта не трогаются."""
    group = state.obj
    # autoflush отключён (db.py): без flush() запросы ниже не увидели бы VLAN/IP/порты, только что
    # добавленные _sync_single_interface() в этой же сессии, и продублировали бы их.
    session.flush()
    if group.vlan_mode:
        iface.vlan_mode = group.vlan_mode
        # «Все VLAN» группы: порт получает тот же признак и не хранит связей — набор вычисляется из VLAN устройства.
        iface.all_vlans = bool(group.all_vlans)
        links = session.scalars(select(InterfaceVLAN).where(InterfaceVLAN.interface_id == iface.id)).all()
        wanted = set() if group.all_vlans else set(state.vlan_ids)
        kept: set[str] = set()
        for link in links:
            if link.vlan_id in wanted and link.vlan_id not in kept:
                link.mode = group.vlan_mode
                kept.add(link.vlan_id)
            else:
                session.delete(link)
        for vlan_id in [] if group.all_vlans else state.vlan_ids:
            if vlan_id not in kept:
                session.add(InterfaceVLAN(interface_id=iface.id, vlan_id=vlan_id, mode=group.vlan_mode))
    if state.ips:
        _apply_group_ips(iface, state.ips, session)
    if group.manage_open_ports:
        _apply_group_open_ports(iface, state.open_ports, session)
    # Подинтерфейсы — последними: их VLAN входят в VLAN группы, которые порту записаны выше.
    if group.manage_subinterfaces:
        apply_group_subinterfaces(iface, state.subinterfaces, session)


def _apply_group_ips(iface: DeviceInterface, group_ips: list[dict[str, Any]], session: Session) -> None:
    """Приводит IP порта в точное соответствие списку группы, не пересоздавая записи: строка с тем же (адрес, префикс)
    остаётся как есть, лишние строки порта переиспользуются под ещё не размещённые адреса группы (id и дата создания
    сохраняются), остаток удаляется. Назначение — часть общего IP: группа записывает его безусловно (пустое очищает
    назначение порта). is_management наследуется от порта, как у IP, заданных вручную."""
    current = session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == iface.id).order_by(IPAddress.created_at, IPAddress.id)).all()
    wanted = with_reused_ids([(ip.id, (ip.ip_address, ip.prefix_length)) for ip in current], group_ips, lambda d: (d["ip_address"], d["prefix_length"]))
    sync_owner_ip_addresses(
        OwnerType.DEVICE_INTERFACE, iface.id, [{**ip, "is_management": bool(iface.is_management)} for ip in wanted], session, array_error="Поле ips порта должно быть массивом", foreign_id_error="IP не принадлежит выбранному порту"
    )


def _apply_group_open_ports(iface: DeviceInterface, group_ports: list[dict[str, Any]], session: Session) -> None:
    """Приводит открытые порты интерфейса в точное соответствие списку группы, не пересоздавая записи:
    строка с тем же (запись справочника, транспорт) остаётся как есть (обновляется только описание);
    оставшиеся лишние строки порта переиспользуются под ещё не размещённые порты группы — меняется
    запись справочника/транспорт, id и дата создания сохраняются (как при правке порта вручную и у ВМ);
    удаляются только строки, которым не хватило пары, создаются только порты группы без пары."""
    rows = session.scalars(select(OpenPort).where(OpenPort.owner_type == OwnerType.DEVICE_INTERFACE, OpenPort.owner_id == iface.id).order_by(OpenPort.created_at, OpenPort.id)).all()
    wanted = {(p["protocol_catalog_id"], p["transport_protocol"]): p for p in group_ports}
    kept: set[tuple[str, str]] = set()
    spare: list[OpenPort] = []
    for row in rows:
        key = (row.protocol_catalog_id, row.transport_protocol)
        if key in wanted and key not in kept:
            row.description = wanted[key]["description"]
            kept.add(key)
        else:
            spare.append(row)
    for key, data in wanted.items():
        if key in kept:
            continue
        if spare:
            row = spare.pop(0)
            row.protocol_catalog_id = data["protocol_catalog_id"]
            row.transport_protocol = data["transport_protocol"]
            row.description = data["description"]
        else:
            session.add(OpenPort(owner_type=OwnerType.DEVICE_INTERFACE, owner_id=iface.id, protocol_catalog_id=data["protocol_catalog_id"], transport_protocol=data["transport_protocol"], description=data["description"]))
    for row in spare:
        session.delete(row)


def _delete_stale_groups(device_id: str, kept_group_ids: set[str], session: Session) -> None:
    """Удаляет группы устройства, которых нет в payload['groups'], вместе с их VLAN, общими IP и открытыми
    портами. Порты уже отвязаны (group_id выставлен по payload выше). Сам бэкенд значения портов при
    этом не стирает: PUT передаёт полное состояние порта, и в БД остаётся ровно то, что прислал
    клиент — форма шлёт значения, ранее записанные из группы («оставить»), либо пустые («стереть»,
    выбор пользователя при удалении группы)."""
    stale = [g for g in session.scalars(select(InterfaceGroup).where(InterfaceGroup.physical_device_id == device_id)).all() if g.id not in kept_group_ids]
    purge_subinterfaces_of_groups([g.id for g in stale], session)
    for group in stale:
        session.execute(update(DeviceInterface).where(DeviceInterface.group_id == group.id).values(group_id=None))
        session.execute(delete(InterfaceGroupVLAN).where(InterfaceGroupVLAN.group_id == group.id))
        session.execute(delete(InterfaceGroupIP).where(InterfaceGroupIP.group_id == group.id))
        session.execute(delete(InterfaceGroupOpenPort).where(InterfaceGroupOpenPort.group_id == group.id))
        session.delete(group)
    session.flush()
