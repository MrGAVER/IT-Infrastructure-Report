"""Код-ревью Н-1: SVG-иконка ограничена по длине, вложенности и числу элементов при записи.

Белый список тегов и атрибутов работал, но размер не проверялся: API принимал (201) SVG в 1 МБ с 150 000 вложенных <g>, хотя экспорт
диаграммы иконки длиннее MAX_CUSTOM_ICON_SVG_LENGTH пропускает. Данные сохранялись и отдавались в каждом GET /resources/diagram-icons.

Запуск: pytest backend/tests/test_review_p1_svg_icon_size_limits.py -v
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.constants import MAX_CUSTOM_ICON_SVG_LENGTH, MAX_SVG_DEPTH, MAX_SVG_NODES
from app.services.diagram_icons import validate_svg_markup

URL = "/api/v1/resources/diagram-icons"
NORMAL_ICON = "".join(
    [
        '<svg viewBox="0 0 24 24"><g fill="none" stroke="#fff">',
        '<rect x="3" y="3" width="18" height="18"/><path d="M3 12h18"/></g></svg>',
    ]
)


def _nested(levels: int) -> str:
    """<svg> — первый уровень, дальше levels-1 вложенных <g>: всего ровно levels уровней."""
    inner = levels - 1
    return "<svg>" + "<g>" * inner + "</g>" * inner + "</svg>"


def _rejected(markup: str) -> str:
    with pytest.raises(HTTPException) as caught:
        validate_svg_markup(markup)
    assert caught.value.status_code == 422
    return str(caught.value.detail)


# --- обычные иконки проходят -----------------------------------------------------------------------------------------------------


def test_a_normal_icon_passes():
    validate_svg_markup(NORMAL_ICON)


def test_a_bare_fragment_without_svg_root_passes():
    validate_svg_markup('<rect width="10" height="10"/><circle r="4"/>')


@pytest.mark.parametrize("markup", [None, "", "   "])
def test_empty_markup_is_not_checked(markup):
    validate_svg_markup(markup)


# --- вложенность -----------------------------------------------------------------------------------------------------------------


def test_nesting_at_the_limit_passes_and_one_more_level_is_rejected():
    validate_svg_markup(_nested(MAX_SVG_DEPTH))
    message = _rejected(_nested(MAX_SVG_DEPTH + 1))
    assert "вложенность" in message and str(MAX_SVG_DEPTH) in message


def test_depth_of_a_bare_fragment_counts_from_its_first_element():
    """У голого фрагмента нет <svg>: первый же элемент — первый уровень (обёртка корня не считается)."""
    validate_svg_markup("<g>" * MAX_SVG_DEPTH + "</g>" * MAX_SVG_DEPTH)
    assert "вложенность" in _rejected("<g>" * (MAX_SVG_DEPTH + 1) + "</g>" * (MAX_SVG_DEPTH + 1))


def test_extreme_nesting_is_rejected_without_recursion_errors():
    """Прежняя проверка принимала 150 000 уровней; новая обходит дерево без рекурсии и не падает на глубине."""
    deep = "<g>" * 30_000 + "</g>" * 30_000
    assert "вложенность" in _rejected(f"<svg>{deep}</svg>")


# --- число элементов -------------------------------------------------------------------------------------------------------------


def test_element_count_at_the_limit_passes_and_one_more_is_rejected():
    validate_svg_markup("<svg>" + "<rect/>" * (MAX_SVG_NODES - 1) + "</svg>")  # вместе с <svg> — ровно MAX_SVG_NODES
    message = _rejected("<svg>" + "<rect/>" * MAX_SVG_NODES + "</svg>")
    assert "элементов" in message and str(MAX_SVG_NODES) in message


# --- длина -----------------------------------------------------------------------------------------------------------------------


def _padded(length: int) -> str:
    prefix, suffix = "<svg><text>", "</text></svg>"
    return prefix + "я" * (length - len(prefix) - len(suffix)) + suffix


def test_length_at_the_limit_passes_and_one_more_character_is_rejected():
    validate_svg_markup(_padded(MAX_CUSTOM_ICON_SVG_LENGTH))
    message = _rejected(_padded(MAX_CUSTOM_ICON_SVG_LENGTH + 1))
    assert "размер" in message


def test_length_is_checked_before_parsing():
    """Не разбор, а длина отклоняет слишком большое: даже разметка с ошибкой синтаксиса получает сообщение о размере."""
    assert "размер" in _rejected("<" * (MAX_CUSTOM_ICON_SVG_LENGTH + 1))


def test_the_original_whitelist_still_applies_to_small_icons():
    assert "не разрешён" in _rejected("<svg><script>alert(1)</script></svg>")
    _rejected('<svg onload="alert(1)"></svg>')


def test_the_first_violation_in_document_order_is_reported():
    message = _rejected("<svg><g><foreignObject/></g><script/></svg>")
    assert "foreignobject" in message.lower()


# --- через API: воспроизведение из ревью -----------------------------------------------------------------------------------------


def test_api_rejects_the_one_megabyte_nesting_case_from_the_review(client):
    markup = "<svg>" + "<g>" * 150_000 + "</g>" * 150_000 + "</svg>"
    assert len(markup) > 1_000_000
    response = client.post(URL, json={"name": "Глубокая", "svg_markup": markup})
    assert response.status_code == 422, response.status_code
    assert "Недопустимое содержимое SVG" in response.json()["detail"]
    assert client.get(URL).json()["items"] == [], "отклонённая иконка не сохраняется"


def test_api_rejects_deep_nesting_on_update_too(client):
    created = client.post(URL, json={"name": "Обычная", "svg_markup": NORMAL_ICON})
    assert created.status_code == 201, created.text
    response = client.put(f"{URL}/{created.json()['id']}", json={"svg_markup": _nested(MAX_SVG_DEPTH + 1)})
    assert response.status_code == 422
    assert client.get(f"{URL}/{created.json()['id']}").json()["svg_markup"] == NORMAL_ICON


def test_api_accepts_a_normal_icon(client):
    response = client.post(URL, json={"name": "Нормальная", "svg_markup": NORMAL_ICON})
    assert response.status_code == 201, response.text


def test_the_length_limit_is_one_constant_for_api_and_export():
    from app.services import diagram_export
    from app.services.diagram_export import _common

    assert diagram_export.MAX_CUSTOM_ICON_SVG_LENGTH == _common.MAX_CUSTOM_ICON_SVG_LENGTH == MAX_CUSTOM_ICON_SVG_LENGTH
