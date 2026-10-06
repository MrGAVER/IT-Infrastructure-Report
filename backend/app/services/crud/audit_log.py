"""Запись в журнал аудита и человекочитаемое описание изменений (кто — см. services/actor_context.py)."""
from __future__ import annotations

from typing import Any
from sqlalchemy.orm import Session
from ...models import AuditLog
from ..actor_context import Actor, current_actor


def audit(session: Session, entity_type: str, entity_id: str, action: str, details: str = '', actor: Actor | None = None) -> None:
    """Запись в журнал аудита. Автор берётся из actor, а если он не передан — из current_actor, который
    выставляет auth_gate_middleware на время запроса (см. services/actor_context.py): так записи
    отвечают на вопрос «кто это сделал» без изменения сигнатур десятков вызывающих функций. Явный actor
    нужен там, где запрос ещё анонимен, а действие уже принадлежит пользователю (вход)."""
    if entity_type == 'audit-log': return
    who = actor or current_actor.get()
    session.add(AuditLog(entity_type=entity_type, entity_id=entity_id, action=action, details=details, actor_id=who.user_id, actor_username=who.username, actor_ip=who.ip))


def _fmt_audit_value(value: Any) -> str:
    """Короткое читаемое представление значения поля для diff'а в audit-log — не сериализация
    для API (см. serialize()), только текст в одну строку. None и '' показываются одинаково
    ('—') — иначе None → '' выглядело бы как изменение, хотя по сути и то, и то "не заполнено".
    Длинные значения (например, текст описания ИС) обрезаются — иначе правка одного длинного
    текстового поля раздувала бы запись журнала на весь текст целиком."""
    if value is None or value == '':
        return '—'
    if isinstance(value, bool):
        return 'да' if value else 'нет'
    text = str(value)
    return text if len(text) <= 60 else text[:57] + '…'


def _describe_update(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Человекочитаемый diff изменённых полей для audit-log: 'поле: старое → новое', через '; '.
    Раньше update_resource писал в audit-log одну и ту же строку 'Изменение записи' на любое
    изменение ЛЮБОЙ из ~40 сущностей реестра — колонка "Детали" в журнале аудита дублировала
    колонку "Действие" (там уже был бейдж "Изменено"), не добавляя ни одного факта о том, что
    именно изменилось (найдено при ревизии фронтенда на предмет неинформативных технических
    записей, показываемых пользователю). Сравнение по allowed_columns() модели — единый
    механизм для всех ресурсов без хардкода полей под конкретную модель, в отличие от ручного
    списка changes в services/auth.py:update_user (там модель всегда одна — User).
    Сортировка по строке diff'а, а не порядок allowed_columns() (это set(), не гарантированно
    стабильный порядок) — для детерминированного и читаемого результата."""
    changes = sorted(
        f'{key}: {_fmt_audit_value(before[key])} → {_fmt_audit_value(after[key])}'
        for key in after if before.get(key) != after.get(key)
    )
    return '; '.join(changes) if changes else 'Изменение записи (переданные значения совпадают с текущими)'
