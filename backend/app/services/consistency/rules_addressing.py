"""Правила адресации: некорректные IP-адреса, один адрес у разных узлов, одно системное имя у разных устройств."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...constants import OwnerType
from ...models import IPAddress, PhysicalDevice
from ._owners import resolve_ip_owners
from ._support import device_labels, join_names, stack_by_device
from .engine import RuleSpec, rule
from .model import Category, Finding, Severity

# Адреса «ручных» источников ИС (адрес внешней системы) в проверку повторов не входят: несколько ИС законно ссылаются на один адрес.
_DUPLICATE_CHECK_OWNERS = (
    OwnerType.PHYSICAL_DEVICE,
    OwnerType.VIRTUAL_MACHINE,
    OwnerType.DEVICE_INTERFACE,
    OwnerType.DEVICE_SUBINTERFACE,
)


def parse_ip(raw: str | None) -> str | None:
    """Нормализованная запись адреса или None, если строка адресом не является.

    Маска («/24») — отдельное поле, в самом адресе её быть не должно.
    """
    try:
        return str(ipaddress.ip_address((raw or "").strip()))
    except ValueError:
        return None


@rule("invalid_ip", "Некорректная запись IP-адреса", Severity.ERROR, Category.CONSISTENCY)
def check_invalid_ip(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    rows = [
        row
        for row in session.execute(select(IPAddress.id, IPAddress.owner_type, IPAddress.owner_id, IPAddress.ip_address))
        if parse_ip(row.ip_address) is None
    ]
    holders = resolve_ip_owners(session, {(row.owner_type, row.owner_id) for row in rows})
    for row in rows:
        holder = holders[(row.owner_type, row.owner_id)]
        place = f", {holder.place}" if holder.place else ""
        yield spec.finding(
            holder.entity_type,
            holder.entity_id,
            holder.name,
            f"«{row.ip_address}» не похоже на IP-адрес ({holder.name}{place}). Маска вводится в отдельное поле, без «/».",
            ip_address=row.ip_address,
            ip_record_id=row.id,
        )


@rule("duplicate_ip", "Один IP-адрес у разных объектов", Severity.WARNING, Category.CONSISTENCY)
def check_duplicate_ip(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Адрес, назначенный двум и более разным узлам. Порты одного устройства и участники одного стека — один узел.

    Предупреждение, а не ошибка: общий виртуальный адрес (VRRP/HSRP) и одинаковые адреса в разных изолированных сетях бывают
    намеренными, и отличить их по данным реестра нельзя.
    """
    owners_by_ip: dict[str, set[tuple[str, str]]] = {}
    for row in session.execute(
        select(IPAddress.owner_type, IPAddress.owner_id, IPAddress.ip_address).where(IPAddress.owner_type.in_(_DUPLICATE_CHECK_OWNERS))
    ):
        address = parse_ip(row.ip_address)
        if address is not None:
            owners_by_ip.setdefault(address, set()).add((row.owner_type, row.owner_id))
    repeated = {address: owners for address, owners in owners_by_ip.items() if len(owners) > 1}
    if not repeated:
        return
    holders = resolve_ip_owners(session, {owner for owners in repeated.values() for owner in owners})
    for address in sorted(repeated):
        nodes = {holders[owner].key: holders[owner] for owner in sorted(repeated[address])}
        if len(nodes) < 2:
            continue
        found = sorted(nodes.values(), key=lambda holder: (holder.name.casefold(), holder.place or ""))
        yield spec.finding(
            "ip_address",
            address,
            address,
            f"IP-адрес {address} назначен разным объектам: {join_names(holder.name for holder in found)}.",
            holders=[holder.to_dict() for holder in found],
        )


@rule("duplicate_system_name", "Одно системное имя у разных устройств", Severity.WARNING, Category.CONSISTENCY, sheet=2)
def check_duplicate_system_name(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Системное имя (без учёта регистра и пробелов по краям) у устройств, не входящих в один стек: по имени устройство
    находят в сети и в отчёте, повтор делает такие устройства неразличимыми."""
    ids_by_name: dict[str, list[str]] = {}
    shown: dict[str, str] = {}
    for row in session.execute(select(PhysicalDevice.id, PhysicalDevice.system_name).where(PhysicalDevice.system_name.is_not(None))):
        name = row.system_name.strip()
        if name:
            ids_by_name.setdefault(name.casefold(), []).append(row.id)
            shown.setdefault(name.casefold(), name)
    repeated = {name: ids for name, ids in ids_by_name.items() if len(ids) > 1}
    if not repeated:
        return
    stacks = stack_by_device(session)
    labels = device_labels(session, {device_id for ids in repeated.values() for device_id in ids})
    for name in sorted(repeated):
        ids = sorted(repeated[name])
        if len({stacks.get(device_id, device_id) for device_id in ids}) < 2:
            continue
        yield spec.finding(
            "physical_device",
            ids[0],
            shown[name],
            f"Системное имя «{shown[name]}» носят {len(ids)} устройства, не входящие в один стек.",
            devices=[{"entity_id": device_id, "name": labels.get(device_id, device_id)} for device_id in ids],
        )
