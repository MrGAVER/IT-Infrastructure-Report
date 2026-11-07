"""Код-ревью (раздел 5, backend, п. 1): ни один записывающий эндпоинт не отвечает 5xx на экстремальные значения.

Единственный подтверждённый дефект ревью (BE-01) был классом «неограниченный ввод → исключение драйвера БД → 500»: целое
``10**30`` в поле порога диаграммы не превращалось в 4xx. Тест ловит такие дефекты в новых и будущих моделях запросов сам:
обходит ``app.openapi()``, для каждой операции с телом JSON строит тела по схеме и подставляет в них

* в целые и вещественные поля — ``10**30``, ``-10**30``, ``2**31``, ``2**63``, ``1e308``, ``NaN``, ``±Infinity``;
* в строковые — строку в 1 МБ (по одному полю за запрос: тело больше ``MAX_REQUEST_BODY_BYTES`` отвечало бы 413, не доходя до модели).

Остальные поля заполняются «обычными» значениями, чтобы запрос по возможности проходил дальше проверки формы. Допустим любой ответ
ниже 500 (200, 404, 413, 422 …). Исключение, которое ``TestClient`` поднимает из-за необработанной ошибки сервера, — это тот же 500.

Универсальный CRUD (``/resources/{resource}``) схемы тела не имеет (произвольный объект), поэтому для него значения подставляются в
колонки модели по типу колонки — отдельным тестом ниже.

Запуск: pytest backend/tests/test_no_5xx_on_extreme_input.py -v
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Numeric, String, Text
from sqlalchemy.inspection import inspect

from app.main import app
from app.registry import MODEL_MAP, READONLY_RESOURCES
from app.services.crud.columns import allowed_columns

JSON_TYPE = "application/json"
WRITE_METHODS = ("post", "put", "patch")

EXTREME_INTEGERS = (10**30, -(10**30), 2**31, -(2**31) - 1, 2**63)
EXTREME_FLOATS = (1e308, -1e308, float("nan"), float("inf"), float("-inf"))
HUGE_STRING = "x" * 1_000_000
# Для объекта без описанных полей (произвольный dict: правила синхронизации портов, сверка) — ключи, которые реально читают сервисы.
GENERIC_KEYS = ("name", "description", "enabled", "priority", "apply", "action", "ids", "rule_id", "connection_ids", "plan_hash", "confirm", "limit", "offset")
MAX_DEPTH = 4
NESTING = 50_000  # глубина вложенности «сырых» тел: json.loads упирается в предел рекурсии — ответом должен быть 4xx, а не 500
RAW_BODIES: tuple[tuple[str, bytes], ...] = (
    ("массив глубиной 50000", b"[" * NESTING + b"]" * NESTING),
    ("объект глубиной 50000", b'{"a":' * NESTING + b"1" + b"}" * NESTING),
    ("оборванный JSON", b'{"a": '),
    ("пустое тело", b""),
    ("NaN в корне", b"NaN"),
)
PATH_PARAM = re.compile(r"\{(\w+)\}")
MISSING_ID = "does-not-exist"

# Допустимое описание листа отчёта: схема OpenAPI называет ``config`` просто объектом, поэтому глубокие поля (ширина столбца, высота
# строки …) обход по схеме не видит. Для таких операций экстремальные значения подставляются в листья готового примера тела.
REPORT_CONFIG = {"sheets": [{"title": "Лист1", "columns": [{"width": 25}], "rows": [{
    "height": 18, "repeat": True, "data_source": {"root_entity": "information-systems", "limit": 5},
    "cells": [{"col": 0, "kind": "field", "path": "name"}]}]}]}
EXAMPLE_BODIES: dict[tuple[str, str], dict] = {
    ("post", "/api/v1/report-templates"): {"name": "Шаблон", "config": REPORT_CONFIG},
    ("put", "/api/v1/report-templates/{template_id}"): {"name": "Шаблон", "config": REPORT_CONFIG},
    ("post", "/api/v1/report-builder/preview"): {"format": "xlsx", "config": REPORT_CONFIG, "limit": 15},
    ("post", "/api/v1/report-templates/{template_id}/generate"): {"params": {"a": 1, "b": "x"}, "structural_unit_ids": ["x"]},
    ("put", "/api/v1/diagrams/{diagram_id}/layout"): {"node_positions": {"n1": {"x": 1, "y": 2}}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
    ("put", "/api/v1/diagrams/{diagram_id}/groups/{group_key}"): {"is_collapsed": True, "custom_threshold": 5},
}

_PLAIN_STRING = "a"
_REPORTED_TEXT = 160  # знаков ответа в сообщении об ошибке: тело ответа может эхом возвращать мегабайт


# --- обход схемы OpenAPI ---------------------------------------------------------------------------------------------------

def _deref(spec: dict, schema: dict) -> dict:
    """Раскрывает ``$ref`` (на любую глубину цепочки ссылок)."""
    while "$ref" in schema:
        node: Any = spec
        for part in schema["$ref"].removeprefix("#/").split("/"):
            node = node[part]
        schema = node
    return schema


def _variants(spec: dict, schema: dict) -> list[dict]:
    """Варианты верхнего уровня: для ``anyOf``/``oneOf`` (отчёты принимают объект или null) — каждый вариант, кроме null."""
    schema = _deref(spec, schema)
    options = schema.get("anyOf") or schema.get("oneOf")
    if not options:
        return [schema]
    return [variant for option in options for variant in _variants(spec, option) if variant.get("type") != "null"]


class _Builder:
    """Строит тело запроса по схеме. ``leaves`` собирает пути листьев (путь, вид) при первом проходе; ``overrides`` подменяет значения листьев."""

    def __init__(self, spec: dict) -> None:
        self.spec = spec
        self.leaves: list[tuple[str, str]] = []

    def build(self, schema: dict, path: str, overrides: dict[str, Any], depth: int = 0) -> Any:
        schema = _deref(self.spec, schema)
        options = schema.get("anyOf") or schema.get("oneOf")
        if options:  # вложенный союз — первый вариант, кроме null
            schema = next((_deref(self.spec, o) for o in options if _deref(self.spec, o).get("type") != "null"), {})
        if "allOf" in schema:
            schema = _deref(self.spec, schema["allOf"][0])
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


def _example_leaves(node: Any, path: tuple = ()) -> Iterator[tuple[tuple, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _example_leaves(value, (*path, key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _example_leaves(value, (*path, index))
    else:
        yield path, node


def _with_leaf(node: Any, path: tuple, value: Any) -> Any:
    """Копия примера, где лист по ``path`` заменён на ``value``."""
    if not path:
        return value
    head, *rest = path
    if isinstance(node, dict):
        return {key: (_with_leaf(sub, tuple(rest), value) if key == head else sub) for key, sub in node.items()}
    return [_with_leaf(sub, tuple(rest), value) if index == head else sub for index, sub in enumerate(node)]


def extreme_bodies_from_example(example: dict) -> Iterator[tuple[str, Any]]:
    """Экстремальные значения в каждый числовой и строковый лист готового примера тела — по одному листу за запрос."""
    for path, leaf in _example_leaves(example):
        label = ".".join(str(part) for part in path)
        if isinstance(leaf, bool) or leaf is None:
            continue
        if isinstance(leaf, (int, float)):
            for value in (*EXTREME_INTEGERS, *EXTREME_FLOATS):
                yield f"{label} = {value!r}", _with_leaf(example, path, value)
        elif isinstance(leaf, str):
            yield f"{label} = строка 1 МБ", _with_leaf(example, path, HUGE_STRING)


def extreme_bodies(spec: dict, schema: dict) -> Iterator[tuple[str, Any]]:
    """(подпись, тело) для всех экстремальных значений, применимых к листьям схемы."""
    for variant in _variants(spec, schema):
        builder = _Builder(spec)
        builder.build(variant, "$", {})
        numeric = [path for path, kind in builder.leaves if kind in {"integer", "number", "any"}]
        floats = [path for path, kind in builder.leaves if kind in {"number", "any"}]
        strings = [path for path, kind in builder.leaves if kind in {"string", "any"}]

        def with_value(paths: list[str], value: Any) -> Any:
            return _Builder(spec).build(variant, "$", dict.fromkeys(paths, value))

        if numeric:
            for value in EXTREME_INTEGERS:
                yield f"целое {value!r}", with_value(numeric, value)
        if floats:
            for value in EXTREME_FLOATS:
                yield f"вещественное {value!r}", with_value(floats, value)
        for leaf in strings:
            yield f"строка 1 МБ в {leaf}", with_value([leaf], HUGE_STRING)


# --- отправка запроса -------------------------------------------------------------------------------------------------------

def _send(client, db_session, method: str, url: str, body: Any) -> tuple[int, str]:
    """(статус, начало ответа). ``body`` — объект (кодируется в JSON) или готовые байты. Необработанное исключение сервера — 500:
    ``TestClient`` поднимает его в тест вместо ответа."""
    content = body if isinstance(body, bytes) else json.dumps(body).encode()
    try:
        response = client.request(method.upper(), url, content=content, headers={"content-type": JSON_TYPE})
    except Exception as exc:  # noqa: BLE001 — любое исключение приложения здесь и есть найденный дефект
        db_session.rollback()  # общая сессия теста могла остаться в оборванной транзакции — следующие запросы не должны падать из-за неё
        return 500, f"{type(exc).__name__}: {exc}"
    return response.status_code, response.text


def _fill_path(path: str, values: dict[str, str]) -> str:
    return PATH_PARAM.sub(lambda match: values.get(match.group(1), MISSING_ID), path)


def _created_id(client, url: str, body: dict) -> str | None:
    response = client.post(url, json=body)
    return str(response.json()["id"]) if response.status_code == 201 else None


def _seed_path_values(client) -> dict[str, str]:
    """Существующие родительские записи — чтобы тело доходило до записи в БД, а не обрывалось 404 на пути.

    Запись, которую не удалось создать, просто не попадает в словарь: путь получит ``MISSING_ID`` и запрос ответит 404 (не 5xx)."""
    api = "/api/v1/resources"
    values: dict[str, str] = {"group_key": "g1"}
    category = client.get(f"{api}/device-categories", params={"limit": 1}).json()["items"][0]["id"]
    device_type = _created_id(client, f"{api}/device-types", {"name": "Тип для проверки", "category_id": category})
    device = _created_id(client, f"{api}/devices", {"device_type_id": device_type, "serial_number": "EXT-1", "system_name": "ext-1"})
    created = {
        "diagram_id": _created_id(client, "/api/v1/diagrams", {"name": "Диаграмма для проверки"}),
        "device_id": device,
        "interface_id": _created_id(client, f"{api}/interfaces", {"physical_device_id": device, "name": "Gi0/1"}),
        "vm_id": _created_id(client, f"{api}/vms", {"name": "vm-ext"}),
        "stack_id": _created_id(client, f"{api}/device-stacks", {"name": "Стек для проверки"}),
        "vlan_id": _created_id(client, f"{api}/vlans", {"vlan_id": 10, "name": "v10"}),
        "domain_id": _created_id(client, f"{api}/vlan-domains", {"name": "Домен для проверки"}),
        "item_id": _created_id(client, f"{api}/information-systems", {"name": "ИС для проверки"}),
        "template_id": _created_id(client, "/api/v1/report-templates", {"name": "Шаблон для проверки", "config": REPORT_CONFIG}),
        "user_id": _created_id(client, "/api/v1/auth/users", {"username": "viewer-ext", "password": "Viewer1234", "role": "viewer"}),
    }
    values.update({name: value for name, value in created.items() if value})
    rules = client.get("/api/v1/port-sync/rules")
    if rules.status_code == 200 and rules.json().get("items"):
        values["rule_id"] = str(rules.json()["items"][0]["id"])
    return values


def _operations() -> list:
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


OPERATIONS = _operations()


# --- тесты -------------------------------------------------------------------------------------------------------------------

def test_the_walk_finds_the_write_endpoints():
    # Охрана самого теста: если обход схемы перестанет находить операции, остальные тесты станут пустыми и «зелёными».
    assert len(OPERATIONS) >= 30
    assert any(param.id == "POST /api/v1/diagrams" for param in OPERATIONS)


@pytest.mark.parametrize(("method", "path", "schema"), OPERATIONS)
def test_extreme_values_never_give_5xx(client, db_session, method, path, schema):
    spec = app.openapi()
    url = _fill_path(path, _seed_path_values(client))
    bodies = [*extreme_bodies(spec, schema), *RAW_BODIES]
    if (method, path) in EXAMPLE_BODIES:
        bodies += list(extreme_bodies_from_example(EXAMPLE_BODIES[(method, path)]))
    failures = []
    for label, body in bodies:
        status, text = _send(client, db_session, method, url, body)
        if status >= 500:
            failures.append(f"{label} → {status}: {text[:_REPORTED_TEXT]}")
    assert not failures, f"{method.upper()} {url} ответил 5xx:\n" + "\n".join(failures)


# --- универсальный CRUD ------------------------------------------------------------------------------------------------------

WRITABLE_RESOURCES = sorted(set(MODEL_MAP) - READONLY_RESOURCES)
GENERIC_CRUD_PATH = "/api/v1/resources"


def _column_extremes(column) -> tuple[Any, ...]:
    """Экстремальные значения для колонки по её типу; для остальных типов — сверхбольшое целое."""
    if isinstance(column.type, Boolean):
        return (10**30,)
    if isinstance(column.type, Integer):
        return (10**30, 2**31, -(2**31) - 1)
    if isinstance(column.type, (Float, Numeric)):
        return (1e308, float("nan"), float("inf"))
    if isinstance(column.type, (String, Text)):
        return ("x" * 100_000,)
    if isinstance(column.type, (Date, DateTime)):
        return (10**30, "9999-99-99")
    return (10**30,)


def _generic_cases(resource: str) -> Iterator[tuple[str, dict[str, Any]]]:
    columns = {c.key: c for c in inspect(MODEL_MAP[resource]).columns}
    for name in sorted(allowed_columns(MODEL_MAP[resource])):
        for value in _column_extremes(columns[name]):
            yield f"{name}={str(value)[:20]!r}", {name: value}


@pytest.mark.parametrize("resource", WRITABLE_RESOURCES)
def test_generic_crud_extreme_values_never_give_5xx(client, db_session, resource):
    failures = []
    for label, body in _generic_cases(resource):
        for method, url in (("post", f"{GENERIC_CRUD_PATH}/{resource}"), ("put", f"{GENERIC_CRUD_PATH}/{resource}/{MISSING_ID}")):
            status, text = _send(client, db_session, method, url, body)
            if status >= 500:
                failures.append(f"{method.upper()} {label} → {status}: {text[:_REPORTED_TEXT]}")
    assert not failures, f"{resource}: 5xx на экстремальных значениях:\n" + "\n".join(failures)
