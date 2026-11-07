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

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Boolean, Date, DateTime, Float, Integer, Numeric, String, Text
from sqlalchemy.inspection import inspect

from openapi_walk import MISSING_ID, REPORT_CONFIG, Builder, fill_path, operations, seed_path_values, send, variants

from app.main import app
from app.registry import MODEL_MAP, READONLY_RESOURCES
from app.services.crud.columns import allowed_columns


EXTREME_INTEGERS = (10**30, -(10**30), 2**31, -(2**31) - 1, 2**63)
EXTREME_FLOATS = (1e308, -1e308, float("nan"), float("inf"), float("-inf"))
HUGE_STRING = "x" * 1_000_000
NESTING = 50_000  # глубина вложенности «сырых» тел: json.loads упирается в предел рекурсии — ответом должен быть 4xx, а не 500
RAW_BODIES: tuple[tuple[str, bytes], ...] = (
    ("массив глубиной 50000", b"[" * NESTING + b"]" * NESTING),
    ("объект глубиной 50000", b'{"a":' * NESTING + b"1" + b"}" * NESTING),
    ("оборванный JSON", b'{"a": '),
    ("пустое тело", b""),
    ("NaN в корне", b"NaN"),
)

EXAMPLE_BODIES: dict[tuple[str, str], dict] = {
    ("post", "/api/v1/report-templates"): {"name": "Шаблон", "config": REPORT_CONFIG},
    ("put", "/api/v1/report-templates/{template_id}"): {"name": "Шаблон", "config": REPORT_CONFIG},
    ("post", "/api/v1/report-builder/preview"): {"format": "xlsx", "config": REPORT_CONFIG, "limit": 15},
    ("post", "/api/v1/report-templates/{template_id}/generate"): {"params": {"a": 1, "b": "x"}, "structural_unit_ids": ["x"]},
    ("put", "/api/v1/diagrams/{diagram_id}/layout"): {"node_positions": {"n1": {"x": 1, "y": 2}}, "viewport": {"x": 0, "y": 0, "zoom": 1}},
    ("put", "/api/v1/diagrams/{diagram_id}/groups/{group_key}"): {"is_collapsed": True, "custom_threshold": 5},
}

_REPORTED_TEXT = 160  # знаков ответа в сообщении об ошибке: тело ответа может эхом возвращать мегабайт


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
    for variant in variants(spec, schema):
        builder = Builder(spec)
        builder.build(variant, "$", {})
        numeric = [path for path, kind in builder.leaves if kind in {"integer", "number", "any"}]
        floats = [path for path, kind in builder.leaves if kind in {"number", "any"}]
        strings = [path for path, kind in builder.leaves if kind in {"string", "any"}]

        def with_value(paths: list[str], value: Any) -> Any:
            return Builder(spec).build(variant, "$", dict.fromkeys(paths, value))

        if numeric:
            for value in EXTREME_INTEGERS:
                yield f"целое {value!r}", with_value(numeric, value)
        if floats:
            for value in EXTREME_FLOATS:
                yield f"вещественное {value!r}", with_value(floats, value)
        for leaf in strings:
            yield f"строка 1 МБ в {leaf}", with_value([leaf], HUGE_STRING)


OPERATIONS = operations()


# --- тесты -------------------------------------------------------------------------------------------------------------------

def test_the_walk_finds_the_write_endpoints():
    # Охрана самого теста: если обход схемы перестанет находить операции, остальные тесты станут пустыми и «зелёными».
    assert len(OPERATIONS) >= 30
    assert any(param.id == "POST /api/v1/diagrams" for param in OPERATIONS)


@pytest.mark.parametrize(("method", "path", "schema"), OPERATIONS)
def test_extreme_values_never_give_5xx(client, db_session, method, path, schema):
    spec = app.openapi()
    url = fill_path(path, seed_path_values(client))
    bodies = [*extreme_bodies(spec, schema), *RAW_BODIES]
    if (method, path) in EXAMPLE_BODIES:
        bodies += list(extreme_bodies_from_example(EXAMPLE_BODIES[(method, path)]))
    failures = []
    for label, body in bodies:
        status, text = send(client, db_session, method, url, body)
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
            status, text = send(client, db_session, method, url, body)
            if status >= 500:
                failures.append(f"{method.upper()} {label} → {status}: {text[:_REPORTED_TEXT]}")
    assert not failures, f"{resource}: 5xx на экстремальных значениях:\n" + "\n".join(failures)
