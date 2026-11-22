"""Код-ревью (раздел 5, backend, п. 2): границы строк и списков в моделях тел запросов описаны в схеме, а не «тихо» в сервисах.

Что сделано:

* строки, уходящие в колонки ``VARCHAR(n)`` (название шаблона отчёта — 255, название диаграммы — 255, короткое имя ИС — 255), и
  строки, которые разбирает сервис (``q`` — 200, ``plan_hash`` — 64), получили ``max_length``; списки (``connection_ids`` — 500,
  ``vlan_ids`` — 5000) — ``max_length`` по тем же константам, что и разбор в сервисе. Эти границы теперь видны в OpenAPI
  (``maxLength`` / ``maxItems``), по ним генерируют клиентов и формы;
* у названия шаблона и короткого имени ИС появилась проверка длины с понятным текстом (раньше на PostgreSQL длинное название
  давало общий 422 «значение не подходит по типу или размеру», на SQLite — запись без проверки);
* охранный тест: новая строка в модели тела без ``max_length`` ломает этот файл, пока её не ограничат или не внесут в список
  исключений с причиной.

Запуск: pytest backend/tests/test_body_field_limits.py -v
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import types
import typing

import pytest
from pydantic import ValidationError

import app.api as api_package
from app.api.diagram_schemas import MAX_DIAGRAM_NAME_LENGTH, DiagramCreate, DiagramRename
from app.api.port_config_schemas import MAX_PLAN_HASH_LENGTH
from app.api.report_schemas import MAX_IS_NAME_LENGTH, MAX_TEMPLATE_NAME_LENGTH, ReportTemplateWrite, StructuralAppendixRequest
from app.api.schema_base import RequestBody
from app.main import app
from app.services.connection_query import MAX_SEARCH_LENGTH
from app.services.connection_review import MAX_APPROVE_BATCH
from app.services.port_edit import MAX_VLAN_IDS

API = "/api/v1"
CONFIG = {
    "sheets": [
        {
            "title": "Лист1",
            "columns": [{"width": 25}],
            "rows": [
                {"height": 18, "repeat": True, "data_source": {"root_entity": "information-systems"}, "cells": [{"col": 0, "kind": "field", "path": "name"}]}
            ],
        }
    ]
}


class TestDeclaredInOpenApi:
    @pytest.mark.parametrize(
        ("schema", "field", "key", "limit"),
        [
            ("ApproveMatch", "q", "maxLength", MAX_SEARCH_LENGTH),
            ("ApprovePortConfigRequest", "connection_ids", "maxItems", MAX_APPROVE_BATCH),
            ("CascadeApplyRequest", "plan_hash", "maxLength", MAX_PLAN_HASH_LENGTH),
            ("PortConfigUpdate", "vlan_ids", "maxItems", MAX_VLAN_IDS),
            ("DiagramCreate", "name", "maxLength", MAX_DIAGRAM_NAME_LENGTH),
            ("DiagramRename", "name", "maxLength", MAX_DIAGRAM_NAME_LENGTH),
            ("ReportTemplateWrite", "name", "maxLength", MAX_TEMPLATE_NAME_LENGTH),
            ("StructuralAppendixRequest", "is_name", "maxLength", MAX_IS_NAME_LENGTH),
        ],
    )
    def test_limit_is_in_the_schema(self, schema, field, key, limit):
        prop = app.openapi()["components"]["schemas"][schema]["properties"][field]
        variants = prop.get("anyOf") or [prop]  # у необязательных полей схема лежит в anyOf вместе с null
        assert any(variant.get(key) == limit for variant in variants), f"{schema}.{field}: нет {key}={limit} в {prop}"


class TestNewLengthChecks:
    def test_template_name_of_255_characters_is_accepted_and_256_is_not(self, client):
        accepted = client.post(f"{API}/report-templates", json={"name": "а" * MAX_TEMPLATE_NAME_LENGTH, "config": CONFIG})
        assert accepted.status_code == 201, accepted.text
        refused = client.post(f"{API}/report-templates", json={"name": "а" * (MAX_TEMPLATE_NAME_LENGTH + 1), "config": CONFIG})
        assert refused.status_code == 422
        assert refused.json()["detail"] == f"Название шаблона не должно быть длиннее {MAX_TEMPLATE_NAME_LENGTH} символов"

    def test_template_name_is_measured_after_trimming(self):
        body = ReportTemplateWrite.model_validate({"name": f"  {'а' * MAX_TEMPLATE_NAME_LENGTH}  ", "config": CONFIG})
        assert len(body.name) == MAX_TEMPLATE_NAME_LENGTH

    def test_short_is_name_limit(self):
        assert StructuralAppendixRequest.model_validate({"is_name": "а" * MAX_IS_NAME_LENGTH}).is_name
        with pytest.raises(ValidationError) as caught:
            StructuralAppendixRequest.model_validate({"is_name": "а" * (MAX_IS_NAME_LENGTH + 1)})
        assert f"Короткое имя ИС не должно быть длиннее {MAX_IS_NAME_LENGTH} символов" in str(caught.value)

    @pytest.mark.parametrize("model", [DiagramCreate, DiagramRename])
    def test_diagram_name_message_is_unchanged(self, model):
        with pytest.raises(ValidationError) as caught:
            model.model_validate({"name": "а" * (MAX_DIAGRAM_NAME_LENGTH + 1)})
        assert f"Название диаграммы не должно быть длиннее {MAX_DIAGRAM_NAME_LENGTH} символов" in str(caught.value)


# --- охранный тест: строка в модели тела без границы ---------------------------------------------------------------------------

# Поля, где ограничение длины не нужно, — и почему. Добавляя сюда запись, укажите причину.
UNBOUNDED_ON_PURPOSE = {
    "DiagramCreate.description": "колонка Text: длина ограничена только общим пределом тела запроса",
    "ReportTemplateWrite.description": "колонка Text: длина ограничена только общим пределом тела запроса",
    "DiagramCreate.group_by": "значение — одно из GROUP_DIMENSIONS, проверяется валидатором",
    "ReportPreviewRequest.format": "значение — xlsx или docx, проверяется валидатором",
    "ReportTemplateWrite.format": "значение — xlsx или docx, проверяется валидатором",
    "PortConfigUpdate.role": "значение — одна из ролей порта, проверяется разбором port_edit",
}


def _request_models() -> list[type[RequestBody]]:
    found: dict[str, type[RequestBody]] = {}
    for module_info in pkgutil.iter_modules(api_package.__path__):
        if not module_info.name.endswith("schemas"):
            continue
        module = importlib.import_module(f"app.api.{module_info.name}")
        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, RequestBody) and cls is not RequestBody and cls.__module__ == module.__name__:
                found[f"{cls.__module__}.{cls.__qualname__}"] = cls
    return list(found.values())


def _is_plain_string(annotation: object) -> bool:
    """``str`` и ``str | None`` — поля, в которые клиент может прислать строку любой длины."""
    if annotation is str:
        return True
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return str in typing.get_args(annotation)
    return False


def _has_max_length(field) -> bool:
    return any(getattr(item, "max_length", None) is not None for item in field.metadata)


def _is_plain_number(annotation: object) -> bool:
    """``int`` / ``float`` и их необязательные варианты — поля, в которые клиент может прислать число любой величины."""
    if annotation in (int, float):
        return True
    if typing.get_origin(annotation) in (typing.Union, types.UnionType):
        return any(_is_plain_number(arg) for arg in typing.get_args(annotation))
    return False


def _bound_kinds(field) -> set[str]:
    """Какие границы заданы у поля: ``lower`` (ge/gt) и ``upper`` (le/lt)."""
    kinds = set()
    for item in field.metadata:
        if hasattr(item, "ge") or hasattr(item, "gt"):
            kinds.add("lower")
        if hasattr(item, "le") or hasattr(item, "lt"):
            kinds.add("upper")
    return kinds


# Числовые поля, которым не нужны обе границы, — и почему. Сейчас таких нет: все три числовых поля тел ограничены с обеих сторон.
NUMBER_BOUNDS_OPTIONAL: dict[str, str] = {}


def test_the_walk_finds_request_models():
    assert len(_request_models()) >= 15  # иначе охранный тест ниже ничего не проверял бы


@pytest.mark.parametrize("model", _request_models(), ids=lambda cls: cls.__qualname__)
def test_every_string_field_is_bounded_or_listed(model):
    unbounded = [
        name
        for name, field in model.model_fields.items()
        if _is_plain_string(field.annotation) and not _has_max_length(field) and f"{model.__qualname__}.{name}" not in UNBOUNDED_ON_PURPOSE
    ]
    assert not unbounded, (
        f"{model.__qualname__}: строковые поля без max_length: {unbounded}. Ограничьте длину по колонке БД или внесите поле в UNBOUNDED_ON_PURPOSE с причиной."
    )


@pytest.mark.parametrize("model", _request_models(), ids=lambda cls: cls.__qualname__)
def test_every_number_field_has_both_bounds_or_is_listed(model):
    """Число вне диапазона колонки БД — это 500 (BE-01: ``10**30`` в пороге диаграммы). Новое числовое поле без ``ge``/``le``
    ломает этот тест, пока его не ограничат (по колонке БД или по смыслу) или не внесут в список исключений с причиной."""
    unbounded = [
        name
        for name, field in model.model_fields.items()
        if _is_plain_number(field.annotation) and _bound_kinds(field) != {"lower", "upper"} and f"{model.__qualname__}.{name}" not in NUMBER_BOUNDS_OPTIONAL
    ]
    assert not unbounded, (
        f"{model.__qualname__}: числовые поля без обеих границ: {unbounded}. Задайте ge/le по колонке БД или внесите поле в NUMBER_BOUNDS_OPTIONAL с причиной."
    )


def test_number_guard_sees_the_known_bounded_fields():
    # Охрана самого теста: обход находит числовые поля и распознаёт у них границы (иначе проверка выше ничего бы не проверяла).
    found = {
        f"{model.__qualname__}.{name}": _bound_kinds(field)
        for model in _request_models()
        for name, field in model.model_fields.items()
        if _is_plain_number(field.annotation)
    }
    assert {"DiagramCreate.collapse_threshold", "DiagramGroupStateUpdate.custom_threshold", "ReportPreviewRequest.limit"} <= set(found)
    assert all(kinds == {"lower", "upper"} for kinds in found.values())
