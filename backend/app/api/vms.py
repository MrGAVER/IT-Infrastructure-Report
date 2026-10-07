"""Вложенные коллекции виртуальных машин: открытые порты, IP-адреса, развёрнутое ПО."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import DeployedSoftwareSync, VMIPAddressesSync, VMOpenPortsSync
from ..services.crud import sync_vm_deployed_software, sync_vm_ip_addresses, sync_vm_open_ports

router = APIRouter(tags=['Virtual machines'])

@router.put('/api/v1/vms/{vm_id}/open-ports')
def sync_vm_ports(vm_id: str, payload: VMOpenPortsSync, session: Session = Depends(get_db)):
    """Атомарная синхронизация открытых портов ВМ: тело {open_ports: [{id?, protocol_catalog_id,
    transport_protocol, description}]} — полный список портов ВМ, diff по id (см.
    services/crud/owned_rows.py:sync_vm_open_ports)."""
    return sync_vm_open_ports(vm_id, payload.model_dump(exclude_unset=True), session)

@router.put('/api/v1/vms/{vm_id}/ip-addresses')
def sync_vm_ips(vm_id: str, payload: VMIPAddressesSync, session: Session = Depends(get_db)):
    """Атомарная синхронизация IP-адресов ВМ: тело {ip_addresses: [{id?, ip_address, prefix_length,
    purpose, is_management}]} — полный список IP-адресов ВМ, diff по id (см.
    services/crud/owned_rows.py:sync_vm_ip_addresses)."""
    return sync_vm_ip_addresses(vm_id, payload.model_dump(exclude_unset=True), session)

@router.put('/api/v1/vms/{vm_id}/deployed-software')
def sync_vm_software(vm_id: str, payload: DeployedSoftwareSync, session: Session = Depends(get_db)):
    """Атомарная синхронизация программных активов ВМ: тело {deployed_software: [{id?,
    software_asset_id, version}]} — полный список ПО ВМ, diff по id (см.
    services/crud/owned_rows.py:sync_vm_deployed_software)."""
    return sync_vm_deployed_software(vm_id, payload.model_dump(exclude_unset=True), session)
