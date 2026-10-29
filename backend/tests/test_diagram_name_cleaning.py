"""A-16: название диаграммы очищается от управляющих символов, а экспорт устойчив к уже сохранённым «грязным» названиям.

Раньше название только `strip()`-илось, а `ascii_fallback` в Content-Disposition исключал лишь `"` и `\\`: диаграмма с названием
`inj\\r\\nX-Injected: yes` создавалась (201), а её экспорт на живом uvicorn обрывался `RuntimeError: Invalid HTTP header value` без
ответа. Разделение ответа сервер блокировал, но экспорт был недоступен, а ошибка попадала в лог как необработанная.

Запуск: pytest backend/tests/test_diagram_name_cleaning.py -v
"""
from __future__ import annotations

from urllib.parse import unquote

import h11
import pytest

from app.api.diagrams import COPY_SUFFIX, MAX_DIAGRAM_NAME_LENGTH, _clean_name
from app.models import SavedDiagram

API = "/api/v1/diagrams"
DIRTY = "inj\r\nX-Injected: yes\r\nSet-Cookie: a=b"
CLEAN = "inj X-Injected: yes Set-Cookie: a=b"
EXPORTS = [("svg", "image/svg+xml"), ("drawio", "application/xml"), ("vsdx", "application/vnd.ms-visio.drawing")]


def _store_diagram(db_session, name: str) -> str:
    """Диаграмма «как до исправления»: прямая запись в БД мимо API."""
    row = SavedDiagram(name=name, scope_filter="{}", group_by="structural_unit", collapse_threshold=20)
    db_session.add(row)
    db_session.commit()
    return row.id


def _assert_header_is_safe(response) -> None:
    """Заголовки принимает настоящий HTTP-стек: h11 (его использует uvicorn) отвергает CR/LF в значении так же, как сервер."""
    disposition = response.headers["content-disposition"]
    assert "\r" not in disposition and "\n" not in disposition
    assert "x-injected" not in response.headers and "set-cookie" not in response.headers
    h11.Response(status_code=200, headers=response.headers.raw)  # LocalProtocolError при недопустимом значении


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (DIRTY, CLEAN),
        ("  Схема\tсети  ", "Схема сети"),
        ("a\x00b\x7fc\x85d e f", "a b c d e f"),
        ("двойной    пробел", "двойной пробел"),
        ("Схема 🌐 «ЦОД» №1", "Схема 🌐 «ЦОД» №1"),
        ("\r\n\t ", ""),
        (None, ""),
        (123, ""),
    ],
)
def test_clean_name(raw, expected):
    assert _clean_name(raw) == expected


class TestCreateAndRename:
    def test_create_strips_control_characters(self, client):
        response = client.post(API, json={"name": DIRTY})
        assert response.status_code == 201, response.text
        assert response.json()["name"] == CLEAN

    def test_exports_of_a_diagram_created_with_dirty_name_work(self, client):
        diagram = client.post(API, json={"name": DIRTY}).json()
        for export_format, media_type in EXPORTS:
            response = client.get(f"{API}/{diagram['id']}/export", params={"format": export_format})
            assert response.status_code == 200, (export_format, response.text)
            assert response.headers["content-type"].startswith(media_type)
            _assert_header_is_safe(response)
            assert unquote(response.headers["content-disposition"].split("filename*=UTF-8''")[1]) == f"{CLEAN}.{export_format}"

    def test_rename_strips_control_characters_and_keeps_uniqueness_check(self, client):
        client.post(API, json={"name": "Занято"})
        diagram = client.post(API, json={"name": "Исходная"}).json()
        renamed = client.put(f"{API}/{diagram['id']}/rename", json={"name": "Новое\r\nназвание\t"})
        assert renamed.status_code == 200 and renamed.json()["name"] == "Новое название"
        assert client.put(f"{API}/{diagram['id']}/rename", json={"name": "Занято\r\n"}).status_code == 409

    @pytest.mark.parametrize("name", ["", "   ", "\r\n\t", None, 5, ["x"]])
    def test_name_without_visible_text_is_rejected_with_422(self, client, name):
        assert client.post(API, json={"name": name}).status_code == 422
        diagram = client.post(API, json={"name": "Есть"}).json()
        assert client.put(f"{API}/{diagram['id']}/rename", json={"name": name}).status_code == 422

    def test_length_is_limited_to_the_column_size(self, client):
        longest = "я" * MAX_DIAGRAM_NAME_LENGTH
        assert client.post(API, json={"name": longest}).status_code == 201
        too_long = client.post(API, json={"name": longest + "я"})
        assert too_long.status_code == 422 and "255" in too_long.json()["detail"]
        diagram = client.post(API, json={"name": "Короткая"}).json()
        assert client.put(f"{API}/{diagram['id']}/rename", json={"name": longest + "я"}).status_code == 422


class TestExistingDirtyNames:
    @pytest.mark.parametrize("export_format", [fmt for fmt, _ in EXPORTS])
    def test_export_of_a_diagram_saved_before_the_fix_does_not_break(self, client, db_session, export_format):
        diagram_id = _store_diagram(db_session, DIRTY)
        response = client.get(f"{API}/{diagram_id}/export", params={"format": export_format})
        assert response.status_code == 200
        _assert_header_is_safe(response)
        assert 'filename="inj__X-Injected: yes__Set-Cookie: a=b.' in response.headers["content-disposition"]

    def test_fallback_name_has_no_separators_or_quotes(self, client, db_session):
        diagram_id = _store_diagram(db_session, 'a/b;c"d\\e\x7ff')
        response = client.get(f"{API}/{diagram_id}/export", params={"format": "svg"})
        assert response.status_code == 200
        _assert_header_is_safe(response)
        assert 'filename="a_b_c_d_e_f.svg"' in response.headers["content-disposition"]

    def test_duplicate_of_a_dirty_diagram_gets_a_clean_name(self, client, db_session):
        diagram_id = _store_diagram(db_session, DIRTY)
        copy = client.post(f"{API}/{diagram_id}/duplicate")
        assert copy.status_code == 201
        assert copy.json()["name"] == f"{CLEAN}{COPY_SUFFIX}"
        assert client.get(f"{API}/{copy.json()['id']}/export", params={"format": "svg"}).status_code == 200


class TestDuplicateNameFitsTheColumn:
    def test_copy_of_the_longest_name_fits_with_the_suffix(self, client):
        source = client.post(API, json={"name": "я" * MAX_DIAGRAM_NAME_LENGTH}).json()
        first = client.post(f"{API}/{source['id']}/duplicate")
        second = client.post(f"{API}/{source['id']}/duplicate")
        assert first.status_code == second.status_code == 201
        names = [first.json()["name"], second.json()["name"]]
        assert all(len(name) <= MAX_DIAGRAM_NAME_LENGTH for name in names)
        assert names[0].endswith(COPY_SUFFIX) and names[1].endswith(" 2") and names[0] != names[1]
