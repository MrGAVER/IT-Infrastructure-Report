"""
Код-ревью r3, ИА-06: SVG-глифы категорий (`SHAPE_GLYPHS`) записаны читаемо — по элементам SVG, без строк в сотни символов.

При `line-length = 400` форматтер склеил неявную конкатенацию в строки до 397 символов. Теперь блок защищён директивами `# fmt: off/on`,
а тест следит за двумя вещами: (1) в `diagram_icons.py` нет строк длиннее 140 символов (целевой предел из test_code_style_limits.py);
(2) разметка глифов осталась ровно той, что отдаётся фронтенду и в экспорт, — переразбивка не должна менять ни байта.

Запуск: pytest backend/tests/test_diagram_icon_glyph_source.py -v
"""

from __future__ import annotations

import hashlib
import io
import re
import tokenize
from pathlib import Path

from app.services import diagram_icons
from app.services.diagram_icons import SHAPE_GLYPHS

SOURCE = Path(diagram_icons.__file__)
TARGET_LINE_LENGTH = 140

# Разметка глифов на момент ревью (до разбивки): первые 16 символов sha256 каждого глифа. Это снимок: осознанно меняете значок — обновите хеш.
EXPECTED_GLYPH_HASHES = {
    "server": "7d637f251abfe93b",
    "switch_l2": "420dce3b9ee5e796",
    "switch_l3": "f9cd35c6dbbdd219",
    "router": "47d7ed11f492f813",
    "firewall": "b190ec4bebc933bf",
    "workstation": "7ffed08cc10121af",
    "peripheral": "32873f068955158a",
    "generic": "e29e2b4fd2f21879",
    "switch": "420dce3b9ee5e796",
}


def test_no_line_in_diagram_icons_is_longer_than_the_target_line_length():
    too_long = [(number, len(line)) for number, line in enumerate(SOURCE.read_text(encoding="utf-8").splitlines(), 1) if len(line) > TARGET_LINE_LENGTH]
    assert too_long == [], f"строки длиннее {TARGET_LINE_LENGTH} символов (номер, длина): {too_long}"


def test_the_glyph_block_is_protected_from_the_formatter():
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index("SHAPE_GLYPHS: dict[str, str] = {")
    assert source.rindex("# fmt: off", 0, start) > source.rindex("\n\n", 0, start), "перед SHAPE_GLYPHS должна стоять директива # fmt: off"
    assert "# fmt: on" in source[start:]


def test_every_glyph_literal_is_split_into_short_pieces():
    """Каждый строковый литерал блока SHAPE_GLYPHS — кусок не длиннее 120 символов; длинные элементы разбиты по границам атрибутов.

    Смотрим токены, а не AST: parser склеивает соседние литералы в один, и разбивки в дереве не видно."""
    source = SOURCE.read_text(encoding="utf-8")
    lines = source.splitlines()
    first = next(number for number, line in enumerate(lines, 1) if line.startswith("SHAPE_GLYPHS: dict"))
    last = next(number for number, line in enumerate(lines, 1) if number > first and line.startswith("# fmt: on"))
    pieces = [
        token.string for token in tokenize.generate_tokens(io.StringIO(source).readline) if token.type == tokenize.STRING and first <= token.start[0] <= last
    ]
    markup = [piece for piece in pieces if piece.startswith("'<")]
    assert len(markup) > len(SHAPE_GLYPHS), "каждый глиф должен состоять минимум из одного литерала, а большинство — из нескольких"
    assert max(len(piece) for piece in markup) <= 120 + 2  # плюс две кавычки


def test_glyph_markup_is_unchanged_by_the_split():
    assert {key: hashlib.sha256(value.encode("utf-8")).hexdigest()[:16] for key, value in SHAPE_GLYPHS.items()} == EXPECTED_GLYPH_HASHES
    assert SHAPE_GLYPHS["switch"] == SHAPE_GLYPHS["switch_l2"]


def test_each_glyph_is_well_formed_svg_fragment():
    for key, markup in SHAPE_GLYPHS.items():
        assert re.fullmatch(r"(<(rect|path|circle)\b[^<>]*/>)+", markup), f"глиф {key} — не последовательность самозакрытых элементов"
