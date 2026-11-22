"""Метаданные ресурсов: какая модель стоит за ключом ресурса и какие колонки в неё можно писать."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.inspection import inspect
from ...models import Connection, InformationSystem
from ...registry import MODEL_MAP


def model_for(resource: str):
    try:
        return MODEL_MAP[resource]
    except KeyError as exc:
        raise HTTPException(404, f"Ресурс '{resource}' не найден") from exc


def _static_default(column) -> str | None:
    """Значение по умолчанию как строка — только для постоянных значений. У вычисляемых умолчаний (`default=lambda: ...`,
    `utcnow_naive`) у `default.arg` нет осмысленного текста: `str()` давал `<function ... at 0x7f…>` — имя внутренней
    функции и адрес в памяти процесса. Для них отдаём `null` (ключ `default` в ответе остаётся)."""
    default = column.default
    if default is None or default.is_callable:
        return None
    return str(default.arg)


def columns_for(model):
    return [
        {
            "name": c.key,
            "type": str(c.type),
            "nullable": c.nullable,
            "primary_key": c.primary_key,
            "default": _static_default(c),
            "foreign_key": next(iter(c.foreign_keys)).target_fullname if c.foreign_keys else None,
        }
        for c in inspect(model).columns
    ]


def allowed_columns(model) -> set[str]:
    allowed = {c.key for c in inspect(model).columns if c.key not in {"id", "created_at", "updated_at"}}
    if model is InformationSystem:
        allowed.discard("number")
    # Одобрение расхождения ролей портов пишется только эндпоинтами services/connection_review.py:
    # иначе клиент мог бы «одобрить» подключение произвольной строкой в обход проверки статуса.
    if model is Connection:
        allowed.discard("port_config_approved_signature")
    return allowed
