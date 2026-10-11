from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..db import get_db
from ..schemas import DeployedSoftwareSync, DeviceInterfacesSync, DeviceVlansSync
from ..services.crud import get_device_interface_vlans, get_device_subinterfaces, get_interface_groups, sync_device_deployed_software, sync_device_vlans, sync_interfaces
from ..services.device_connectivity import list_device_options, list_free_interfaces, list_interface_connections
router = APIRouter(prefix='/api/v1/devices', tags=['Devices'])
@router.put('/{device_id}/interfaces')
def sync_device_interfaces(device_id: str, payload: DeviceInterfacesSync, session: Session = Depends(get_db)):
    return sync_interfaces(device_id, payload.model_dump(exclude_unset=True), session)


@router.put('/{device_id}/vlans')
def sync_vlans(device_id: str, payload: DeviceVlansSync, session: Session = Depends(get_db)):
    return sync_device_vlans(device_id, payload.model_dump(exclude_unset=True), session)


@router.put('/{device_id}/deployed-software')
def sync_deployed_software(device_id: str, payload: DeployedSoftwareSync, session: Session = Depends(get_db)):
    return sync_device_deployed_software(device_id, payload.model_dump(exclude_unset=True), session)


@router.get('/{device_id}/interface-groups')
def interface_groups(device_id: str, session: Session = Depends(get_db)):
    return get_interface_groups(device_id, session)


@router.get('/{device_id}/interface-vlans')
def device_interface_vlans(device_id: str, session: Session = Depends(get_db)):
    """VLAN всех портов устройства (с учётом «Все VLAN») — для формы устройства; ответ ограничен одним устройством."""
    return get_device_interface_vlans(device_id, session)


@router.get('/{device_id}/subinterfaces')
def device_subinterfaces(device_id: str, session: Session = Depends(get_db)):
    """Подинтерфейсы всех портов устройства (с IP-адресами и открытыми портами) — для формы устройства."""
    return get_device_subinterfaces(device_id, session)


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


@router.get('/options')
def device_options(
    q: str | None = None,
    include: list[str] = Query(default=[]),
    exclude: list[str] = Query(default=[]),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db),
):
    """Устройства для выбора соседа в форме подключения (поиск и страницы, без полного списка устройств).
    include — id устройств, которые вернуть независимо от поиска (текущий сосед); exclude — id, которые не возвращать."""
    return list_device_options(session, q=q, include=include, exclude=exclude, offset=offset, limit=limit)
