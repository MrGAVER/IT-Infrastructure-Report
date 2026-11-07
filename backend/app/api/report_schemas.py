"""Pydantic-модели тел запросов отчётов и конструктора шаблонов (код-ревью main, F-06, этап 2).

Заменяют ``payload: dict`` в ``api/reports.py`` и ``api/report_builder.py``. Правила проверки — прежние и по-прежнему в
``services/report_params.py`` (A-10): валидаторы вызывают их через ``delegate_to_parser`` (см. ``schema_base``), поэтому тексты
ошибок не изменились. Предметная проверка шаблона (``validate_grid_config`` / ``validate_config``) осталась в обработчике: ей нужны
метаданные сущностей, и она не про форму тела.

Отличия от прежнего поведения (все — в сторону строгости, на корректных запросах ничего не меняется):
* порядок «сначала 404, потом 422 про тело» сохранён зависимостью ``_existing_template`` в ``report_builder.py``;
* ``name`` шаблона не строка — «Укажите название шаблона» (раньше ``.strip()`` у числа давал 500);
* ``description`` шаблона — строка или null (раньше в БД уходил любой JSON-тип).
"""
from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, StringConstraints, field_validator, model_validator

from ..services.report_params import (
    DEFAULT_PREVIEW_LIMIT,
    MAX_ID_LENGTH,
    MAX_REPORT_PARAMS,
    MAX_STRUCTURAL_UNIT_IDS,
    PREVIEW_MAX_LIMIT,
    PREVIEW_MIN_LIMIT,
    parse_config_object,
    parse_preview_limit,
    parse_report_params,
    parse_structural_unit_ids,
)
from ..services.structural_appendix_docx import DEFAULT_IS_NAME
from .schema_base import RequestBody, absent_as_null, delegate_to_parser

DEFAULT_FORMAT = "xlsx"
# Ограничения длины и числа элементов нужны схеме OpenAPI: сообщение об ошибке даёт валидатор из report_params, он срабатывает раньше.
StructuralUnitId = Annotated[str, StringConstraints(min_length=1, max_length=MAX_ID_LENGTH)]


def _checked_format(value: object) -> str:
    """Формат отчёта — строка. Какие строки допустимы (xlsx / docx), решает предметная проверка шаблона в обработчике."""
    if not isinstance(value, str):
        raise ValueError(f"Неизвестный формат отчёта: '{value}' (ожидается xlsx или docx)")
    return value


class _WithStructuralUnits(RequestBody):
    structural_unit_ids: list[StructuralUnitId] | None = Field(
        default=None,
        max_length=MAX_STRUCTURAL_UNIT_IDS,
        description="Ограничить отчёт оборудованием выбранных структурных единиц; null или пустой список — без ограничения.",
    )

    @field_validator("structural_unit_ids", mode="before")
    @classmethod
    def _structural_unit_ids(cls, value: object) -> list[str] | None:
        return delegate_to_parser(parse_structural_unit_ids, value)


class InventoryReportRequest(_WithStructuralUnits):
    """POST /api/v1/reports/inventory (тело необязательное)."""


class StructuralAppendixRequest(_WithStructuralUnits):
    """POST /api/v1/reports/structural-appendix (тело необязательное)."""

    is_name: str = Field(
        default=DEFAULT_IS_NAME,
        description="Короткое имя ИС для заголовков; ведущее «ЕАИС» / «ИС» в заголовках не дублируется.",
    )

    @field_validator("is_name", mode="before")
    @classmethod
    def _is_name(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("Короткое имя ИС должно быть строкой")
        return value


class ReportGenerateRequest(_WithStructuralUnits):
    """POST /api/v1/report-templates/{id}/generate (тело необязательное)."""

    params: dict[str, Any] = Field(
        default_factory=dict,
        description=f"Подстановки {{ключ}} в тексте шаблона: строка, число, true/false или null; не более {MAX_REPORT_PARAMS} значений.",
    )

    @field_validator("params", mode="before")
    @classmethod
    def _params(cls, value: object) -> dict[str, Any]:
        return delegate_to_parser(parse_report_params, value)


class ReportPreviewRequest(RequestBody):
    """POST /api/v1/report-builder/preview — предпросмотр без сохранения шаблона."""

    format: str = Field(default=DEFAULT_FORMAT, description="xlsx или docx.")
    config: dict[str, Any] = Field(default_factory=dict, description="Описание листов (xlsx) или блоков (docx).")
    # ge/le нужны только схеме OpenAPI: сообщение об ошибке даёт parse_preview_limit.
    limit: int = Field(
        default=DEFAULT_PREVIEW_LIMIT,
        ge=PREVIEW_MIN_LIMIT,
        le=PREVIEW_MAX_LIMIT,
        description="Сколько первых строк показать.",
    )

    @field_validator("format", mode="before")
    @classmethod
    def _format(cls, value: object) -> str:
        return _checked_format(value)

    @field_validator("config", mode="before")
    @classmethod
    def _config(cls, value: object) -> dict[str, Any]:
        return delegate_to_parser(parse_config_object, value)

    @field_validator("limit", mode="before")
    @classmethod
    def _limit(cls, value: object) -> int:
        return delegate_to_parser(lambda raw: parse_preview_limit({"limit": raw}), value)


class ReportTemplateWrite(RequestBody):
    """POST /api/v1/report-templates и PUT /api/v1/report-templates/{id} — шаблон целиком."""

    # validate_default: отсутствующее поле проходит ту же проверку и получает то же сообщение, что и неверное значение.
    name: str = Field(default="", validate_default=True, description="Название шаблона, уникальное; пробелы по краям обрезаются.")
    format: str = Field(default=DEFAULT_FORMAT, description="xlsx или docx.")
    config: dict[str, Any] = Field(description="Описание листов (xlsx) или блоков (docx); проверяется под формат шаблона.")
    description: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _config_present(cls, raw: object) -> object:
        return absent_as_null(raw, "config")  # отсутствие — то же сообщение, что у неверного значения (_config)

    @field_validator("name", mode="before")
    @classmethod
    def _name(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Укажите название шаблона")
        return value.strip()

    @field_validator("format", mode="before")
    @classmethod
    def _format(cls, value: object) -> str:
        return _checked_format(value)

    @field_validator("config", mode="before")
    @classmethod
    def _config(cls, value: object) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("Поле config должно быть объектом с описанием листов/блоков")
        return delegate_to_parser(parse_config_object, value)  # NaN/Infinity в ширине, высоте и т. п. — 422, а не 500 при ответе

    @field_validator("description", mode="before")
    @classmethod
    def _description(cls, value: object) -> object:
        if value is not None and not isinstance(value, str):
            raise ValueError("Поле description должно быть строкой или null")
        return value
