"""Подинтерфейсы портов устройства (models.DeviceSubinterface): синхронизация, чтение, удаление."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Sequence
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from ...constants import OwnerType
from ...models import DeviceInterface, DeviceSubinterface, InterfaceGroupSubinterface, IPAddress, OpenPort, PhysicalDevice, ProtocolPortCatalog, VLAN
from ..port_vlans import effective_vlan_ids
from ..serialization import enrich_open_ports, serialize
from .owned_rows import sync_owner_ip_addresses, sync_owner_open_ports


# Длина колонки device_subinterfaces.name (models.DeviceSubinterface).
_NAME_MAX_LENGTH = 100


def _normalize_subinterface_item(item: dict[str, Any], allowed_vlans: set[str]) -> dict[str, Any]:
    """Валидирует один элемент payload['interfaces'][i]['subinterfaces'] и приводит его к значениям
    колонок. VLAN обязателен: подинтерфейс — это логический интерфейс на конкретном VLAN, без него
    он не определён. Разрешённые VLAN те же, что у портов устройства (allowed_vlans приходит готовым
    из sync_interfaces)."""
    name = str(item.get("name") or "").strip()
    if not name:
        raise HTTPException(422, "У каждого подинтерфейса должно быть имя")
    if len(name) > _NAME_MAX_LENGTH:
        raise HTTPException(422, f"Имя подинтерфейса «{name[:30]}…» не должно превышать {_NAME_MAX_LENGTH} символов")
    vlan_id = item.get("vlan_id")
    if not vlan_id:
        raise HTTPException(422, f"У подинтерфейса «{name}» не выбран VLAN")
    if not isinstance(vlan_id, str) or vlan_id not in allowed_vlans:
        raise HTTPException(422, f"VLAN подинтерфейса «{name}» не разрешён для данного устройства: выберите другой VLAN или добавьте этот в «VLAN устройства»")
    return {
        "name": name,
        "vlan_id": vlan_id,
        "is_management": bool(item.get("is_management")),
        "is_data_transfer": bool(item.get("is_data_transfer")),
        "description": item.get("description") or None,
    }


def _sync_subinterface_children(sub: DeviceSubinterface, item: dict[str, Any], session: Session) -> None:
    """IP-адреса и открытые порты подинтерфейса — та же diff-синхронизация по id, что и у порта
    (sync_owner_ip_addresses / sync_owner_open_ports), с owner_type=DEVICE_SUBINTERFACE. is_management
    IP наследуется от самого подинтерфейса, как у IP порта (отдельно у IP не редактируется)."""
    ips = item.get("ips") or []
    if not isinstance(ips, list):
        raise HTTPException(422, f"Поле ips подинтерфейса «{sub.name}» должно быть массивом")
    try:
        sync_owner_ip_addresses(
            OwnerType.DEVICE_SUBINTERFACE,
            sub.id,
            [{**ip, "is_management": sub.is_management} if isinstance(ip, dict) else ip for ip in ips],
            session,
            array_error=f"Поле ips подинтерфейса «{sub.name}» должно быть массивом",
            foreign_id_error="IP не принадлежит выбранному подинтерфейсу",
        )
    except HTTPException as exc:
        # Общие сообщения проверки IP не называют владельца — для формы с десятками подинтерфейсов
        # без этого неясно, где ошибка.
        if exc.status_code == 422 and isinstance(exc.detail, str) and "подинтерфейс" not in exc.detail:
            raise HTTPException(422, f"Подинтерфейс «{sub.name}»: {exc.detail}") from exc
        raise
    sync_owner_open_ports(
        OwnerType.DEVICE_SUBINTERFACE,
        sub.id,
        item.get("open_ports") or [],
        session,
        owner_label=f"Подинтерфейс «{sub.name}»",
        array_error=f"Поле open_ports подинтерфейса «{sub.name}» должно быть массивом",
        foreign_id_error="Открытый порт не принадлежит выбранному подинтерфейсу",
    )


def sync_subinterfaces(parent: DeviceInterface, items: Any, allowed_vlans: set[str], session: Session) -> int:
    """Приводит подинтерфейсы порта parent к присланному списку (diff по id, как у IP порта):
    элемент с id обновляет существующий подинтерфейс, без id — создаёт новый, отсутствующие в
    списке удаляются вместе со своими IP и открытыми портами. Возвращает число подинтерфейсов
    порта после синхронизации.

    parent уже должен быть записан (flush) — у нового порта иначе нет id. Транзакцию функция не
    коммитит. Уникальность имён и VLAN на уровне устройства проверяет validate_device_subinterfaces()
    после того, как записаны все порты.

    Пример payload порта: {"name": "Gi0/0", ..., "subinterfaces": [{"name": "Gi0/0.10",
    "vlan_id": "<uuid VLAN>", "is_data_transfer": true, "ips": [{"ip_address": "10.0.10.1",
    "prefix_length": 24}], "open_ports": []}]}"""
    if not isinstance(items, list):
        raise HTTPException(422, "Поле subinterfaces интерфейса должно быть массивом")
    existing = session.scalars(select(DeviceSubinterface).where(DeviceSubinterface.parent_interface_id == parent.id)).all()
    existing_map = {x.id: x for x in existing}
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise HTTPException(422, "Каждый подинтерфейс должен быть объектом")
        values = _normalize_subinterface_item(item, allowed_vlans)
        sub_id = item.get("id")
        if sub_id:
            sub = existing_map.get(sub_id)
            if not sub:
                raise HTTPException(422, "Подинтерфейс не принадлежит выбранному порту")
            if sub_id in seen:
                raise HTTPException(422, "Один и тот же подинтерфейс указан в списке несколько раз")
            seen.add(sub_id)
        else:
            sub = DeviceSubinterface(parent_interface_id=parent.id)
            session.add(sub)
        for key, value in values.items():
            setattr(sub, key, value)
        # autoflush отключён (db.py): без flush() у нового подинтерфейса нет id для владельца IP/портов.
        session.flush()
        _sync_subinterface_children(sub, item, session)
    delete_subinterfaces([x.id for x in existing if x.id not in seen], session)
    return len(items)


def validate_device_subinterfaces(device_id: str, session: Session) -> None:
    """Инварианты подинтерфейсов устройства, которые нельзя проверить по одному порту: имя уникально
    на устройстве (без учёта регистра) и не совпадает с именем порта; на одном порту не бывает двух
    подинтерфейсов на одном VLAN. Вызывать после записи всех портов устройства: проверяется
    итоговое состояние БД, поэтому обмен именами или VLAN между подинтерфейсами одним запросом
    допустим. Бросает HTTPException(422).

    Правила: имя уникально на устройстве (без учёта регистра) и не совпадает с именем порта; на порту VLAN
    подинтерфейса используется один раз и входит в VLAN самого порта."""
    session.flush()
    rows = session.execute(
        select(DeviceSubinterface.name, DeviceSubinterface.parent_interface_id, DeviceSubinterface.vlan_id, DeviceInterface.name.label("parent_name"), VLAN.vlan_id.label("vlan_number"))
        .join(DeviceInterface, DeviceInterface.id == DeviceSubinterface.parent_interface_id)
        .join(VLAN, VLAN.id == DeviceSubinterface.vlan_id)
        .where(DeviceInterface.physical_device_id == device_id)
        .order_by(DeviceInterface.name, VLAN.vlan_id, DeviceSubinterface.name)
    ).all()
    if not rows:
        return
    names = Counter(r.name.casefold() for r in rows)
    for r in rows:
        if names[r.name.casefold()] > 1:
            raise HTTPException(422, f"Имя подинтерфейса «{r.name}» повторяется на устройстве — имена подинтерфейсов должны быть уникальны")
    vlans = Counter((r.parent_interface_id, r.vlan_number) for r in rows)
    for r in rows:
        if vlans[(r.parent_interface_id, r.vlan_number)] > 1:
            raise HTTPException(422, f"На порту «{r.parent_name}» несколько подинтерфейсов на VLAN {r.vlan_number} — на одном порту VLAN используется один раз")
    port_names = {n.casefold() for n in session.scalars(select(DeviceInterface.name).where(DeviceInterface.physical_device_id == device_id)).all()}
    for r in rows:
        if r.name.casefold() in port_names:
            raise HTTPException(422, f"Имя подинтерфейса «{r.name}» совпадает с именем порта устройства")
    # VLAN подинтерфейса — один из VLAN его порта (у порта с «Все VLAN» — любой VLAN устройства): форма выбирает VLAN только
    # из них, API не должен обходить это правило. Проверяется итоговое состояние: к этому моменту записаны и VLAN портов, и
    # применённые группами. Порт без VLAN подинтерфейсов иметь не может.
    port_vlans = effective_vlan_ids(session, list({r.parent_interface_id for r in rows}))
    for r in rows:
        if r.vlan_id not in port_vlans.get(r.parent_interface_id, set()):
            raise HTTPException(422, f"VLAN {r.vlan_number} подинтерфейса «{r.name}» не выбран на порту «{r.parent_name}» — выберите другой VLAN подинтерфейса или добавьте этот VLAN порту")


def delete_subinterfaces(subinterface_ids: Iterable[str], session: Session) -> None:
    """Удаляет подинтерфейсы и их IP-адреса/открытые порты. Полиморфные строки (owner_type/owner_id)
    без FK сами не каскадируются — без явного удаления они осиротели бы."""
    ids = list(subinterface_ids)
    if not ids:
        return
    for model in (IPAddress, OpenPort):
        session.execute(delete(model).where(model.owner_type == OwnerType.DEVICE_SUBINTERFACE, model.owner_id.in_(ids)))
    session.execute(delete(DeviceSubinterface).where(DeviceSubinterface.id.in_(ids)))


def purge_subinterfaces_of_interfaces(interface_ids: Iterable[str], session: Session) -> None:
    """Удаляет все подинтерфейсы указанных портов (со своими IP и открытыми портами) — вызывать до
    удаления самих портов: FK ON DELETE CASCADE убрал бы строки подинтерфейсов, но не их IP/порты."""
    ids = list(interface_ids)
    if not ids:
        return
    sub_ids = session.scalars(select(DeviceSubinterface.id).where(DeviceSubinterface.parent_interface_id.in_(ids))).all()
    delete_subinterfaces(sub_ids, session)


def subinterface_references(resource: str, item_id: str, session: Session) -> list[tuple[str, int]]:
    """Ссылки подинтерфейсов на удаляемую запись в формате (название, количество), как у
    _find_referencing_counts(): подинтерфейсы не зарегистрированы в MODEL_MAP, поэтому структурный
    поиск ссылок их не видит. Сейчас на подинтерфейсы ссылается только VLAN."""
    if resource != "vlans":
        return []
    count = len(session.scalars(select(DeviceSubinterface.id).where(DeviceSubinterface.vlan_id == item_id)).all())
    group_count = len(session.scalars(select(InterfaceGroupSubinterface.id).where(InterfaceGroupSubinterface.vlan_id == item_id)).all())
    return [pair for pair in (("Подинтерфейсы устройств", count), ("Подинтерфейсы групп портов", group_count)) if pair[1]]


def enrich_subinterfaces(subinterfaces: Sequence[DeviceSubinterface], session: Session) -> list[dict[str, Any]]:
    """Подинтерфейсы с вложенными ips и open_ports (в формате элементов interfaces у порта). Два
    запроса на весь список, а не по запросу на подинтерфейс. Порядок сохраняется."""
    if not subinterfaces:
        return []
    ids = [s.id for s in subinterfaces]
    ips_by_owner: dict[str, list[dict[str, Any]]] = {}
    for ip in session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_SUBINTERFACE, IPAddress.owner_id.in_(ids)).order_by(IPAddress.ip_address, IPAddress.id)).all():
        ips_by_owner.setdefault(ip.owner_id, []).append(serialize(ip))
    ports = session.scalars(select(OpenPort).join(ProtocolPortCatalog, OpenPort.protocol_catalog_id == ProtocolPortCatalog.id).where(OpenPort.owner_type == OwnerType.DEVICE_SUBINTERFACE, OpenPort.owner_id.in_(ids)).order_by(ProtocolPortCatalog.port, OpenPort.transport_protocol, OpenPort.id)).all()
    ports_by_owner: dict[str, list[dict[str, Any]]] = {}
    for port in enrich_open_ports(ports, session):
        ports_by_owner.setdefault(port["owner_id"], []).append(port)
    return [{**serialize(s), "ips": ips_by_owner.get(s.id, []), "open_ports": ports_by_owner.get(s.id, [])} for s in subinterfaces]


def subinterfaces_by_parent(interface_ids: Sequence[str], session: Session) -> dict[str, list[dict[str, Any]]]:
    """{id порта -> его подинтерфейсы (enrich_subinterfaces)}, порядок — по номеру VLAN, затем по имени."""
    if not interface_ids:
        return {}
    subs = session.scalars(select(DeviceSubinterface).join(VLAN, VLAN.id == DeviceSubinterface.vlan_id).where(DeviceSubinterface.parent_interface_id.in_(list(interface_ids))).order_by(VLAN.vlan_id, DeviceSubinterface.name, DeviceSubinterface.id)).all()
    result: dict[str, list[dict[str, Any]]] = {}
    for data in enrich_subinterfaces(subs, session):
        result.setdefault(data["parent_interface_id"], []).append(data)
    return result


def get_device_subinterfaces(device_id: str, session: Session) -> dict[str, Any]:
    """GET /devices/{id}/subinterfaces — все подинтерфейсы портов устройства (с IP и открытыми
    портами), порядок — по порту, затем по VLAN. Одним запросом на устройство вместо выборки по всем
    устройствам сразу, как у портов через generic /resources."""
    if not session.get(PhysicalDevice, device_id):
        raise HTTPException(404, "Физическое устройство не найдено")
    subs = session.scalars(select(DeviceSubinterface).join(DeviceInterface, DeviceInterface.id == DeviceSubinterface.parent_interface_id).join(VLAN, VLAN.id == DeviceSubinterface.vlan_id).where(DeviceInterface.physical_device_id == device_id).order_by(DeviceInterface.name, DeviceInterface.id, VLAN.vlan_id, DeviceSubinterface.name, DeviceSubinterface.id)).all()
    return {"items": enrich_subinterfaces(subs, session)}
