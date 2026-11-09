"""Код-ревью (раздел 5, backend, п. 1): ``NaN`` и ``±Infinity`` в теле запроса — 422, а не 500.

Найдено системным тестом ``test_no_5xx_on_extreme_input.py``. В JSON-стандарте этих значений нет, но Python-разбор их принимает.
Ширина столбца ``NaN`` в ``config`` шаблона проходила предметную проверку (любое сравнение с ``NaN`` ложно), сохранялась, а ответ с ней
не кодировался — 500 на создание и чтение шаблона. Теперь:

* типизированные модели тел (``RequestBody``) отклоняют нечисловое вещественное значение: ``allow_inf_nan=False``;
* свободный объект ``config`` отчёта проверяет ``reject_non_finite_numbers`` (обход итеративный — вложенность задаёт клиент).

Запуск: pytest backend/tests/test_non_finite_numbers.py -v
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from app.services.report_params import reject_non_finite_numbers

API = "/api/v1"
NON_FINITE = [float("nan"), float("inf"), float("-inf")]


def _config(**cell_overrides) -> dict:
    column = {"width": 25, **cell_overrides}
    return {"sheets": [{"title": "Лист1", "columns": [column], "rows": [{
        "height": 18, "repeat": True, "data_source": {"root_entity": "information-systems"},
        "cells": [{"col": 0, "kind": "field", "path": "name"}]}]}]}


def _post(client, url: str, body: dict, method: str = "post"):
    # json.dumps пишет NaN/Infinity как есть (как и браузерный клиент с нестрогим сериализатором), httpx в json= это запрещает.
    return client.request(method.upper(), url, content=json.dumps(body).encode(), headers={"content-type": "application/json"})


class TestRejectNonFiniteNumbers:
    @pytest.mark.parametrize("value", NON_FINITE)
    def test_rejects_at_any_depth(self, value):
        with pytest.raises(HTTPException) as caught:
            reject_non_finite_numbers({"a": [{"b": {"c": [1, 2, value]}}]}, "config")
        assert caught.value.status_code == 422
        assert caught.value.detail == "config: значения NaN и Infinity не допускаются"

    def test_accepts_ordinary_numbers_booleans_and_strings(self):
        reject_non_finite_numbers({"a": [1, 2.5, -3, 1e308, True, None, "NaN", {"b": 0.0}]}, "config")

    def test_deeply_nested_value_does_not_exhaust_the_recursion_limit(self):
        nested: object = float("nan")
        for _ in range(20_000):  # на рекурсивном обходе это был бы RecursionError → 500
            nested = [nested]
        with pytest.raises(HTTPException):
            reject_non_finite_numbers(nested, "config")


class TestReportConfig:
    @pytest.mark.parametrize("value", NON_FINITE)
    def test_preview_rejects_non_finite_column_width(self, client, value):
        response = _post(client, f"{API}/report-builder/preview", {"format": "xlsx", "config": _config(width=value)})
        assert response.status_code == 422, response.text
        assert response.json()["detail"] == "config: значения NaN и Infinity не допускаются"

    @pytest.mark.parametrize("value", NON_FINITE)
    def test_template_create_and_update_reject_non_finite_numbers(self, client, value):
        created = client.post(f"{API}/report-templates", json={"name": "Шаблон", "config": _config()})
        assert created.status_code == 201, created.text
        template_id = created.json()["id"]
        for method, url in (("post", f"{API}/report-templates"), ("put", f"{API}/report-templates/{template_id}")):
            response = _post(client, url, {"name": "Шаблон 2", "config": _config(width=value)}, method)
            assert response.status_code == 422, f"{method}: {response.status_code} {response.text[:200]}"
            assert "NaN и Infinity" in response.json()["detail"]
        # шаблон не испорчен: читается и отдаёт прежнюю конфигурацию
        assert client.get(f"{API}/report-templates/{template_id}").status_code == 200
        assert client.get(f"{API}/report-templates").status_code == 200


class TestTypedFloatFields:
    @pytest.mark.parametrize("value", NON_FINITE)
    def test_typed_model_rejects_non_finite_float(self, client, value):
        created = client.post(f"{API}/diagrams", json={"name": "Диаграмма"})
        assert created.status_code == 201, created.text
        diagram_id = created.json()["id"]
        body = {"node_positions": {"n1": {"x": value, "y": 1}}}
        response = _post(client, f"{API}/diagrams/{diagram_id}/layout", body, "put")
        assert response.status_code == 422, f"{response.status_code} {response.text[:200]}"
        assert isinstance(response.json()["detail"], str)
