from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..db import get_db
from ..services.crud import get_interface_groups, sync_device_deployed_software, sync_device_vlans, sync_interfaces
from ..services.device_connectivity import list_free_interfaces, list_interface_connections
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


@router.get('/{device_id}/free-interfaces')
def free_interfaces(
    device_id: str,
    q: str | None = None,
    include: list[str] = Query(default=[]),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    session: Session = Depends(get_db),
):
    """Свободные порты устройства (без активного подключения) для выбора соседа в форме подключения.
    include — id портов, которые вернуть даже занятыми (текущий сосед, порты, освобождаемые формой)."""
    return list_free_interfaces(device_id, session, q=q, include=include, offset=offset, limit=limit)


@router.get('/{device_id}/interface-connections')
def interface_connections(device_id: str, session: Session = Depends(get_db)):
    """Действующие подключения портов устройства со сведениями о соседнем порте и устройстве."""
    return list_interface_connections(device_id, session)
