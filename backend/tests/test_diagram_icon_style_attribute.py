"""R1-06 код-ревью: серверная проверка SVG согласована с клиентом по атрибуту `style`.

Клиент (`frontend-vue/src/utils/sanitizeSvg.ts`) вырезает атрибут `style`, а сервер его допускал (проверяя лишь `url()` и «script»
внутри значения): иконка со `style` сохранялась, но отрисовывалась иначе, чем рассчитывал автор. Теперь при ЗАПИСИ (создание и изменение
иконки) `style` отвергается с понятным сообщением — два фильтра дают один результат. Уже сохранённые иконки со `style` не отвергаются при
чтении и экспорте: проверка вызывается только из валидатора записи.

Запуск: pytest backend/tests/test_diagram_icon_style_attribute.py -v
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models import DiagramIcon
from app.services.diagram_export import _standalone_custom_svg
from app.services.diagram_icons import validate_svg_markup

ICONS = "/api/v1/resources/diagram-icons"
STYLED = '<svg viewBox="0 0 24 24"><rect width="24" height="24" style="fill:red"/></svg>'
PLAIN = '<svg viewBox="0 0 24 24"><rect width="24" height="24" fill="red"/></svg>'


@pytest.mark.parametrize(
    "markup",
    [
        STYLED,
        '<rect style="fill:red"/>',  # голый фрагмент
        '<svg><g><rect STYLE="fill:red"/></g></svg>',  # регистр имени атрибута
        '<svg><text style="font-weight:bold">x</text></svg>',
        '<svg><rect style=""/></svg>',  # даже пустой: клиент вырежет его целиком
    ],
)
def test_validator_rejects_the_style_attribute_with_a_clear_message(markup):
    with pytest.raises(HTTPException) as exc_info:
        validate_svg_markup(markup)
    assert exc_info.value.status_code == 422
    detail = exc_info.value.detail
    assert "style" in detail and "fill" in detail and "stroke" in detail  # называет атрибут и подсказывает замену


def test_message_names_the_offending_tag():
    with pytest.raises(HTTPException) as exc_info:
        validate_svg_markup('<svg><circle r="3" style="fill:red"/></svg>')
    assert "circle" in exc_info.value.detail


@pytest.mark.parametrize("markup", [PLAIN, '<svg><rect class="style" id="style" data-style="x" fill="#fff" stroke="#000"/></svg>', '<svg><text>style="x"</text></svg>'])
def test_validator_still_accepts_icons_that_only_mention_style(markup):
    validate_svg_markup(markup)  # имя «style» — только у самого атрибута; значения и другие атрибуты не затрагиваются


# --- Запись через API ------------------------------------------------------------------------------------------------------------
def test_creating_an_icon_with_style_gives_422(client):
    response = client.post(ICONS, json={"name": "Со стилем", "svg_markup": STYLED})
    assert response.status_code == 422
    assert "style" in response.text and "rect" in response.text


def test_updating_an_icon_to_use_style_gives_422_and_keeps_the_old_markup(client):
    icon = client.post(ICONS, json={"name": "Чистая", "svg_markup": PLAIN}).json()
    response = client.put(f"{ICONS}/{icon['id']}", json={"name": "Чистая", "svg_markup": STYLED})
    assert response.status_code == 422
    assert client.get(f"{ICONS}/{icon['id']}").json()["svg_markup"] == PLAIN


def test_icon_without_style_is_saved_and_updated(client):
    icon = client.post(ICONS, json={"name": "Без стиля", "svg_markup": PLAIN})
    assert icon.status_code == 201, icon.text
    updated = client.put(f"{ICONS}/{icon.json()['id']}", json={"name": "Без стиля 2", "svg_markup": '<svg><circle r="3" fill="blue"/></svg>'})
    assert updated.status_code == 200, updated.text


# --- Старые иконки читаются и экспортируются ----------------------------------------------------------------------------------------
@pytest.fixture()
def legacy_icon(db_session) -> DiagramIcon:
    """Иконка, сохранённая до появления правила: в БД она попала мимо валидатора записи."""
    icon = DiagramIcon(name="Старая со стилем", svg_markup=STYLED)
    db_session.add(icon)
    db_session.commit()
    return icon


def test_existing_icon_with_style_is_still_readable(client, legacy_icon):
    one = client.get(f"{ICONS}/{legacy_icon.id}")
    assert one.status_code == 200 and one.json()["svg_markup"] == STYLED
    listed = client.get(ICONS, params={"limit": 50}).json()["items"]
    assert any(item["id"] == legacy_icon.id and item["svg_markup"] == STYLED for item in listed)


def test_existing_icon_with_style_is_still_exported():
    document = _standalone_custom_svg({"mode": "custom", "svg_markup": STYLED})
    assert document is not None and "rect" in document  # экспорт не вызывает проверку записи и не отвергает старую иконку
