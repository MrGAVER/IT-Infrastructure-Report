"""Проверка входного payload generic CRUD: запись в защищённые ресурсы, схемы Pydantic и неизвестные ключи."""
from __future__ import annotations

import difflib
from typing import Any
from fastapi import HTTPException
from pydantic import ValidationError
from ...registry import READONLY_RESOURCES
from ...schemas import RESOURCE_SCHEMAS
from .columns import allowed_columns, model_for


def ensure_writable(resource: str) -> None:
    """Запрещает запись через generic CRUD для ресурсов из READONLY_RESOURCES (сейчас — только
    audit-log). Вызывается из create_resource/update_resource/delete_resource, а не только на
    уровне роутера (api/resources.py), чтобы гарантия действовала для любого текущего и
    будущего вызывающего кода, а не только для одного набора HTTP-эндпоинтов."""
    if resource in READONLY_RESOURCES:
        raise HTTPException(403, f"Ресурс '{resource}' доступен только для чтения")


def validate_payload_schema(resource: str, payload: dict[str, Any], *, is_update: bool) -> dict[str, Any]:
    """Валидирует и приводит типы payload по Pydantic-схеме, если она зарегистрирована для
    этого ресурса (см. schemas.RESOURCE_SCHEMAS: пока только devices/information-systems/vlans
    — код-ревью п.2). Для остальных ресурсов возвращает payload без изменений — они по-прежнему
    проходят через generic CRUD как сырой dict, это осознанное инкрементальное покрытие.

    Возвращает НОВЫЙ dict — исходный payload с наложенными сверху провалидированными полями,
    а не просто dump схемы: так ключи вне схемы (confirm_system_name_duplicate,
    confirm_rack_position_reassign), которые читаются из payload напрямую в create_resource/
    update_resource, не теряются."""
    schemas = RESOURCE_SCHEMAS.get(resource)
    if schemas is None:
        return payload
    _reject_unknown_keys(resource, payload)
    schema = schemas[1] if is_update else schemas[0]
    try:
        validated = schema.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(422, _format_schema_validation_error(exc)) from exc
    return {**payload, **validated.model_dump(exclude_unset=True)}


# Служебные ключи, которые generic CRUD читает из payload напрямую (они не колонки модели).
_SERVICE_PAYLOAD_KEYS = frozenset({'confirm_system_name_duplicate', 'confirm_rack_position_reassign'})


# Ключи, которые клиент может вернуть «эхом» из ранее полученной записи; generic CRUD их и так игнорирует
# (id/created_at/updated_at не входят в allowed_columns, number у ИС присваивается сервером) — отказывать
# на них значило бы ломать обычный цикл «прочитал запись — поправил — отправил обратно».
_ECHOED_READONLY_KEYS = frozenset({'id', 'created_at', 'updated_at', 'number'})


def _reject_unknown_keys(resource: str, payload: dict[str, Any]) -> None:
    """422 на ключ, которого нет среди колонок модели, служебных флагов и «эхо»-ключей (код-ревью, п. 8).

    Generic CRUD отбрасывает ключи вне allowed_columns() молча (`{k: v ... if k in allowed}`), поэтому
    опечатка в имени поля — `serial_numbr`, `rack_positon` — давала «успех»: запись создавалась без
    значения, а при правке просто не менялась, и пользователь узнавал об этом позже. Схемы
    devices/information-systems/vlans объявляют не все колонки (например, diagram_icon_id), поэтому
    проверка идёт по колонкам модели, а не через extra="forbid" схемы: так она не отстаёт от модели.

    К ресурсам без схемы это не применяется (их инкрементальное покрытие — см. validate_payload_schema).
    В сообщении — ближайшее по написанию допустимое имя, если оно есть."""
    known = allowed_columns(model_for(resource)) | _SERVICE_PAYLOAD_KEYS | _ECHOED_READONLY_KEYS
    unknown = sorted(str(key) for key in payload if key not in known)
    if not unknown:
        return
    hints = []
    for key in unknown:
        close = difflib.get_close_matches(key, sorted(known), n=1, cutoff=0.7)
        hints.append(f"«{key}»" + (f" (возможно, «{close[0]}»)" if close else ''))
    raise HTTPException(422, f"Ошибка валидации: неизвестные поля: {', '.join(hints)}")


def _format_schema_validation_error(exc: ValidationError) -> str:
    """Сводит структурированный Pydantic ValidationError к одной строке — в стиле остальных
    422-ошибок этого модуля (см. validate_resource в services/validation.py), чтобы формат
    ошибки был единообразным независимо от того, какой слой её обнаружил."""
    parts = [f"{'.'.join(str(p) for p in err['loc']) or '(payload)'}: {err['msg']}" for err in exc.errors()]
    return 'Ошибка валидации: ' + '; '.join(parts)
