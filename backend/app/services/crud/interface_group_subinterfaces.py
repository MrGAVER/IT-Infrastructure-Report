"""Подинтерфейсы групп портов (models.InterfaceGroupSubinterface): проверка payload, синхронизация шаблонов группы,
чтение и запись шаблонов в подинтерфейсы портов группы.

Вынесено из interface_groups.py (тест test_modules_are_small_enough_to_review). Зависимость направлена в одну сторону:
interface_groups -> interface_group_subinterfaces -> subinterfaces / owned_rows.

Группа с manage_subinterfaces задаёт ПОЛНЫЙ список подинтерфейсов каждого своего порта (как manage_open_ports — полный
список открытых портов): шаблон записывается в порт подинтерфейсом `<имя порта>.<номер VLAN>`, подинтерфейсы порта,
которых нет в шаблоне, удаляются. Строки порта и шаблона сопоставляются по VLAN — на порту VLAN используется один раз.
Правила имён и повторов на уровне устройства, как и для подинтерфейсов, заданных вручную, проверяет
subinterfaces.validate_device_subinterfaces() после записи всех портов.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from ...constants import OwnerType
from ...models import DeviceInterface, DeviceSubinterface, InterfaceGroupSubinterface, InterfaceGroupSubinterfaceIP, InterfaceGroupSubinterfaceOpenPort, IPAddress, OpenPort, ProtocolPortCatalog, VLAN
from ..serialization import serialize
from ..validation import validate_ipv4_field, validate_prefix_length_field, validate_unique_open_port_numbers
from .owned_rows import _IP_PURPOSE_MAX_LENGTH, _validate_open_port_catalog, sync_owner_ip_addresses, sync_owner_open_ports
from .subinterfaces import delete_subinterfaces


def _vlan_number(vlan_id: str, session: Session) -> str:
    """Номер VLAN для текста ошибки (при неизвестном id — сам id)."""
    number = session.scalar(select(VLAN.vlan_id).where(VLAN.id == vlan_id))
    return str(number) if number is not None else vlan_id


def normalize_ips(raw: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise HTTPException(422, f"{label}: поле ips должно быть массивом")
    result: list[dict[str, Any]] = []
    for ip in raw:
        if not isinstance(ip, dict):
            raise HTTPException(422, f"{label}: каждый IP-адрес должен быть объектом")
        address = str(ip.get("ip_address") or "").strip()
        if not address:
            continue  # пустой плейсхолдер формы, как у IP порта
        validate_ipv4_field(address, f"{label}: IP-адрес")
        validate_prefix_length_field(ip.get("prefix_length"), f"{label}: префикс IP-адреса")
        purpose = ip.get("purpose") or None
        if purpose is not None and len(str(purpose)) > _IP_PURPOSE_MAX_LENGTH:
            raise HTTPException(422, f"{label}: назначение IP-адреса не должно превышать {_IP_PURPOSE_MAX_LENGTH} символов")
        prefix = ip.get("prefix_length")
        result.append({"id": ip.get("id"), "ip_address": address, "prefix_length": None if prefix in (None, "") else int(prefix), "purpose": purpose})
    return result


def _normalize_open_ports(raw: Any, label: str, session: Session) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise HTTPException(422, f"{label}: поле open_ports должно быть массивом")
    result: list[dict[str, Any]] = []
    for port in raw:
        if not isinstance(port, dict):
            raise HTTPException(422, f"{label}: каждый открытый порт должен быть объектом")
        if not port.get("protocol_catalog_id"):
            continue  # плейсхолдер без выбранной записи справочника
        _validate_open_port_catalog(port, session)
        result.append(
            {"id": port.get("id"), "protocol_catalog_id": port["protocol_catalog_id"], "transport_protocol": port.get("transport_protocol") or "TCP", "description": port.get("description") or None}
        )
    validate_unique_open_port_numbers((p["protocol_catalog_id"] for p in result), session, label)
    return result


def normalize_group_subinterfaces(raw: Any, *, group_name: str, vlan_mode: str | None, group_vlans: set[str], session: Session) -> list[dict[str, Any]]:
    """Проверяет payload['groups'][i]['subinterfaces'] и приводит к значениям колонок. group_vlans — VLAN, которые группа
    записывает своим портам (при «Все VLAN» — все VLAN устройства): подинтерфейс группы может быть только на них — то
    же правило, что подинтерфейс порта выбирается из VLAN этого порта. VLAN обязателен и уникален в группе. Подинтерфейсы
    без режима порта и VLAN группы не задаются — VLAN порта группа тогда не определяет, и проверить их нечем.

    Пример элемента: {"vlan_id": "<uuid VLAN>", "is_data_transfer": true, "ips": [{"ip_address": "10.0.10.1", "prefix_length": 24}], "open_ports": []}"""
    if not isinstance(raw, list):
        raise HTTPException(422, "Поле subinterfaces группы портов должно быть массивом")
    label = f"Группа портов «{group_name}»"
    if raw and vlan_mode is None:
        raise HTTPException(422, f"{label}: подинтерфейсы можно задать только вместе с режимом порта и VLAN группы")
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise HTTPException(422, f"{label}: каждый подинтерфейс должен быть объектом")
        vlan_id = item.get("vlan_id")
        if not vlan_id or not isinstance(vlan_id, str):
            raise HTTPException(422, f"{label}: у подинтерфейса не выбран VLAN")
        number = _vlan_number(vlan_id, session)
        if vlan_id not in group_vlans:
            raise HTTPException(422, f"{label}: VLAN {number} подинтерфейса не входит в VLAN группы — выберите другой VLAN или добавьте этот в VLAN группы")
        if vlan_id in seen:
            raise HTTPException(422, f"{label}: несколько подинтерфейсов на VLAN {number} — на порту VLAN используется один раз")
        seen.add(vlan_id)
        item_label = f"{label}, подинтерфейс на VLAN {number}"
        result.append(
            {
                "id": item.get("id"),
                "vlan_id": vlan_id,
                "is_management": bool(item.get("is_management")),
                "is_data_transfer": bool(item.get("is_data_transfer")),
                "description": item.get("description") or None,
                "ips": normalize_ips(item.get("ips") or [], item_label),
                "open_ports": _normalize_open_ports(item.get("open_ports") or [], item_label, session),
            }
        )
    return result


def _sync_children(model: type, parent_id: str, items: list[dict[str, Any]], fields: Sequence[str], session: Session) -> None:
    """Diff по id вложенных строк шаблона (IP, открытые порты): с id — обновляет, без — создаёт, отсутствующие удаляет."""
    old = {row.id: row for row in session.scalars(select(model).where(model.subinterface_id == parent_id)).all()}
    seen: set[str] = set()
    for data in items:
        row_id = data.get("id")
        if row_id:
            row = old.get(row_id)
            if not row or row_id in seen:
                raise HTTPException(422, "Запись не принадлежит выбранному подинтерфейсу группы портов")
            seen.add(row_id)
        else:
            row = model(subinterface_id=parent_id)
            session.add(row)
        for field in fields:
            setattr(row, field, data[field])
    for row_id, row in old.items():
        if row_id not in seen:
            session.delete(row)


def sync_group_subinterfaces(group_id: str, subinterfaces: list[dict[str, Any]], session: Session) -> None:
    """Приводит шаблоны подинтерфейсов группы к нормализованному списку (diff по id, как у подинтерфейсов порта): новые
    создаются, существующие обновляются, отсутствующие удаляются вместе со своими IP и открытыми портами. Пустой список
    (в том числе когда группа перестала управлять подинтерфейсами) удаляет все шаблоны. Транзакцию не коммитит."""
    existing = {row.id: row for row in session.scalars(select(InterfaceGroupSubinterface).where(InterfaceGroupSubinterface.group_id == group_id)).all()}
    seen: set[str] = set()
    for data in subinterfaces:
        row_id = data.get("id")
        if row_id:
            row = existing.get(row_id)
            if not row:
                raise HTTPException(422, "Подинтерфейс не принадлежит выбранной группе портов")
            if row_id in seen:
                raise HTTPException(422, "Один и тот же подинтерфейс группы указан в списке несколько раз")
        else:
            row = InterfaceGroupSubinterface(group_id=group_id)
            session.add(row)
        row.vlan_id = data["vlan_id"]
        row.is_management = data["is_management"]
        row.is_data_transfer = data["is_data_transfer"]
        row.description = data["description"]
        session.flush()  # autoflush отключён (db.py): без flush() у нового шаблона нет id для его IP и открытых портов
        seen.add(row.id)
        _sync_children(InterfaceGroupSubinterfaceIP, row.id, data["ips"], ("ip_address", "prefix_length", "purpose"), session)
        _sync_children(InterfaceGroupSubinterfaceOpenPort, row.id, data["open_ports"], ("protocol_catalog_id", "transport_protocol", "description"), session)
    delete_group_subinterfaces([row_id for row_id in existing if row_id not in seen], session)


def delete_group_subinterfaces(subinterface_ids: Iterable[str], session: Session) -> None:
    """Удаляет шаблоны подинтерфейсов группы и их IP/открытые порты (явно: не полагаемся на каскад БД)."""
    ids = list(subinterface_ids)
    if not ids:
        return
    for model in (InterfaceGroupSubinterfaceIP, InterfaceGroupSubinterfaceOpenPort):
        session.execute(delete(model).where(model.subinterface_id.in_(ids)))
    session.execute(delete(InterfaceGroupSubinterface).where(InterfaceGroupSubinterface.id.in_(ids)))


def purge_subinterfaces_of_groups(group_ids: Iterable[str], session: Session) -> None:
    """Удаляет все шаблоны подинтерфейсов указанных групп — вызывать до удаления самих групп."""
    ids = list(group_ids)
    if ids:
        delete_group_subinterfaces(session.scalars(select(InterfaceGroupSubinterface.id).where(InterfaceGroupSubinterface.group_id.in_(ids))).all(), session)


def group_subinterfaces_by_group(group_ids: Sequence[str], session: Session) -> dict[str, list[dict[str, Any]]]:
    """{id группы -> её подинтерфейсы с вложенными ips и open_ports}, порядок — по номеру VLAN. Три запроса на все группы."""
    if not group_ids:
        return {}
    rows = session.scalars(
        select(InterfaceGroupSubinterface)
        .join(VLAN, VLAN.id == InterfaceGroupSubinterface.vlan_id)
        .where(InterfaceGroupSubinterface.group_id.in_(list(group_ids)))
        .order_by(VLAN.vlan_id, InterfaceGroupSubinterface.id)
    ).all()
    if not rows:
        return {}
    ids = [row.id for row in rows]
    ips: dict[str, list[dict[str, Any]]] = {}
    for ip in session.scalars(
        select(InterfaceGroupSubinterfaceIP).where(InterfaceGroupSubinterfaceIP.subinterface_id.in_(ids)).order_by(InterfaceGroupSubinterfaceIP.ip_address, InterfaceGroupSubinterfaceIP.id)
    ).all():
        ips.setdefault(ip.subinterface_id, []).append(serialize(ip))
    ports: dict[str, list[dict[str, Any]]] = {}
    for port in session.scalars(
        select(InterfaceGroupSubinterfaceOpenPort)
        .join(ProtocolPortCatalog, InterfaceGroupSubinterfaceOpenPort.protocol_catalog_id == ProtocolPortCatalog.id)
        .where(InterfaceGroupSubinterfaceOpenPort.subinterface_id.in_(ids))
        .order_by(ProtocolPortCatalog.port, InterfaceGroupSubinterfaceOpenPort.transport_protocol)
    ).all():
        ports.setdefault(port.subinterface_id, []).append(serialize(port))
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(row.group_id, []).append({**serialize(row), "ips": ips.get(row.id, []), "open_ports": ports.get(row.id, [])})
    return result


def with_reused_ids(existing: list[tuple[str, Any]], wanted: list[dict[str, Any]], key: Callable[[dict[str, Any]], Any]) -> list[dict[str, Any]]:
    """Строки `wanted` с id уже стоящих у подинтерфейса записей: сначала запись с тем же смыслом (key), затем лишние
    записи по порядку — сервер обновит их на месте, а не пересоздаст (id и дата создания сохраняются). Остаток existing
    без пары попадёт под удаление в sync_owner_*; строка без свободной записи создастся новой."""
    pool: dict[Any, list[str]] = {}
    for row_id, row_key in existing:
        pool.setdefault(row_key, []).append(row_id)
    assigned: list[str | None] = [pool[key(w)].pop(0) if pool.get(key(w)) else None for w in wanted]
    taken = {a for a in assigned if a}
    spare = [row_id for row_id, _ in existing if row_id not in taken]
    return [{**w, "id": a or (spare.pop(0) if spare else None)} for w, a in zip(wanted, assigned)]


def apply_group_subinterfaces(iface: DeviceInterface, templates: list[dict[str, Any]], session: Session) -> None:
    """Записывает подинтерфейсы группы в порт: полный список — по шаблону на каждый VLAN группы, имя `<порт>.<номер VLAN>`.
    Подинтерфейс порта на том же VLAN обновляется на месте (id сохраняется, как и id его IP и открытых портов), недостающие
    создаются, остальные подинтерфейсы порта удаляются. Повторный вызов с теми же шаблонами ничего не меняет."""
    session.flush()  # autoflush отключён (db.py): иначе подинтерфейсы, только что записанные из payload порта, не видны
    existing = session.scalars(select(DeviceSubinterface).where(DeviceSubinterface.parent_interface_id == iface.id).order_by(DeviceSubinterface.created_at, DeviceSubinterface.id)).all()
    by_vlan: dict[str, DeviceSubinterface] = {}
    for sub in existing:
        by_vlan.setdefault(sub.vlan_id, sub)
    numbers = dict(session.execute(select(VLAN.id, VLAN.vlan_id).where(VLAN.id.in_({t["vlan_id"] for t in templates}))).all()) if templates else {}
    kept: set[str] = set()
    for template in templates:
        sub = by_vlan.get(template["vlan_id"])
        if sub is None:
            sub = DeviceSubinterface(parent_interface_id=iface.id, vlan_id=template["vlan_id"])
            session.add(sub)
        sub.name = f"{iface.name}.{numbers[template['vlan_id']]}"
        sub.is_management = template["is_management"]
        sub.is_data_transfer = template["is_data_transfer"]
        sub.description = template["description"]
        session.flush()
        kept.add(sub.id)
        current_ips = session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_SUBINTERFACE, IPAddress.owner_id == sub.id).order_by(IPAddress.created_at, IPAddress.id)).all()
        ips = with_reused_ids([(ip.id, (ip.ip_address, ip.prefix_length)) for ip in current_ips], template["ips"], lambda d: (d["ip_address"], d["prefix_length"]))
        # is_management IP наследуется от подинтерфейса, как у IP подинтерфейса, заданного вручную.
        sync_owner_ip_addresses(
            OwnerType.DEVICE_SUBINTERFACE,
            sub.id,
            [{**ip, "is_management": sub.is_management} for ip in ips],
            session,
            array_error="Поле ips подинтерфейса должно быть массивом",
            foreign_id_error="IP не принадлежит выбранному подинтерфейсу",
        )
        current_ports = session.scalars(select(OpenPort).where(OpenPort.owner_type == OwnerType.DEVICE_SUBINTERFACE, OpenPort.owner_id == sub.id).order_by(OpenPort.created_at, OpenPort.id)).all()
        ports = with_reused_ids([(p.id, (p.protocol_catalog_id, p.transport_protocol)) for p in current_ports], template["open_ports"], lambda d: (d["protocol_catalog_id"], d["transport_protocol"]))
        sync_owner_open_ports(
            OwnerType.DEVICE_SUBINTERFACE,
            sub.id,
            ports,
            session,
            owner_label=f"Подинтерфейс «{sub.name}»",
            array_error="Поле open_ports подинтерфейса должно быть массивом",
            foreign_id_error="Открытый порт не принадлежит выбранному подинтерфейсу",
        )
    delete_subinterfaces([sub.id for sub in existing if sub.id not in kept], session)
