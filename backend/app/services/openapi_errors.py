"""Описание форматов ошибок в схеме OpenAPI.

Приложение отвечает на ошибки не так, как FastAPI по умолчанию, а схема OpenAPI описывала умолчания:

* 422 при ошибке разбора запроса — строка ``{"detail": "<сообщение по-русски>"}`` (services/request_errors.py), а схема
  ``HTTPValidationError`` по-прежнему говорила «список объектов ``{loc, msg, type}``». По схеме генерируют клиентов, и такой клиент
  не смог бы разобрать настоящий ответ;
* 413 при слишком большом теле (services/body_limit.py) вообще не был описан.

Здесь схема приводится в соответствие с поведением: ``HTTPValidationError.detail`` — строка, а каждая операция с телом запроса получает
ответ 413. Код (``detail.code``) и ограничение на число сообщений берутся из тех же констант, что и сам обработчик, поэтому описание
не разойдётся с ним при правках.

Пример::

    install_error_formats(app, max_body_bytes=MAX_REQUEST_BODY_BYTES)
    app.openapi()["components"]["schemas"]["HTTPValidationError"]["properties"]["detail"]["type"]  # "string"
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from ..constants import ErrorCode
from .body_limit import describe_limit
from .request_errors import MAX_REPORTED_ERRORS

VALIDATION_ERROR_SCHEMA = "HTTPValidationError"
# Вложенная схема из стандартного списка ошибок: после замены детали строкой на неё никто не ссылается.
_LEGACY_ITEM_SCHEMA = "ValidationError"
TOO_LARGE_SCHEMA = "RequestBodyTooLarge"
_SCHEMA_REF_PREFIX = "#/components/schemas/"


def flat_validation_error_schema() -> dict[str, Any]:
    """HTTPValidationError в том виде, в каком его отдаёт request_validation_handler: ``detail`` — строка."""
    return {
        "title": VALIDATION_ERROR_SCHEMA,
        "type": "object",
        "properties": {
            "detail": {
                "type": "string",
                "title": "Detail",
                "description": f"Сообщение об ошибке запроса на русском языке (не более {MAX_REPORTED_ERRORS} различных, через «; »).",
            }
        },
    }


def too_large_schema() -> dict[str, Any]:
    """Тело ответа 413: структурированная ошибка ``detail.code`` + ``detail.message`` (body_limit.too_large_detail)."""
    return {
        "title": TOO_LARGE_SCHEMA,
        "type": "object",
        "required": ["detail"],
        "properties": {
            "detail": {
                "type": "object",
                "title": "Detail",
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "string", "title": "Code", "enum": [ErrorCode.REQUEST_BODY_TOO_LARGE]},
                    "message": {"type": "string", "title": "Message", "description": "Сообщение по-русски: предел и как его поднять."},
                },
            }
        },
    }


def _references(node: object, target: str) -> bool:
    """Есть ли в схеме ссылка ``$ref`` на ``target`` (обход вложенных словарей и списков)."""
    if isinstance(node, dict):
        return any((key == "$ref" and value == target) or _references(value, target) for key, value in node.items())
    if isinstance(node, list):
        return any(_references(item, target) for item in node)
    return False


def _operations_with_body(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Операции, у которых описано тело запроса: только им предел размера тела бывает «виден» клиенту."""
    operations = []
    for path_item in schema.get("paths", {}).values():
        for operation in path_item.values():
            if isinstance(operation, dict) and "requestBody" in operation:
                operations.append(operation)
    return operations


def apply_error_formats(schema: dict[str, Any], max_body_bytes: int) -> dict[str, Any]:
    """Правит схему OpenAPI на месте и возвращает её же. Повторный вызов ничего не меняет.

    ``max_body_bytes`` — предел размера тела (config.MAX_REQUEST_BODY_BYTES); 0 означает «проверка выключена», тогда 413 не описывается.
    """
    schemas = schema.setdefault("components", {}).setdefault("schemas", {})
    if VALIDATION_ERROR_SCHEMA in schemas:  # его нет, если ни одна операция не может ответить 422
        schemas[VALIDATION_ERROR_SCHEMA] = flat_validation_error_schema()
        if _LEGACY_ITEM_SCHEMA in schemas and not _references(schema, _SCHEMA_REF_PREFIX + _LEGACY_ITEM_SCHEMA):
            del schemas[_LEGACY_ITEM_SCHEMA]
    if max_body_bytes > 0:
        operations = _operations_with_body(schema)
        if operations:
            schemas[TOO_LARGE_SCHEMA] = too_large_schema()
        for operation in operations:
            operation.setdefault("responses", {}).setdefault(
                "413",
                {
                    "description": f"Тело запроса больше {describe_limit(max_body_bytes)} (INFRA_REGISTRY_MAX_REQUEST_BODY_BYTES); тело не разбирается.",
                    "content": {"application/json": {"schema": {"$ref": _SCHEMA_REF_PREFIX + TOO_LARGE_SCHEMA}}},
                },
            )
    return schema


def install_error_formats(app: FastAPI, max_body_bytes: int) -> None:
    """Подменяет ``app.openapi`` так, чтобы схема строилась один раз и сразу с описанием ошибок приложения.

    Результат кэшируется в ``app.openapi_schema`` — там же, где его хранит сам FastAPI, поэтому ``/openapi.json``, Swagger UI и прямой
    вызов ``app.openapi()`` видят одну и ту же схему."""
    build_default = app.openapi

    def openapi_with_error_formats() -> dict[str, Any]:
        schema = app.openapi_schema
        if schema is None:
            schema = apply_error_formats(build_default(), max_body_bytes)  # build_default заполняет app.openapi_schema и возвращает его же
        return schema

    app.openapi = openapi_with_error_formats  # type: ignore[method-assign]  # штатный способ переопределить схему (документация FastAPI)
