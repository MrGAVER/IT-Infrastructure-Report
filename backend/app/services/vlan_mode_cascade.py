"""Каскадная смена режима порта (access / trunk) вместе с группами и связанными портами.

Зачем. Режим порта у двух сторон подключения должен совпадать, иначе в форме устройства и на
дашборде появляется расхождение. Если порт соседа состоит в группе, задающей режим
(InterfaceGroup.vlan_mode), поменять его у одного порта нельзя: группа — источник истины, и
следующее сохранение устройства вернёт её значение. Поэтому режим меняется целиком, а область
изменения считается так, чтобы после операции расхождений на её границе не осталось.

Область изменения — замыкание от порта-инициатора по двум правилам:
  1. порт в группе, которая задаёт режим и ещё не равна целевому, меняется вместе со ВСЕЙ группой
     (все её порты и список VLAN группы);
  2. у каждого меняемого порта соседи по АКТИВНЫМ подключениям тоже должны получить целевой режим —
     если он у них другой, они (и их группы) входят в область, и так далее. Порты, у которых режим
     уже целевой, в область не входят и дальше не распространяют: их собственные расхождения
     (если есть) к этой операции не относятся. Неактивные подключения игнорируются — как и в форме.

Правила для VLAN (те же, что у переключателя режима в форме устройства):
  * в access у порта/группы может быть не более одного VLAN: остаётся VLAN с наименьшим номером,
    остальные снимаются (список снимаемых показывается ДО применения);
  * в trunk сохраняются только уже назначенные VLAN — «все VLAN» автоматически не добавляются,
    чтобы операция не придумывала конфигурацию на чужих устройствах.

Редактируемое устройство (edited). Форма этого устройства открыта и сохраняется целиком
(PUT /devices/{id}/interfaces) — запись в обход неё была бы перезаписана черновиком. Поэтому его
порты и группы входят в план с пометкой deferred: сервер их НЕ пишет, клиент вносит изменения в
черновик формы, и они сохраняются вместе с формой. Всё остальное применяется сразу, одной транзакцией.

Состояние формы. Для портов и групп редактируемого устройства «текущее состояние» — то, что в
ЧЕРНОВИКЕ формы (клиент присылает его в edited.ports / edited.groups), а не в БД: пользователь мог уже
переключить режим, перенести порт в другую группу или поменять VLAN группы, и именно из-за этого
возникло расхождение. Из черновика берутся режим и VLAN порта/группы, ЧЛЕНСТВО портов в группах
(в т.ч. в новой, ещё не сохранённой группе — её ключ временный), а также имена для показа в плане.
Порты и группы, у которых в черновике уже целевой режим, в область не входят и дальше не
распространяют. То, чего в edited нет (порт или группа не переданы, поле опущено), берётся из БД.

Двухшаговый протокол: preview возвращает план и его hash; apply требует confirm=true и тот же hash —
если данные изменились между предпросмотром и применением, операция отклоняется (409), а не
выполняется по не показанному пользователю плану.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..models import Connection, DeviceInterface, InterfaceGroup, InterfaceGroupVLAN, InterfaceVLAN, PhysicalDevice, VLAN
from .crud import audit
from .serialization import enrich_interfaces

VLAN_MODES = ("access", "trunk")
# Предел области изменения: каскад по большой сети не должен превратиться в неуправляемую правку.
MAX_CASCADE_PORTS = 1000
# Порог, с которого в плане появляется предупреждение «область большая».
LARGE_CASCADE_PORTS = 100
# У SQLite/psycopg число параметров в IN ограничено — как в services/connection_review.py.
_CHUNK = 400
# Сколько имён портов перечисляется в одной записи аудита и одном предупреждении.
_MAX_LISTED = 12


def _chunks(items: list[str]) -> Iterable[list[str]]:
    for start in range(0, len(items), _CHUNK):
        yield items[start:start + _CHUNK]


@dataclass(frozen=True)
class _EditedPort:
    """Порт редактируемого устройства в черновике формы. Опущенные поля (None / group_given=False)
    означают «как в БД»."""
    mode: str
    group_given: bool = False
    group: str | None = None  # ключ группы: id сохранённой или временный ключ новой; None — порт вне групп
    vlan_ids: tuple[str, ...] | None = None
    name: str | None = None


@dataclass(frozen=True)
class _EditedGroup:
    """Группа редактируемого устройства в черновике формы (в т.ч. новая, ещё без записи в БД)."""
    mode: str  # '' — группа режимом не управляет
    vlan_ids: tuple[str, ...] | None = None
    name: str | None = None


@dataclass(frozen=True)
class _Edited:
    """Редактируемое устройство и его порты/группы в черновике формы (порты — по id, группы — по ключу)."""
    device_id: str | None = None
    ports: dict[str, _EditedPort] = field(default_factory=dict)
    groups: dict[str, _EditedGroup] = field(default_factory=dict)

    def owns(self, port: DeviceInterface) -> bool:
        return bool(self.device_id) and port.physical_device_id == self.device_id

    def port_state(self, port: DeviceInterface) -> _EditedPort | None:
        return self.ports.get(port.id) if self.owns(port) else None

    def port_mode(self, port: DeviceInterface) -> str:
        state = self.port_state(port)
        return state.mode if state else port.vlan_mode

    def port_name(self, port: DeviceInterface) -> str:
        state = self.port_state(port)
        return state.name if state and state.name is not None else port.name

    def port_group_key(self, port: DeviceInterface) -> str | None:
        """Ключ группы порта: у порта формы — по черновику (если передан), иначе — по БД."""
        state = self.port_state(port)
        return state.group if state is not None and state.group_given else port.group_id


@dataclass
class _GroupInfo:
    """Группа в том виде, в каком её видит каскад: из БД, а у редактируемого устройства — из черновика."""
    key: str  # id группы; у новой группы формы — её временный ключ
    name: str
    device_id: str
    mode: str  # '' — группа режимом не управляет
    vlan_ids: list[str] | None  # None — взять из БД (подгрузится в _load_details)
    deferred: bool  # группа редактируемого устройства: сервер её не пишет
    members: list[str] = field(default_factory=list)


class _Loader:
    """Подгружает порты, группы и подключения пачками и кэширует их: обход по уровням делает по
    одному IN-запросу на уровень, а не по запросу на каждый порт."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.ports: dict[str, DeviceInterface] = {}
        self.groups: dict[str, InterfaceGroup] = {}  # группы из БД
        self.infos: dict[str, _GroupInfo | None] = {}
        self.members: dict[str, list[str]] = {}
        self.active: dict[str, list[str]] = {}
        self.inactive: dict[str, list[str]] = {}
        self._probed_groups: set[str] = set()
        self._db_members: dict[str, list[str]] = {}

    def load_ports(self, ids: Iterable[str]) -> None:
        missing = [i for i in dict.fromkeys(ids) if i not in self.ports]
        for chunk in _chunks(missing):
            for port in self.session.scalars(select(DeviceInterface).where(DeviceInterface.id.in_(chunk))).all():
                self.ports[port.id] = port

    def load_groups(self, keys: Iterable[str]) -> None:
        """Ключ — id группы из БД либо временный ключ новой группы формы (его в БД нет, это не ошибка)."""
        missing = [k for k in dict.fromkeys(keys) if k not in self._probed_groups]
        self._probed_groups.update(missing)
        for chunk in _chunks(missing):
            for group in self.session.scalars(select(InterfaceGroup).where(InterfaceGroup.id.in_(chunk))).all():
                self.groups[group.id] = group

    def _build_info(self, edited: _Edited, key: str) -> _GroupInfo | None:
        group = self.groups.get(key)
        draft = edited.groups.get(key) if edited.device_id else None
        if group is not None and group.physical_device_id != edited.device_id:
            draft = None  # группа другого устройства: форма о ней ничего не знает
        if group is None and draft is None:
            return None
        device_id = group.physical_device_id if group is not None else str(edited.device_id)
        if draft is None:
            assert group is not None  # проверено выше: нет ни группы, ни черновика — вернули None
            mode, name, vlan_ids = group.vlan_mode or "", group.name, None
        else:
            mode = draft.mode
            name = draft.name if draft.name is not None else (group.name if group is not None else "")
            # VLAN не переданы: у сохранённой группы берутся из БД, у новой их ещё нет.
            vlan_ids = list(draft.vlan_ids) if draft.vlan_ids is not None else ([] if group is None else None)
        return _GroupInfo(key=key, name=name, device_id=device_id, mode=mode, vlan_ids=vlan_ids, deferred=device_id == edited.device_id)

    def managing_group(self, edited: _Edited, port: DeviceInterface) -> _GroupInfo | None:
        """Группа порта, если она ЗАДАЁТ режим; иначе None. Группы должны быть подгружены (load_groups)."""
        key = edited.port_group_key(port)
        if not key:
            return None
        if key not in self.infos:
            self.infos[key] = self._build_info(edited, key)
        info = self.infos[key]
        if info is None or not info.mode:
            return None
        if edited.owns(port) != info.deferred:
            return None  # порт формы ссылается на группу другого устройства (или наоборот) — такой группы для него нет
        return info

    def load_members(self, edited: _Edited, keys: Iterable[str]) -> None:
        """Участники групп: у группы из БД — её порты; у группы редактируемого устройства порты, переданные
        в форме, определяет черновик, остальные — БД."""
        wanted = [k for k in dict.fromkeys(keys) if k not in self.members]
        db_keys = [k for k in wanted if k in self.groups and k not in self._db_members]
        for chunk in _chunks(db_keys):
            found: dict[str, list[str]] = {k: [] for k in chunk}
            for port in self.session.scalars(select(DeviceInterface).where(DeviceInterface.group_id.in_(chunk)).order_by(DeviceInterface.name)).all():
                self.ports[port.id] = port
                found[port.group_id].append(port.id)
            self._db_members.update(found)
        for key in wanted:
            info = self.infos[key]
            assert info is not None
            ids = list(self._db_members.get(key, []))
            if info.deferred:
                ids = [p for p in ids if p not in edited.ports or not edited.ports[p].group_given]
                ids += [p for p, state in edited.ports.items() if state.group_given and state.group == key]
                self.load_ports(ids)
                ids = [p for p in dict.fromkeys(ids) if p in self.ports and self.ports[p].physical_device_id == edited.device_id]
                ids.sort(key=lambda p: (edited.port_name(self.ports[p]), p))
            self.members[key] = ids

    def load_links(self, port_ids: Iterable[str]) -> None:
        wanted = [p for p in dict.fromkeys(port_ids) if p not in self.active]
        for chunk in _chunks(wanted):
            requested = set(chunk)
            for port_id in chunk:
                self.active[port_id] = []
                self.inactive[port_id] = []
            connections = self.session.scalars(
                select(Connection).where(or_(Connection.source_interface_id.in_(chunk), Connection.destination_interface_id.in_(chunk)))
            ).all()
            for conn in connections:
                bucket = self.active if conn.is_active else self.inactive
                for here, there in ((conn.source_interface_id, conn.destination_interface_id), (conn.destination_interface_id, conn.source_interface_id)):
                    if here in requested:
                        bucket[here].append(there)


@dataclass
class _Change:
    """Результат расчёта: что именно меняется (внутреннее представление, из него строится план)."""
    target: str
    start_id: str
    edited: _Edited
    loader: _Loader
    changed_ports: dict[str, str] = field(default_factory=dict)  # id порта -> прежний режим
    changed_groups: dict[str, str] = field(default_factory=dict)  # ключ группы -> прежний режим
    group_of_port: dict[str, str] = field(default_factory=dict)  # id порта -> ключ меняемой группы, в запись которой он входит
    group_vlans: dict[str, list[str]] = field(default_factory=dict)  # ключ группы -> id VLAN (до изменения)
    port_vlans: dict[str, list[str]] = field(default_factory=dict)  # id порта -> id VLAN (до изменения), только одиночные порты
    vlans: dict[str, VLAN] = field(default_factory=dict)
    devices: dict[str, PhysicalDevice] = field(default_factory=dict)
    inactive_ports: set[str] = field(default_factory=set)
    plan: dict[str, Any] = field(default_factory=dict)


def _collect_area(loader: _Loader, edited: _Edited, start_id: str, target: str) -> tuple[dict[str, str], dict[str, str]]:
    """Обход по уровням. Возвращает (меняемые порты, меняемые группы) — id/ключ -> прежний режим.

    Все участники меняемой группы попадают в область сами: группа отмечается на первом же
    обработанном порту из неё, а её участники ставятся в очередь и оцениваются уже с учётом этой
    отметки (режим порта != target или группа меняется)."""
    changed_ports: dict[str, str] = {}
    changed_groups: dict[str, str] = {}
    done: set[str] = set()
    frontier: list[str] = [start_id]
    while frontier:
        batch = [p for p in dict.fromkeys(frontier) if p not in done]
        if not batch:
            break
        done.update(batch)
        if len(done) > MAX_CASCADE_PORTS:
            raise HTTPException(422, f"Область изменения превышает {MAX_CASCADE_PORTS} портов — смените режим по частям: в самой группе или у отдельных устройств")
        loader.load_ports(batch)
        loader.load_groups(key for p in batch if (key := edited.port_group_key(loader.ports[p])))
        new_groups: list[str] = []
        for port_id in batch:
            group = loader.managing_group(edited, loader.ports[port_id])
            if group is not None and group.mode != target and group.key not in changed_groups:
                changed_groups[group.key] = group.mode
                new_groups.append(group.key)
        loader.load_members(edited, new_groups)
        next_frontier: list[str] = [member for key in new_groups for member in loader.members[key]]
        propagate: list[str] = []
        for port_id in batch:
            port = loader.ports[port_id]
            group = loader.managing_group(edited, port)
            if edited.port_mode(port) != target or (group is not None and group.key in changed_groups):
                changed_ports[port_id] = edited.port_mode(port)
                propagate.append(port_id)
        loader.load_links(propagate)
        for port_id in propagate:
            next_frontier.extend(loader.active[port_id])
        frontier = next_frontier
    return changed_ports, changed_groups


def _vlans_sorted(vlan_ids: list[str], vlans: dict[str, VLAN]) -> list[str]:
    """По номеру VLAN; VLAN, которого нет в справочнике (id из черновика устарел), — в начало."""
    return sorted(vlan_ids, key=lambda v: (vlans[v].vlan_id if v in vlans else 0, v))


def _split_vlans(vlan_ids: list[str], vlans: dict[str, VLAN], target: str) -> tuple[list[str], list[str]]:
    """(остаются, снимаются). access: один VLAN с наименьшим номером; trunk: без изменений."""
    ordered = _vlans_sorted(vlan_ids, vlans)
    if target == "access" and len(ordered) > 1:
        return ordered[:1], ordered[1:]
    return ordered, []


def _vlan_ref(vlan_id: str, vlans: dict[str, VLAN]) -> dict[str, Any]:
    vlan = vlans.get(vlan_id)
    return {"id": vlan_id, "vlan_id": vlan.vlan_id if vlan else None, "name": vlan.name if vlan else ""}


def _device_name(device: PhysicalDevice | None) -> str:
    return (device.system_name or device.serial_number) if device else ""


def _short_list(names: list[str]) -> str:
    shown = ", ".join(names[:_MAX_LISTED])
    return shown + (f" и ещё {len(names) - _MAX_LISTED}" if len(names) > _MAX_LISTED else "")


def _load_details(change: _Change) -> None:
    """Подгружает VLAN, устройства и неактивные подключения для уже посчитанной области. VLAN и
    имена у портов и групп редактируемого устройства берутся из черновика формы, у остальных — из БД."""
    loader, edited = change.loader, change.edited
    session = loader.session
    for key in change.changed_groups:
        for member in loader.members[key]:
            change.group_of_port[member] = key
    stored_groups: list[str] = []
    for key in change.changed_groups:
        info = loader.infos[key]
        assert info is not None
        if info.vlan_ids is not None:
            change.group_vlans[key] = list(dict.fromkeys(info.vlan_ids))
        else:
            stored_groups.append(key)
    for chunk in _chunks(stored_groups):
        for row in session.scalars(select(InterfaceGroupVLAN).where(InterfaceGroupVLAN.group_id.in_(chunk))).all():
            change.group_vlans.setdefault(row.group_id, []).append(row.vlan_id)
    stored_ports: list[str] = []
    for port_id in change.changed_ports:
        if port_id in change.group_of_port:
            continue
        state = edited.port_state(loader.ports[port_id])
        if state is not None and state.vlan_ids is not None:
            change.port_vlans[port_id] = list(dict.fromkeys(state.vlan_ids))
        else:
            stored_ports.append(port_id)
    for chunk in _chunks(stored_ports):
        for row in session.scalars(select(InterfaceVLAN).where(InterfaceVLAN.interface_id.in_(chunk))).all():
            change.port_vlans.setdefault(row.interface_id, []).append(row.vlan_id)
    vlan_ids = {v for ids in change.group_vlans.values() for v in ids} | {v for ids in change.port_vlans.values() for v in ids}
    for chunk in _chunks(list(vlan_ids)):
        for vlan in session.scalars(select(VLAN).where(VLAN.id.in_(chunk))).all():
            change.vlans[vlan.id] = vlan
    device_ids = {loader.ports[p].physical_device_id for p in change.changed_ports}
    for chunk in _chunks(list(device_ids)):
        for device in session.scalars(select(PhysicalDevice).where(PhysicalDevice.id.in_(chunk))).all():
            change.devices[device.id] = device
    # Неактивные подключения: только для информирующего предупреждения.
    changed = list(change.changed_ports)
    loader.load_links(changed)
    ports_to_check = {there for p in changed for there in loader.inactive[p]}
    loader.load_ports(ports_to_check)
    for port_id in changed:
        if any(edited.port_mode(loader.ports[o]) != change.target for o in loader.inactive[port_id] if o in loader.ports):
            change.inactive_ports.add(port_id)


def _build_plan(change: _Change) -> dict[str, Any]:
    loader, target, edited = change.loader, change.target, change.edited
    groups_out: list[dict[str, Any]] = []
    for key, from_mode in change.changed_groups.items():
        info = loader.infos[key]
        assert info is not None
        before = change.group_vlans.get(key, [])
        after, dropped = _split_vlans(before, change.vlans, target)
        groups_out.append({
            "id": key, "name": info.name, "device_id": info.device_id, "device_name": _device_name(change.devices.get(info.device_id)),
            "deferred": info.deferred, "from_mode": from_mode, "to_mode": target,
            "ports": [{"id": m, "name": edited.port_name(loader.ports[m])} for m in loader.members[key]],
            "vlans_before": [_vlan_ref(v, change.vlans) for v in _vlans_sorted(before, change.vlans)],
            "vlans_after": [_vlan_ref(v, change.vlans) for v in after], "dropped_vlans": [_vlan_ref(v, change.vlans) for v in dropped],
        })
    ports_out: list[dict[str, Any]] = []
    for pid, from_mode in change.changed_ports.items():
        if pid in change.group_of_port:
            continue  # входит в запись своей группы
        port = loader.ports[pid]
        before = change.port_vlans.get(pid, [])
        after, dropped = _split_vlans(before, change.vlans, target)
        ports_out.append({
            "id": pid, "name": edited.port_name(port), "device_id": port.physical_device_id, "device_name": _device_name(change.devices.get(port.physical_device_id)),
            "deferred": edited.owns(port), "from_mode": from_mode, "to_mode": target,
            "vlans_before": [_vlan_ref(v, change.vlans) for v in _vlans_sorted(before, change.vlans)],
            "vlans_after": [_vlan_ref(v, change.vlans) for v in after], "dropped_vlans": [_vlan_ref(v, change.vlans) for v in dropped],
        })
    groups_out.sort(key=lambda g: (g["device_name"], g["name"]))
    ports_out.sort(key=lambda p: (p["device_name"], p["name"]))
    devices_out: dict[str, dict[str, Any]] = {}
    for pid in change.changed_ports:
        port = loader.ports[pid]
        entry = devices_out.setdefault(port.physical_device_id, {
            "id": port.physical_device_id, "name": _device_name(change.devices.get(port.physical_device_id)),
            "deferred": edited.owns(port), "port_count": 0, "group_count": 0,
        })
        entry["port_count"] += 1
    for group in groups_out:
        devices_out[group["device_id"]]["group_count"] += 1
    devices = sorted(devices_out.values(), key=lambda d: d["name"])
    deferred_ports = sum(d["port_count"] for d in devices if d["deferred"])
    plan: dict[str, Any] = {
        "target_mode": target, "start_interface_id": change.start_id, "edited_device_id": edited.device_id, "empty": not change.changed_ports,
        "groups": groups_out, "ports": ports_out, "devices": devices,
        "totals": {
            "ports": len(change.changed_ports), "devices": len(devices), "groups": len(groups_out),
            "deferred_ports": deferred_ports, "immediate_ports": len(change.changed_ports) - deferred_ports,
            "immediate_devices": sum(1 for d in devices if not d["deferred"]), "dropped_vlans": sum(len(x["dropped_vlans"]) for x in groups_out + ports_out),
        },
    }
    plan["warnings"] = _warnings(plan, change)
    plan["hash"] = _plan_hash(plan)
    return plan


def _plan_hash(plan: dict[str, Any]) -> str:
    """Отпечаток того, что будет записано: цель, редактируемое устройство и для каждой группы/порта
    прежний/новый режим и итоговые VLAN. Предупреждения и подписи в него не входят."""
    material = {
        "target": plan["target_mode"], "start": plan["start_interface_id"], "edited": plan["edited_device_id"],
        "groups": sorted((g["id"], g["from_mode"], g["to_mode"], [v["id"] for v in g["vlans_after"]], [p["id"] for p in g["ports"]]) for g in plan["groups"]),
        "ports": sorted((p["id"], p["from_mode"], p["to_mode"], [v["id"] for v in p["vlans_after"]]) for p in plan["ports"]),
    }
    return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:32]


def _warning(code: str, severity: str, text: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "text": text}


def _warnings(plan: dict[str, Any], change: _Change) -> list[dict[str, str]]:
    """Предупреждения о последствиях — показываются пользователю ДО применения."""
    if plan["empty"]:
        return []
    totals, target = plan["totals"], plan["target_mode"]
    result: list[dict[str, str]] = []
    if totals["immediate_ports"]:
        result.append(_warning("immediate", "warning", f"Изменения на других устройствах ({totals['immediate_ports']} портов на {totals['immediate_devices']} устройствах) применяются сразу и не отменяются кнопкой «Отмена» формы; они записываются в журнал аудита."))
    if totals["deferred_ports"]:
        result.append(_warning("deferred", "info", f"Изменения на редактируемом устройстве ({totals['deferred_ports']} портов) попадут в форму и сохранятся только после нажатия «Сохранить». Если форму не сохранить, режим у соседей уже будет другим, и расхождения появятся снова."))
    if plan["groups"]:
        listed = _short_list([f"«{g['name']}» ({len(g['ports'])} портов, {g['device_name']})" for g in plan["groups"]])
        result.append(_warning("groups", "warning", f"Режим порта задаётся группами, поэтому он изменится у всех портов группы, а не только у связанного порта: {listed}."))
    start_group = change.group_of_port.get(change.start_id)
    start_scope = {change.start_id} | (set(change.loader.members[start_group]) if start_group else set())
    beyond = [p for p in change.changed_ports if p not in start_scope]
    if beyond:
        beyond_devices = {change.loader.ports[p].physical_device_id for p in beyond}
        result.append(_warning("cascade", "warning", f"Чтобы на портах соседей не осталось расхождений, режим меняется и у связанных с ними портов: ещё {len(beyond)} портов на {len(beyond_devices)} устройствах."))
    dropped = [(g["name"], g, v) for g in plan["groups"] + plan["ports"] for v in g["dropped_vlans"]]
    if dropped:
        listed = _short_list([f"VLAN {v['vlan_id']} «{v['name']}» ({'группа' if 'ports' in g else 'порт'} «{owner}»)" for owner, g, v in dropped])
        result.append(_warning("vlans_dropped", "warning", f"Режим access допускает у порта или группы не более одного VLAN: останется VLAN с наименьшим номером, будут сняты {listed}. Это изменит VLAN ID и VLAN Name в отчётах (лист «Организация подключений») и на диаграммах."))
    if target == "trunk":
        result.append(_warning("trunk", "info", "В режиме trunk остаются только уже назначенные VLAN — «все VLAN» автоматически не добавляются. При необходимости добавьте VLAN в группе или у порта."))
    if change.inactive_ports:
        result.append(_warning("inactive", "info", f"Неактивные подключения не учитываются: у {len(change.inactive_ports)} изменяемых портов они ведут к портам с другим режимом."))
    if totals["ports"] > LARGE_CASCADE_PORTS:
        result.append(_warning("large", "warning", f"Область изменения большая — {totals['ports']} портов. Проверьте список перед применением."))
    return result


def _parse_mode(mode: Any) -> str:
    if mode not in VLAN_MODES:
        raise HTTPException(422, "Режим порта должен быть 'access' или 'trunk'")
    return mode


def _vlan_id_list(raw: Any, where: str) -> tuple[str, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or any(not isinstance(v, str) for v in raw):
        raise HTTPException(422, f"{where}: vlan_ids должен быть списком строк")
    return tuple(raw)


def _optional_text(raw: Any, where: str, field_name: str) -> str | None:
    if raw is not None and not isinstance(raw, str):
        raise HTTPException(422, f"{where}: {field_name} должно быть строкой")
    return raw


def _parse_edited_port(port_id: Any, raw: Any) -> _EditedPort:
    where = f"edited.ports[{port_id!r}]"
    if not isinstance(port_id, str) or not isinstance(raw, dict):
        raise HTTPException(422, f"{where} должен быть объектом {{mode, group?, vlan_ids?, name?}}")
    if raw.get("mode") not in VLAN_MODES:
        raise HTTPException(422, f"{where}: режим порта должен быть 'access' или 'trunk'")
    group = raw.get("group")
    if group is not None and not isinstance(group, str):
        raise HTTPException(422, f"{where}: group должна быть ключом группы или null")
    return _EditedPort(
        mode=raw["mode"], group_given="group" in raw, group=group or None,
        vlan_ids=_vlan_id_list(raw.get("vlan_ids"), where), name=_optional_text(raw.get("name"), where, "name"),
    )


def _parse_edited_group(key: Any, raw: Any) -> _EditedGroup:
    where = f"edited.groups[{key!r}]"
    if not isinstance(key, str) or not key or not isinstance(raw, dict):
        raise HTTPException(422, f"{where} должен быть объектом {{mode, vlan_ids?, name?}} с непустым ключом группы")
    if raw.get("mode") not in (*VLAN_MODES, ""):
        raise HTTPException(422, f"{where}: режим группы должен быть 'access', 'trunk' или пустым")
    return _EditedGroup(mode=raw["mode"], vlan_ids=_vlan_id_list(raw.get("vlan_ids"), where), name=_optional_text(raw.get("name"), where, "name"))


def _parse_edited(raw: Any) -> _Edited:
    """edited = {device_id, ports: {id: {mode, group?, vlan_ids?, name?}}, groups: {ключ: {mode, vlan_ids?, name?}}}
    или null/отсутствует. group у порта — ключ группы формы (null — порт вне групп); группы формы — и
    сохранённые (ключ = id), и новые (временный ключ)."""
    if raw is None:
        return _Edited()
    if not isinstance(raw, dict) or not isinstance(raw.get("device_id"), str) or not raw["device_id"]:
        raise HTTPException(422, "Поле edited должно быть объектом с непустым device_id")
    # Не `or {}`: пустой список вместо объекта тоже должен отклоняться, а не молча становиться {}.
    ports = {} if raw.get("ports") is None else raw["ports"]
    groups = {} if raw.get("groups") is None else raw["groups"]
    if not isinstance(ports, dict) or not isinstance(groups, dict):
        raise HTTPException(422, "Поля edited.ports и edited.groups должны быть объектами")
    return _Edited(
        device_id=raw["device_id"],
        ports={port_id: _parse_edited_port(port_id, state) for port_id, state in ports.items()},
        groups={key: _parse_edited_group(key, state) for key, state in groups.items()},
    )


def _compute(start_id: str, mode: str, edited: _Edited, session: Session) -> _Change:
    loader = _Loader(session)
    loader.load_ports([start_id])
    if start_id not in loader.ports:
        raise HTTPException(404, "Порт не найден")
    changed_ports, changed_groups = _collect_area(loader, edited, start_id, mode)
    change = _Change(target=mode, start_id=start_id, edited=edited, loader=loader, changed_ports=changed_ports, changed_groups=changed_groups)
    if changed_ports:
        _load_details(change)
    change.plan = _build_plan(change)
    return change


def preview_vlan_mode_cascade(interface_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """План смены режима порта и всех зависимых портов — ничего не записывает.

    payload: {mode, edited?} — edited: устройство с открытой формой и режимы его портов/групп в черновике."""
    if not isinstance(payload, dict):
        raise HTTPException(422, "Тело запроса должно быть объектом")
    return _compute(interface_id, _parse_mode(payload.get("mode")), _parse_edited(payload.get("edited")), session).plan


def _write_port(port: DeviceInterface, target: str, keep: list[str], session: Session) -> None:
    port.vlan_mode = target
    session.flush()
    links = session.scalars(select(InterfaceVLAN).where(InterfaceVLAN.interface_id == port.id)).all()
    kept: set[str] = set()
    for link in links:
        if link.vlan_id in keep and link.vlan_id not in kept:
            link.mode = target
            kept.add(link.vlan_id)
        else:
            session.delete(link)
    for vlan_id in keep:
        if vlan_id not in kept:
            session.add(InterfaceVLAN(interface_id=port.id, vlan_id=vlan_id, mode=target))


def _audit_text(plan: dict[str, Any], device_id: str, start_label: str) -> str:
    groups = [g for g in plan["groups"] if g["device_id"] == device_id and not g["deferred"]]
    ports = [p for p in plan["ports"] if p["device_id"] == device_id and not p["deferred"]]
    parts = [f"Каскадная смена режима порта → {plan['target_mode']} (инициатор: {start_label})"]
    if groups:
        parts.append("группы: " + _short_list([f"«{g['name']}» ({len(g['ports'])} портов)" for g in groups]))
    if ports:
        parts.append("порты: " + _short_list([p["name"] for p in ports]))
    dropped = [f"VLAN {v['vlan_id']} у «{x['name']}»" for x in groups + ports for v in x["dropped_vlans"]]
    if dropped:
        parts.append("сняты " + _short_list(dropped))
    return "; ".join(parts)


def apply_vlan_mode_cascade(interface_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """Применяет план к данным (кроме редактируемого устройства — его порты и группы клиент вносит
    в черновик формы). Одна транзакция: либо записано всё, либо ничего.

    payload: {mode, edited?, plan_hash, confirm: true} — mode и edited те же, что при предпросмотре.
    Без confirm=true — 422; если план при применении отличается от показанного при предпросмотре
    (hash) — 409."""
    if not isinstance(payload, dict):
        raise HTTPException(422, "Тело запроса должно быть объектом")
    mode, edited = _parse_mode(payload.get("mode")), _parse_edited(payload.get("edited"))
    if payload.get("confirm") is not True:
        raise HTTPException(422, "Применение требует подтверждения: confirm = true")
    change = _compute(interface_id, mode, edited, session)
    plan = change.plan
    if plan["empty"]:
        return {"plan": plan, "applied": {"ports": 0, "groups": 0, "devices": 0}, "interfaces": []}
    if payload.get("plan_hash") != plan["hash"]:
        raise HTTPException(409, "Данные изменились после предпросмотра — повторите операцию и проверьте новый план")
    loader = change.loader
    written_ports: list[DeviceInterface] = []
    for g in plan["groups"]:
        if g["deferred"]:
            continue
        group = loader.groups[g["id"]]
        keep = [v["id"] for v in g["vlans_after"]]
        group.vlan_mode = mode
        for row in session.scalars(select(InterfaceGroupVLAN).where(InterfaceGroupVLAN.group_id == group.id)).all():
            if row.vlan_id not in keep:
                session.delete(row)
        for member in g["ports"]:
            port = loader.ports[member["id"]]
            _write_port(port, mode, keep, session)
            written_ports.append(port)
    for p in plan["ports"]:
        if p["deferred"]:
            continue
        port = loader.ports[p["id"]]
        _write_port(port, mode, [v["id"] for v in p["vlans_after"]], session)
        written_ports.append(port)
    start = loader.ports[interface_id]
    start_label = f"порт «{change.edited.port_name(start)}» устройства «{_device_name(change.devices.get(start.physical_device_id))}»"
    for device in plan["devices"]:
        if not device["deferred"]:
            audit(session, "interfaces", device["id"], AuditAction.UPDATE, _audit_text(plan, device["id"], start_label))
    session.commit()
    applied = {"ports": len(written_ports), "groups": sum(1 for g in plan["groups"] if not g["deferred"]), "devices": plan["totals"]["immediate_devices"]}
    return {"plan": plan, "applied": applied, "interfaces": enrich_interfaces(written_ports, session)}
