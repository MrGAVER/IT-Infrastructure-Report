"""Generic CRUD: список с фильтрами и пагинацией, создание и изменение записей любого ресурса.

Модуль не знает о конкретных моделях: всё особое (порядок строк, обогащение, проверки, побочные действия) берётся из
реестра хуков — см. crud/hooks.py. Новый ресурс с особым поведением правит только реестр, а не этот файл.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session
from ...constants import AuditAction, ErrorCode
from ..integrity import integrity_error_response
from .audit_log import _describe_update, audit, describe_record
from .columns import allowed_columns, model_for
from ..timeutil import to_naive_utc
from .hooks import hooks_for
from .payload import ensure_writable, validate_column_types, validate_payload_schema
from .validators import _release_rack_slot, validate_resource


def _parse_range_datetime(value: str, *, end_of_day: bool) -> datetime:
    """Парсит date_from/date_to для list_resource(). Принимает как чистую дату
    (input[type=date] с фронтенда, 'YYYY-MM-DD'), так и полный ISO datetime.
    Чистая дата в end_of_day-позиции трактуется как конец дня (включительно),
    иначе фильтр 'по 15.08.2026' исключал бы записи, сделанные в течение этого дня."""
    text = value
    if end_of_day and "T" not in value:
        text = f"{value}T23:59:59.999999"
    try:
        # В БД время хранится как naive UTC, а API отдаёт его с «+00:00» (services/timeutil.py): значение со смещением,
        # присланное клиентом обратно (например, created_at записи как граница периода), приводится к UTC без tzinfo —
        # иначе сравнение с колонкой шло бы по тексту со смещением. Чистая дата и время без смещения — как раньше.
        return to_naive_utc(datetime.fromisoformat(text))
    except (ValueError, OverflowError) as exc:
        # OverflowError — не подкласс ValueError: приведение крайней даты со смещением к UTC («0001-01-01T00:00:00+14:00»,
        # «9999-12-31T23:59:59-14:00») выходит за пределы datetime и раньше отвечало 500.
        raise HTTPException(422, f"Некорректная дата: {value}") from exc


def _apply_ordering(stmt, model):
    return stmt.order_by(*hooks_for(model).ordering(model))


def _apply_search(stmt, model, q: str | None):
    """Поиск q: подстрока без учёта регистра по всем текстовым колонкам модели."""
    if not q:
        return stmt
    text_cols = [c for c in inspect(model).columns if str(c.type).upper().startswith(("VARCHAR", "TEXT", "CHAR"))]
    if not text_cols:
        return stmt
    return stmt.where(or_(*[func.lower(c).contains(q.lower(), autoescape=True) for c in text_cols]))  # autoescape: «%» и «_» из поиска — обычные символы, а не шаблон LIKE


def _apply_filters(stmt, model, filters: dict[str, str] | None):
    """Фильтры «поле = значение»; пустое значение означает IS NULL; неизвестное поле — 422."""
    if not filters:
        return stmt
    column_names = {c.key for c in inspect(model).columns}
    for key, value in filters.items():
        if key not in column_names:
            raise HTTPException(422, f"Неизвестное поле фильтра: {key}")
        col = getattr(model, key)
        stmt = stmt.where(col.is_(None)) if value == "" else stmt.where(col == value)
    return stmt


def _apply_date_range(stmt, model, date_from: str | None, date_to: str | None):
    if date_from:
        stmt = stmt.where(model.created_at >= _parse_range_datetime(date_from, end_of_day=False))
    if date_to:
        stmt = stmt.where(model.created_at <= _parse_range_datetime(date_to, end_of_day=True))
    return stmt


def _enrich_rows(model, rows, session: Session):
    return hooks_for(model).enrich_rows(rows, session)


def list_resource(resource: str, session: Session, q: str | None = None, offset: int = 0, limit: int = 100, filters: dict[str, str] | None = None, date_from: str | None = None, date_to: str | None = None):
    model = model_for(resource)
    stmt = _apply_ordering(select(model), model)
    stmt = _apply_search(stmt, model, q)
    stmt = _apply_filters(stmt, model, filters)
    stmt = _apply_date_range(stmt, model, date_from, date_to)
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.offset(offset).limit(limit)).all()
    return {"items": _enrich_rows(model, rows, session), "total": total, "offset": offset, "limit": limit}


@contextmanager
def _translated_write_errors(resource: str, session: Session) -> Iterator[None]:
    """Откат транзакции и перевод ошибок БД при записи: нарушение ограничения → понятный ответ, неподходящее значение → 422."""
    try:
        yield
    except IntegrityError as exc:
        session.rollback()
        raise integrity_error_response(resource, exc) from exc
    except DataError:
        # Значение не подошло колонке (тип/размер) уже в БД: откатываем явно, а не полагаясь на закрытие сессии, и отдаём
        # дальше — main.data_error_handler ответит 422 без текста драйвера.
        session.rollback()
        raise


def create_resource(resource: str, payload: dict[str, Any], session: Session):
    ensure_writable(resource)
    payload = validate_payload_schema(resource, payload, is_update=False)
    model = model_for(resource)
    allowed = allowed_columns(model)
    hooks = hooks_for(model)
    data = {k: v for k, v in payload.items() if k in allowed}
    validate_column_types(model, data)
    hooks.prepare(data, session)
    hooks.validate_create(data, session)
    validate_resource(model, data, session, confirm_duplicate=bool(payload.get("confirm_system_name_duplicate")), confirm_rack_reassign=bool(payload.get("confirm_rack_position_reassign")))
    _release_rack_slot(model, data, session)
    obj = model(**data)
    session.add(obj)
    with _translated_write_errors(resource, session):
        session.flush()
        hooks.after_create(obj, session)
        audit(session, resource, str(obj.id), AuditAction.CREATE, f"Создание записи: {describe_record(obj)}")
        session.commit()
        return hooks.to_dict(obj, session)


_STALE_RECORD_MESSAGE = "Запись изменена другим пользователем. Обновите форму и повторите правку."


def _to_millis(value: datetime) -> datetime:
    """Время с точностью до миллисекунды: JavaScript (Date.toISOString) микросекунды отбрасывает, и клиент, пересобравший строку,
    иначе получал бы ложный конфликт на собственной непротиворечивой записи."""
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def _assert_not_stale(obj: Any, expected: Any) -> None:
    """Оптимистичная блокировка: если клиент прислал expected_updated_at — значение updated_at записи, которое он
    получил при чтении, — а в БД оно уже другое, запись изменил кто-то ещё и тихо затирать его правку нельзя: 409 STALE_RECORD.

    Поле необязательное: без него (старый клиент, скрипт, импорт) поведение прежнее — выигрывает последняя запись. Модель без
    отметки updated_at сверять не с чем, её проверка пропускается. Значение не строка или не дата — 422, а не молчаливый пропуск:
    клиент, который проверку просил, должен узнать, что она не сработала."""
    if expected is None:
        return
    current = getattr(obj, "updated_at", None)
    if current is None:
        return
    if not isinstance(expected, str):
        raise HTTPException(422, "expected_updated_at: ожидается строка с датой и временем ISO 8601")
    if _to_millis(_parse_range_datetime(expected, end_of_day=False)) != _to_millis(current):
        raise HTTPException(409, {"code": ErrorCode.STALE_RECORD, "message": _STALE_RECORD_MESSAGE})


def update_resource(resource: str, item_id: str, payload: dict[str, Any], session: Session):
    ensure_writable(resource)
    payload = validate_payload_schema(resource, payload, is_update=True)
    # with_for_update: на PostgreSQL строка блокируется до commit, и два одновременных PUT выстраиваются в очередь — второй увидит
    # новый updated_at и получит 409, а не пройдёт проверку по старому снимку. SQLite FOR UPDATE игнорирует (запись и так одна за раз).
    model = model_for(resource)
    hooks = hooks_for(model)
    obj = session.get(model, item_id, with_for_update=True)
    if obj is None:
        raise HTTPException(404, "Запись не найдена")
    _assert_not_stale(obj, payload.get("expected_updated_at"))
    allowed = allowed_columns(model)
    before = {k: getattr(obj, k) for k in allowed}
    changes = {k: v for k, v in payload.items() if k in allowed}
    validate_column_types(model, changes)
    proposed = dict(before)
    proposed.update(changes)
    hooks.prepare(proposed, session)
    hooks.validate_update(proposed, before, session, item_id)
    validate_resource(model, proposed, session, item_id, bool(payload.get("confirm_system_name_duplicate")), bool(payload.get("confirm_rack_position_reassign")))
    _release_rack_slot(model, proposed, session, item_id)
    for key, value in payload.items():
        if key in allowed:
            setattr(obj, key, value)
    hooks.apply_derived(obj, proposed)
    with _translated_write_errors(resource, session):
        session.flush()
        notes = hooks.after_update(obj, payload, before, session)
        audit(session, resource, str(obj.id), AuditAction.UPDATE, _describe_update(before, proposed))
        for note in notes:
            audit(session, resource, str(obj.id), AuditAction.UPDATE, note)
        session.commit()
        return hooks.to_dict(obj, session)
