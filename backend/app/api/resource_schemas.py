"""Тела запросов роутера ``/api/v1/resources`` (код-ревью main, F-06, этап 2).

Два вида тел:

* **Детали информационной системы** (``PUT /information-systems/{id}/details``) — форма известна, поэтому у неё обычная модель
  ``InformationSystemDetailsUpdate``. Правила разбора элементов остаются в ``services/crud/information_system.py``.
* **Универсальный CRUD** (``POST /{resource}``, ``PUT /{resource}/{id}``) — поля тела зависят от ресурса, и одной моделью их не
  описать: 30+ ресурсов с разными колонками. Проверку по-настоящему делает сервис — Pydantic-схемы ``schemas.RESOURCE_SCHEMAS``
  (devices / information-systems / vlans), проверка типов колонок и правила ``validate_resource``. Поэтому тело остаётся
  объектом произвольных полей (``ResourceBody``), но теперь с описанием в OpenAPI, а не безымянным ``dict``. Модель на ресурс — отдельный
  этап: сначала нужно решить, как поддерживать 30+ схем рядом с колонками SQLAlchemy, чтобы они не разошлись.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import Body
from pydantic import Field, field_validator

from .schema_base import RequestBody

ResourceBody = Annotated[
    dict[str, Any],
    Body(
        description=(
            "Поля записи — колонки ресурса из {resource} (список: GET /api/v1/resources/{resource}/schema). "
            "Неизвестные колонки игнорируются; типы и правила проверяются по ресурсу, ошибка — 422 с текстом на русском."
        ),
    ),
]

_DETAIL_LISTS = ("departments", "protocols", "placement_assets", "sources")


class InformationSystemDetailsUpdate(RequestBody):
    """PUT /api/v1/resources/information-systems/{id}/details — связанные данные ИС целиком.

    Каждый список — ПОЛНЫЙ набор строк: то, чего в списке нет, удаляется (поэтому отсутствующий список — это пустой, как и раньше).
    Строки — объекты; не объекты пропускаются."""

    departments: list[Any] = Field(default_factory=list, description="Подразделения ИС.")
    protocols: list[Any] = Field(default_factory=list, description="Протоколы и порты ИС (строка со ссылкой protocol_catalog_id на справочник).")
    placement_assets: list[Any] = Field(default_factory=list, description="Размещение: активы, на которых работает ИС.")
    sources: list[Any] = Field(default_factory=list, description="Источники: оборудование, ВМ, контейнеры или IP-адрес вручную.")

    @field_validator(*_DETAIL_LISTS, mode="before")
    @classmethod
    def _is_list(cls, value: object, info: Any) -> object:
        if not isinstance(value, list):
            raise ValueError(f"Поле {info.field_name} должно быть массивом")
        return value
