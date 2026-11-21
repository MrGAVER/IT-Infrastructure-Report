"""VLAN: панель, участники и синхронизация доменов, копирование и массовое назначение (код-ревью п. 10).

Обработчики только разбирают запрос и вызывают services/vlan_operations.py — вся логика там.
"""

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import BulkVlanAssignRequest, VLANDomainMemberRequest, VLANDomainSyncRequest, VlanCopyRequest
from ..services.vlan_operations import (
    add_domain_member,
    build_vlan_dashboard,
    sync_domain,
)
from ..services.vlan_operations import bulk_assign_vlan as bulk_assign_vlans
from ..services.vlan_operations import copy_device_vlans as copy_vlans_between_devices

router = APIRouter(tags=["VLAN"])


@router.get("/api/v1/vlan-dashboard")
def vlan_dashboard(session: Session = Depends(get_db)):
    """Dashboard-friendly VLAN view: same VLAN ID can have different definitions."""
    return build_vlan_dashboard(session)


@router.post("/api/v1/vlan-domains/{domain_id}/members")
def add_vlan_domain_member(domain_id: str, payload: VLANDomainMemberRequest, session: Session = Depends(get_db)):
    return add_domain_member(session, domain_id, payload.physical_device_id)


@router.post("/api/v1/vlan-domains/{domain_id}/sync")
def sync_vlan_domain(domain_id: str, payload: VLANDomainSyncRequest = Body(default_factory=VLANDomainSyncRequest), session: Session = Depends(get_db)):
    """Пункт 1 правки "домен VLAN" — payload может содержать replace=true (посылается
    VLANDomainFormModal.vue при смене устройства-источника, после подтверждения
    пользователем предупреждения о перезаписи): помимо обычного добавления недостающих VLAN
    участникам (как и раньше), ЕЩЁ убирает у них те VLAN этого домена (VLAN.domain_id==domain_id),
    которых больше нет у устройства-источника. Именно replace=true даёт то самое "все VLAN на
    устройствах домена будут перезаписаны на VLAN устройства-источника", о котором предупреждает
    форма — обычная синхронизация (кнопка "Синхронизировать" в VLANDomainsPanel.vue,
    replace не передаётся) только добавляет отсутствующее и НЕ трогает лишнее, это её штатное,
    уже используемое поведение, менять его не нужно."""
    return sync_domain(session, domain_id, payload.replace)


@router.post("/api/v1/devices/{device_id}/vlan-copy")
def copy_device_vlans(device_id: str, payload: VlanCopyRequest, session: Session = Depends(get_db)):
    return copy_vlans_between_devices(session, device_id, payload.source_device_id)


@router.post("/api/v1/device-vlans/bulk-assign")
def bulk_assign_vlan(payload: BulkVlanAssignRequest, session: Session = Depends(get_db)):
    """Назначает один существующий VLAN сразу нескольким устройствам — без создания формального
    VLANDomain (тот нужен для периодической синхронизации набора VLAN, см. sync_vlan_domain; это —
    разовое массовое назначение, по аналогии с bulk-редактором интерфейсов на фронтенде).
    IP-адрес в bulk-режиме не задаётся намеренно: одинаковый IP на нескольких устройствах в одном
    VLAN был бы некорректен, а различающиеся значения для каждого устройства — уже не bulk-действие;
    IP при необходимости проставляется потом по каждой записи individually."""
    return bulk_assign_vlans(session, payload.physical_device_ids, payload.vlan_id, payload.description)
