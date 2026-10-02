from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..db import get_db
from ..services.connection_query import ConnectionQuery, MAX_SEARCH_LENGTH, list_connections
from ..services.connection_review import approve_port_config, revoke_port_config_approval, set_port_role
from ..services.port_config import PortConfigStatus
from ..services.vlan_mode_cascade import apply_vlan_mode_cascade, preview_vlan_mode_cascade

# Записывающие методы защищены общей мидлварью авторизации (viewer получает 403) — отдельной
# проверки роли здесь не нужно.
router = APIRouter(prefix='/api/v1', tags=['Connections'])


@router.get('/connections')
def connections_page(
    q: str | None = Query(None, max_length=MAX_SEARCH_LENGTH),
    is_active: bool | None = None,
    port_config_status: PortConfigStatus | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    session: Session = Depends(get_db),
):
    """Страница подключений для дашборда: поиск, фильтры и статус сверки ролей портов считаются на
    сервере. `total` — под теми же условиями; `summary` — по всем подключениям (счётчики не зависят
    от поиска и фильтров). Каждая запись — как в GET /resources/connections, плюс
    `source_port_role` / `destination_port_role` / `port_config_status`."""
    return list_connections(session, ConnectionQuery(q=q, is_active=is_active, status=port_config_status), offset=offset, limit=limit)


@router.put('/interfaces/{interface_id}/port-role')
def update_port_role(interface_id: str, payload: dict, session: Session = Depends(get_db)):
    return set_port_role(interface_id, payload, session)


@router.post('/interfaces/{interface_id}/vlan-mode-cascade/preview')
def vlan_mode_cascade_preview(interface_id: str, payload: dict, session: Session = Depends(get_db)):
    """Предпросмотр каскадной смены режима порта (access/trunk): затронутые группы и порты, VLAN,
    которые будут сняты, предупреждения о последствиях и hash плана. Ничего не записывает.

    Тело: {mode, edited?}; edited = {device_id, ports: {id: режим}, groups: {id: режим}} — устройство с
    открытой формой и режимы его портов/групп в черновике: его порты и группы только возвращаются в
    плане (deferred), но не записываются. POST, а не GET — состояние формы не помещается в query."""
    return preview_vlan_mode_cascade(interface_id, payload, session)


@router.post('/interfaces/{interface_id}/vlan-mode-cascade')
def vlan_mode_cascade_apply(interface_id: str, payload: dict, session: Session = Depends(get_db)):
    """Применяет план из предпросмотра: тело {mode, edited?, plan_hash, confirm: true} (mode и edited
    те же, что при предпросмотре). Если данные изменились после предпросмотра — 409."""
    return apply_vlan_mode_cascade(interface_id, payload, session)


@router.post('/connections/port-config/approve')
def approve(payload: dict, session: Session = Depends(get_db)):
    return approve_port_config(payload, session)


@router.delete('/connections/{connection_id}/port-config/approval')
def revoke_approval(connection_id: str, session: Session = Depends(get_db)):
    return revoke_port_config_approval(connection_id, session)
