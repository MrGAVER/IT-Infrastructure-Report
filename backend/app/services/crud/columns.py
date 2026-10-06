"""Метаданные ресурсов: какая модель стоит за ключом ресурса и какие колонки в неё можно писать."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.inspection import inspect
from ...models import Connection, InformationSystem
from ...registry import MODEL_MAP


def model_for(resource: str):
    try: return MODEL_MAP[resource]
    except KeyError as exc: raise HTTPException(404, f"Ресурс '{resource}' не найден") from exc


def columns_for(model):
    return [{'name': c.key, 'type': str(c.type), 'nullable': c.nullable, 'primary_key': c.primary_key, 'default': None if c.default is None else str(c.default.arg), 'foreign_key': next(iter(c.foreign_keys)).target_fullname if c.foreign_keys else None} for c in inspect(model).columns]


def allowed_columns(model) -> set[str]:
    allowed = {c.key for c in inspect(model).columns if c.key not in {'id', 'created_at', 'updated_at'}}
    if model is InformationSystem: allowed.discard('number')
    # Одобрение расхождения ролей портов пишется только эндпоинтами services/connection_review.py:
    # иначе клиент мог бы «одобрить» подключение произвольной строкой в обход проверки статуса.
    if model is Connection: allowed.discard('port_config_approved_signature')
    return allowed
