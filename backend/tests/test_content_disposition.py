"""
Код-ревью r3, ИА-03 (и ИА-06, вторая часть): заголовок Content-Disposition при скачивании диаграммы.

Раньше значение `filename*` строилось как `quote(filename)`, а у `quote` по умолчанию `safe="/"`: название диаграммы с «/»
попадало в заголовок со слэшем (ASCII-вариант слэш уже заменял на «_»). Теперь сборка — в функции `_content_disposition`, слэш
кодируется как %2F.

Запуск: pytest backend/tests/test_content_disposition.py -v
"""

from __future__ import annotations

from urllib.parse import unquote

import pytest

from app.api.diagrams import _content_disposition

API = "/api/v1/diagrams"


def _encoded_part(header: str) -> str:
    return header.split("filename*=UTF-8''")[1]


def test_slash_in_the_name_is_percent_encoded_in_the_extended_filename():
    header = _content_disposition("План/А.vsdx", "diagram.vsdx")
    assert _encoded_part(header) == "%D0%9F%D0%BB%D0%B0%D0%BD%2F%D0%90.vsdx"
    assert unquote(_encoded_part(header)) == "План/А.vsdx"  # клиент получит исходное имя; замену «/» делает он сам (ИБ-01)


def test_slash_in_the_name_is_replaced_in_the_ascii_fallback():
    header = _content_disposition("План/А.vsdx", "diagram.vsdx")
    assert header.split("; filename*=")[0] == 'attachment; filename="______.vsdx"'  # «План» + «/» + «А» — шесть символов вне ASCII-набора
    assert "/" not in header


def test_a_plain_ascii_name_is_kept_as_is():
    assert _content_disposition("plan.svg", "diagram.svg") == """attachment; filename="plan.svg"; filename*=UTF-8''plan.svg"""


@pytest.mark.parametrize("char", ['"', "\\", ";", "/"])
def test_characters_that_break_the_header_are_replaced_in_the_fallback_and_encoded_in_the_extended_name(char):
    header = _content_disposition(f"a{char}b.svg", "diagram.svg")
    assert header.startswith('attachment; filename="a_b.svg"; ')
    assert unquote(_encoded_part(header)) == f"a{char}b.svg"
    assert char not in _encoded_part(header)  # в percent-кодированной части этих символов нет вовсе


def test_an_empty_name_falls_back_to_the_default_file_name():
    assert _content_disposition("", "diagram.vsdx").startswith('attachment; filename="diagram.vsdx"; ')


def test_the_header_can_be_sent_over_http():
    """Заголовок состоит только из символов latin-1 (иначе Starlette не смог бы его закодировать) — даже для кириллицы и эмодзи."""
    header = _content_disposition("Схема 🌐 «ЦОД» №1.drawio", "diagram.drawio")
    header.encode("latin-1")
    assert unquote(_encoded_part(header)) == "Схема 🌐 «ЦОД» №1.drawio"


@pytest.mark.parametrize("export_format", ["svg", "drawio"])
def test_export_of_a_diagram_with_a_slash_in_the_name(client, export_format):
    created = client.post(API, json={"name": "План/А"})
    assert created.status_code == 201
    response = client.get(f"{API}/{created.json()['id']}/export", params={"format": export_format})
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert _encoded_part(disposition) == f"%D0%9F%D0%BB%D0%B0%D0%BD%2F%D0%90.{export_format}"
    assert "/" not in disposition
