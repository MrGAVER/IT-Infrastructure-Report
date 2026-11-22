"""Синхронизация портов (интерфейсов) устройства: sync_interfaces и запись одного порта. Группы портов — interface_groups.py."""

from __future__ import annotations

from typing import Any
from fastapi import HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ...models import DeviceInterface, IPAddress, OpenPort, PhysicalDevice, ProtocolPortCatalog, DeviceTypeVLAN, PhysicalDeviceVLAN, InterfaceVLAN, VLAN
from ...constants import AuditAction, OwnerType
from ..serialization import enrich_open_ports, serialize
from ..integrity import integrity_error_response
from ..port_vlans import effective_vlan_ids
from ..interface_connections import assert_interfaces_not_connected, sync_interface_connections
from ..validation import validate_ipv4_field, validate_prefix_length_field
from .audit_log import audit
from .interface_groups import _VLAN_MODES, _apply_group_to_interface, _delete_stale_groups, _resolve_interface_group, _sync_interface_groups, list_interface_groups
from .owned_rows import sync_owner_open_ports
from .subinterfaces import purge_subinterfaces_of_interfaces, subinterfaces_by_parent, sync_subinterfaces, validate_device_subinterfaces


_PLAIN_PORT_FIELDS = ("name", "interface_type_id", "mac_address", "speed_id", "is_management", "is_data_transfer", "description")


def _apply_port_fields_and_mode(obj: DeviceInterface, item: dict[str, Any], session: Session) -> tuple[str, bool]:
    """Простые поля порта, режим VLAN и признак «Все VLAN»; возвращает (vlan_mode, all_vlans) для следующих шагов."""
    for key in _PLAIN_PORT_FIELDS:
        if key in item:
            setattr(obj, key, item[key])
    # vlan_mode хранится на самом интерфейсе (фикс п.1.3.9 — см. миграцию 5b5ea0e81d32), а не
    # только выводится из InterfaceVLAN.mode: иначе access-порт без единого VLAN нечем было бы
    # запомнить между сохранением и следующей загрузкой. 'trunk', если поле не прислано вовсе, —
    # тот же дефолт, что и у колонки в БД (совместимо со старыми клиентами API).
    vlan_mode = item.get("vlan_mode") or "trunk"
    if vlan_mode not in _VLAN_MODES:
        raise HTTPException(422, "Поле vlan_mode интерфейса должно быть 'access' или 'trunk'")
    # Аудит fix/usability-batch4 (находка №2): присваиваем ДО flush() — простые поля выше по
    # функции попадут в тот же autoflush-UPDATE, вместо отдельного второго UPDATE на этот же
    # интерфейс при следующем autoflush (session.execute(delete(...)) ниже). При синхронизации
    # устройства с десятками портов это лишний десяток write-запросов на каждый PUT.
    obj.vlan_mode = vlan_mode
    # «Все VLAN» — сохраняемый признак порта, а не вывод из числа выбранных VLAN (см. models.DeviceInterface.all_vlans):
    # порт с признаком хранит только его, а набор VLAN вычисляется из VLAN устройства при чтении
    # (services/port_vlans.py). Ключ не прислан (старый клиент) — признак снят, как у нового порта.
    all_vlans = item.get("all_vlans", False)
    if not isinstance(all_vlans, bool):
        raise HTTPException(422, "Поле all_vlans интерфейса должно быть true или false")
    if all_vlans and vlan_mode != "trunk":
        raise HTTPException(422, "«Все VLAN» возможно только в режиме trunk")
    obj.all_vlans = all_vlans
    session.flush()
    return vlan_mode, all_vlans


def _replace_port_vlans(obj: DeviceInterface, item: dict[str, Any], vlan_mode: str, all_vlans: bool, allowed_vlans: set[str], session: Session) -> None:
    """Заменяет VLAN-привязки порта списком из payload (с проверкой допустимости и ограничением access)."""
    vlan_ids = item.get("vlan_ids") or []
    if not isinstance(vlan_ids, list):
        raise HTTPException(422, "Поле vlan_ids интерфейса должно быть массивом")
    # С «Все VLAN» список vlan_ids игнорируется (клиент присылает его как отражение черновика формы): хранится
    # только признак, и допустимость VLAN проверять не нужно — набор всегда равен набору устройства.
    if not all_vlans:
        bad = [v for v in vlan_ids if v not in allowed_vlans]
        if bad:
            raise HTTPException(422, "Один или несколько VLAN не разрешены для типа данного устройства")
    unique_vlan_ids = [] if all_vlans else list(dict.fromkeys(vlan_ids))
    # Защита на бэкенде того же инварианта, что и validateInterfaceDraftRows() на фронтенде —
    # там это только UI-проверка перед отправкой запроса, здесь гарантия для любого вызывающего
    # API-код напрямую (или старого кэшированного фронтенд-бандла). Читает локальную переменную
    # vlan_mode, а не obj.vlan_mode — та уже присвоена выше и не меняется дальше по функции.
    if vlan_mode == "access" and len(unique_vlan_ids) > 1:
        raise HTTPException(422, "В режиме access у порта может быть не более одного VLAN")
    session.execute(delete(InterfaceVLAN).where(InterfaceVLAN.interface_id == obj.id))
    for vlan_id in unique_vlan_ids:
        session.add(InterfaceVLAN(interface_id=obj.id, vlan_id=vlan_id, mode=vlan_mode))


def _sync_port_ips(obj: DeviceInterface, item: dict[str, Any], session: Session) -> None:
    """IP-адреса порта: diff по id — новые создаются, переданные обновляются, пропавшие удаляются."""
    ips = item.get("ips") or []
    if not isinstance(ips, list):
        raise HTTPException(422, "Поле ips интерфейса должно быть массивом")
    old_ips = session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == obj.id)).all()
    old_map = {x.id: x for x in old_ips}
    seen: set[str] = set()
    for ip_data in ips:
        if not isinstance(ip_data, dict) or not ip_data.get("ip_address"):
            continue
        # Формат проверялся только на фронтенде (ipValidation.ts) — прямой
        # запрос к API мог записать в IPAddress произвольную строку вместо IPv4-адреса.
        validate_ipv4_field(ip_data.get("ip_address"), "IP-адрес интерфейса")
        validate_prefix_length_field(ip_data.get("prefix_length"), "Префикс IP-адреса интерфейса")
        ip_id = ip_data.get("id")
        if ip_id:
            ip_obj = old_map.get(ip_id)
            if not ip_obj:
                raise HTTPException(422, "IP не принадлежит выбранному интерфейсу")
            seen.add(ip_id)
        else:
            ip_obj = IPAddress(owner_type=OwnerType.DEVICE_INTERFACE, owner_id=obj.id)
            session.add(ip_obj)
        ip_obj.ip_address = ip_data["ip_address"]
        ip_obj.prefix_length = ip_data.get("prefix_length")
        ip_obj.purpose = ip_data.get("purpose")
        ip_obj.is_management = bool(obj.is_management)
    for old_ip in old_ips:
        if old_ip.id not in seen:
            session.delete(old_ip)


def _sync_single_interface(obj: DeviceInterface, item: dict[str, Any], device: PhysicalDevice, session: Session, allowed_vlans: set[str]) -> None:
    """Применяет данные одного элемента payload['interfaces'] к объекту DeviceInterface:
    простые поля, VLAN-привязки, вложенные IP и открытые порты (шаги — выше).

    allowed_vlans приходит готовым от вызывающей стороны: набор допустимых VLAN одинаков для всех
    интерфейсов одного device, поэтому вычисляется один раз в sync_interfaces(), а не запросом на
    каждый интерфейс здесь (было N+1 при синхронизации устройства с несколькими портами)."""
    vlan_mode, all_vlans = _apply_port_fields_and_mode(obj, item, session)
    _replace_port_vlans(obj, item, vlan_mode, all_vlans, allowed_vlans, session)
    _sync_port_ips(obj, item, session)
    _sync_interface_open_ports(obj, item.get("open_ports") or [], session)


def _sync_interface_open_ports(obj: DeviceInterface, open_ports: Any, session: Session) -> None:
    """п.1.4 (батч4): "Открытые порты" — теперь свойство конкретного интерфейса, а не всего
    устройства (полиморфный OpenPort.owner_type=DEVICE_INTERFACE, owner_id=интерфейс), той же
    diff-схемой по id, что и IP интерфейса чуть выше (см. sync_owner_open_ports). Раньше один
    список открытых портов относился ко всему устройству разом (owner_type=PHYSICAL_DEVICE) —
    это не позволяло корректно заполнить Лист 3 отчёта, где колонка "Перечень открытых портов"
    относится к КОНКРЕТНОМУ физическому/логическому порту (см. reporting.py:_port_open_info)."""
    sync_owner_open_ports(
        OwnerType.DEVICE_INTERFACE,
        obj.id,
        open_ports,
        session,
        owner_label=f"Порт «{obj.name or 'без имени'}»",
        array_error="Поле open_ports интерфейса должно быть массивом",
        foreign_id_error="Открытый порт не принадлежит выбранному интерфейсу",
    )


def _read_sync_payload(payload: dict[str, Any]) -> tuple[list[Any], Any, bool]:
    """Возвращает (interfaces, groups, управляем_ли_группами) с проверкой типов."""
    items = payload.get("interfaces", [])
    if not isinstance(items, list):
        raise HTTPException(422, "Поле interfaces должно быть массивом")
    # Группы портов: payload['groups'] — полный список групп устройства (как и interfaces — diff с
    # БД). Ключа нет вовсе (старый клиент API) — группы и group_id портов не трогаем; ключ есть —
    # он единственный источник истины о группах и о принадлежности к ним каждого порта.
    groups_payload = payload.get("groups")
    manage_groups = groups_payload is not None
    if manage_groups and not isinstance(groups_payload, list):
        raise HTTPException(422, "Поле groups должно быть массивом")
    return items, groups_payload, manage_groups


def _allowed_vlans_for_device(device: PhysicalDevice, session: Session) -> set[str]:
    """VLAN, допустимые для портов устройства: VLAN его типа и собственные VLAN устройства.

    Allowed VLANs depend only on the device (its type and its own local VLANs), not on the
    interface, so they're resolved once per sync instead of once per interface inside the loop."""
    allowed_type = set(session.scalars(select(DeviceTypeVLAN.vlan_id).where(DeviceTypeVLAN.device_type_id == device.device_type_id)).all())
    allowed_device = set(session.scalars(select(PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id == device.id)).all())
    return allowed_type | allowed_device


def _remove_stale_interfaces(existing: list[DeviceInterface], incoming_ids: set[str], session: Session) -> None:
    """Удаляет порты, которых нет в payload, вместе с их подинтерфейсами, IP и открытыми портами (если порт не подключён)."""
    stale = [obj for obj in existing if obj.id not in incoming_ids]
    assert_interfaces_not_connected(stale, session)
    purge_subinterfaces_of_interfaces([obj.id for obj in stale], session)
    for obj in stale:
        session.execute(delete(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == obj.id))
        # Открытые порты полиморфны (нет FK/каскада на уровне БД, см. models.OpenPort) —
        # без явного удаления здесь они осиротели бы при удалении своего интерфейса.
        session.execute(delete(OpenPort).where(OpenPort.owner_type == OwnerType.DEVICE_INTERFACE, OpenPort.owner_id == obj.id))
        session.delete(obj)


def _synced_interfaces_response(device_id: str, session: Session) -> dict[str, Any]:
    """Ответ PUT /devices/{id}/interfaces: группы и порты в порядке sort_order с IP, открытыми портами и подинтерфейсами."""
    result = session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id == device_id).order_by(DeviceInterface.sort_order, DeviceInterface.created_at, DeviceInterface.id)).all()
    subinterfaces = subinterfaces_by_parent([iface.id for iface in result], session)
    return {
        "groups": list_interface_groups(device_id, session),
        "items": [
            {
                **serialize(iface),
                "subinterfaces": subinterfaces.get(iface.id, []),
                "ips": [serialize(ip) for ip in session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == iface.id).order_by(IPAddress.ip_address)).all()],
                # port больше не колонка OpenPort (см. models.py) — сортируем по номеру порта из
                # справочника через join, а не по несуществующей больше колонке.
                "open_ports": enrich_open_ports(
                    session.scalars(select(OpenPort).join(ProtocolPortCatalog, OpenPort.protocol_catalog_id == ProtocolPortCatalog.id).where(OpenPort.owner_type == OwnerType.DEVICE_INTERFACE, OpenPort.owner_id == iface.id).order_by(ProtocolPortCatalog.port)).all(),
                    session,
                ),
            }
            for iface in result
        ],
    }


def _resolve_port_object(item: Any, device_id: str, existing_map: dict[str, DeviceInterface], incoming_ids: set[str], session: Session) -> DeviceInterface:
    """Порт для элемента payload: существующий по id (он обязан принадлежать устройству) или новый."""
    if not isinstance(item, dict):
        raise HTTPException(422, "Каждый интерфейс должен быть объектом")
    iid = item.get("id")
    if not iid:
        obj = DeviceInterface(physical_device_id=device_id)
        session.add(obj)
        return obj
    obj = existing_map.get(iid)
    if not obj:
        raise HTTPException(422, "Интерфейс не принадлежит выбранному физическому устройству")
    incoming_ids.add(iid)
    return obj


def sync_interfaces(device_id: str, payload: dict[str, Any], session: Session):
    device = session.get(PhysicalDevice, device_id)
    if not device:
        raise HTTPException(404, "Физическое устройство не найдено")
    items, groups_payload, manage_groups = _read_sync_payload(payload)
    existing = session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id == device_id)).all()
    existing_map = {x.id: x for x in existing}
    incoming_ids: set[str] = set()
    allowed_vlans = _allowed_vlans_for_device(device, session)
    # Подключения портов (необязательный ключ connection в элементе interfaces, см.
    # services/interface_connections.py): применяются после записи всех портов — у новых уже есть id.
    connection_requests: list[tuple[DeviceInterface, Any]] = []
    row_objects: list[DeviceInterface] = []  # порты всех элементов payload по порядку — на них ссылается connection.peer_row
    subinterface_total = 0  # подинтерфейсов в payload — для записи в журнал аудита
    try:
        group_states = _sync_interface_groups(device_id, groups_payload, allowed_vlans, session) if manage_groups else {}
        for position, item in enumerate(items):
            obj = _resolve_port_object(item, device_id, existing_map, incoming_ids, session)
            # Порядок портов — порядок элементов payload (стрелки в форме). Присваивается ДО первого flush() в
            # _sync_single_interface: так новый порт вставляется сразу с нужной позицией, а не получает её отдельным UPDATE.
            obj.sort_order = position
            group_state = _resolve_interface_group(item, group_states) if manage_groups else None
            if manage_groups:
                obj.group_id = group_state.obj.id if group_state else None
            _sync_single_interface(obj, item, device, session, allowed_vlans)
            # Подинтерфейсы порта: ключ subinterfaces — полный список подинтерфейсов этого порта (как ips и
            # open_ports); без ключа (старый клиент, окно без их редактирования) подинтерфейсы не трогаются.
            if "subinterfaces" in item:
                subinterface_total += sync_subinterfaces(obj, item["subinterfaces"], allowed_vlans, session)
            # Параметры группы применяются ПОСЛЕ значений из payload и перекрывают их: группа —
            # источник истины для заданных ею параметров, что бы ни прислал клиент.
            if group_state:
                _apply_group_to_interface(obj, group_state, session)
            row_objects.append(obj)
            if "connection" in item:
                connection_requests.append((obj, item["connection"]))
        _remove_stale_interfaces(existing, incoming_ids, session)
        session.flush()
        validate_device_subinterfaces(device_id, session)
        if manage_groups:
            _delete_stale_groups(device_id, {state.obj.id for state in group_states.values()}, session)
        connections_changed = sync_interface_connections(connection_requests, session, row_objects) if connection_requests else 0
        all_ifaces = session.scalars(select(DeviceInterface).where(DeviceInterface.physical_device_id == device_id)).all()
        for iface in all_ifaces:
            session.execute(update(IPAddress).where(IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id == iface.id).values(is_management=bool(iface.is_management)))
        audit(
            session,
            "interfaces",
            device_id,
            AuditAction.SYNC,
            f"Синхронизация интерфейсов: {len(items)}" + (f", групп: {len(groups_payload)}" if manage_groups else "") + (f", подинтерфейсов: {subinterface_total}" if subinterface_total else "") + (f", подключений изменено: {connections_changed}" if connections_changed else ""),
        )
        session.commit()
        return _synced_interfaces_response(device_id, session)
    except HTTPException:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        raise integrity_error_response("device-interfaces", exc) from exc


def get_device_interface_vlans(device_id: str, session: Session) -> dict[str, Any]:
    """VLAN портов устройства для формы: `{items: [{interface_id, all_vlans, vlan_ids}]}` — по одной записи на порт, VLAN по
    номеру. У порта с «Все VLAN» vlan_ids — все VLAN устройства (набор хранится не связями, а вычисляется, см.
    services/port_vlans.py), у остальных — выбранные. Запрос ограничен устройством: форма больше не читает связи
    всех портов реестра общим списком с потолком записей, за которым VLAN порта «пропадали»."""
    if not session.get(PhysicalDevice, device_id):
        raise HTTPException(404, "Физическое устройство не найдено")
    ports = session.execute(select(DeviceInterface.id, DeviceInterface.all_vlans, DeviceInterface.vlan_mode).where(DeviceInterface.physical_device_id == device_id).order_by(DeviceInterface.name, DeviceInterface.id)).all()
    by_port = effective_vlan_ids(session, [port_id for port_id, _, _ in ports])
    wanted = set().union(*by_port.values()) if by_port else set()
    number_of = {vlan_id: number for vlan_id, number in session.execute(select(VLAN.id, VLAN.vlan_id).where(VLAN.id.in_(wanted))).all()} if wanted else {}
    return {"items": [{"interface_id": port_id, "all_vlans": bool(all_vlans) and mode == "trunk", "vlan_ids": sorted(by_port.get(port_id, ()), key=lambda v: (number_of.get(v, 0), v))} for port_id, all_vlans, mode in ports]}


def _interface_owned_rows(model: type[IPAddress] | type[OpenPort], device_id: str, session: Session) -> list[Any]:
    """Строки `model` (IPAddress / OpenPort), принадлежащие ПОРТАМ одного устройства (owner_type = device_interface).
    Порядок тот же, что у generic-списка (создание, затем id), — форма не должна менять порядок строк."""
    if not session.get(PhysicalDevice, device_id):
        raise HTTPException(404, "Физическое устройство не найдено")
    return list(session.scalars(select(model).join(DeviceInterface, DeviceInterface.id == model.owner_id).where(model.owner_type == OwnerType.DEVICE_INTERFACE, DeviceInterface.physical_device_id == device_id).order_by(model.created_at, model.id)).all())


def get_device_interface_ips(device_id: str, session: Session) -> dict[str, Any]:
    """IP-адреса портов устройства для формы: `{items: [...]}` в том же виде, что generic-список `ip-addresses`.
    Запрос ограничен устройством: форма больше не читает IP всех портов реестра общим списком с потолком записей —
    при его превышении IP свежих портов отрезались, форма открывалась без них, а сохранение их удаляло."""
    return {"items": [serialize(ip) for ip in _interface_owned_rows(IPAddress, device_id, session)]}


def get_device_interface_open_ports(device_id: str, session: Session) -> dict[str, Any]:
    """Открытые порты портов устройства для формы: `{items: [...]}` в том же виде, что generic-список `open-ports`
    (с port/protocol из справочника). Ограничены устройством по той же причине, что и IP (get_device_interface_ips)."""
    return {"items": enrich_open_ports(_interface_owned_rows(OpenPort, device_id, session), session)}
