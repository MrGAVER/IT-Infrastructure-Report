from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db import get_db
from ..services.crud import get_interface_groups, sync_device_deployed_software, sync_device_vlans, sync_interfaces
router = APIRouter(prefix='/api/v1/devices', tags=['Devices'])
@router.put('/{device_id}/interfaces')
def sync(device_id: str, payload: dict, session: Session = Depends(get_db)):
    return sync_interfaces(device_id, payload, session)


@router.put('/{device_id}/vlans')
def sync_vlans(device_id: str, payload: dict, session: Session = Depends(get_db)):
    return sync_device_vlans(device_id, payload, session)


@router.put('/{device_id}/deployed-software')
def sync_deployed_software(device_id: str, payload: dict, session: Session = Depends(get_db)):
    return sync_device_deployed_software(device_id, payload, session)


@router.get('/{device_id}/interface-groups')
def interface_groups(device_id: str, session: Session = Depends(get_db)):
    return get_interface_groups(device_id, session)
