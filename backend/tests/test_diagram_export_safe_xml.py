"""Безопасный разбор XML при сборке .vsdx (services/diagram_export/, ревью 2.158.0, П-6).

Bandit B314: xml.etree.ElementTree.fromstring разбирал части пакета VSDX (строки 604, 657, 658) без защиты от
DTD-сущностей. Части формирует само приложение, поэтому эксплуатация маловероятна, но defusedxml уже в зависимостях и
применяется в diagram_icons.py. Теперь разбор идёт через defusedxml; запись (ElementTree.write, SubElement,
register_namespace) осталась на стандартной библиотеке — defusedxml отвечает только за разбор.

Тесты вызывают функции постобработки пакета напрямую на собранных вручную zip-архивах: нужны только сами XML-части, а не
полный экспорт с шаблоном Visio.
"""

from __future__ import annotations

import ast
import re
import zipfile
from pathlib import Path

import pytest
from defusedxml.common import DefusedXmlException

from app.services import diagram_export

# Модуль стал пакетом (A-07 код-ревью r3): `diagram_export.__file__` — это `__init__.py` с одними реэкспортами, и проверки исходника по нему
# молча стали бы бессмысленными (разбора там нет, значит «нарушений нет»). Поэтому сканируются все файлы пакета.
PACKAGE_FILES = sorted(Path(diagram_export.__file__).parent.glob("*.py"))
VISIO_NS = "http://schemas.microsoft.com/office/visio/2012/main"

# Взрыв сущностей («billion laughs» в миниатюре) и внешняя сущность (XXE): обе объявляют сущность в DTD.
ENTITY_BOMB = b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]><ns0:Pages xmlns:ns0="urn:x">&lol2;</ns0:Pages>'
EXTERNAL_ENTITY = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/hostname">]><ns0:Pages xmlns:ns0="urn:x">&x;</ns0:Pages>'
HOSTILE_PARTS = [pytest.param(ENTITY_BOMB, id="entity-expansion"), pytest.param(EXTERNAL_ENTITY, id="external-entity")]


def _write_zip(path: Path, parts: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in parts.items():
            zf.writestr(name, data)


def _read_zip(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _finalize_inputs(tmp_path: Path, page1: bytes, pages: bytes = b"<Pages/>") -> tuple[Path, Path]:
    saved, template = tmp_path / "saved.vsdx", tmp_path / "template.vsdx"
    _write_zip(saved, {"visio/pages/page1.xml": page1, "visio/pages/pages.xml": pages, "docProps/app.xml": b"<Properties/>"})
    _write_zip(template, {"docProps/app.xml": b"<Properties pristine='1'/>"})
    return saved, template


ICON_RELS = b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
ICON_CONTENT_TYPES = b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>'
PNG = b"\x89PNG\r\n\x1a\n-test-"


def _icon_package(tmp_path: Path, rels: bytes = ICON_RELS, content_types: bytes = ICON_CONTENT_TYPES) -> Path:
    saved = tmp_path / "icons.vsdx"
    _write_zip(saved, {"[Content_Types].xml": content_types, "visio/pages/_rels/page1.xml.rels": rels, "visio/pages/page1.xml": b"<Page/>"})
    return saved


class TestFinalizePackageParsesSafely:
    @pytest.mark.parametrize("hostile", HOSTILE_PARTS)
    def test_hostile_page_part_is_rejected_and_nothing_is_rewritten(self, tmp_path, hostile):
        saved, template = _finalize_inputs(tmp_path, page1=hostile)
        before = saved.read_bytes()
        with pytest.raises(DefusedXmlException):
            diagram_export._finalize_vsdx_package(str(saved), str(template))
        assert saved.read_bytes() == before  # архив перезаписывается только после успешного разбора всех частей

    def test_hostile_pages_part_is_rejected_too(self, tmp_path):
        saved, template = _finalize_inputs(tmp_path, page1=b"<Page/>", pages=ENTITY_BOMB)
        with pytest.raises(DefusedXmlException):
            diagram_export._finalize_vsdx_package(str(saved), str(template))

    def test_regular_package_is_still_repaired(self, tmp_path):
        """Штатный путь не сломан: синтетический префикс ns0 заменяется пространством имён по умолчанию, как и раньше."""
        broken = f'<ns0:Page xmlns:ns0="{VISIO_NS}"><ns0:Shapes/></ns0:Page>'.encode()
        saved, template = _finalize_inputs(tmp_path, page1=broken)
        diagram_export._finalize_vsdx_package(str(saved), str(template))
        parts = _read_zip(saved)
        assert f'xmlns="{VISIO_NS}"'.encode() in parts["visio/pages/page1.xml"]
        assert b"ns0" not in parts["visio/pages/page1.xml"]
        assert parts["docProps/app.xml"] == b"<Properties pristine='1'/>"  # неизменяемые части возвращены из шаблона

    def test_part_without_synthetic_namespace_is_left_untouched(self, tmp_path):
        clean = f'<Page xmlns="{VISIO_NS}"><Shapes/></Page>'.encode()
        saved, template = _finalize_inputs(tmp_path, page1=clean)
        diagram_export._finalize_vsdx_package(str(saved), str(template))
        assert _read_zip(saved)["visio/pages/page1.xml"] == clean


class TestEmbedIconsParsesSafely:
    @pytest.mark.parametrize("hostile", HOSTILE_PARTS)
    def test_hostile_relationships_part_is_rejected(self, tmp_path, hostile):
        saved = _icon_package(tmp_path, rels=hostile)
        before = saved.read_bytes()
        with pytest.raises(DefusedXmlException):
            diagram_export._embed_vsdx_category_icons(str(saved), {"rIdIcon1": PNG})
        assert saved.read_bytes() == before

    @pytest.mark.parametrize("hostile", HOSTILE_PARTS)
    def test_hostile_content_types_part_is_rejected(self, tmp_path, hostile):
        saved = _icon_package(tmp_path, content_types=hostile)
        with pytest.raises(DefusedXmlException):
            diagram_export._embed_vsdx_category_icons(str(saved), {"rIdIcon1": PNG})

    def test_regular_package_gets_the_icon_relationship_and_png_default(self, tmp_path):
        saved = _icon_package(tmp_path)
        diagram_export._embed_vsdx_category_icons(str(saved), {"rIdIcon1": PNG})
        parts = _read_zip(saved)
        assert parts["visio/media/image1.png"] == PNG
        rels = parts["visio/pages/_rels/page1.xml.rels"].decode()
        assert 'Id="rIdIcon1"' in rels and 'Target="../media/image1.png"' in rels
        assert 'Extension="png"' in parts["[Content_Types].xml"].decode()

    def test_no_icons_means_no_parsing_at_all(self, tmp_path):
        """Без иконок функция выходит сразу — даже «испорченная» часть не разбирается и не вызывает ошибки."""
        saved = _icon_package(tmp_path, rels=ENTITY_BOMB)
        before = saved.read_bytes()
        diagram_export._embed_vsdx_category_icons(str(saved), {})
        assert saved.read_bytes() == before


class TestNoUnsafeParsingInModule:
    """Страж от возврата: стандартный xml.etree годится в модуле только для записи, разбор — через SafeET."""

    UNSAFE_PARSERS = {"fromstring", "XML", "parse", "iterparse", "XMLParser", "XMLPullParser", "fromstringlist"}

    def _calls(self) -> list[tuple[str, str, int]]:
        """Вызовы вида `имя.метод(...)` во всех файлах пакета; номер строки — внутри своего файла."""
        calls = []
        for path in PACKAGE_FILES:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            calls.extend((node.func.value.id, node.func.attr, node.lineno) for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name))
        return calls

    def test_the_scan_really_covers_the_package(self):
        """Страж стража: без этого перенос кода в другой файл снова сделал бы остальные проверки класса пустыми."""
        assert {path.name for path in PACKAGE_FILES} >= {"__init__.py", "_common.py", "_icons.py", "svg.py", "drawio.py", "vsdx.py"}
        assert any(name == "SafeET" for name, _attr, _line in self._calls()), "в просканированном коде нет ни одного вызова SafeET"

    def test_standard_library_etree_does_not_parse(self):
        offenders = [(name, attr, line) for name, attr, line in self._calls() if name == "ET" and attr in self.UNSAFE_PARSERS]
        assert offenders == [], f"разбор через xml.etree вместо defusedxml: {offenders}"

    def test_the_three_reviewed_sites_use_safe_parser(self):
        safe = [line for name, attr, line in self._calls() if name == "SafeET" and attr == "fromstring"]
        assert len(safe) == 3

    def test_standard_library_is_still_used_for_writing(self):
        """defusedxml разбирает в обычные Element, поэтому SubElement/ElementTree.write на стандартной библиотеке работают."""
        used = {attr for name, attr, _line in self._calls() if name == "ET"}
        assert {"ElementTree", "SubElement", "register_namespace"} <= used

    def test_import_is_annotated_for_bandit(self):
        importing = [path for path in PACKAGE_FILES if re.search(r"^import xml\.etree\.ElementTree as ET\b", path.read_text(encoding="utf-8"), re.MULTILINE)]
        assert importing, "стандартный xml.etree больше нигде не импортируется — проверка записи/разбора устарела"
        for path in importing:
            source = path.read_text(encoding="utf-8")
            assert re.search(r"^import xml\.etree\.ElementTree as ET\s+# nosec B405", source, re.MULTILINE), path.name
