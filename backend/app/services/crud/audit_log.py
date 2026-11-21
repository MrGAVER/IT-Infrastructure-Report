"""Запись в журнал аудита и человекочитаемое описание изменений (кто — см. services/actor_context.py)."""

from __future__ import annotations

import re
from typing import Any
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from ...models import AuditLog
from ..actor_context import Actor, current_actor
from .columns import allowed_columns


def audit(session: Session, entity_type: str, entity_id: str, action: str, details: str = "", actor: Actor | None = None) -> None:
    """Запись в журнал аудита. Автор берётся из actor, а если он не передан — из current_actor, который
    выставляет AuthGateMiddleware на время запроса (см. services/actor_context.py): так записи
    отвечают на вопрос «кто это сделал» без изменения сигнатур десятков вызывающих функций. Явный actor
    нужен там, где запрос ещё анонимен, а действие уже принадлежит пользователю (вход)."""
    if entity_type == "audit-log":
        return
    who = actor or current_actor.get()
    session.add(AuditLog(entity_type=entity_type, entity_id=entity_id, action=action, details=details, actor_id=who.user_id, actor_username=who.username, actor_ip=who.ip))


def _fmt_audit_value(value: Any) -> str:
    """Короткое читаемое представление значения поля для diff'а в audit-log — не сериализация
    для API (см. serialize()), только текст в одну строку. None и '' показываются одинаково
    ('—') — иначе None → '' выглядело бы как изменение, хотя по сути и то, и то "не заполнено".
    Длинные значения (например, текст описания ИС) обрезаются — иначе правка одного длинного
    текстового поля раздувала бы запись журнала на весь текст целиком."""
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    text = str(value)
    return text if len(text) <= 60 else text[:57] + "…"


def _describe_update(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Человекочитаемый diff изменённых полей для audit-log: 'поле: старое → новое', через '; '.
    Раньше update_resource писал в audit-log одну и ту же строку 'Изменение записи' на любое
    изменение ЛЮБОЙ из ~40 сущностей реестра — колонка "Детали" в журнале аудита дублировала
    колонку "Действие" (там уже был бейдж "Изменено"), не добавляя ни одного факта о том, что
    именно изменилось (найдено при ревизии фронтенда на предмет неинформативных технических
    записей, показываемых пользователю). Сравнение по allowed_columns() модели — единый
    механизм для всех ресурсов без хардкода полей под конкретную модель, в отличие от ручного
    списка changes в services/auth/users.py:update_user (там модель всегда одна — User).
    Сортировка по строке diff'а, а не порядок allowed_columns() (это set(), не гарантированно
    стабильный порядок) — для детерминированного и читаемого результата."""
    changes = sorted(f"{key}: {_fmt_audit_value(before[key])} → {_fmt_audit_value(after[key])}" for key in after if before.get(key) != after.get(key))
    return "; ".join(changes) if changes else "Изменение записи (переданные значения совпадают с текущими)"


# Поля, которыми запись узнают в журнале, по убыванию приоритета: у большинства справочников это name,
# у устройства — серийный номер и системное имя, у VLAN — имя и номер, у IP-адреса — сам адрес.
# Список общий для всех ресурсов (без хардкода под модель, как и в _describe_update).
_IDENTITY_FIELDS = ("name", "title", "serial_number", "system_name", "username", "vlan_id", "ip_address")
_MAX_IDENTITY_FIELDS = 5
_MAX_FALLBACK_FIELDS = 3  # у записей без «имени» (подключение, связи ИС) — первые заполненные колонки, чтобы строка не была пустой
# В реестре секретных колонок нет (проверено поиском по моделям), но журнал — архив, который выгружают в CSV/Excel
# и хранят годами: новая колонка с паролем или токеном не должна попасть в него молча, поэтому такие имена
# отсекаются по шаблону.
_SECRET_KEY = re.compile(r"password|passphrase|secret|token|community|credential|api_?key", re.IGNORECASE)
_NO_FILLED_FIELDS = "без заполненных полей"


def describe_record(obj: Any, max_len: int = 300) -> str:
    """Короткое описание записи для журнала аудита: «name: Коммутатор-1; serial_number: SN123» — чтобы по CREATE/DELETE было видно, ЧТО
    создали или удалили (id записи — UUID, после удаления по нему ничего не найти).

    Берутся поля из _IDENTITY_FIELDS (не больше _MAX_IDENTITY_FIELDS), а если у модели их нет — первые заполненные колонки. Значения
    форматирует _fmt_audit_value (обрезка до 60 знаков, None и '' — «—»), переводы строк схлопываются в пробелы, итог не длиннее max_len.
    Пустые поля и поля с секретными именами в описание не попадают. Для удаления вызывать ДО session.delete(obj): у удалённого
    объекта атрибуты уже недоступны.

    Пример: describe_record(device) → 'serial_number: SN123; system_name: srv-205'."""
    if max_len < 2:
        raise ValueError("max_len должен быть не меньше 2")
    model = type(obj)
    allowed = allowed_columns(model)
    ordered = [c.key for c in inspect(model).columns if c.key in allowed and not _SECRET_KEY.search(c.key)]
    filled = [key for key in ordered if _fmt_audit_value(getattr(obj, key, None)) != "—"]
    keys = [key for key in _IDENTITY_FIELDS if key in filled][:_MAX_IDENTITY_FIELDS] or filled[:_MAX_FALLBACK_FIELDS]
    text = "; ".join(f"{key}: {_fmt_audit_value(getattr(obj, key))}" for key in keys) or _NO_FILLED_FIELDS
    text = " ".join(text.split())
    return text if len(text) <= max_len else text[: max_len - 1] + "…"
