from __future__ import annotations
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import select
from ..db import get_db
from ..models import PhysicalDevice
from ..registry import DISPLAY_NAMES, MODEL_MAP
from ..services.crud import columns_for, create_resource, delete_resource, list_resource, model_for, sync_interfaces, update_resource, get_information_system_details, sync_information_system_details
from ..services.serialization import serialize

router = APIRouter(prefix='/api/v1/resources', tags=['CRUD'])

RESERVED_QUERY_PARAMS = {'q', 'offset', 'limit'}

@router.get('')
def resources():
    return [{'key': k, 'name': DISPLAY_NAMES.get(k, k), 'columns': columns_for(v)} for k, v in MODEL_MAP.items() if k != 'audit-log']

@router.get('/{resource}/schema')
def resource_schema(resource: str):
    model = model_for(resource)
    return {'key': resource, 'name': DISPLAY_NAMES.get(resource, resource), 'columns': columns_for(model)}

@router.get('/{resource}')
def list_endpoint(resource: str, request: Request, q: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000), session: Session = Depends(get_db)):
    # Any query param other than q/offset/limit is treated as an equality filter on that column,
    # e.g. GET /resources/interfaces?physical_device_id=<id> — validated against real model columns
    # in list_resource, so this cannot be used to reach arbitrary attributes.
    filters = {k: v for k, v in request.query_params.items() if k not in RESERVED_QUERY_PARAMS}
    return list_resource(resource, session, q, offset, limit, filters or None)

@router.get('/information-systems/{item_id}/details')
def information_system_details(item_id: str, session: Session = Depends(get_db)):
    return get_information_system_details(item_id, session)

@router.put('/information-systems/{item_id}/details')
def information_system_details_update(item_id: str, payload: dict, session: Session = Depends(get_db)):
    return sync_information_system_details(item_id, payload, session)

@router.get('/{resource}/{item_id}')
def get_endpoint(resource: str, item_id: str, session: Session = Depends(get_db)):
    model = model_for(resource); obj = session.get(model, item_id)
    if not obj: from fastapi import HTTPException; raise HTTPException(404, 'Запись не найдена')
    return serialize(obj)

@router.post('/{resource}', status_code=201)
def create_endpoint(resource: str, payload: dict, session: Session = Depends(get_db)):
    return create_resource(resource, payload, session)

@router.put('/{resource}/{item_id}')
def update_endpoint(resource: str, item_id: str, payload: dict, session: Session = Depends(get_db)):
    return update_resource(resource, item_id, payload, session)

@router.delete('/{resource}/{item_id}')
def delete_endpoint(resource: str, item_id: str, session: Session = Depends(get_db)):
    return delete_resource(resource, item_id, session)

