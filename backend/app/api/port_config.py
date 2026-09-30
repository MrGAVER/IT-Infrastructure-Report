from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..db import get_db
from ..services.connection_review import approve_port_config, find_port_config_mismatches, revoke_port_config_approval, set_port_role
from ..services.port_config import PortConfigStatus

# Записывающие методы защищены общей мидлварью авторизации (viewer получает 403) — отдельной
# проверки роли здесь не нужно.
router = APIRouter(prefix='/api/v1', tags=['Port config'])


@router.put('/interfaces/{interface_id}/port-role')
def update_port_role(interface_id: str, payload: dict, session: Session = Depends(get_db)):
    return set_port_role(interface_id, payload, session)


@router.get('/connections/port-config')
def port_config_review(status: PortConfigStatus = PortConfigStatus.MISMATCH, session: Session = Depends(get_db)):
    items = find_port_config_mismatches(session, statuses=(status,))
    return {'items': items, 'total': len(items)}


@router.post('/connections/port-config/approve')
def approve(payload: dict, session: Session = Depends(get_db)):
    return approve_port_config(payload, session)


@router.delete('/connections/{connection_id}/port-config/approval')
def revoke_approval(connection_id: str, session: Session = Depends(get_db)):
    return revoke_port_config_approval(connection_id, session)
