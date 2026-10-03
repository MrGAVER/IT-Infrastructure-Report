"""Хранение правил согласования данных порта (таблица port_sync_rules): создание, правка, удаление,
сброс стандартных правил к исходным, порядок проверки и стартовое заполнение.

Логика самих правил (условия, выбор, проверка введённых значений) — в services/port_sync_rules.py и
не знает про БД; здесь только перевод между строкой таблицы и RuleSpec, уникальность названия,
защита стандартных правил от удаления и запись в журнал аудита.

Стандартные правила (DEFAULT_RULES) создаёт ensure_default_rules() при старте приложения — по
устойчивому `code`, идемпотентно. Администратор может менять их так же, как свои (условия, действие,
порядок, «включено»), поэтому заполнение НЕ перезаписывает существующую строку: изменённое правило
остаётся изменённым, пока его не сбросят явно (reset_rule). Удалить стандартное правило нельзя —
его отключают: так «все текущие правила» всегда на месте и их можно вернуть.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..models import PortSyncRule
from .crud import audit
from .port_sync_rules import (
    DEFAULT_RULES,
    DEFAULT_RULES_BY_CODE,
    RuleSpec,
    RuleValidationError,
    Side,
    rule_from_payload,
    rules_equal_ignoring_state,
    sort_rules,
)

ENTITY = "port-sync-rules"
PRIORITY_STEP = 10

_FIELD_LABELS = {
    "name": "название",
    "description": "описание",
    "enabled": "включено",
    "priority": "порядок",
    "action": "действие",
    "target": "условия целевого порта",
    "source": "условия порта-источника",
    "relation": "отношение портов",
    "apply_role": "применять роль",
    "apply_mode": "применять режим",
    "vlan_policy": "политика VLAN",
}


# --- строка таблицы ↔ RuleSpec ------------------------------------------------------------------


def row_to_spec(row: PortSyncRule) -> RuleSpec:
    return RuleSpec(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description or "",
        enabled=row.enabled,
        priority=row.priority,
        action=row.action,
        target=Side(row.target_role, row.target_mode, row.target_vlans),
        source=Side(row.source_role, row.source_mode, row.source_vlans),
        relation=Side(row.rel_role, row.rel_mode, row.rel_vlans),
        apply_role=row.apply_role,
        apply_mode=row.apply_mode,
        vlan_policy=row.vlan_policy,
    )


def _write_spec(row: PortSyncRule, spec: RuleSpec) -> None:
    row.name = spec.name
    row.description = spec.description
    row.enabled = spec.enabled
    row.priority = spec.priority
    row.action = spec.action
    row.target_role, row.target_mode, row.target_vlans = spec.target.role, spec.target.mode, spec.target.vlans
    row.source_role, row.source_mode, row.source_vlans = spec.source.role, spec.source.mode, spec.source.vlans
    row.rel_role, row.rel_mode, row.rel_vlans = spec.relation.role, spec.relation.mode, spec.relation.vlans
    row.apply_role, row.apply_mode, row.vlan_policy = spec.apply_role, spec.apply_mode, spec.vlan_policy


def _side_dict(side: Side) -> dict[str, str]:
    return {"role": side.role, "mode": side.mode, "vlans": side.vlans}


def spec_to_dict(spec: RuleSpec) -> dict[str, Any]:
    """Правило в форме API (то же, что принимают POST/PUT) плюс служебные поля."""
    default = DEFAULT_RULES_BY_CODE.get(spec.code) if spec.code else None
    return {
        "id": spec.id,
        "code": spec.code,
        "builtin": spec.code is not None,
        # Изменено ли стандартное правило относительно исходного — для пометки и кнопки «Сбросить».
        "modified": default is not None and not rules_equal_ignoring_state(spec, default),
        "name": spec.name,
        "description": spec.description,
        "enabled": spec.enabled,
        "priority": spec.priority,
        "action": spec.action,
        "target": _side_dict(spec.target),
        "source": _side_dict(spec.source),
        "relation": _side_dict(spec.relation),
        "apply": {"role": spec.apply_role, "mode": spec.apply_mode, "vlans": spec.vlan_policy},
    }


def serialize_rule(row: PortSyncRule) -> dict[str, Any]:
    data = spec_to_dict(row_to_spec(row))
    data["created_at"] = row.created_at.isoformat() if row.created_at else None
    data["updated_at"] = row.updated_at.isoformat() if row.updated_at else None
    return data


# --- чтение -------------------------------------------------------------------------------------


def _ordered_rows(session: Session) -> list[PortSyncRule]:
    return list(session.scalars(select(PortSyncRule).order_by(PortSyncRule.priority, PortSyncRule.id)).all())


def list_rules(session: Session) -> dict[str, Any]:
    items = [serialize_rule(row) for row in _ordered_rows(session)]
    return {"items": items, "total": len(items)}


def load_specs(session: Session, *, only_enabled: bool = True) -> list[RuleSpec]:
    """Правила в порядке проверки — вход для decide()."""
    specs = [row_to_spec(row) for row in _ordered_rows(session)]
    return sort_rules(s for s in specs if s.enabled or not only_enabled)


def get_rule(rule_id: str, session: Session) -> PortSyncRule:
    row = session.get(PortSyncRule, rule_id)
    if row is None:
        raise HTTPException(404, "Правило не найдено")
    return row


# --- запись -------------------------------------------------------------------------------------


def _parse(payload: Any, *, base: RuleSpec | None = None) -> RuleSpec:
    try:
        return rule_from_payload(payload, base=base)
    except RuleValidationError as error:
        raise HTTPException(422, str(error)) from error


def _ensure_unique_name(session: Session, name: str, *, exclude_id: str | None = None) -> None:
    stmt = select(PortSyncRule.id).where(func.lower(PortSyncRule.name) == name.lower())
    if exclude_id is not None:
        stmt = stmt.where(PortSyncRule.id != exclude_id)
    if session.scalar(stmt) is not None:
        raise HTTPException(409, f"Правило с названием «{name}» уже есть")


def _next_priority(session: Session) -> int:
    top = session.scalar(select(func.max(PortSyncRule.priority)))
    return (top if top is not None else 0) + PRIORITY_STEP


def _changed_fields(before: RuleSpec, after: RuleSpec) -> list[str]:
    return [label for key, label in _FIELD_LABELS.items() if getattr(before, key) != getattr(after, key)]


def create_rule(payload: Any, session: Session) -> dict[str, Any]:
    """Создаёт пользовательское правило. Без `priority` оно встаёт в конец списка проверки."""
    spec = _parse(payload)
    if isinstance(payload, dict) and "priority" not in payload:
        spec = replace(spec, priority=_next_priority(session))
    _ensure_unique_name(session, spec.name)
    row = PortSyncRule()
    _write_spec(row, spec)
    session.add(row)
    session.flush()
    audit(session, ENTITY, row.id, AuditAction.CREATE, f"Создано правило согласования портов «{row.name}» (действие: {row.action})")
    session.commit()
    return serialize_rule(row)


def update_rule(rule_id: str, payload: Any, session: Session) -> dict[str, Any]:
    """Частичное обновление: переданные поля заменяют текущие, остальные сохраняются. Работает и для
    стандартных правил; `code` и признак «стандартное» изменить нельзя."""
    row = get_rule(rule_id, session)
    before = row_to_spec(row)
    after = _parse(payload, base=before)
    _ensure_unique_name(session, after.name, exclude_id=row.id)
    changed = _changed_fields(before, after)
    if not changed:
        return serialize_rule(row)
    _write_spec(row, after)
    session.flush()
    audit(session, ENTITY, row.id, AuditAction.UPDATE, f"Изменено правило согласования портов «{row.name}»: {', '.join(changed)}")
    session.commit()
    return serialize_rule(row)


def delete_rule(rule_id: str, session: Session) -> None:
    row = get_rule(rule_id, session)
    if row.code is not None:
        raise HTTPException(409, "Стандартное правило нельзя удалить — отключите его (при необходимости его можно сбросить к исходному виду)")
    name = row.name
    session.delete(row)
    audit(session, ENTITY, rule_id, AuditAction.DELETE, f"Удалено правило согласования портов «{name}»")
    session.commit()


def reset_rule(rule_id: str, session: Session) -> dict[str, Any]:
    """Возвращает стандартное правило к исходному виду: условия, действие, описание, порядок, «включено»."""
    row = get_rule(rule_id, session)
    default = DEFAULT_RULES_BY_CODE.get(row.code) if row.code else None
    if default is None:
        raise HTTPException(409, "Сбросить можно только стандартное правило")
    # Исходное название могло быть занято пользовательским правилом после переименования стандартного.
    _ensure_unique_name(session, default.name, exclude_id=row.id)
    _write_spec(row, default)
    session.flush()
    audit(session, ENTITY, row.id, AuditAction.UPDATE, f"Стандартное правило согласования портов «{row.name}» сброшено к исходному виду")
    session.commit()
    return serialize_rule(row)


def reorder_rules(ids: Any, session: Session) -> dict[str, Any]:
    """Задаёт порядок проверки: `ids` — ВСЕ правила в нужном порядке (каждое ровно один раз).
    Приоритеты переписываются как 10, 20, 30… — между ними остаётся место для правки вручную."""
    rows = _ordered_rows(session)
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise HTTPException(422, "Поле ids должно быть массивом идентификаторов правил")
    if len(set(ids)) != len(ids) or set(ids) != {row.id for row in rows}:
        raise HTTPException(422, "Передайте все правила, каждое ровно один раз")
    by_id = {row.id: row for row in rows}
    changed = False
    for position, rule_id in enumerate(ids, start=1):
        wanted = position * PRIORITY_STEP
        if by_id[rule_id].priority != wanted:
            by_id[rule_id].priority = wanted
            changed = True
    if changed:
        session.flush()
        audit(session, ENTITY, "order", AuditAction.UPDATE, "Изменён порядок проверки правил согласования портов")
        session.commit()
    return list_rules(session)


# --- стартовое заполнение ----------------------------------------------------------------------


def ensure_default_rules(session: Session) -> int:
    """Добавляет отсутствующие стандартные правила (по `code`). Существующие строки не трогает —
    администратор мог их изменить. Возвращает, сколько правил добавлено."""
    existing = set(session.scalars(select(PortSyncRule.code).where(PortSyncRule.code.is_not(None))).all())
    taken_names = {name.lower() for name in session.scalars(select(PortSyncRule.name)).all()}
    added = 0
    for default in DEFAULT_RULES:
        if default.code in existing:
            continue
        spec = default
        if spec.name.lower() in taken_names:
            # Название успели занять пользовательским правилом — стандартное не должно упасть на
            # уникальности и не должно пропасть, поэтому получает пометку в названии.
            spec = replace(spec, name=f"{spec.name} (стандартное)")
        row = PortSyncRule(code=spec.code)
        _write_spec(row, spec)
        session.add(row)
        taken_names.add(spec.name.lower())
        added += 1
    if added:
        session.commit()
    return added


def rules_for_reconcile(session: Session, rule_id: str | None) -> Sequence[RuleSpec]:
    """Правила для проверки: все включённые в порядке приоритета либо одно указанное (даже если
    оно отключено — чтобы можно было посмотреть, что сделает правило, до его включения)."""
    if rule_id is None:
        return load_specs(session)
    return [row_to_spec(get_rule(rule_id, session))]
