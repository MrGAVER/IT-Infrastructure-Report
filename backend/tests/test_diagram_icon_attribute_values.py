"""
Код-ревью r3, A-03: валидатор SVG-иконок (services/diagram_icons.validate_svg_markup) не должен отвергать безобидные значения атрибутов.

Раньше любое значение любого атрибута, содержащее подстроку «script» или «expression(», давало 422 «содержит исполняемый код»:
отклонялись `id="description"`, `aria-label="Transcript"`, `class="subscription"` — а такие атрибуты обычны в иконках из Inkscape и Figma.
Опасное закрыто другими рубежами (белый список тегов, запрет on*, style, href только на #id, url() только на #id), поэтому подстрочная
проверка оставлена только как проверка исполняемых СХЕМ с нормализацией: браузер игнорирует перевод строки, табуляцию и пробелы внутри
схемы (`java\\nscript:`), поэтому сравнивать надо после их удаления.

Запуск: pytest backend/tests/test_diagram_icon_attribute_values.py -v
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.diagram_icons import validate_svg_markup


def _icon(attribute: str, value: str) -> str:
    """Иконка, в которой проверяемое значение лежит в атрибуте `attribute` разрешённого тега (значение — готовая XML-запись)."""
    return f'<svg viewBox="0 0 24 24"><rect width="24" height="24" {attribute}="{value}"/></svg>'


# --- безобидные значения со словом «script» принимаются ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attribute", "value"),
    [
        ("id", "description"),  # «description» содержит «script»
        ("aria-label", "Transcript"),
        ("class", "subscription"),
        ("data-name", "Manuscript"),
        ("class", "javascript-icon"),  # слово без двоеточия — не схема
        ("id", "expression"),  # без скобки — не выражение
        ("fill", "#4f7cff"),
        ("id", "descriptor-1 subscript"),
    ],
)
def test_harmless_attribute_values_with_script_inside_are_accepted(attribute, value):
    validate_svg_markup(_icon(attribute, value))


def test_a_use_reference_to_an_element_with_such_an_id_is_accepted():
    # Реальная форма из редакторов: id со словом «description» и ссылка на него внутри документа.
    validate_svg_markup('<svg><defs><g id="description"><rect width="5" height="5"/></g></defs><use href="#description"/><use href="#a"/></svg>')


# --- исполняемые схемы по-прежнему отвергаются, в том числе спрятанные от подстрочного сравнения ------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "java&#10;script:alert(1)",  # перевод строки внутри схемы: браузер его выбрасывает
        "JaVa&#9;ScRiPt:x",  # табуляция и разный регистр
        "  javascript:alert(1)",  # ведущие пробелы
        "java&#13;&#10;&#32;script:x",
        "&#106;avascript:alert(1)",  # HTML-сущность: XML-парсер раскрывает её до проверки
        "vbscript:x",
        "VBScript:msgbox(1)",
        "expression(alert(1))",
        "Expression (alert(1))",
        "ex&#9;pression(alert(1))",
    ],
)
def test_executable_schemes_are_rejected_in_any_attribute(value):
    # data-x не входит ни в один другой рубеж проверки: отвергает именно проверка схем.
    with pytest.raises(HTTPException) as exc_info:
        validate_svg_markup(_icon("data-x", value))
    assert exc_info.value.status_code == 422


def test_the_message_names_the_attribute_the_tag_and_the_scheme_problem():
    with pytest.raises(HTTPException) as exc_info:
        validate_svg_markup(_icon("data-x", "javascript:alert(1)"))
    detail = exc_info.value.detail
    assert "data-x" in detail and "rect" in detail
    assert "схем" in detail  # «ссылку с исполняемой схемой», а не расплывчатое «исполняемый код»
    assert "исполняемый код" not in detail


# --- остальные рубежи не ослаблены ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "markup",
    [
        '<svg><rect onclick="x"/></svg>',
        '<svg><rect style="fill:red"/></svg>',
        '<svg><use href="https://evil.example/x.svg#a"/></svg>',
        '<svg><use href="javascript:alert(1)"/></svg>',
        '<svg><rect fill="url(https://evil.example/x)"/></svg>',
        '<svg><rect fill="url(javascript:alert(1))"/></svg>',
        "<svg><script>alert(1)</script></svg>",
    ],
)
def test_other_defences_still_reject(markup):
    with pytest.raises(HTTPException):
        validate_svg_markup(markup)
