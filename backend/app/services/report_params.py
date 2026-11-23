"""Проверка параметров запросов формирования отчётов и предпросмотра.

Эти POST-эндпоинты доступны роли viewer (`READ_ONLY_POST_PATHS`) и при выключенной аутентификации — любому клиенту, а тело
запроса раньше шло в код как есть: `limit=10**9` собирал огромную сетку в памяти, `limit="x"` и `config` не-словарь давали
500, `structural_unit_ids` или `params` неподходящего типа падали уже внутри построения отчёта. Здесь — единые проверки с
понятным ответом 422; сообщения в стиле остальных 422 приложения (`detail: str`).
"""

from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException

PREVIEW_MIN_LIMIT = 1
PREVIEW_MAX_LIMIT = 200  # интерфейс просит 15 (xlsx) и 20 (docx); больше — уже не «предпросмотр»
DEFAULT_PREVIEW_LIMIT = 15
MAX_STRUCTURAL_UNIT_IDS = 1000
MAX_ID_LENGTH = 64  # идентификаторы — UUID (36 символов); запас на нестандартные
MAX_REPORT_PARAMS = 100
MAX_PARAM_VALUE_LENGTH = 1000


def parse_preview_limit(payload: dict[str, Any]) -> int:
    """`limit` предпросмотра: ключ не прислан — значение по умолчанию; иначе целое от 1 до 200 (bool — не число, `null` — ошибка)."""
    if "limit" not in payload:
        return DEFAULT_PREVIEW_LIMIT
    raw = payload["limit"]
    if isinstance(raw, bool) or not isinstance(raw, int) or not PREVIEW_MIN_LIMIT <= raw <= PREVIEW_MAX_LIMIT:
        raise HTTPException(422, f"limit должен быть целым числом от {PREVIEW_MIN_LIMIT} до {PREVIEW_MAX_LIMIT}")
    return raw


def reject_non_finite_numbers(value: Any, field: str) -> None:
    """422, если в произвольном JSON (объект/список любой глубины) есть ``NaN`` или ``±Infinity``.

    Python-разбор JSON принимает эти значения (в стандарте JSON их нет): ширина столбца ``NaN`` проходила предметную проверку шаблона
    (любое сравнение с ``NaN`` ложно), сохранялась в БД, а ответ с ней не кодировался (``Out of range float values are not JSON compliant``)
    — 500 на каждое чтение шаблона. Обход итеративный: глубину вложенности клиент задаёт сам."""
    pending = [value]
    while pending:
        node = pending.pop()
        if isinstance(node, float) and not math.isfinite(node):
            raise HTTPException(422, f"{field}: значения NaN и Infinity не допускаются")
        if isinstance(node, dict):
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)


def parse_config_object(raw: Any) -> dict[str, Any]:
    """`config` предпросмотра и шаблона: не прислан или `null` — пустой объект (его отклонит валидатор шаблона с понятным
    текстом), иначе объект без ``NaN``/``Infinity``."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(422, "config должен быть объектом с описанием листов/блоков")
    reject_non_finite_numbers(raw, "config")
    return raw


def parse_structural_unit_ids(raw: Any) -> list[str] | None:
    """`structural_unit_ids`: `null` или пустой список — без фильтра (None), иначе список непустых строк-идентификаторов."""
    if raw is None:
        return None
    valid = (
        isinstance(raw, list)
        and len(raw) <= MAX_STRUCTURAL_UNIT_IDS
        and all(isinstance(item, str) and 0 < len(item) <= MAX_ID_LENGTH for item in raw)
    )
    if not valid:
        raise HTTPException(422, "structural_unit_ids должен быть списком идентификаторов")
    return raw or None


def parse_report_params(raw: Any) -> dict[str, Any]:
    """`params` шаблона отчёта — подстановки `{ключ}` в тексте: объект с текстовыми ключами и простыми значениями
    (строка, число, true/false, null). Вложенные объекты и списки не нужны и отклоняются."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise HTTPException(422, "params должен быть объектом {ключ: значение}")
    if len(raw) > MAX_REPORT_PARAMS:
        raise HTTPException(422, f"params: не более {MAX_REPORT_PARAMS} значений")
    for key, value in raw.items():
        if not isinstance(key, str):
            raise HTTPException(422, "params: ключи должны быть строками")
        if value is not None and not isinstance(value, (str, int, float, bool)):
            raise HTTPException(422, f"params.{key}: допустимы строка, число, true/false или null")
        if isinstance(value, str) and len(value) > MAX_PARAM_VALUE_LENGTH:
            raise HTTPException(422, f"params.{key}: не более {MAX_PARAM_VALUE_LENGTH} символов")
    return raw
