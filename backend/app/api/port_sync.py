from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import port_sync_reconcile as reconcile
from ..services import port_sync_store as store

# Правила автоматического согласования данных порта (services/port_sync_rules.py) и их хранение.
# Изменяющие запросы доступны только администратору — общая проверка роли по методу (auth_gate_middleware).
router = APIRouter(prefix='/api/v1/port-sync', tags=['PortSync'])


@router.get('/rules')
def list_rules(session: Session = Depends(get_db)):
    """Все правила в порядке проверки (по возрастанию приоритета), включая отключённые."""
    return store.list_rules(session)


@router.post('/rules', status_code=201)
def create_rule(payload: Any = Body(...), session: Session = Depends(get_db)):
    """Новое пользовательское правило; без `priority` встаёт в конец списка проверки."""
    return store.create_rule(payload, session)


@router.post('/rules/reorder')
def reorder_rules(payload: Any = Body(...), session: Session = Depends(get_db)):
    """Порядок проверки: `{"ids": [...]}` — все правила в нужном порядке."""
    ids = payload.get('ids') if isinstance(payload, dict) else None
    return store.reorder_rules(ids, session)


@router.put('/rules/{rule_id}')
def update_rule(rule_id: str, payload: Any = Body(...), session: Session = Depends(get_db)):
    """Частичное обновление правила, в том числе стандартного (переданные поля заменяют текущие)."""
    return store.update_rule(rule_id, payload, session)


@router.delete('/rules/{rule_id}', status_code=204)
def delete_rule(rule_id: str, session: Session = Depends(get_db)):
    """Удаляет пользовательское правило; стандартное — 409 (его можно отключить)."""
    store.delete_rule(rule_id, session)


@router.post('/rules/{rule_id}/reset')
def reset_rule(rule_id: str, session: Session = Depends(get_db)):
    """Возвращает стандартное правило к исходному виду."""
    return store.reset_rule(rule_id, session)


@router.post('/preview')
def preview(payload: Any = Body(default_factory=dict), session: Session = Depends(get_db)):
    """План согласования портов по правилам — ничего не записывает. `{connection_ids?, rule_id?}`:
    без списка — все активные подключения с неодобренным расхождением."""
    return reconcile.preview_reconcile(payload, session)


@router.post('/apply')
def apply(payload: Any = Body(...), session: Session = Depends(get_db)):
    """Применяет план к данным (одна транзакция). Нужны `confirm: true` и `plan_hash` из предпросмотра;
    если данные изменились после предпросмотра — 409."""
    return reconcile.apply_reconcile(payload, session)
