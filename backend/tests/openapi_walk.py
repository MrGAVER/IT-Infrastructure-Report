"""Общий обход схемы OpenAPI для системных тестов API (``test_no_5xx_on_extreme_input.py``, ``test_request_errors_contract.py``).

Строит тела запросов по схеме операции, подставляет реальные родительские записи в путь и отправляет запрос так, чтобы
необработанное исключение сервера считалось ответом 500. Это вспомогательный модуль, не тестовый: тестов здесь нет.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from app.main import app

JSON_TYPE = "application/json"
WRITE_METHODS = ("post", "put", "patch")
# Для объекта без описанных полей (произвольный dict: правила синхронизации портов, сверка) — ключи, которые реально читают сервисы.
GENERIC_KEYS = (
    "name",
    "description",
    "enabled",
    "priority",
    "apply",
    "action",
    "ids",
    "rule_id",
    "connection_ids",
    "plan_hash",
    "confirm",
    "limit",
    "offset",
)
MAX_DEPTH = 4
PATH_PARAM = re.compile(r"\{(\w+)\}")
MISSING_ID = "does-not-exist"

# Допустимое описание листа отчёта: схема OpenAPI называет ``config`` просто объектом, поэтому глубокие поля (ширина столбца, высота
# строки …) обход по схеме не видит.
REPORT_CONFIG = {
    "sheets": [
        {
            "title": "Лист1",
            "columns": [{"width": 25}],
            "rows": [
                {
                    "height": 18,
                    "repeat": True,
                    "data_source": {"root_entity": "information-systems", "limit": 5},
                    "cells": [{"col": 0, "kind": "field", "path": "name"}],
                }
            ],
        }
    ]
}

_PLAIN_STRING = "a"


# --- обход схемы OpenAPI ---------------------------------------------------------------------------------------------------


def deref(spec: dict, schema: dict) -> dict:
    """Раскрывает ``$ref`` (на любую глубину цепочки ссылок)."""
    while "$ref" in schema:
        node: Any = spec
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        schema = node
    return schema


def variants(spec: dict, schema: dict) -> list[dict]:
    """Варианты верхнего уровня: для ``anyOf``/``oneOf`` (отчёты принимают объект или null) — каждый вариант, кроме null."""
    schema = deref(spec, schema)
    options = schema.get("anyOf") or schema.get("oneOf")
    if not options:
        return [schema]
    return [variant for option in options for variant in variants(spec, option) if variant.get("type") != "null"]


class Builder:
    """Строит тело запроса по схеме. ``leaves`` собирает пути листьев (путь, вид) при первом проходе; ``overrides`` подменяет
    значения листьев."""

    def __init__(self, spec: dict) -> None:
        self.spec = spec
        self.leaves: list[tuple[str, str]] = []

    def build(self, schema: dict, path: str, overrides: dict[str, Any], depth: int = 0) -> Any:
        schema = deref(self.spec, schema)
        options = schema.get("anyOf") or schema.get("oneOf")
        if options:  # вложенный союз — первый вариант, кроме null
            schema = next((deref(self.spec, o) for o in options if deref(self.spec, o).get("type") != "null"), {})
        if "allOf" in schema:
            schema = deref(self.spec, schema["allOf"][0])
        kind = schema.get("type")
        if kind == "object" or "properties" in schema:
            return self._object(schema, path, overrides, depth)
        if kind == "array":
            if depth >= MAX_DEPTH:
                return []
            return [self.build(schema.get("items", {}), f"{path}[]", overrides, depth + 1)]
        return self._leaf(schema, path, overrides, kind)

    def _object(self, schema: dict, path: str, overrides: dict[str, Any], depth: int) -> dict:
        if depth >= MAX_DEPTH:
            return {}
        properties = schema.get("properties") or {}
        if not properties:  # произвольный объект: ключи, которые читают сервисы, — по листу «any»
            return {key: self._leaf({}, f"{path}.{key}", overrides, None) for key in GENERIC_KEYS}
        return {name: self.build(sub, f"{path}.{name}", overrides, depth + 1) for name, sub in properties.items()}

    def _leaf(self, schema: dict, path: str, overrides: dict[str, Any], kind: str | None) -> Any:
        leaf_kind = kind if kind in {"integer", "number", "string"} else ("any" if kind is None else "other")
        if leaf_kind != "other":
            self.leaves.append((path, leaf_kind))
        if path in overrides:
            return overrides[path]
        if schema.get("enum"):
            return schema["enum"][0]
        if kind == "integer":
            return max(1, schema.get("minimum", 1))
        if kind == "number":
            return max(1.0, float(schema.get("minimum", 1)))
        if kind == "string":
            return _PLAIN_STRING * max(1, schema.get("minLength", 1))
        if kind == "boolean":
            return False  # False, а не True: «включить аутентификацию» посреди прогона сделало бы следующие запросы чужими (401)
        return _PLAIN_STRING if kind is None else None


# --- отправка запроса -------------------------------------------------------------------------------------------------------


def send(client, db_session, method: str, url: str, body: Any) -> tuple[int, str]:
    """(статус, начало ответа). ``body`` — объект (кодируется в JSON) или готовые байты. Необработанное исключение сервера — 500:
    ``TestClient`` поднимает его в тест вместо ответа."""
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    try:
        response = client.request(method.upper(), url, content=content, headers={"content-type": JSON_TYPE})
    except Exception as exc:  # noqa: BLE001 — любое исключение приложения здесь и есть найденный дефект
        db_session.rollback()  # общая сессия теста могла остаться в оборванной транзакции — следующие запросы не должны падать из-за неё
        return 500, f"{type(exc).__name__}: {exc}"
    return response.status_code, response.text


def fill_path(path: str, values: dict[str, str]) -> str:
    return PATH_PARAM.sub(lambda match: values.get(match.group(1), MISSING_ID), path)


def created_id(client, url: str, body: dict) -> str | None:
    response = client.post(url, json=body)
    return str(response.json()["id"]) if response.status_code == 201 else None


def seed_path_values(client) -> dict[str, str]:
    """Существующие родительские записи — чтобы тело доходило до записи в БД, а не обрывалось 404 на пути.

    Запись, которую не удалось создать, просто не попадает в словарь: путь получит ``MISSING_ID`` и запрос ответит 404 (не 5xx)."""
    api = "/api/v1/resources"
    values: dict[str, str] = {"group_key": "g1"}
    category = client.get(f"{api}/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    device_type = created_id(client, f"{api}/device-types", {"name": "Тип для проверки", "category_id": category})
    device = created_id(client, f"{api}/devices", {"device_type_id": device_type, "serial_number": "EXT-1", "system_name": "ext-1"})
    created = {
        "diagram_id": created_id(client, "/api/v1/diagrams", {"name": "Диаграмма для проверки"}),
        "device_id": device,
        "interface_id": created_id(client, f"{api}/interfaces", {"physical_device_id": device, "name": "Gi0/1"}),
        "vm_id": created_id(client, f"{api}/vms", {"name": "vm-ext"}),
        "stack_id": created_id(client, f"{api}/device-stacks", {"name": "Стек для проверки"}),
        "vlan_id": created_id(client, f"{api}/vlans", {"vlan_id": 10, "name": "v10"}),
        "domain_id": created_id(client, f"{api}/vlan-domains", {"name": "Домен для проверки"}),
        "item_id": created_id(client, f"{api}/information-systems", {"name": "ИС для проверки"}),
        "template_id": created_id(client, "/api/v1/report-templates", {"name": "Шаблон для проверки", "config": REPORT_CONFIG}),
        "user_id": created_id(client, "/api/v1/auth/users", {"username": "viewer-ext", "password": "Viewer1234", "role": "viewer"}),
    }
    values.update({name: value for name, value in created.items() if value})
    rules = client.get("/api/v1/port-sync/rules")
    if rules.status_code == 200 and rules.json().get("items"):
        values["rule_id"] = str(rules.json()["items"][0]["id"])
    return values


def operations() -> list:
    spec = app.openapi()
    found = []
    for path, item in spec["paths"].items():
        if "{resource}" in path:
            continue  # универсальный CRUD — отдельным тестом, по колонкам модели
        for method in WRITE_METHODS:
            operation = item.get(method)
            content = ((operation or {}).get("requestBody") or {}).get("content", {}).get(JSON_TYPE)
            if content is not None:
                found.append(pytest.param(method, path, content["schema"], id=f"{method.upper()} {path}"))
    return found
