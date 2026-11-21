"""A-10: проверка параметров эндпоинтов отчётов и предпросмотра.

`POST /report-builder/preview` и формирование отчётов доступны роли viewer (и любому клиенту при выключенной
аутентификации), а тело запроса шло в код как есть: `limit=10**9` собирал огромную сетку, `limit="x"`, `config` не-словарь,
`params` и `structural_unit_ids` неподходящих типов давали 500 уже внутри построения отчёта.

Запуск: pytest backend/tests/test_report_endpoint_limits.py -v
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.report_params import (
    MAX_PARAM_VALUE_LENGTH,
    MAX_REPORT_PARAMS,
    MAX_STRUCTURAL_UNIT_IDS,
    parse_config_object,
    parse_preview_limit,
    parse_report_params,
    parse_structural_unit_ids,
)

API = "/api/v1"
VALID_CONFIG = {"sheets": [{"title": "Лист1", "columns": [{"width": 25}], "rows": [{"height": 18, "repeat": True, "data_source": {"root_entity": "information-systems"}, "cells": [{"col": 0, "kind": "field", "path": "name"}]}]}]}


@pytest.fixture()
def report_dir(tmp_path, monkeypatch):
    """Каталог отчётов — временный, одинаковый для всех эндпоинтов; очистку не троттлим между тестами."""
    from app.api import report_builder, reports
    from app.services import report_cleanup

    monkeypatch.setattr(reports, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(report_builder, "REPORT_DIR", tmp_path)
    monkeypatch.setattr(report_cleanup, "_last_age_scan", {})
    return tmp_path


def _files(directory) -> list[str]:
    return sorted(path.name for path in directory.iterdir())


@pytest.fixture()
def template_id(client, report_dir):
    created = client.post(f"{API}/report-templates", json={"name": "Шаблон А-10", "config": VALID_CONFIG})
    assert created.status_code == 201, created.text
    return created.json()["id"]


# ---------------------------------------------------------------------------------------------------------------------
# Предпросмотр: limit и config
# ---------------------------------------------------------------------------------------------------------------------
class TestPreviewLimit:
    @pytest.mark.parametrize("limit", [1, 15, 20, 200])
    def test_values_inside_the_range_are_accepted(self, client, limit):
        response = client.post(f"{API}/report-builder/preview", json={"format": "xlsx", "config": VALID_CONFIG, "limit": limit})
        assert response.status_code == 200, response.text

    def test_missing_limit_means_default(self, client):
        assert client.post(f"{API}/report-builder/preview", json={"format": "xlsx", "config": VALID_CONFIG}).status_code == 200

    @pytest.mark.parametrize("limit", [10**9, 201, 0, -1, "x", "15", 1.5, 15.0, True, False, None, [15], {"a": 1}])
    def test_values_outside_the_range_or_of_wrong_type_are_422(self, client, limit):
        response = client.post(f"{API}/report-builder/preview", json={"format": "xlsx", "config": VALID_CONFIG, "limit": limit})
        assert response.status_code == 422, f"{limit!r}: {response.status_code} {response.text[:200]}"
        assert "limit должен быть целым числом от 1 до 200" in response.json()["detail"]

    def test_huge_limit_is_rejected_before_any_work_is_done(self, client, monkeypatch):
        from app.api import report_builder

        def must_not_run(*args, **kwargs):
            raise AssertionError("предпросмотр не должен собираться при неверном limit")

        monkeypatch.setattr(report_builder, "preview_grid", must_not_run)
        monkeypatch.setattr(report_builder, "preview_rows", must_not_run)
        for fmt in ("xlsx", "docx"):
            assert client.post(f"{API}/report-builder/preview", json={"format": fmt, "config": VALID_CONFIG, "limit": 10**9}).status_code == 422

    def test_docx_preview_uses_the_same_limit_rule(self, client):
        config = {"blocks": [{"type": "table", "root_entity": "information-systems", "columns": [{"header": "Наименование", "source": "field", "path": "name"}]}]}
        assert client.post(f"{API}/report-builder/preview", json={"format": "docx", "config": config, "limit": 20}).status_code == 200
        assert client.post(f"{API}/report-builder/preview", json={"format": "docx", "config": config, "limit": 0}).status_code == 422


class TestPreviewConfigAndPayload:
    @pytest.mark.parametrize("config", ["строка", [1, 2], 5, True, [], ""])
    def test_config_that_is_not_an_object_is_422(self, client, config):
        response = client.post(f"{API}/report-builder/preview", json={"format": "xlsx", "config": config})
        assert response.status_code == 422, response.text
        assert "config должен быть объектом" in response.json()["detail"]

    @pytest.mark.parametrize("body", [{"format": "xlsx"}, {"format": "xlsx", "config": None}, {"format": "xlsx", "config": {}}])
    def test_missing_or_empty_config_is_a_clean_422_from_the_template_validator(self, client, body):
        response = client.post(f"{API}/report-builder/preview", json=body)
        assert response.status_code == 422, response.text

    @pytest.mark.parametrize("body", [[1, 2], "строка", 5, None])
    def test_body_that_is_not_an_object_is_422(self, client, body):
        assert client.post(f"{API}/report-builder/preview", json=body).status_code == 422

    @pytest.mark.parametrize("fmt", [["xlsx"], 5, {"a": 1}, "pdf", None])
    def test_unknown_or_malformed_format_is_422(self, client, fmt):
        assert client.post(f"{API}/report-builder/preview", json={"format": fmt, "config": VALID_CONFIG}).status_code == 422


# ---------------------------------------------------------------------------------------------------------------------
# Формирование отчётов: structural_unit_ids и params во всех трёх POST-эндпоинтах
# ---------------------------------------------------------------------------------------------------------------------
BAD_UNIT_IDS = ["строка", 5, True, {"a": 1}, [1, 2], ["ok", 5], [None], [""], [["nested"]], ["я" * 65], ["x"] * (MAX_STRUCTURAL_UNIT_IDS + 1)]


class TestStructuralUnitIds:
    @pytest.mark.parametrize("value", BAD_UNIT_IDS, ids=lambda v: repr(v)[:30])
    def test_inventory_rejects_bad_ids_without_writing_a_file(self, client, report_dir, value):
        response = client.post(f"{API}/reports/inventory", json={"structural_unit_ids": value})
        assert response.status_code == 422, f"{value!r:.40}: {response.status_code} {response.text[:200]}"
        assert response.json()["detail"] == "structural_unit_ids должен быть списком идентификаторов"
        assert _files(report_dir) == []

    @pytest.mark.parametrize("value", BAD_UNIT_IDS, ids=lambda v: repr(v)[:30])
    def test_structural_appendix_rejects_bad_ids_without_writing_a_file(self, client, report_dir, value):
        response = client.post(f"{API}/reports/structural-appendix", json={"structural_unit_ids": value})
        assert response.status_code == 422, f"{value!r:.40}: {response.status_code} {response.text[:200]}"
        assert _files(report_dir) == []

    @pytest.mark.parametrize("value", BAD_UNIT_IDS, ids=lambda v: repr(v)[:30])
    def test_template_generate_rejects_bad_ids_without_writing_a_file(self, client, report_dir, template_id, value):
        response = client.post(f"{API}/report-templates/{template_id}/generate", json={"structural_unit_ids": value})
        assert response.status_code == 422, f"{value!r:.40}: {response.status_code} {response.text[:200]}"
        assert _files(report_dir) == []

    @pytest.mark.parametrize("value", [None, [], ["единица-1", "единица-2"]])
    def test_valid_ids_are_accepted(self, client, report_dir, template_id, value):
        assert client.post(f"{API}/reports/inventory", json={"structural_unit_ids": value}).status_code == 200
        assert client.post(f"{API}/report-templates/{template_id}/generate", json={"structural_unit_ids": value}).status_code == 200

    def test_missing_body_is_still_fine(self, client, report_dir, template_id):
        assert client.post(f"{API}/reports/inventory").status_code == 200
        assert client.post(f"{API}/report-templates/{template_id}/generate").status_code == 200
        assert client.post(f"{API}/reports/inventory", json=None).status_code == 200

    @pytest.mark.parametrize("path", ["/reports/inventory", "/reports/structural-appendix"])
    @pytest.mark.parametrize("body", [[1, 2], "строка", 5])
    def test_payload_that_is_not_an_object_is_422(self, client, report_dir, path, body):
        assert client.post(f"{API}{path}", json=body).status_code == 422
        assert _files(report_dir) == []

    def test_template_generate_payload_list_is_422(self, client, report_dir, template_id):
        assert client.post(f"{API}/report-templates/{template_id}/generate", json=[1]).status_code == 422
        assert _files(report_dir) == []

    def test_appendix_keeps_its_name_check(self, client, report_dir):
        response = client.post(f"{API}/reports/structural-appendix", json={"is_name": 5})
        assert response.status_code == 422 and "строкой" in response.json()["detail"]


class TestReportParams:
    @pytest.mark.parametrize("params", ["строка", [1], 5, True, [["a", "b"]]])
    def test_params_that_are_not_an_object_are_422(self, client, report_dir, template_id, params):
        response = client.post(f"{API}/report-templates/{template_id}/generate", json={"params": params})
        assert response.status_code == 422, response.text
        assert "params должен быть объектом" in response.json()["detail"]
        assert _files(report_dir) == []

    @pytest.mark.parametrize("value", [{"a": 1}, [1], ["x"]])
    def test_nested_values_are_422(self, client, report_dir, template_id, value):
        response = client.post(f"{API}/report-templates/{template_id}/generate", json={"params": {"report_date": value}})
        assert response.status_code == 422 and "params.report_date" in response.json()["detail"]
        assert _files(report_dir) == []

    def test_too_many_or_too_long_values_are_422(self, client, report_dir, template_id):
        many = {f"k{i}": "x" for i in range(MAX_REPORT_PARAMS + 1)}
        assert client.post(f"{API}/report-templates/{template_id}/generate", json={"params": many}).status_code == 422
        long = {"report_date": "я" * (MAX_PARAM_VALUE_LENGTH + 1)}
        assert client.post(f"{API}/report-templates/{template_id}/generate", json={"params": long}).status_code == 422

    def test_scalars_and_null_are_accepted(self, client, report_dir, template_id):
        params = {"report_date": "23.10.2026", "number": 5, "ratio": 1.5, "flag": True, "empty": None, "limit_text": "я" * MAX_PARAM_VALUE_LENGTH}
        response = client.post(f"{API}/report-templates/{template_id}/generate", json={"params": params})
        assert response.status_code == 200, response.text
        assert len(_files(report_dir)) == 1

    def test_null_and_empty_params_are_accepted(self, client, report_dir, template_id):
        assert client.post(f"{API}/report-templates/{template_id}/generate", json={"params": None}).status_code == 200
        assert client.post(f"{API}/report-templates/{template_id}/generate", json={"params": {}}).status_code == 200

    def test_unknown_template_is_still_404_before_payload_checks(self, client, report_dir):
        assert client.post(f"{API}/report-templates/нет-такого/generate", json={"params": "x"}).status_code == 404


# ---------------------------------------------------------------------------------------------------------------------
# Функции проверки: unit
# ---------------------------------------------------------------------------------------------------------------------
class TestParsers:
    @staticmethod
    def _raises(function, *args) -> str:
        with pytest.raises(HTTPException) as info:
            function(*args)
        assert info.value.status_code == 422
        return info.value.detail

    def test_parse_preview_limit(self):
        assert parse_preview_limit({}) == 15
        assert parse_preview_limit({"limit": 1}) == 1 and parse_preview_limit({"limit": 200}) == 200
        for bad in (0, 201, -5, "5", 2.0, True, None):
            assert "от 1 до 200" in self._raises(parse_preview_limit, {"limit": bad})

    def test_parse_config_object(self):
        assert parse_config_object(None) == {}
        config = {"a": 1}
        assert parse_config_object(config) is config
        assert "config должен быть объектом" in self._raises(parse_config_object, [1])

    def test_parse_structural_unit_ids(self):
        assert parse_structural_unit_ids(None) is None and parse_structural_unit_ids([]) is None
        assert parse_structural_unit_ids(["a", "b"]) == ["a", "b"]
        assert parse_structural_unit_ids(["x"] * MAX_STRUCTURAL_UNIT_IDS) is not None
        for bad in ("a", 0, False, {}, [1], [""], ["x"] * (MAX_STRUCTURAL_UNIT_IDS + 1)):
            self._raises(parse_structural_unit_ids, bad)

    def test_parse_report_params(self):
        assert parse_report_params(None) == {}
        assert parse_report_params({"k": None, "n": 1, "s": "t", "b": False, "f": 0.5}) == {"k": None, "n": 1, "s": "t", "b": False, "f": 0.5}
        for bad in ([], "x", 3, {"k": {}}, {"k": [1]}, {1: "int-key"}):
            self._raises(parse_report_params, bad)
