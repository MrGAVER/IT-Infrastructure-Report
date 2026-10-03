from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..db import get_db
from ..services.connection_query import ConnectionQuery, MAX_SEARCH_LENGTH, list_connections
from ..services.connection_review import approve_port_config, preview_port_config, revoke_port_config_approval, set_port_role
from ..services.port_config import PortConfigStatus

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


@router.get('/connections/port-config/preview')
def preview(
    source_interface_id: str = Query(..., max_length=64),
    destination_interface_id: str = Query(..., max_length=64),
    connection_id: str | None = Query(None, max_length=64),
    is_active: bool = True,
    session: Session = Depends(get_db),
):
    """Статус сверки конфигурации пары портов (роль, режим, VLAN) до сохранения подключения — для
    предупреждения в форме. С `connection_id` учитывает одобрение этого подключения."""
    return preview_port_config(source_interface_id, destination_interface_id, session, connection_id=connection_id, is_active=is_active)


@router.post('/connections/port-config/approve')
def approve(payload: dict, session: Session = Depends(get_db)):
    return approve_port_config(payload, session)


@router.delete('/connections/{connection_id}/port-config/approval')
def revoke_approval(connection_id: str, session: Session = Depends(get_db)):
    return revoke_port_config_approval(connection_id, session)
