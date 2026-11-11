"""Иконки узлов для экспортёров: SVG-глиф категории и пользовательская (custom) иконка — нормализация разметки, data URI для .svg/.drawio
и растеризация в PNG (resvg_py) для .vsdx. Все функции чистые: на входе дескриптор иконки, на выходе строка/байты либо None.
"""

from __future__ import annotations

import base64
import logging
import re
from urllib.parse import quote

from ._common import (
    CUSTOM_ICON_BACKGROUND_COLOR,
    CUSTOM_ICON_PNG_SCALE,
    CUSTOM_ICON_TILE_HEIGHT,
    CUSTOM_ICON_TILE_PADDING,
    CUSTOM_ICON_TILE_RADIUS,
    MAX_CUSTOM_ICON_SVG_LENGTH,
    NODE_HEIGHT,
    NODE_WIDTH,
    _SVG_NS_URI,
    _SVG_ROOT_TAG,
    _XLINK_NS_URI,
)

logger = logging.getLogger(__name__)


def _glyph_data_uri(glyph: str) -> str:
    """SVG-глиф категории (icon["glyph"], см. diagram_icons.py:SHAPE_GLYPHS) как data URI для
    .drawio (находка №3 отчёта, Фаза 2 п.2; узнаваемая иконка вместо мелкого акцента — находка
    №5, Фаза 3 п.5). mxGraph/draw.io поддерживает style="shape=image;image=<url>" с любым URL,
    включая data: — это заметно надёжнее и дешевле, чем воспроизводить path через собственный
    (недокументированный публично) формат stencil-шаблонов draw.io.
    Percent-encoding, а не base64: drawpyo.Object.apply_style_string() режет значение стиля по
    ПЕРВОМУ "=" в строке (см. _add_and_set_style_attrib ниже, который мы поэтому вызываем
    напрямую, а не через apply_style_string) — base64-padding ("==") сломал бы декодирование,
    percent-encoded URI такого символа не содержит.
    glyph — фрагмент разметки (rect/circle/path), а не готовый <path d=...> — те же элементы без
    жёсткого fill/stroke, что и в _svg_node; fill+color на обёртке ниже дают им обоим по цепочке
    наследования один и тот же белый цвет."""
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="rgba(255,255,255,0.9)" color="rgba(255,255,255,0.9)">{glyph}</g></svg>'
    return f"data:image/svg+xml,{quote(svg)}"


def _rasterize_glyph_png(glyph: str) -> bytes:
    """Растрирует SVG-глиф категории (icon["glyph"]) в PNG с прозрачным фоном — для .vsdx
    (находка №5 отчёта, Фаза 3 п.5, часть 2). vsdx не поддерживает произвольную SVG-разметку
    поверх фигуры напрямую (в отличие от .svg — родной формат, и .drawio — умеет shape=image, см.
    _glyph_data_uri), поэтому здесь та же разметка растрируется в готовую картинку заранее и
    встраивается как отдельная фигура-оверлей (см. _embed_vsdx_category_icons и вызывающий код).
    Тот же rgba(255,255,255,0.9), что и в .svg/.drawio — картинка кладётся ПОВЕРХ уже закрашенной
    цветом категории фигуры узла (находка №1, Фаза 1), поэтому фон должен быть прозрачным, а не
    залитым: там, где глиф ничего не рисует, должен быть виден цвет фигуры под картинкой, а не
    чёрный/белый прямоугольник. resvg_py — Rust-биндинг (resvg), выбран вместо cairosvg/
    ImageMagick: устанавливается как обычное prebuilt-колесо, без системных библиотек (проверено:
    ни cairo, ни librsvg на хосте не нужны)."""
    import resvg_py

    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><g fill="rgba(255,255,255,0.9)" color="rgba(255,255,255,0.9)">{glyph}</g></svg>'
    return bytes(resvg_py.svg_to_bytes(svg_string=svg, width=128, height=128))


def _has_svg_attr(tag: str, name: str) -> bool:
    """Есть ли у открывающего тега атрибут name. \\s перед именем — чтобы \"width\" не находился
    внутри \"stroke-width\", а \"xmlns\" — внутри \"xmlns:xlink\"."""
    return re.search(rf"\s{name}\s*=", tag, re.IGNORECASE) is not None


def _standalone_custom_svg(icon: dict) -> str | None:
    """Приводит svg_markup custom-иконки (icon[\"mode\"] == \"custom\") к самодостаточному SVG-
    документу, который можно положить в data URI или отдать растеризатору; None — если рисовать
    нечего (не custom-иконка, пустая или слишком длинная разметка).

    В БД лежит как полный <svg>...</svg> (типичная иконка из внешнего редактора), так и голый
    фрагмент (<circle .../>): .svg-экспорт вставляет разметку дословно со сдвигом на левый верхний
    угол узла, то есть координаты фрагмента — пиксели бокса NODE_WIDTH x NODE_HEIGHT. Ту же
    систему координат сохраняем и здесь: фрагмент оборачиваем в <svg viewBox=\"0 0 W H\">, а у
    полного <svg> без viewBox и без width+height добавляем такой же viewBox. Без размера
    вложенное изображение не отрисуется вовсе (нечего масштабировать). Недостающие xmlns/
    xmlns:xlink добавляем — без них документ не разбирается вне HTML.
    """
    if icon.get("mode") != "custom":
        return None
    markup = (icon.get("svg_markup") or "").strip()
    if not markup:
        return None
    if len(markup) > MAX_CUSTOM_ICON_SVG_LENGTH:
        logger.warning("svg_markup custom-иконки слишком велик (%d символов) — иконка пропущена", len(markup))
        return None

    match = _SVG_ROOT_TAG.search(markup)
    if match is None:
        return f'<svg xmlns="{_SVG_NS_URI}" viewBox="0 0 {NODE_WIDTH} {NODE_HEIGHT}">{markup}</svg>'

    root_tag = match.group(0)
    extra_attrs = []
    if not _has_svg_attr(root_tag, "xmlns"):
        extra_attrs.append(f'xmlns="{_SVG_NS_URI}"')
    if "xlink:" in markup and not _has_svg_attr(root_tag, "xmlns:xlink"):
        extra_attrs.append(f'xmlns:xlink="{_XLINK_NS_URI}"')
    if not _has_svg_attr(root_tag, "viewBox") and not (_has_svg_attr(root_tag, "width") and _has_svg_attr(root_tag, "height")):
        extra_attrs.append(f'viewBox="0 0 {NODE_WIDTH} {NODE_HEIGHT}"')
    if not extra_attrs:
        return markup
    patched_tag = re.sub(r"<svg\b", "<svg " + " ".join(extra_attrs), root_tag, count=1, flags=re.IGNORECASE)
    return markup[: match.start()] + patched_tag + markup[match.end() :]


def _custom_icon_tile_svg(standalone_svg: str) -> str:
    """Плитка custom-иконки размером NODE_WIDTH x CUSTOM_ICON_TILE_HEIGHT: тёмный фон канваса со
    скруглёнными верхними углами и сама иконка, вписанная с сохранением пропорций (как
    max-width/max-height: 100% в .custom-icon канваса).

    Пользовательская разметка кладётся ТОЛЬКО как вложенное <image href=\"data:image/svg+xml;
    base64,...\"> — никогда на корень документа. Это принципиально: проверено напрямую — resvg на
    корневом уровне читает локальные файлы по <image href=\"/абсолютный/путь\"> (содержимое попало
    бы в PNG для .vsdx), а во вложенном SVG-изображении внешние ресурсы не загружаются. Браузеры и
    draw.io обрабатывают такой data URI как изображение — без скриптов и без внешних запросов.
    Проверка validate_svg_markup (diagram_icons.py) этого класса атак не ловит: это легитимный элемент SVG, поэтому
    вложенность в data URI — единственная защита именно от него.
    """
    width, height, radius, pad = NODE_WIDTH, CUSTOM_ICON_TILE_HEIGHT, CUSTOM_ICON_TILE_RADIUS, CUSTOM_ICON_TILE_PADDING
    encoded = base64.b64encode(standalone_svg.encode("utf-8")).decode("ascii")
    return (
        f'<svg xmlns="{_SVG_NS_URI}" xmlns:xlink="{_XLINK_NS_URI}" viewBox="0 0 {width} {height}" width="{width}" height="{height}">'
        f'<path d="M0 {height}V{radius}a{radius} {radius} 0 0 1 {radius} -{radius}H{width - radius}'
        f'a{radius} {radius} 0 0 1 {radius} {radius}V{height}z" fill="{CUSTOM_ICON_BACKGROUND_COLOR}"/>'
        f'<image xlink:href="data:image/svg+xml;base64,{encoded}" x="{pad}" y="{pad}" '
        f'width="{width - 2 * pad}" height="{height - 2 * pad}" preserveAspectRatio="xMidYMid meet"/></svg>'
    )


def _custom_icon_data_uri(standalone_svg: str) -> str:
    """Плитка custom-иконки как data URI для .drawio — percent-encoding по той же причине, что и в
    _glyph_data_uri (drawpyo режет значение стиля по первому \"=\", а base64 внутри плитки его
    содержит: после quote() символа \"=\" (как и \";\") в строке не остаётся)."""
    return f"data:image/svg+xml,{quote(_custom_icon_tile_svg(standalone_svg))}"


def _rasterize_custom_icon_png(standalone_svg: str) -> bytes | None:
    """Растрирует плитку custom-иконки в PNG для .vsdx. None — если resvg не смог разобрать
    документ (битая разметка): такая иконка пропускается, а экспорт всей диаграммы не падает
    из-за одного некорректного svg_markup в каталоге."""
    import resvg_py

    try:
        return bytes(
            resvg_py.svg_to_bytes(
                svg_string=_custom_icon_tile_svg(standalone_svg),
                width=NODE_WIDTH * CUSTOM_ICON_PNG_SCALE,
                height=CUSTOM_ICON_TILE_HEIGHT * CUSTOM_ICON_PNG_SCALE,
            )
        )
    except ValueError as exc:
        logger.warning("Не удалось растрировать custom-иконку для .vsdx: %s", exc)
        return None
