from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import port_sync_reconcile as reconcile
from ..services import port_sync_store as store
from ..services.port_sync_plan_cache import plan_cache

# Правила автоматического согласования данных порта (services/port_sync_rules.py) и их хранение.
# Изменяющие запросы доступны только администратору — общая проверка роли по методу (AuthGateMiddleware).
router = APIRouter(prefix="/api/v1/port-sync", tags=["PortSync"])


@router.get("/rules")
def list_rules(session: Session = Depends(get_db)):
    """Все правила в порядке проверки (по возрастанию приоритета), включая отключённые."""
    return store.list_rules(session)


@router.post("/rules", status_code=201)
def create_rule(payload: Any = Body(...), session: Session = Depends(get_db)):
    """Новое пользовательское правило; без `priority` встаёт в конец списка проверки."""
    rule = store.create_rule(payload, session)
    plan_cache.clear()  # правила изменились — снимки планов в кэше устарели
    return rule


@router.post("/rules/reorder")
def reorder_rules(payload: Any = Body(...), session: Session = Depends(get_db)):
    """Порядок проверки: `{"ids": [...]}` — все правила в нужном порядке."""
    ids = payload.get("ids") if isinstance(payload, dict) else None
    result = store.reorder_rules(ids, session)
    plan_cache.clear()
    return result


@router.put("/rules/{rule_id}")
def update_rule(rule_id: str, payload: Any = Body(...), session: Session = Depends(get_db)):
    """Частичное обновление правила, в том числе стандартного (переданные поля заменяют текущие)."""
    rule = store.update_rule(rule_id, payload, session)
    plan_cache.clear()
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(rule_id: str, session: Session = Depends(get_db)):
    """Удаляет пользовательское правило; стандартное — 409 (его можно отключить)."""
    store.delete_rule(rule_id, session)
    plan_cache.clear()


@router.post("/rules/{rule_id}/reset")
def reset_rule(rule_id: str, session: Session = Depends(get_db)):
    """Возвращает стандартное правило к исходному виду."""
    rule = store.reset_rule(rule_id, session)
    plan_cache.clear()
    return rule


@router.post("/preview")
def preview(payload: Any = Body(default_factory=dict), session: Session = Depends(get_db)):
    """План согласования портов по правилам — ничего не записывает. `{connection_ids?, rule_id?, offset?, limit?,
    plan_hash?}`: без списка — все активные подключения с неодобренным расхождением. Элементы плана — страницами
    (`page` в ответе); следующие страницы запрашиваются с `plan_hash` первой и берутся из кэша без пересчёта."""
    return reconcile.preview_reconcile(payload, session)


@router.post("/apply")
def apply(payload: Any = Body(...), session: Session = Depends(get_db)):
    """Применяет план к данным (одна транзакция). Нужны `confirm: true` и `plan_hash` из предпросмотра;
    если данные изменились после предпросмотра — 409."""
    return reconcile.apply_reconcile(payload, session)
