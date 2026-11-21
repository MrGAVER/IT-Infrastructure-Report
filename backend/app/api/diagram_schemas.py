"""Pydantic-модели тел запросов роутера диаграмм.

Раньше четыре обработчика (POST /diagrams, PUT .../rename, PUT .../layout, PUT .../groups/{key}) принимали ``payload: dict`` и
проверяли поля вручную: у таких эндпоинтов не было описания в OpenAPI, а проверки были размазаны по обработчикам. Теперь форма тела
описана моделями, а правила — валидаторами рядом с полями; обработчикам остаётся предметная логика.

Сообщения об ошибках остались прежними и русскими: валидаторы поднимают ``ValueError`` с тем же текстом, а общий обработчик
``RequestValidationError`` (services/request_errors.py) отдаёт его клиенту строкой в ``detail`` — в том виде, в котором фронтенд
показывает ошибки (api/client.ts).

Отличия от прежнего поведения (все — в сторону строгости, на корректных запросах ничего не меняется):
* тело проверяется до обработчика, поэтому запрос с неверным телом к несуществующей диаграмме получает 422, а не 404;
* ``description`` — строка или null (раньше в БД уходил любой JSON-тип);
* ``is_collapsed`` — булево значение (раньше любое значение приводилось через ``bool(...)``).
* ``collapse_threshold`` и ``custom_threshold`` не больше MAX_COLLAPSE_THRESHOLD (раньше сверхбольшое целое доходило до драйвера БД: 500).
"""

from __future__ import annotations

import re
from typing import Any, TypeAlias

from pydantic import Field, StrictBool, field_validator, model_validator

from ..services.diagram_graph import GROUP_DIMENSIONS, MAX_LAYOUT_KEY_LENGTH, MAX_LAYOUT_NODES, clean_position, finite_number
from .schema_base import RequestBody, absent_as_null

Number: TypeAlias = int | float  # int | float, а не float: целые координаты сохраняются целыми, как их прислал клиент
DEFAULT_COLLAPSE_THRESHOLD = 20
# Верхняя граница порогов сворачивания (collapse_threshold, custom_threshold). Заведомо больше MAX_LAYOUT_NODES (5000) и помещается в
# INTEGER и SQLite, и PostgreSQL. Без границы значение вроде 10**30 доходило до драйвера БД и заканчивалось 500 (OverflowError).
# Это же число стоит в поле ввода frontend (DiagramFormModal.vue, max="1000000"): менять их нужно вместе.
MAX_COLLAPSE_THRESHOLD = 1_000_000
MAX_DIAGRAM_NAME_LENGTH = 255  # длина колонки SavedDiagram.name
# Управляющие символы C0/C1 (в том числе CR, LF, табуляция, DEL) и разделители строк/абзацев Unicode.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
# Поля viewport: x/y/zoom — как в описании контракта, pan_x/pan_y — как их шлёт и читает frontend (DiagramViewport).
VIEWPORT_KEYS = frozenset({"x", "y", "zoom", "pan_x", "pan_y"})


def clean_name(raw: object) -> str:
    """Название диаграммы без управляющих символов: они заменяются пробелом, подряд идущие пробельные символы
    схлопываются, края обрезаются. Нестрока даёт пустое название (его отвергает checked_name). Название попадает в
    имя файла экспорта и в заголовок Content-Disposition, где CR/LF обрывали ответ (RuntimeError: Invalid HTTP header value)."""
    if not isinstance(raw, str):
        return ""
    return " ".join(_CONTROL_CHARS.sub(" ", raw).split())


def checked_name(raw: object) -> str:
    name = clean_name(raw)
    if not name:
        raise ValueError("Укажите название диаграммы")
    if len(name) > MAX_DIAGRAM_NAME_LENGTH:
        raise ValueError(f"Название диаграммы не должно быть длиннее {MAX_DIAGRAM_NAME_LENGTH} символов")
    return name


def checked_positions(raw: object) -> dict[str, dict]:
    """Строгая проверка раскладки из PUT: объект {id: {x, y}} с числами и не более MAX_LAYOUT_NODES узлов. Некорректный
    элемент — ошибка с названием узла, а не молчаливая запись в БД, после которой диаграмма не открывалась."""
    if not isinstance(raw, dict) or len(raw) > MAX_LAYOUT_NODES:
        raise ValueError(f"node_positions должен быть объектом {{id: {{x, y}}}} (не более {MAX_LAYOUT_NODES} узлов)")
    cleaned: dict[str, dict] = {}
    for key, position in raw.items():
        clean = clean_position(position)
        if not isinstance(key, str) or len(key) > MAX_LAYOUT_KEY_LENGTH or clean is None:
            raise ValueError(f"Некорректная позиция узла «{str(key)[:60]}»: ожидается {{x: число, y: число}}")
        cleaned[key] = clean
    return cleaned


def checked_viewport(raw: object) -> dict | None:
    """None либо объект только из VIEWPORT_KEYS с конечными числами; иначе ошибка."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or not set(raw) <= VIEWPORT_KEYS or not all(finite_number(v) for v in raw.values()):
        raise ValueError("viewport должен быть объектом с числовыми полями " + ", ".join(sorted(VIEWPORT_KEYS)) + " или null")
    return dict(raw)


def checked_threshold(value: object, field: str, *, nullable: bool = False) -> int | None:
    """Порог сворачивания: целое число от 1 до MAX_COLLAPSE_THRESHOLD (для nullable-поля допустим ещё null).

    Тип и нижняя граница дают прежние сообщения; верхняя граница — новое, с названием поля. Булево значение целым не считается
    (True — это int в Python, но не число в JSON)."""
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field} должен быть положительным целым числом" + (" или null" if nullable else ""))
    if value > MAX_COLLAPSE_THRESHOLD:
        raise ValueError(f"{field} не должен превышать {MAX_COLLAPSE_THRESHOLD}")
    return value


class DiagramCreate(RequestBody):
    """POST /api/v1/diagrams."""

    # validate_default: отсутствующее название проходит ту же проверку и получает то же сообщение «Укажите название диаграммы».
    name: str = Field(default="", validate_default=True, max_length=MAX_DIAGRAM_NAME_LENGTH, description="Название диаграммы; управляющие символы заменяются пробелом, не длиннее 255 символов.")
    group_by: str = Field(default="structural_unit", description="Измерение группировки узлов.", json_schema_extra={"enum": list(GROUP_DIMENSIONS)})
    scope_filter: dict[str, Any] = Field(default_factory=dict, description="Фильтр охвата: какие устройства попадают на диаграмму.")
    description: str | None = None
    # ge/le нужны только схеме OpenAPI (minimum/maximum): сообщение об ошибке даёт валидатор ниже.
    collapse_threshold: int = Field(default=DEFAULT_COLLAPSE_THRESHOLD, ge=1, le=MAX_COLLAPSE_THRESHOLD, description="Группа крупнее этого числа устройств сворачивается.")

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: object) -> str:
        return checked_name(value)

    @field_validator("group_by", mode="before")
    @classmethod
    def _group_by(cls, value: object) -> str:
        if not isinstance(value, str) or value not in GROUP_DIMENSIONS:
            raise ValueError(f"group_by должен быть одним из: {', '.join(GROUP_DIMENSIONS)}")
        return value

    @field_validator("scope_filter", mode="before")
    @classmethod
    def _scope_filter(cls, value: object) -> object:
        if not value:  # null, пустой объект и прочие «пустые» значения означают «без фильтра», как и раньше
            return {}
        if not isinstance(value, dict):
            raise ValueError("scope_filter должен быть объектом-фильтром охвата")
        return value

    @field_validator("collapse_threshold", mode="before")
    @classmethod
    def _collapse_threshold(cls, value: object) -> int | None:
        return checked_threshold(value, "collapse_threshold")


class DiagramRename(RequestBody):
    """PUT /api/v1/diagrams/{id}/rename."""

    name: str = Field(default="", validate_default=True, max_length=MAX_DIAGRAM_NAME_LENGTH)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: object) -> str:
        return checked_name(value)


class DiagramLayoutUpdate(RequestBody):
    """PUT /api/v1/diagrams/{id}/layout."""

    node_positions: dict[str, dict[str, Number]] = Field(description=f"Позиции узлов {{id: {{x, y}}}}, не более {MAX_LAYOUT_NODES} узлов.")
    viewport: dict[str, Number] | None = Field(default=None, description="Положение и масштаб холста: x, y, zoom, pan_x, pan_y — или null.")

    @model_validator(mode="before")
    @classmethod
    def _node_positions_present(cls, raw: object) -> object:
        return absent_as_null(raw, "node_positions")  # отсутствие — то же сообщение, что у неверного значения (_node_positions)

    @field_validator("node_positions", mode="before")
    @classmethod
    def _node_positions(cls, value: object) -> dict[str, dict]:
        return checked_positions(value)

    @field_validator("viewport", mode="before")
    @classmethod
    def _viewport(cls, value: object) -> dict | None:
        return checked_viewport(value)


class DiagramGroupStateUpdate(RequestBody):
    """PUT /api/v1/diagrams/{id}/groups/{group_key}. Применяется только то, что прислано: отсутствующее поле состояние не трогает,
    а ``custom_threshold: null`` сбрасывает порог группы (различие — по ``model_fields_set``)."""

    is_collapsed: StrictBool = False
    custom_threshold: int | None = Field(default=None, ge=1, le=MAX_COLLAPSE_THRESHOLD, description="Свой порог сворачивания группы; null — использовать порог диаграммы.")

    @field_validator("custom_threshold", mode="before")
    @classmethod
    def _custom_threshold(cls, value: object) -> int | None:
        return checked_threshold(value, "custom_threshold", nullable=True)
