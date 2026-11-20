"""Операции с VLAN устройств и доменов: панель VLAN, участники и синхронизация домена, копирование и массовое назначение.

Вынесено из api/vlan.py (бизнес-логика не должна жить в обработчиках). Функции работают с
открытой сессией, коммитят сами и бросают HTTPException (404/422) — так же, как сервисы generic CRUD.
Тела функций перенесены из обработчиков без изменения логики; описание контрактов эндпоинтов — в docstring
соответствующих обработчиков api/vlan.py (они же попадают в /docs).
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..models import VLAN, PhysicalDevice, PhysicalDeviceVLAN, VLANDomain, VLANDomainDevice
from .crud import assign_domain_vlans_to_device, audit
from .device_label import device_label
from .serialization import serialize


def build_vlan_dashboard(session: Session) -> dict[str, Any]:
    """Панель VLAN: один номер VLAN может иметь разные определения; к каждому приложены устройства."""

    vlans = session.scalars(select(VLAN).order_by(VLAN.vlan_id, VLAN.name)).all()
    devices = session.scalars(select(PhysicalDevice)).all()
    device_names = {d.id: device_label(d, fallback=d.id) for d in devices}
    domains = {d.id: d for d in session.scalars(select(VLANDomain)).all()}
    assignments = session.scalars(select(PhysicalDeviceVLAN)).all()
    grouped = {}
    for v in vlans:
        grouped.setdefault(v.vlan_id, []).append({"id": v.id, "vlan_id": v.vlan_id, "name": v.name, "description": v.description or "", "domain_id": v.domain_id, "domain_name": domains[v.domain_id].name if v.domain_id in domains else "Локальный VLAN", "devices": []})
    by_vlan = {}
    for a in assignments:
        by_vlan.setdefault(a.vlan_id, []).append({"device_id": a.physical_device_id, "device_name": device_names.get(a.physical_device_id, a.physical_device_id), "ip_address": a.ip_address, "is_management": a.is_management})
    for defs in grouped.values():
        for item in defs:
            item["devices"] = by_vlan.get(item["id"], [])
    return {"items": [{"vlan_id": k, "definitions": v} for k, v in sorted(grouped.items())]}


def add_domain_member(session: Session, domain_id: str, physical_device_id: str | None) -> dict[str, Any]:
    """Добавляет устройство в VLAN-домен (идемпотентно) и сразу переносит на него VLAN домена."""

    domain = session.get(VLANDomain, domain_id)
    device = session.get(PhysicalDevice, physical_device_id) if physical_device_id else None
    if not domain or not device:
        raise HTTPException(404, "Домен или физическое устройство не найдено")
    existing = session.scalar(select(VLANDomainDevice).where(VLANDomainDevice.domain_id == domain_id, VLANDomainDevice.physical_device_id == device.id))
    if existing:
        return serialize(existing)
    obj = VLANDomainDevice(domain_id=domain_id, physical_device_id=device.id)
    session.add(obj)
    session.flush()
    # Пункт 2 правки "домен VLAN": сразу переносим на новое устройство то, что уже определено для
    # этого домена (assign_domain_vlans_to_device — общая с create_resource('vlan-domain-devices')
    # логика, см. её docstring в services/crud/).
    assign_domain_vlans_to_device(domain_id, device.id, session)
    audit(session, "vlan-domain-devices", obj.id, AuditAction.CREATE, f"Устройство добавлено в VLAN-домен «{domain.name}»")
    session.commit()
    session.refresh(obj)
    return serialize(obj)


def _load_domain_for_sync(session: Session, domain_id: str) -> VLANDomain:
    domain = session.get(VLANDomain, domain_id)
    if not domain:
        raise HTTPException(404, "Домен VLAN не найден")
    if not domain.source_device_id:
        raise HTTPException(422, "Для домена не задано устройство-источник")
    return domain


def _ensure_domain_vlan_definitions(session: Session, domain_id: str, source_vlans: list[VLAN]) -> tuple[dict[str, VLAN], dict[int, VLAN], int]:
    """Для каждого VLAN источника находит или создаёт определение VLAN в домене.

    Возвращает (определение домена по id VLAN источника, определения домена по номеру, сколько создано).
    Domain-local VLAN definitions are shared by every member device, so each source VLAN is
    resolved/created here once — not once per (device, source VLAN) pair as before, which was an
    N+1 query (member devices × source VLANs) inside the loop of the caller."""
    domain_vlans_by_number = {v.vlan_id: v for v in session.scalars(select(VLAN).where(VLAN.domain_id == domain_id)).all()}
    target_by_source_id: dict[str, VLAN] = {}
    created = 0
    for sv in source_vlans:
        target = domain_vlans_by_number.get(sv.vlan_id)
        if not target:
            target = VLAN(vlan_id=sv.vlan_id, name=sv.name, description=sv.description, domain_id=domain_id)
            session.add(target)
            session.flush()
            created += 1
            domain_vlans_by_number[sv.vlan_id] = target
        target_by_source_id[sv.id] = target
    return target_by_source_id, domain_vlans_by_number, created


def _existing_vlan_ids_by_device(session: Session, device_ids: list[str]) -> dict[str, set[str]]:
    """Существующие назначения VLAN для всех устройств сразу (одним запросом, а не по устройству)."""
    existing_by_device: dict[str, set[str]] = {}
    if device_ids:
        for row in session.scalars(select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id.in_(device_ids))).all():
            existing_by_device.setdefault(row.physical_device_id, set()).add(row.vlan_id)
    return existing_by_device


def _sync_member_device(session: Session, device_id: str, existing_ids: set[str], source_vlans: list[VLAN], target_by_source_id: dict[str, VLAN], domain_vlan_ids: set[str], keep_ids: set[str], replace: bool) -> tuple[int, int]:
    """Назначает участнику недостающие VLAN источника; при replace убирает VLAN этого домена, которых у источника нет.

    Возвращает (сколько назначено, сколько убрано)."""
    assigned = 0
    for sv in source_vlans:
        target = target_by_source_id[sv.id]
        if target.id not in existing_ids:
            session.add(PhysicalDeviceVLAN(physical_device_id=device_id, vlan_id=target.id, description=sv.description))
            assigned += 1
    removed = 0
    if replace:
        # Только VLAN ЭТОГО домена (domain_vlan_ids) — VLAN участника из ДРУГИХ доменов или
        # локальные (без domain_id вовсе) синхронизация трогать не должна ни в каком режиме.
        stale_ids = (existing_ids & domain_vlan_ids) - keep_ids
        if stale_ids:
            session.execute(delete(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id == device_id, PhysicalDeviceVLAN.vlan_id.in_(stale_ids)))
            removed = len(stale_ids)
    return assigned, removed


def sync_domain(session: Session, domain_id: str, replace: bool) -> dict[str, Any]:
    """Синхронизирует VLAN устройства-источника на участников домена; replace=True ещё и убирает лишние VLAN домена."""

    domain = _load_domain_for_sync(session, domain_id)
    member_ids = session.scalars(select(VLANDomainDevice.physical_device_id).where(VLANDomainDevice.domain_id == domain_id)).all()
    source_ids = session.scalars(select(PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id == domain.source_device_id)).all()
    source_vlans = session.scalars(select(VLAN).where(VLAN.id.in_(source_ids))).all() if source_ids else []
    target_by_source_id, domain_vlans_by_number, created = _ensure_domain_vlan_definitions(session, domain_id, source_vlans)
    existing_by_device = _existing_vlan_ids_by_device(session, member_ids)
    domain_vlan_ids = {v.id for v in domain_vlans_by_number.values()}
    keep_ids = {t.id for t in target_by_source_id.values()}
    updated = removed = 0
    for device_id in member_ids:
        if device_id == domain.source_device_id:
            continue
        assigned, stale_removed = _sync_member_device(session, device_id, existing_by_device.get(device_id, set()), source_vlans, target_by_source_id, domain_vlan_ids, keep_ids, replace)
        updated += assigned
        removed += stale_removed
    detail = f"Синхронизация VLAN-домена: создано определений {created}, назначено {updated}"
    if replace:
        detail += f", убрано {removed}"
    audit(session, "vlan-domains", domain_id, AuditAction.SYNC, detail)
    session.commit()
    return {"status": "ok", "created_definitions": created, "assigned": updated, "removed": removed}


def copy_device_vlans(session: Session, device_id: str, source_device_id: str | None) -> dict[str, Any]:
    """Копирует VLAN с устройства-источника на целевое; повторный вызов дублей не создаёт."""

    target = session.get(PhysicalDevice, device_id)
    source = session.get(PhysicalDevice, source_device_id) if source_device_id else None
    if not target or not source:
        raise HTTPException(404, "Исходное или целевое устройство не найдено")
    source_assignments = session.scalars(select(PhysicalDeviceVLAN).where(PhysicalDeviceVLAN.physical_device_id == source.id)).all()
    # Определения VLAN источника — одним запросом (раньше session.get на каждое назначение).
    source_vlan_ids = [a.vlan_id for a in source_assignments]
    source_vlans = {v.id: v for v in session.scalars(select(VLAN).where(VLAN.id.in_(source_vlan_ids)))} if source_vlan_ids else {}
    # Идемпотентность: VLAN с тем же номером и именем, что уже назначен целевому устройству, второй раз не
    # создаётся — повторный вызов раньше плодил дубли определений VLAN и назначений.
    already_on_target = {(v.vlan_id, v.name) for v in session.scalars(select(VLAN).join(PhysicalDeviceVLAN, PhysicalDeviceVLAN.vlan_id == VLAN.id).where(PhysicalDeviceVLAN.physical_device_id == target.id))}
    created = 0
    assigned = 0
    skipped = 0
    for a in source_assignments:
        sv = source_vlans.get(a.vlan_id)
        if not sv:
            continue
        if (sv.vlan_id, sv.name) in already_on_target:
            skipped += 1
            continue
        already_on_target.add((sv.vlan_id, sv.name))
        # Copy creates a device-local definition so same ID/name can diverge later.
        v = VLAN(vlan_id=sv.vlan_id, name=sv.name, description=sv.description, domain_id=None)
        session.add(v)
        session.flush()
        created += 1
        session.add(PhysicalDeviceVLAN(physical_device_id=target.id, vlan_id=v.id, ip_address=None, prefix_length=None, is_management=False, description=sv.description))
        assigned += 1
    audit(session, "devices", target.id, AuditAction.SYNC, f"Скопированы VLAN с устройства «{device_label(source)}»: определений {created}, назначено {assigned}" + (f", уже были на устройстве {skipped}" if skipped else ""))
    session.commit()
    return {"status": "ok", "created_definitions": created, "assigned": assigned}


def bulk_assign_vlan(session: Session, device_ids: list[str], vlan_id: str | None, description: str | None) -> dict[str, Any]:
    """Назначает один существующий VLAN сразу нескольким устройствам."""

    description = description or None
    if not device_ids:
        raise HTTPException(422, "Укажите хотя бы одно устройство")
    if not vlan_id or not session.get(VLAN, vlan_id):
        raise HTTPException(404, "VLAN не найден")
    found_ids = set(session.scalars(select(PhysicalDevice.id).where(PhysicalDevice.id.in_(device_ids))).all())  # одним запросом, а не session.get на каждое устройство
    missing = [d for d in device_ids if d not in found_ids]
    if missing:
        raise HTTPException(404, f"Устройства не найдены: {', '.join(missing)}")
    existing = set(
        session.scalars(
            select(PhysicalDeviceVLAN.physical_device_id).where(
                PhysicalDeviceVLAN.physical_device_id.in_(device_ids),
                PhysicalDeviceVLAN.vlan_id == vlan_id,
            )
        ).all()
    )
    assigned = 0
    for device_id in dict.fromkeys(device_ids):  # dict.fromkeys: сохраняет порядок, убирает дубли
        if device_id in existing:
            continue
        session.add(PhysicalDeviceVLAN(physical_device_id=device_id, vlan_id=vlan_id, description=description))
        assigned += 1
    audit(session, "device-vlans", vlan_id, AuditAction.SYNC, f"Массовое назначение VLAN: устройств {assigned}, уже было назначено ранее {len(existing)}")
    session.commit()
    return {"status": "ok", "assigned": assigned, "skipped_existing": len(existing)}
