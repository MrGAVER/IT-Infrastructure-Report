from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import InformationSystem
from ..registry import DISPLAY_NAMES, MODEL_MAP
from ..services.auth import require_admin_if_auth_enabled
from ..services.crud import columns_for, create_resource, delete_resource, list_resource, model_for, update_resource, get_information_system_details, sync_information_system_details
from ..services.serialization import serialize
from .resource_schemas import InformationSystemDetailsUpdate, ResourceBody

router = APIRouter(prefix='/api/v1/resources', tags=['CRUD'])

RESERVED_QUERY_PARAMS = {'q', 'offset', 'limit', 'date_from', 'date_to'}

# Ресурсы generic-роутера, которые при включённой аутентификации читает только администратор. Журнал аудита
# (имена пользователей, IP-адреса, неудачные входы) есть и в MODEL_MAP, а зависимость require_admin_if_auth_enabled
# висит лишь на выделенном роутере /api/v1/audit-log, — без этой проверки viewer читал бы журнал здесь.
# Запись в такие ресурсы закрыта отдельно: роль viewer не пишет вовсе, а audit-log ещё и в registry.READONLY_RESOURCES.
ADMIN_ONLY_RESOURCES = frozenset({'audit-log'})

def _guard(resource: str, request: Request) -> None:
    """Проверка роли выполняется раньше поиска ресурса и записи: по коду ответа нельзя понять, есть ли запись."""
    if resource in ADMIN_ONLY_RESOURCES:
        require_admin_if_auth_enabled(request)

@router.get('')
def resources():
    return [{'key': k, 'name': DISPLAY_NAMES.get(k, k), 'columns': columns_for(v)} for k, v in MODEL_MAP.items() if k not in ADMIN_ONLY_RESOURCES]

@router.get('/{resource}/schema')
def resource_schema(resource: str, request: Request):
    _guard(resource, request)
    model = model_for(resource)
    return {'key': resource, 'name': DISPLAY_NAMES.get(resource, resource), 'columns': columns_for(model)}

@router.get('/{resource}')
def list_endpoint(resource: str, request: Request, q: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000), date_from: str | None = None, date_to: str | None = None, session: Session = Depends(get_db)):
    _guard(resource, request)
    # Any query param other than q/offset/limit/date_from/date_to is treated as an equality filter
    # on that column, e.g. GET /resources/interfaces?physical_device_id=<id> — validated against
    # real model columns in list_resource, so this cannot be used to reach arbitrary attributes.
    filters = {k: v for k, v in request.query_params.items() if k not in RESERVED_QUERY_PARAMS}
    return list_resource(resource, session, q, offset, limit, filters or None, date_from, date_to)

@router.get('/information-systems/{item_id}/details')
def information_system_details(item_id: str, session: Session = Depends(get_db)):
    return get_information_system_details(item_id, session)

def _existing_information_system(item_id: str, session: Session = Depends(get_db)) -> None:
    """404 для неизвестной ИС — зависимостью, раньше разбора тела: порядок «сначала 404, потом 422 про тело» остался прежним."""
    if not session.get(InformationSystem, item_id):
        raise HTTPException(404, 'Информационная система не найдена')

@router.put('/information-systems/{item_id}/details', dependencies=[Depends(_existing_information_system)])
def information_system_details_update(item_id: str, body: InformationSystemDetailsUpdate, session: Session = Depends(get_db)):
    """Заменяет связанные данные ИС (подразделения, протоколы, размещение, источники) переданными списками."""
    return sync_information_system_details(item_id, body.model_dump(), session)

@router.get('/{resource}/{item_id}')
def get_endpoint(resource: str, item_id: str, request: Request, session: Session = Depends(get_db)):
    _guard(resource, request)
    model = model_for(resource); obj = session.get(model, item_id)
    if not obj: raise HTTPException(404, 'Запись не найдена')
    return serialize(obj)

@router.post('/{resource}', status_code=201)
def create_endpoint(resource: str, payload: ResourceBody, session: Session = Depends(get_db)):
    """Создаёт запись ресурса {resource}."""
    return create_resource(resource, payload, session)

@router.put('/{resource}/{item_id}')
def update_endpoint(resource: str, item_id: str, payload: ResourceBody, session: Session = Depends(get_db)):
    """Изменяет запись ресурса {resource}: меняются только присланные поля."""
    return update_resource(resource, item_id, payload, session)

@router.delete('/{resource}/{item_id}')
def delete_endpoint(resource: str, item_id: str, session: Session = Depends(get_db)):
    return delete_resource(resource, item_id, session)

