"""Согласование данных портов по правилам (services/port_sync_rules.py): предпросмотр плана и его
применение. Правила берутся из БД (services/port_sync_store.py).

Что обрабатывается. Активные подключения с расхождением конфигурации портов (роль, режим, VLAN — как
на дашборде «Подключения»), которое пользователь не одобрил. Для каждого подключения первое подходящее
правило даёт решение:

    auto     — направление определено: целевому порту будут применены изменения (применяются только
               после предпросмотра и подтверждения; один план — одна транзакция). У симметричного
               правила (политика VLAN «объединить», trunk с разными наборами VLAN) целевых портов
               два — изменения получает каждый, кому есть что менять; порт, которому нельзя, остаётся
               в плане с причиной, а второй всё равно применяется;
    blocked  — правило подошло, но применить нельзя: порт входит в группу, задающую режим и VLAN;
               результат нарушил бы «в access не более одного VLAN»; ни один VLAN соседа недоступен
               устройству; порт уже изменяется другим подключением этого же плана;
    manual   — расхождение известного вида, направление выбирает человек (как и раньше);
    ignored  — правило исключило пару из согласования;
    none     — ни одно правило не подошло;
    skipped  — подключение вне согласования (расхождения нет, неактивно, одобрено, нет порта) — только
               при явном списке подключений, чтобы объяснить, почему с ним ничего не происходит.

Неполный результат (`partial`). Решение auto может не устранить расхождение до конца: часть VLAN
пропущена (их нет у устройства порта) либо один из двух портов симметричного правила не меняется
(группа, чужое подключение). Такие подключения помечаются `partial` и считаются в `summary.partial` —
после применения они останутся в «Расхождениях», и человеку стоит знать об этом до подтверждения.

VLAN переносятся по НОМЕРУ (802.1Q-тегу), как и при сверке: у целевого порта выбирается запись
справочника с тем же номером из VLAN, доступных его устройству (VLAN типа устройства и собственные
VLAN устройства — те же, что проверяет PUT /devices/{id}/interfaces). Номера, которых у целевого
устройства нет, пропускаются с предупреждением — VLAN устройству добавляет человек.

Безопасность применения: без `confirm: true` — 422; план пересчитывается заново и сверяется по
`plan_hash` с тем, что видел пользователь, — иначе 409 (данные изменились после предпросмотра).

Постраничный предпросмотр. Элементов плана может быть тысячи, поэтому предпросмотр отдаёт их страницами
(`offset`, `limit` — не более MAX_PREVIEW_ITEMS), а сводка и `plan_hash` относятся ко всему плану. Первая
страница считает план и кладёт его в кэш (services/port_sync_plan_cache.py); следующие страницы запрашиваются
с `plan_hash` первой и берутся срезом из кэша без запросов к БД. Промах кэша (истёк срок, вытеснен, другой
воркер) — пересчёт; если план при этом изменился (другой `plan_hash`) — 409, как и у применения. Применение
кэш не использует: оно всегда считает план заново.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..models import (
    Connection,
    DeviceInterface,
    DeviceTypeVLAN,
    InterfaceGroup,
    InterfaceVLAN,
    PhysicalDevice,
    PhysicalDeviceVLAN,
    VLAN,
)
from .connection_query import ConnectionQuery, select_connection_ids
from .crud import audit
from .port_config import (
    DEFAULT_VLAN_MODE,
    PORT_ROLE_LABELS,
    PortConfig,
    PortConfigStatus,
    PortRole,
    evaluate_port_config,
    port_role,
)
from .port_sync_plan_cache import CachedPlan, plan_cache, scope_key
from .port_sync_rules import (
    APPLY_TO_SOURCE,
    Changes,
    Decision,
    Option,
    Outcome,
    PortFacts,
    RuleSpec,
    decide,
)
from .port_sync_store import rules_for_reconcile
from .port_writes import load_vlan_links, write_port_roles, write_port_vlans

MAX_CONNECTION_IDS = 500
MAX_PREVIEW_ITEMS = 300  # размер страницы предпросмотра по умолчанию и его верхняя граница
_CHUNK = 400  # число id в одном IN-запросе (у SQLite/psycopg число параметров ограничено)

_OUTCOME_ORDER = {"auto": 0, "blocked": 1, "manual": 2, "ignored": 3, "none": 4, "skipped": 5}


# --- загрузка портов -----------------------------------------------------------------------------


@dataclass
class _Port:
    iface: DeviceInterface
    device: PhysicalDevice | None
    group: InterfaceGroup | None
    vlan_ids: set[str]
    allowed_ids: set[str]
    facts: PortFacts


def _chunks(values: Sequence[str], size: int = _CHUNK):
    for start in range(0, len(values), size):
        yield values[start:start + size]


def _load_ports(session: Session, interface_ids: Sequence[str]) -> tuple[dict[str, _Port], dict[str, VLAN]]:
    """Порты вместе со всем, что нужно для условий правил и для записи: устройство, группа, назначенные
    VLAN и VLAN, доступные устройству. Несколько запросов на весь набор портов, а не по запросу на порт."""
    ids = list(dict.fromkeys(interface_ids))
    interfaces: list[DeviceInterface] = []
    links: list[tuple[str, str]] = []
    for chunk in _chunks(ids):
        interfaces += session.scalars(select(DeviceInterface).where(DeviceInterface.id.in_(chunk))).all()
        links += [tuple(r) for r in session.execute(select(InterfaceVLAN.interface_id, InterfaceVLAN.vlan_id).where(InterfaceVLAN.interface_id.in_(chunk))).all()]
    device_ids = list({i.physical_device_id for i in interfaces})
    devices: dict[str, PhysicalDevice] = {}
    device_vlans: dict[str, set[str]] = {}
    type_vlans: dict[str, set[str]] = {}
    for chunk in _chunks(device_ids):
        for device in session.scalars(select(PhysicalDevice).where(PhysicalDevice.id.in_(chunk))).all():
            devices[device.id] = device
        for device_id, vlan_id in session.execute(select(PhysicalDeviceVLAN.physical_device_id, PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id.in_(chunk))).all():
            device_vlans.setdefault(device_id, set()).add(vlan_id)
    type_ids = list({d.device_type_id for d in devices.values()})
    for chunk in _chunks(type_ids):
        for type_id, vlan_id in session.execute(select(DeviceTypeVLAN.device_type_id, DeviceTypeVLAN.vlan_id).where(DeviceTypeVLAN.device_type_id.in_(chunk))).all():
            type_vlans.setdefault(type_id, set()).add(vlan_id)
    group_ids = list({i.group_id for i in interfaces if i.group_id})
    groups: dict[str, InterfaceGroup] = {}
    for chunk in _chunks(group_ids):
        for group in session.scalars(select(InterfaceGroup).where(InterfaceGroup.id.in_(chunk))).all():
            groups[group.id] = group
    by_iface: dict[str, set[str]] = {}
    for interface_id, vlan_id in links:
        by_iface.setdefault(interface_id, set()).add(vlan_id)
    vlan_ids_needed = set().union(*by_iface.values(), *device_vlans.values(), *type_vlans.values()) if (by_iface or device_vlans or type_vlans) else set()
    vlans: dict[str, VLAN] = {}
    for chunk in _chunks(list(vlan_ids_needed)):
        for vlan in session.scalars(select(VLAN).where(VLAN.id.in_(chunk))).all():
            vlans[vlan.id] = vlan

    ports: dict[str, _Port] = {}
    for iface in interfaces:
        device = devices.get(iface.physical_device_id)
        assigned = by_iface.get(iface.id, set())
        allowed = (device_vlans.get(device.id, set()) | type_vlans.get(device.device_type_id, set())) if device else set()
        numbers = frozenset(vlans[v].vlan_id for v in assigned if v in vlans)
        facts = PortFacts(
            role=port_role(iface),
            mode=iface.vlan_mode or DEFAULT_VLAN_MODE,
            vlans=numbers,
            # «Все VLAN» — назначены все VLAN, доступные устройству (как в форме устройства).
            all_vlans=bool(allowed) and allowed <= assigned,
        )
        ports[iface.id] = _Port(iface, device, groups.get(iface.group_id) if iface.group_id else None, assigned, allowed, facts)
    return ports, vlans


# --- сопоставление VLAN целевого порта -----------------------------------------------------------


def _resolve_vlans(wanted: frozenset[int], target: _Port, source: _Port, vlans: dict[str, VLAN]) -> tuple[list[str], list[int]]:
    """Записи VLAN целевого порта с нужными номерами и номера, которые ему назначить нельзя (нет у
    его устройства). Из нескольких записей с одним номером берётся уже назначенная порту, затем та же
    запись, что у источника, затем с наименьшим id — результат не зависит от порядка выборки."""
    pool = target.allowed_ids | target.vlan_ids
    by_number: dict[int, list[str]] = {}
    for vlan_id in pool:
        if vlan_id in vlans:
            by_number.setdefault(vlans[vlan_id].vlan_id, []).append(vlan_id)
    resolved: list[str] = []
    skipped: list[int] = []
    for number in sorted(wanted):
        candidates = by_number.get(number, [])
        if not candidates:
            skipped.append(number)
            continue
        candidates.sort(key=lambda v: (v not in target.vlan_ids, v not in source.vlan_ids, v))
        resolved.append(candidates[0])
    return resolved, skipped


# --- план ----------------------------------------------------------------------------------------


@dataclass
class _Planned:
    """Что записать для одного подключения с решением auto (и применимого)."""

    connection: Connection
    port: _Port
    rule: RuleSpec
    role: PortRole | None
    mode: str | None
    vlan_ids: list[str] | None  # итоговые записи VLAN; None — набор не меняется
    description: str


@dataclass
class _Plan:
    items: list[dict[str, Any]] = field(default_factory=list)
    planned: list[_Planned] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    hash: str = ""


def _vlan_numbers(ids: set[str] | list[str], vlans: dict[str, VLAN]) -> list[int]:
    return sorted({vlans[v].vlan_id for v in ids if v in vlans})


def _port_view(port: _Port | None, interface_id: str) -> dict[str, Any]:
    if port is None:
        return {"interface_id": interface_id, "name": "", "device_id": None, "device_name": "", "role": None, "mode": None, "vlans": []}
    device = port.device
    return {
        "interface_id": port.iface.id,
        "name": port.iface.name,
        "device_id": port.iface.physical_device_id,
        "device_name": (device.system_name or device.serial_number) if device else "",
        "role": port.facts.role.value,
        "mode": port.facts.mode,
        "vlans": sorted(port.facts.vlans),
    }


def _raw_changes(changes: Changes) -> dict[str, Any]:
    """Изменения как есть, на уровне номеров VLAN (для вариантов ручного решения)."""
    return {
        "role": changes.role.value if changes.role else None,
        "mode": changes.mode,
        "vlans": sorted(changes.vlans) if changes.vlans is not None else None,
    }


def _describe(role: tuple[str, str] | None, mode: tuple[str, str] | None, vlans: tuple[list[int], list[int]] | None) -> str:
    parts = []
    if role:
        parts.append(f"роль {PORT_ROLE_LABELS[PortRole(role[0])]} → {PORT_ROLE_LABELS[PortRole(role[1])]}")
    if mode:
        parts.append(f"режим {mode[0]} → {mode[1]}")
    if vlans:
        before = ", ".join(map(str, vlans[0])) or "нет"
        after = ", ".join(map(str, vlans[1])) or "нет"
        parts.append(f"VLAN {before} → {after}")
    return "; ".join(parts)


@dataclass
class _TargetPlan:
    """Разбор одного варианта решения auto: что записать порту либо почему этого сделать нельзя."""

    apply_to: str  # APPLY_TO_SOURCE | APPLY_TO_DESTINATION
    port: _Port
    changes: dict[str, Any]
    warnings: list[str]
    blocked: str | None
    planned: _Planned | None


def _plan_target(option: Option, rule: RuleSpec, connection: Connection, ports: dict[str, _Port], vlans: dict[str, VLAN], claimed: set[str]) -> _TargetPlan:
    """Сопоставляет VLAN целевого порта и проверяет запреты. `claimed` только читает — порты, занятые
    этим планом, помечает вызывающий, когда решит, что подключение применяется."""
    target_id = connection.source_interface_id if option.apply_to == APPLY_TO_SOURCE else connection.destination_interface_id
    source_id = connection.destination_interface_id if option.apply_to == APPLY_TO_SOURCE else connection.source_interface_id
    target, source = ports[target_id], ports[source_id]
    changes = option.changes
    warnings: list[str] = []

    resolved_ids: list[str] | None = None
    skipped: list[int] = []
    final_numbers = target.facts.vlans
    if changes.vlans is not None:
        resolved_ids, skipped = _resolve_vlans(changes.vlans, target, source, vlans)
        final_numbers = frozenset(vlans[v].vlan_id for v in resolved_ids)
        if final_numbers == target.facts.vlans:
            resolved_ids = None  # из доступных устройству VLAN менять нечего
    new_mode = changes.mode or target.facts.mode

    blocked: str | None = None
    if changes.violation:
        blocked = changes.violation
    elif (changes.mode is not None or changes.vlans is not None) and target.group is not None and target.group.vlan_mode:
        blocked = f"Порт входит в группу «{target.group.name}», которая задаёт режим и VLAN, — измените группу"
    elif changes.vlans is not None and resolved_ids is None and changes.role is None and changes.mode is None:
        blocked = "Ни один из VLAN соседнего порта не доступен устройству этого порта — добавьте их в «VLAN устройства»" if skipped else "Изменений нет"
    elif new_mode == "access" and len(final_numbers) > 1:
        blocked = "В режиме access у порта может быть не более одного VLAN"
    elif target_id in claimed:
        blocked = "Порт уже изменяется другим подключением этого же плана"

    role_pair = (target.facts.role.value, changes.role.value) if changes.role else None
    mode_pair = (target.facts.mode, changes.mode) if changes.mode else None
    vlan_pair = (sorted(target.facts.vlans), sorted(final_numbers)) if resolved_ids is not None else None
    view = {
        "role": {"from": role_pair[0], "to": role_pair[1]} if role_pair else None,
        "mode": {"from": mode_pair[0], "to": mode_pair[1]} if mode_pair else None,
        "vlans": {"from": vlan_pair[0], "to": vlan_pair[1], "skipped": skipped} if vlan_pair else ({"from": sorted(target.facts.vlans), "to": sorted(target.facts.vlans), "skipped": skipped} if skipped else None),
    }
    if skipped and not blocked:
        warnings.append("Не назначены VLAN, которых нет у устройства порта: " + ", ".join(map(str, skipped)))
    planned = None if blocked else _Planned(connection, target, rule, changes.role, changes.mode, resolved_ids, _describe(role_pair, mode_pair, vlan_pair))
    return _TargetPlan(option.apply_to, target, view, warnings, blocked, planned)


def _port_label(port: _Port) -> str:
    device = port.device.system_name or port.device.serial_number if port.device else ""
    return f"«{port.iface.name}» ({device})" if device else f"«{port.iface.name}»"


def _skipped_vlans(part: _TargetPlan) -> list[int]:
    vlans = part.changes.get("vlans")
    return vlans["skipped"] if vlans else []


def _apply_decision(
    decision: Decision, connection: Connection, ports: dict[str, _Port], vlans: dict[str, VLAN], claimed: set[str]
) -> tuple[dict[str, Any], list[_Planned]]:
    """Превращает решение auto в запись плана и список изменений портов (пустой — применять нечего).

    Обычно целевой порт один. У симметричного правила (политика VLAN «объединить») портов два, и они
    независимы: порт, которому изменение запрещено (группа, нет VLAN у устройства, занят другим
    подключением), в плане остаётся с причиной, а второй порт всё равно получает своё — объединение
    VLAN ничего не снимает, поэтому частичное применение расхождение не ухудшает. Подключение
    блокируется, только если не изменяется ни один порт."""
    parts = [_plan_target(option, decision.rule, connection, ports, vlans, claimed) for option in decision.options]
    several = len(parts) > 1
    ready = [part for part in parts if part.planned]
    item: dict[str, Any] = {
        "outcome": "auto" if ready else "blocked",
        # Применимо, но расхождение останется: порт из пары не меняется или часть VLAN ему назначить нельзя.
        "partial": bool(ready) and (len(ready) < len(parts) or any(_skipped_vlans(part) for part in ready)),
        "target": "both" if several else parts[0].apply_to,
        "changes": None if several else parts[0].changes,
        "targets": [{"target": p.apply_to, "changes": p.changes, "blocked": p.blocked} for p in parts],
        "warnings": [f"Порт {_port_label(p.port)}: {w}" if several else w for p in parts for w in p.warnings],
    }
    if not ready:
        item["reason"] = "; ".join(f"Порт {_port_label(p.port)}: {p.blocked}" if several else str(p.blocked) for p in parts)
        return item, []
    for part in ready:
        claimed.add(part.port.iface.id)
    return item, [part.planned for part in ready if part.planned]


def _selected_connections(session: Session, connection_ids: Any) -> tuple[list[Connection], bool]:
    """(подключения, явный ли список). Без списка — все активные подключения с неодобренным расхождением."""
    if connection_ids is None:
        ids = select_connection_ids(session, ConnectionQuery(is_active=True, status=PortConfigStatus.MISMATCH))
        explicit = False
    else:
        if not isinstance(connection_ids, list) or not connection_ids or not all(isinstance(i, str) and i for i in connection_ids):
            raise HTTPException(422, "Поле connection_ids должно быть непустым массивом идентификаторов подключений")
        if len(connection_ids) > MAX_CONNECTION_IDS:
            raise HTTPException(422, f"За один запрос можно обработать не более {MAX_CONNECTION_IDS} подключений")
        ids = list(dict.fromkeys(connection_ids))
        explicit = True
    found: dict[str, Connection] = {}
    for chunk in _chunks(ids):
        for connection in session.scalars(select(Connection).where(Connection.id.in_(chunk))).all():
            found[connection.id] = connection
    missing = [i for i in ids if i not in found]
    if missing and explicit:
        raise HTTPException(404, f"Подключение не найдено: {missing[0]}")
    return [found[i] for i in ids if i in found], explicit


def _skip_reason(status: PortConfigStatus, connection: Connection) -> str:
    if connection.is_active is False:
        return "Подключение неактивно — оно не участвует в сверке"
    if status is PortConfigStatus.APPROVED:
        return "Расхождение одобрено — согласование его не меняет"
    return "Расхождения нет"


def _parse_scope(payload: Any) -> tuple[Any, str | None]:
    if not isinstance(payload, dict):
        raise HTTPException(422, "Тело запроса должно быть объектом")
    rule_id = payload.get("rule_id")
    if rule_id is not None and (not isinstance(rule_id, str) or not rule_id):
        raise HTTPException(422, "Поле rule_id должно быть идентификатором правила")
    return payload.get("connection_ids"), rule_id


def _int_field(payload: dict[str, Any], key: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or (maximum is not None and value > maximum):
        bound = f" от {minimum} до {maximum}" if maximum is not None else f" не меньше {minimum}"
        raise HTTPException(422, f"Поле {key} должно быть целым числом{bound}")
    return value


def _parse_page(payload: dict[str, Any]) -> tuple[int, int, str | None]:
    """(offset, limit, plan_hash). plan_hash — хеш плана, страницы которого запрашиваются (из ответа
    предпросмотра): по нему страница берётся из кэша. Без него план считается заново."""
    offset = _int_field(payload, "offset", 0, minimum=0)
    limit = _int_field(payload, "limit", MAX_PREVIEW_ITEMS, minimum=1, maximum=MAX_PREVIEW_ITEMS)
    plan_hash = payload.get("plan_hash")
    if plan_hash is not None and (not isinstance(plan_hash, str) or not plan_hash):
        raise HTTPException(422, "Поле plan_hash должно быть хешем плана из предпросмотра")
    return offset, limit, plan_hash


def _plan_hash(planned: list[_Planned]) -> str:
    effects = [
        [p.connection.id, p.port.iface.id, p.role.value if p.role else None, p.mode, sorted(p.vlan_ids) if p.vlan_ids is not None else None, p.rule.id or p.rule.code]
        for p in planned
    ]
    return hashlib.sha256(json.dumps(effects, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _compute(session: Session, connection_ids: Any, rule_id: str | None) -> _Plan:
    rules = rules_for_reconcile(session, rule_id)
    connections, explicit = _selected_connections(session, connection_ids)
    interface_ids = [i for c in connections for i in (c.source_interface_id, c.destination_interface_id)]
    ports, vlans = _load_ports(session, interface_ids)
    plan = _Plan()
    claimed: set[str] = set()
    counts = {key: 0 for key in _OUTCOME_ORDER}
    for connection in connections:
        src, dst = ports.get(connection.source_interface_id), ports.get(connection.destination_interface_id)
        item: dict[str, Any] = {
            "connection_id": connection.id,
            "source": _port_view(src, connection.source_interface_id),
            "destination": _port_view(dst, connection.destination_interface_id),
            "rule": None,
            "target": None,
            "changes": None,
            "options": [],
            "warnings": [],
            "reason": None,
            "partial": False,
        }
        if src is None or dst is None:
            item.update(outcome="skipped", reason="У подключения отсутствует один из портов")
        else:
            status = evaluate_port_config(
                PortConfig(src.facts.role, src.facts.mode, src.facts.vlans),
                PortConfig(dst.facts.role, dst.facts.mode, dst.facts.vlans),
                connection.port_config_approved_signature,
                is_active=connection.is_active is not False,
            )
            if status is not PortConfigStatus.MISMATCH:
                item.update(outcome="skipped", reason=_skip_reason(status, connection))
            else:
                decision = decide(rules, src.facts, dst.facts)
                if decision.rule is not None:
                    item["rule"] = {"id": decision.rule.id, "code": decision.rule.code, "name": decision.rule.name, "action": decision.rule.action}
                if decision.outcome is Outcome.AUTO:
                    result, planned = _apply_decision(decision, connection, ports, vlans, claimed)
                    item.update(result)
                    plan.planned.extend(planned)
                else:
                    item["outcome"] = decision.outcome.value
                    item["reason"] = decision.note
                    item["options"] = [{"target": o.apply_to, "changes": _raw_changes(o.changes)} for o in decision.options]
        counts[item["outcome"]] += 1
        plan.items.append(item)

    shown = [i for i in plan.items if explicit or rule_id is None or i["outcome"] not in ("none", "skipped")]
    shown.sort(key=lambda i: _OUTCOME_ORDER[i["outcome"]])
    plan.summary = {
        "connections": len(connections),
        "applicable": len(plan.planned),
        "shown": min(len(shown), MAX_PREVIEW_ITEMS),
        "total_items": len(shown),
        **counts,
        # Считается по всем подключениям плана, а не только по показанным (items обрезаются).
        "partial": sum(1 for i in plan.items if i["partial"]),
    }
    plan.items = shown  # все элементы к показу; на страницы их режет preview_reconcile
    plan.hash = _plan_hash(plan.planned)
    return plan


def preview_reconcile(payload: Any, session: Session) -> dict[str, Any]:
    """План согласования — ничего не записывает. Отдаёт одну страницу его элементов.

    payload: {connection_ids?, rule_id?, offset?, limit?, plan_hash?}. Без connection_ids — все активные
    подключения с неодобренным расхождением; с rule_id проверяется только это правило (даже отключённое —
    чтобы посмотреть, что оно сделает, до включения). offset/limit — страница (по умолчанию первые
    MAX_PREVIEW_ITEMS элементов). plan_hash — хеш плана из ответа на первую страницу: страница берётся из
    кэша без пересчёта, а если кэша нет и план изменился — 409.

    Ответ: {items, summary, plan_hash, page: {offset, limit, total, has_more}}. summary и plan_hash — по
    всему плану; summary.shown — число элементов в ЭТОМ ответе."""
    connection_ids, rule_id = _parse_scope(payload)
    offset, limit, expected_hash = _parse_page(payload)
    scope = scope_key(connection_ids, rule_id)

    cached = plan_cache.get(scope, expected_hash) if expected_hash is not None else None
    if cached is not None:
        plan_hash = expected_hash
    else:
        plan = _compute(session, connection_ids, rule_id)
        if expected_hash is not None and plan.hash != expected_hash:
            raise HTTPException(409, "План изменился после того, как был показан, — обновите предпросмотр")
        cached = CachedPlan(items=tuple(plan.items), summary=plan.summary)
        plan_hash = plan.hash
        plan_cache.put(scope, plan_hash, cached)

    page = list(cached.items[offset:offset + limit])
    return {
        "items": page,
        "summary": {**cached.summary, "shown": len(page)},
        "plan_hash": plan_hash,
        "page": {"offset": offset, "limit": limit, "total": len(cached.items), "has_more": offset + len(page) < len(cached.items)},
    }


# --- применение ----------------------------------------------------------------------------------


def apply_reconcile(payload: Any, session: Session) -> dict[str, Any]:
    """Применяет план: изменения получают только порты решений auto, которые не заблокированы. Одна
    транзакция — записано всё или ничего.

    payload: {connection_ids?, rule_id?, plan_hash, confirm: true} — условия те же, что при предпросмотре.
    Без confirm=true — 422; если план при применении отличается от показанного (hash) — 409."""
    connection_ids, rule_id = _parse_scope(payload)
    if payload.get("confirm") is not True:
        raise HTTPException(422, "Применение требует подтверждения: confirm = true")
    plan = _compute(session, connection_ids, rule_id)
    if not plan.planned:
        return {"applied": {"ports": 0, "connections": 0}, "connection_ids": [], "summary": plan.summary}
    if payload.get("plan_hash") != plan.hash:
        raise HTTPException(409, "Данные изменились после предпросмотра — повторите операцию и проверьте новый план")
    # Запись пакетная: связи порт–VLAN и IP-адреса читаются/обновляются порциями, а не запросом на порт, —
    # иначе применение плана на тысячи портов занимало минуты (см. services/port_writes.py).
    write_port_roles([(p.port.iface, p.role) for p in plan.planned if p.role is not None], session)
    vlan_writes = [p for p in plan.planned if p.mode is not None or p.vlan_ids is not None]
    links = load_vlan_links([p.port.iface.id for p in vlan_writes], session)
    for planned in vlan_writes:
        port = planned.port.iface
        keep = planned.vlan_ids if planned.vlan_ids is not None else list(planned.port.vlan_ids)
        write_port_vlans(port, planned.mode or planned.port.facts.mode, keep, session, links=links[port.id])
    for planned in plan.planned:
        port = planned.port.iface
        audit(session, "interfaces", port.id, AuditAction.UPDATE, f"Согласование порта «{port.name}» по правилу «{planned.rule.name}»: {planned.description}")
    session.commit()
    plan_cache.clear()  # данные изменились — снимки планов в кэше больше не соответствуют действительности
    connection_ids_applied = list(dict.fromkeys(p.connection.id for p in plan.planned))
    return {
        "applied": {"ports": len(plan.planned), "connections": len(connection_ids_applied)},
        "connection_ids": connection_ids_applied,
        "summary": plan.summary,
    }
