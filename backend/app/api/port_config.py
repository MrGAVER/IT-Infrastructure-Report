from __future__ import annotations
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from ..db import get_db
from ..services.connection_query import ConnectionQuery, MAX_SEARCH_LENGTH, list_connections
from ..services.connection_review import approve_port_config, preview_port_config, revoke_port_config_approval, set_port_role
from ..services.port_config import PortConfigStatus
from ..services.port_edit import set_port_config
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


@router.put('/interfaces/{interface_id}/port-config')
def update_port_config(interface_id: str, payload: dict, session: Session = Depends(get_db)):
    """Правка порта с дашборда: роль и/или набор VLAN одной операцией. Тело: {role?, vlan_ids?, mode?} —
    vlan_ids это ПОЛНЫЙ набор (id записей справочника VLAN); mode — не смена режима, а проверка, что набор
    выбран для текущего режима порта (иначе 409). Когда меняется и режим, роль и VLAN передаются в поле `port`
    каскада ниже — тогда режим, роль и VLAN записываются одной транзакцией."""
    return set_port_config(interface_id, payload, session)


@router.post('/interfaces/{interface_id}/vlan-mode-cascade/preview')
def vlan_mode_cascade_preview(interface_id: str, payload: dict, session: Session = Depends(get_db)):
    """Предпросмотр каскадной смены режима порта (access/trunk): затронутые группы и порты, VLAN,
    которые будут сняты, предупреждения о последствиях и hash плана. Ничего не записывает.

    Тело: {mode, edited?}. edited — снимок формы устройства с открытой формой: {device_id,
    ports: {id: {mode, group?, vlan_ids?, name?}}, groups: {ключ: {mode, vlan_ids?, name?}}} — режим,
    группа (ключ; null — вне групп), VLAN и имя порта и группы в ЧЕРНОВИКЕ, включая новые несохранённые
    группы (временный ключ). Порты и группы этого устройства только возвращаются в плане (deferred), но
    не записываются; не переданное берётся из БД. POST, а не GET — состояние формы не помещается в query.

    port: {role?, vlan_ids?} — роль и ПОЛНЫЙ набор VLAN порта-инициатора (окно правки порта на дашборде): они
    проверяются под целевой режим уже здесь и записываются вместе с каскадом (см. apply). С edited не сочетается."""
    return preview_vlan_mode_cascade(interface_id, payload, session)


@router.post('/interfaces/{interface_id}/vlan-mode-cascade')
def vlan_mode_cascade_apply(interface_id: str, payload: dict, session: Session = Depends(get_db)):
    """Применяет план из предпросмотра: тело {mode, edited?, port?, plan_hash, confirm: true} (mode, edited и
    port те же, что при предпросмотре). Если данные изменились после предпросмотра — 409. С `port` режим со
    всей областью каскада, роль и набор VLAN порта-инициатора записываются ОДНОЙ транзакцией (`port_written`
    в ответе); ошибка в роли или VLAN не оставляет ничего записанным, в том числе режима."""
    return apply_vlan_mode_cascade(interface_id, payload, session)


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
