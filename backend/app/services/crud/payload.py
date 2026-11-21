"""Проверка входного payload generic CRUD: запись в защищённые ресурсы, схемы Pydantic, неизвестные ключи, типы и длины колонок."""

from __future__ import annotations

import difflib
from datetime import date, datetime
from functools import lru_cache
from typing import Any
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import BigInteger, Boolean, Date, DateTime, Integer, SmallInteger, String
from sqlalchemy.inspection import inspect
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
_SERVICE_PAYLOAD_KEYS = frozenset({"confirm_system_name_duplicate", "confirm_rack_position_reassign", "expected_updated_at"})


# Ключи, которые клиент может вернуть «эхом» из ранее полученной записи; generic CRUD их и так игнорирует
# (id/created_at/updated_at не входят в allowed_columns, number у ИС присваивается сервером) — отказывать
# на них значило бы ломать обычный цикл «прочитал запись — поправил — отправил обратно».
_ECHOED_READONLY_KEYS = frozenset({"id", "created_at", "updated_at", "number"})


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
        hints.append(f"«{key}»" + (f" (возможно, «{close[0]}»)" if close else ""))
    raise HTTPException(422, f"Ошибка валидации: неизвестные поля: {', '.join(hints)}")


def _format_schema_validation_error(exc: ValidationError) -> str:
    """Сводит структурированный Pydantic ValidationError к одной строке — в стиле остальных
    422-ошибок этого модуля (см. validate_resource в services/validation.py), чтобы формат
    ошибки был единообразным независимо от того, какой слой её обнаружил."""
    parts = [f"{'.'.join(str(p) for p in err['loc']) or '(payload)'}: {err['msg']}" for err in exc.errors()]
    return "Ошибка валидации: " + "; ".join(parts)


# ---------------------------------------------------------------------------------------------------------------------
# Типы и длины по метаданным модели (A-09)
# ---------------------------------------------------------------------------------------------------------------------
# Pydantic-схемы есть только у devices / information-systems / vlans, остальные ресурсы шли «сырым dict» в model(**data):
# строка `{"a": 1}` или список в колонке-строке давали 500 (необработанная ошибка драйвера), число сохранялось как текст,
# а строка длиннее VARCHAR(n) на PostgreSQL падала DataError. Проверка идёт по самим колонкам модели, поэтому не отстаёт
# от моделей и не требует ручной схемы на каждый ресурс.
_INT_RANGES = {SmallInteger: (-(2**15), 2**15 - 1), BigInteger: (-(2**63), 2**63 - 1)}
_DEFAULT_INT_RANGE = (-(2**31), 2**31 - 1)  # Integer: INTEGER в PostgreSQL; вне диапазона — DataError, а в SQLite OverflowError


@lru_cache(maxsize=None)
def _column_rules(model) -> dict[str, tuple[str, Any]]:
    """Правила проверки по колонкам модели: {имя: (вид, параметр)}. Колонки других типов (их сейчас нет) не проверяются.
    Text — это подкласс String без длины; Boolean не подкласс Integer, bool — подкласс int (проверяется отдельно)."""
    rules: dict[str, tuple[str, Any]] = {}
    for column in inspect(model).columns:
        column_type = column.type
        if isinstance(column_type, Boolean):
            rules[column.key] = ("bool", None)
        elif isinstance(column_type, Integer):
            rules[column.key] = ("int", next((r for t, r in _INT_RANGES.items() if isinstance(column_type, t)), _DEFAULT_INT_RANGE))
        elif isinstance(column_type, String):
            rules[column.key] = ("str", column_type.length)
        elif isinstance(column_type, DateTime):
            rules[column.key] = ("datetime", None)
        elif isinstance(column_type, Date):
            rules[column.key] = ("date", None)
    return rules


def _column_value_error(kind: str, parameter: Any, value: Any) -> str | None:
    """Текст ошибки для значения колонки или None, если значение допустимо."""
    if kind == "str":
        if not isinstance(value, str):
            return "ожидается строка"
        if parameter and len(value) > parameter:
            return f"не более {parameter} символов"
        if "\x00" in value:
            return "не должно содержать нулевой символ"
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:  # одиночный суррогат из JSON ("\ud800"): драйвер не сможет его записать
            return "содержит недопустимые символы"
        return None
    if kind == "bool":
        return None if isinstance(value, bool) else "ожидается true/false"
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return "ожидается целое число"
        low, high = parameter
        return None if low <= value <= high else f"число должно быть от {low} до {high}"
    # date / datetime: ISO-строка либо уже разобранное Pydantic значение (devices.oac_certificate_registry_date)
    if isinstance(value, date):  # datetime — подкласс date
        return None
    if not isinstance(value, str):
        return "ожидается дата в формате ГГГГ-ММ-ДД" if kind == "date" else "ожидается дата и время в формате ISO 8601"
    try:
        date.fromisoformat(value) if kind == "date" else datetime.fromisoformat(value)
    except ValueError:
        return "некорректная дата, ожидается ГГГГ-ММ-ДД" if kind == "date" else "некорректные дата и время, ожидается ISO 8601"
    return None


def validate_column_types(model, data: dict[str, Any]) -> None:
    """422 «Ошибка валидации: …» для значений, не подходящих колонке модели по типу или длине.

    Строки — str не длиннее `String(n)`, без символа NUL и одиночных суррогатов; Boolean — true/false; Integer — int (не bool)
    в диапазоне INTEGER; Date/DateTime — ISO-строка или значение date/datetime. `None` пропускается (NOT NULL проверяет БД и
    отвечает 409 как раньше). Ключи вне колонок модели не проверяются: их отбрасывает `allowed_columns` до вызова (поэтому
    «эхо» id/created_at из прочитанной записи не мешает), а опечатки в ключах ловит `_reject_unknown_keys`. Все ошибки
    собираются в одно сообщение. Вызывать до бизнес-проверок: они делают запросы по значениям из payload (`session.get(...)`),
    и словарь вместо id упал бы там 500-й."""
    rules = _column_rules(model)
    errors = []
    for key, value in data.items():
        rule = rules.get(key)
        if rule is None or value is None:
            continue
        error = _column_value_error(rule[0], rule[1], value)
        if error:
            errors.append(f"{key}: {error}")
    if errors:
        raise HTTPException(422, "Ошибка валидации: " + "; ".join(errors))
