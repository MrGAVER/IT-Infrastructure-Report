from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db import get_db
from ..services.crud import sync_device_vlans, sync_interfaces
router = APIRouter(prefix='/api/v1/devices', tags=['Devices'])
@router.put('/{device_id}/interfaces')
def sync(device_id: str, payload: dict, session: Session = Depends(get_db)):
    return sync_interfaces(device_id, payload, session)


@router.put('/{device_id}/vlans')
def sync_vlans(device_id: str, payload: dict, session: Session = Depends(get_db)):
    return sync_device_vlans(device_id, payload, session)
