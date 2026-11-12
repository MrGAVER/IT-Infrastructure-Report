"""Экспорт графа диаграммы в .vsdx: копирование шаблонных фигур media.vsdx библиотекой vsdx и обязательная постобработка пакета
(см. docstring пакета: «Готча .vsdx», _finalize_vsdx_package, _strip_dangling_glue_formulas)."""

from __future__ import annotations

import copy
import io
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET  # nosec B405 # только запись и сборка (ElementTree.write, SubElement, register_namespace); разбор — через SafeET
import zipfile

from defusedxml import ElementTree as SafeET

from ._common import (
    CUSTOM_ICON_TILE_HEIGHT,
    GLYPH_DISPLAY_SIZE,
    GLYPH_TOP_MARGIN,
    GROUP_FILL_COLOR,
    NODE_HEIGHT,
    NODE_WIDTH,
    VSDX_SCALE,
    _device_fill_color,
    _port_anchor_fraction,
    _port_ticks_of,
    _vlan_label,
)
from ._icons import (
    _rasterize_custom_icon_png,
    _rasterize_glyph_png,
    _standalone_custom_svg,
)

# --------------------------------------------------------------------------------------
# .vsdx (vsdx) — копирование шаблонных фигур, см. docstring модуля
# --------------------------------------------------------------------------------------

# xml.etree.ElementTree генерирует именно такие синтетические префиксы (ns0, ns1, ...) для
# любого namespace, для которого не был явно зарегистрирован префикс на момент сериализации —
# подлинные файлы Visio так никогда не называют префиксы, поэтому наличие "xmlns:nsN=" в частях
# пакета — надёжный, самодостаточный признак повреждения (см. _finalize_vsdx_package).
_SYNTHETIC_NAMESPACE_DECLARATION = re.compile(rb"xmlns:ns\d+=")

# Части пакета, которые export_vsdx осмысленно меняет: сама страница с фигурами и — начиная с
# Фазы 2, п.3 (_fit_vsdx_page_to_content) — pages.xml, где хранится PageWidth/PageHeight. Всё
# остальное (мастера, глобальные настройки документа, метаданные, декларация content-types) от
# графа не зависит и не модифицируется вообще — см. _finalize_vsdx_package.
_VSDX_CONTENT_PARTS = ("visio/pages/page1.xml", "visio/pages/pages.xml")


def _finalize_vsdx_package(saved_path: str, template_path: str) -> None:
    """Постобрабатывает уже сохранённый vsdx.VisioFile.save_vsdx() файл — обходит дефекты самой
    библиотеки vsdx 0.6.1, из-за которых пустой лист получался даже без единой content-правки
    (находка №1 отчёта об экспорте диаграмм; воспроизведено напрямую и заведено в
    backend/tests/test_diagram_export.py::test_export_vsdx_opens_in_third_party_reader).

    Обнаружено бисекцией по XML-частям пакета (не предположение):

    1) При импорте vsdx.vsdxfile регистрирует ЧЕТЫРЕ разных namespace на один и тот же пустой
       префикс подряд (namespace, ext_prop_namespace, document_rels_namespace,
       cont_types_namespace) — а xml.etree.ElementTree.register_namespace хранит соответствие
       URI -> префикс и при регистрации НОВОГО URI на уже занятый префикс удаляет запись
       предыдущего. Default-namespace (xmlns=...) остаётся только у ПОСЛЕДНЕГО из четырёх — все
       остальные части сериализуются с синтетическим xmlns:ns0=... вместо исходного. Итог
       валиден как XML и одинаково парсится тем же xml.etree (поэтому тесты, читающие файл
       обратно через vsdx.VisioFile, ничего не замечают), но не открывается сторонними
       читателями — подтверждено headless LibreOffice.

    2) Даже после точечной починки namespace у ВСЕХ пяти незадействованных частей разом (а не
       только у страницы) лист всё равно оставался пустым — тройная и четверная бисекция частей
       друг против друга ничего не находит (каждая пара/тройка/четвёрка по отдельности рендерится
       нормально), из чего следует: причина не в содержимом какой-то одной части, а в том, что
       vsdx вообще пропускает эти части через собственный ElementTree-round-trip. Поскольку
       document.xml/masters/master1.xml/docProps/app.xml/[Content_Types].xml в текущей реализации
       export_vsdx от графа не зависят и никогда не изменяются, самый надёжный фикс — вообще не
       пользоваться тем, что vsdx с ними сделал, а вернуть их как есть из пристинного шаблона.
       Меняются (и чинятся по namespace, а не заменяются целиком) только части из
       _VSDX_CONTENT_PARTS — сама страница с фигурами и (с Фазы 2, п.3) pages.xml, где
       _fit_vsdx_page_to_content меняет PageWidth/PageHeight под контент графа.

    Пример вызова:
        vf.save_vsdx(out_path)
        vf.close_vsdx()
        _finalize_vsdx_package(out_path, template_path)  # out_path перезаписывается на месте
    """
    with zipfile.ZipFile(saved_path, "r") as zf:
        order = zf.namelist()
        entries = {name: zf.read(name) for name in order}
    with zipfile.ZipFile(template_path, "r") as zf:
        pristine = {name: zf.read(name) for name in zf.namelist()}

    for name in order:
        if name in _VSDX_CONTENT_PARTS:
            continue
        if name in pristine:
            entries[name] = pristine[name]

    for part in _VSDX_CONTENT_PARTS:
        data = entries[part]
        if _SYNTHETIC_NAMESPACE_DECLARATION.search(data):
            root = SafeET.fromstring(data)  # части пакета формирует само приложение, но разбор — безопасный: DTD-сущности и внешние ссылки запрещены
            if root.tag.startswith("{"):
                ET.register_namespace("", root.tag[1:].split("}", 1)[0])
            buf = io.BytesIO()
            ET.ElementTree(root).write(buf, xml_declaration=True, encoding="UTF-8", method="xml")
            entries[part] = buf.getvalue()

    with zipfile.ZipFile(saved_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in order:
            zf.writestr(name, entries[name])


# Схема ForeignData/Rel — не догадка и не проба с потолка, сверена дословно с открытой
# спецификацией: https://learn.microsoft.com/en-us/openspecs/sharepoint_protocols/ms-vsdx/
# c5a5df0c-02e6-4e72-9042-d5766f614cf5 (ForeignData_Type) и .../34f54be6-adb2-4aa8-a683-
# 7d1db7a25d46 (Rel_Type). ObjectWidth/ObjectHeight у ForeignData помечены в спецификации как
# "unused and MUST be ignored" для ForeignType="Bitmap" (используются только для OLE2 embedded
# object) — фактический размер картинки задаётся обычными Width/Height фигуры-контейнера, как и
# для любой другой фигуры.
# ВАЖНО: несмотря на то что XML построен дословно по спецификации, ни один доступный инструмент
# проверки саму картинку не показал — headless LibreOffice не крашит и не пустит весь лист (как
# было при более грубых ошибках в находке №1), а тихо откатывает фигуру на обычную геометрию:
# именно поэтому icon_shape ниже явно очищает text/fill/line — единственное отличие от "картинка
# отрисовалась" в разумном фолбэке это небольшой белый прямоугольник на месте иконки вместо самой
# иконки, а не что-то более разрушительное. Похоже на отсутствие поддержки ForeignData/Bitmap в
# конкретно этом импорт-фильтре (libvisio), а не на ошибку в собранном XML — см. learnings в
# памяти проекта. Внедрено по решению пользователя ("внедряй, проверим позже") без подтверждённой
# сторонним инструментом отрисовки самой картинки; при появлении доступа к настоящему Visio эту
# находку стоит перепроверить в первую очередь.
_R_NS_URI = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_RELS_NS_URI = "http://schemas.openxmlformats.org/package/2006/relationships"
_CONTENT_TYPES_NS_URI = "http://schemas.openxmlformats.org/package/2006/content-types"
_IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def _embed_vsdx_category_icons(saved_path: str, icon_pngs: dict[str, bytes]) -> None:
    """Дописывает растрированные иконки категорий (icon_pngs: rId -> PNG-байты) в уже
    финализированный _finalize_vsdx_package() пакет: новые части visio/media/imageN.png, связи в
    page1.xml.rels и Default-запись для "png" в [Content_Types].xml. Выполняется ПОСЛЕ
    _finalize_vsdx_package (а не вместо неё), потому что сама привязка ForeignData/Rel к rId
    прописывается в XML фигуры ДО save_vsdx() (см. export_vsdx), пока r:id ещё не подкреплён
    относящейся к нему связью — эта функция дописывает недостающую связь и саму картинку поверх
    уже готового, namespace-починенного пакета, а не заменяет какую-либо из его частей.
    icon_pngs может быть пустым (в графе нет ни одной сгенерированной иконки) — тогда функция
    ничего не делает."""
    if not icon_pngs:
        return

    with zipfile.ZipFile(saved_path, "r") as zf:
        order = zf.namelist()
        entries = {name: zf.read(name) for name in order}

    rels_path = "visio/pages/_rels/page1.xml.rels"
    rels_root = SafeET.fromstring(entries[rels_path])
    ct_root = SafeET.fromstring(entries["[Content_Types].xml"])
    has_png_default = any(el.get("Extension") == "png" for el in ct_root.findall(f"{{{_CONTENT_TYPES_NS_URI}}}Default"))

    for index, (rel_id, png_bytes) in enumerate(sorted(icon_pngs.items()), start=1):
        media_name = f"visio/media/image{index}.png"
        entries[media_name] = png_bytes
        order.append(media_name)

        relationship = ET.SubElement(rels_root, f"{{{_PKG_RELS_NS_URI}}}Relationship")
        relationship.set("Id", rel_id)
        relationship.set("Type", _IMAGE_REL_TYPE)
        relationship.set("Target", f"../media/image{index}.png")

    if not has_png_default:
        default = ET.SubElement(ct_root, f"{{{_CONTENT_TYPES_NS_URI}}}Default")
        default.set("Extension", "png")
        default.set("ContentType", "image/png")

    # register_namespace регистрирует эти два URI на пустой префикс НЕПОСРЕДСТВЕННО перед
    # сериализацией каждой части — по одной части за раз, тем же приёмом, что и в
    # _finalize_vsdx_package, во избежание той же коллизии реестра namespace (см. её docstring).
    ET.register_namespace("", _PKG_RELS_NS_URI)
    rels_buf = io.BytesIO()
    ET.ElementTree(rels_root).write(rels_buf, xml_declaration=True, encoding="UTF-8", method="xml")
    entries[rels_path] = rels_buf.getvalue()

    ET.register_namespace("", _CONTENT_TYPES_NS_URI)
    ct_buf = io.BytesIO()
    ET.ElementTree(ct_root).write(ct_buf, xml_declaration=True, encoding="UTF-8", method="xml")
    entries["[Content_Types].xml"] = ct_buf.getvalue()

    with zipfile.ZipFile(saved_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in order:
            zf.writestr(name, entries[name])


# "Sheet.N" — то, как формулы шаблонного коннектора (_WALKGLUE(...)/_XFTRIGGER(Sheet.N!...))
# ссылаются по имени на ДРУГИЕ фигуры той же страницы шаблона (RECTANGLE/CONNECTED_SHAPE), см.
# _strip_dangling_glue_formulas — настоящие формулы наших собственных фигур такую подстроку не
# используют, поэтому это надёжный и самодостаточный признак именно шаблонной "приклейки".
_DANGLING_GLUE_FORMULA_MARKER = "Sheet."


def _strip_dangling_glue_formulas(shape) -> None:
    """Shape.set_start_and_finish() (библиотека vsdx) пересчитывает и обновляет числовое
    значение (V) у BeginX/BeginY/EndX/EndY/BegTrigger/EndTrigger, но саму формулу (F) не
    трогает — у скопированного коннектора там остаётся дословно то же, что было в шаблоне:
    _WALKGLUE(BegTrigger,EndTrigger,WalkPreference) и _XFTRIGGER(Sheet.1!EventXFMod) /
    _XFTRIGGER(Sheet.2!EventXFMod). "Sheet.1"/"Sheet.2" — ссылки по имени на шаблонные
    RECTANGLE/CONNECTED_SHAPE, которые export_vsdx следом удаляет со страницы (см. вызывающий
    код) — формула превращается в ссылку в никуда.

    Кэшированное значение (V) к этому моменту уже корректное (see set_start_and_finish), так что
    само по себе на отображение это не повлияло бы — если бы формулу вообще никто не
    пересчитывал. Но проверено напрямую: headless LibreOffice формулу пересчитывает и на такой
    висячей ссылке рендерит лист ПОЛНОСТЬЮ ПУСТЫМ (третий и последний из найденных источников
    находки №1 отчёта об экспорте — после дефекта самой vsdx при сохранении и неочищенной секции
    <Connects>, см. _finalize_vsdx_package и вызывающий код). Наш коннектор координаты не
    "приклеивает" динамически к другим фигурам, а получает явно — поэтому формулу, ссылающуюся
    на шаблонный "Sheet.N", можно просто убрать, оставив только уже посчитанное V.
    """
    for cell in shape.cells.values():
        formula = cell.formula
        if formula and _DANGLING_GLUE_FORMULA_MARKER in formula:
            cell.xml.attrib.pop("F", None)


def _vsdx_port_anchor(shape, fraction: float | None) -> tuple[float, float]:
    """Точка на этом конце коннектора: shape.x/shape.y — PinX/PinY, то есть ЦЕНТР фигуры (см.
    комментарий у target_x/target_y в export_vsdx), а не левый верхний угол. Находка №2 отчёта
    (Фаза 2, п.1): если для этого конца ребра резолвится конкретная засечка порта — точка на
    НИЖНЕЙ (в терминах графа/canvas) грани фигуры на нужной доле ширины, а не центр. "Нижняя"
    грань графа — это МЕНЬШИЙ Y в осях Visio (см. находку №1: страница построена так, что ось Y
    Visio растёт снизу вверх, а не сверху вниз, поэтому "низ" в exported-координатах — это
    shape.y - height/2, а не + height/2). fraction=None (порт не резолвится — группа/
    custom-иконка/устройство без интерфейсов) — прежнее поведение, центр фигуры."""
    if fraction is None:
        return shape.center_x_y
    left = shape.x - shape.width / 2
    bottom = shape.y - shape.height / 2
    return (left + shape.width * fraction, bottom)


def _set_vsdx_shape_size(shape, width: float, height: float) -> None:
    """Задаёт размер фигуры (дюймы) и явно пересчитывает LocPinX/LocPinY.

    vsdx не пересчитывает формульные ячейки при смене Width/Height: у скопированного шаблонного
    прямоугольника LocPinX/LocPinY = Width*0.5/Height*0.5 остаются кэшированными значениями V от
    шаблонного размера, а читатели (проверено в headless LibreOffice) берут именно V — фигура
    после ресайза рисуется смещённой (левый край = PinX - устаревший LocPinX). Поэтому после
    любого ресайза pin ставим в центр вручную. Вызывать ДО расчёта target_x/target_y, которые
    опираются на shape.width/height.
    """
    shape.width = width
    shape.height = height
    shape.set_cell_value("LocPinX", str(width / 2))
    shape.set_cell_value("LocPinY", str(height / 2))


def _add_vsdx_image_overlay(rect_template, node_shape, rel_id: str, width: float, height: float, top_margin: float) -> None:
    """Добавляет на страницу фигуру-оверлей с растровой картинкой (ForeignData/Rel на rId) размера
    width x height (дюймы), по центру верхней части node_shape, с отступом top_margin от её верха.

    Отдельная фигура, а не что-то в самой цветной фигуре узла: ForeignData делает фигуру
    картинкой целиком — подмешивать её в уже закрашенный прямоугольник нельзя. Если читатель
    ForeignData не распознаёт (headless LibreOffice, см. learnings), фигура откатывается на
    обычную геометрию — унаследованный от шаблона текст \"RECTANGLE\" и заливку убираем явно,
    иначе вместо аккуратной картинки останется белый прямоугольник с посторонним текстом.
    """
    from vsdx import namespace as visio_ns

    overlay = rect_template.copy()
    overlay.text = ""
    overlay.fill_color = "#FFFFFF"
    overlay.line_color = "#FFFFFF"
    center_y = node_shape.y + node_shape.height / 2 - top_margin - height / 2
    overlay.move(node_shape.x - overlay.x, center_y - overlay.y)
    _set_vsdx_shape_size(overlay, width, height)
    foreign_data = ET.SubElement(overlay.xml, f"{visio_ns}ForeignData")
    foreign_data.set("ForeignType", "Bitmap")
    rel_el = ET.SubElement(foreign_data, f"{visio_ns}Rel")
    rel_el.set(f"{{{_R_NS_URI}}}id", rel_id)


def _fit_vsdx_page_to_content(page, graph: dict) -> float:
    """Возвращает итоговую высоту страницы (дюймы) — используется вызывающим кодом для формулы
    target_y (находка №1, поправка на высоту страницы). Находка №5 отчёта (Фаза 2, п.3):
    страница .vsdx-экспорта раньше всегда была фиксированного размера шаблона (страница A4 в
    media.vsdx) — большой граф обрезался за пределами видимой страницы, а маленький терялся на
    непропорционально большом пустом листе. .svg этой проблемы по своей природе не имеет —
    viewBox считается по контенту (см. export_svg); здесь воспроизводим тот же расчёт (тот же
    отступ 40px), переведённый в дюймы Visio через тот же VSDX_SCALE, что и позиционирование
    фигур ниже. Пустой граф (нет узлов) — страницу не трогаем, оставляем размер шаблона."""
    if not graph["nodes"]:
        return page.height
    margin = 40
    max_x = max(n["x"] + NODE_WIDTH for n in graph["nodes"]) + margin
    max_y = max(n["y"] + NODE_HEIGHT for n in graph["nodes"]) + margin
    page.width = max_x / VSDX_SCALE
    page.height = max_y / VSDX_SCALE
    return page.height


class _ShapeTemplate:
    """Шаблонная фигура, копии которой делаются за постоянное время (A-06: .vsdx стал быстрым).

    Shape.copy() библиотеки vsdx перед каждым копированием вызывает page.set_max_ids() — обход ВСЕХ фигур страницы ради «наибольшего ID»,
    то есть n копий стоят n² обходов (120 устройств — около 18 с). Но page.max_id только растёт: каждая копия получает max_id + 1 и
    больше ничего не меняет. Поэтому достаточно одного обхода до первой копии, а дальше — те же шаги, что в VisioFile.copy_shape
    (копия XML, новые ID, подстановка ID в формулы, вставка в тег Shapes), без повторного обхода. Результат тот же байт в байт:
    сверка с Shape.copy() — тест test_shape_template_copy_is_identical_to_library_copy (он же страж при обновлении vsdx: метод опирается
    на VisioFile.increment_shape_ids/update_ids и Page.set_max_ids).
    """

    def __init__(self, shape) -> None:
        self._shape = shape
        self._page = shape.page
        self._page.set_max_ids()

    def copy(self):
        from vsdx import Shape
        from vsdx import namespace as visio_ns

        page = self._page
        new_xml = copy.deepcopy(self._shape.xml)  # то же, что у библиотеки (tostring → разбор), но без разбора XML: см. test_diagram_export_safe_xml
        shapes_tag = page.xml.find(f"{visio_ns}Shapes")
        id_map = page.vis.increment_shape_ids(new_xml, page)
        page.vis.update_ids(new_xml, id_map)
        shapes_tag.append(new_xml)
        return Shape(xml=new_xml, parent=self._shape.parent, page=page)


class _VsdxImages:
    """Растровые иконки .vsdx.

    Находка №5 отчёта (Фаза 3, п.5, часть 2): один PNG на УНИКАЛЬНУЮ иконку (глиф категории или
    custom-разметку), а не на узел — картинка одна и та же для всех узлов с этой иконкой (глиф
    рисуется нейтральным белым и ложится на любую заливку). rId начинаются с 2, т.к. rId1 в
    page1.xml.rels уже занят связью на master (см. media.vsdx). None в кэше — иконку растрировать
    не удалось: пропускаем её для всех узлов, не пробуя заново."""

    def __init__(self) -> None:
        self.pngs: dict[str, bytes] = {}  # rId -> PNG; их встраивает _embed_vsdx_category_icons
        self._rel_ids: dict[tuple[str, str], str | None] = {}

    def rel_id_for(self, key: tuple[str, str], make_png) -> str | None:
        if key not in self._rel_ids:
            png = make_png()
            if png is None:
                self._rel_ids[key] = None
            else:
                rel_id = f"rId{len(self.pngs) + 2}"
                self.pngs[rel_id] = png
                self._rel_ids[key] = rel_id
        return self._rel_ids[key]


def _place_vsdx_node(rect_template, node: dict, page_height: float):
    """Копия шаблонного прямоугольника нужного размера на месте узла графа (текст — подпись узла)."""
    shape = rect_template.copy()
    shape.text = node["label"]
    # Размер фигуры должен совпадать с тем, по которому считается страница
    # (_fit_vsdx_page_to_content: NODE_WIDTH/NODE_HEIGHT / VSDX_SCALE) — иначе нижний
    # ряд и правый край графа обрезаются страницей. Ставим ДО target_x/target_y ниже.
    _set_vsdx_shape_size(shape, NODE_WIDTH / VSDX_SCALE, NODE_HEIGHT / VSDX_SCALE)
    # PinX/PinY (shape.x/shape.y) — точка привязки ФИГУРЫ, а не левый верхний угол:
    # у скопированного шаблонного прямоугольника LocPinX/LocPinY = Width*0.5/Height*0.5
    # (см. media.vsdx), то есть это ЦЕНТР. node["x"]/node["y"] графа — левый верхний
    # угол (то же соглашение, что и в _svg_node/.drawio: obj.position = (x, y)) —
    # без поправки на половину размера фигуры весь узел рисуется НИЖЕ И ПРАВЕЕ, чем
    # нужно (на скриншотах — обрезан сверху краем страницы).
    target_x = node["x"] / VSDX_SCALE + shape.width / 2
    # Находка №1 отчёта об экспорте: ось Y в Visio растёт СНИЗУ ВВЕРХ от нижнего
    # края страницы, а node["y"] графа — сверху вниз, как в .svg/канвасе. Простой
    # смены знака недостаточно: -(node["y"]/SCALE) всегда <= 0, то есть ВСЯ
    # диаграмма целиком уходит ниже нижнего края страницы (за пределы видимой
    # области). Нужно ещё вычесть из высоты страницы шаблона, чтобы верх графа
    # (y=0) лёг на верх страницы, а не наоборот.
    target_y = page_height - (node["y"] / VSDX_SCALE + shape.height / 2)
    shape.move(target_x - shape.x, target_y - shape.y)
    return shape


def _style_vsdx_node(shape, node: dict) -> None:
    if node["type"] == "group":
        # Раздел 4.4 ТЗ: группа должна визуально отличаться от устройства так же,
        # как в .svg/.drawio (светло-серая заливка + пунктирная рамка), а не только
        # подписью — иначе на .vsdx-экспорте группу от обычного узла не отличить.
        shape.fill_color = GROUP_FILL_COLOR
        shape.set_cell_value("LinePattern", "2")
        return
    color = _device_fill_color(node["icon"])
    shape.fill_color = color
    shape.line_color = color
    # Подпись у нижнего края узла (0 — верх, 1 — середина, 2 — низ), как на канвасе/
    # в .svg: по умолчанию текст по центру, где теперь иконка.
    shape.set_cell_value("VerticalAlign", "2")


def _overlay_vsdx_icon(rect_template, shape, icon: dict, images: _VsdxImages) -> None:
    """Картинка иконки узла-устройства: глиф категории или custom-разметка (если растрировать не удалось — без картинки)."""
    glyph = icon.get("glyph")
    if glyph:
        rel_id = images.rel_id_for(("glyph", glyph), lambda: _rasterize_glyph_png(glyph))
        if rel_id is not None:
            # Та же позиция/размер иконки, что и в .svg (_svg_node) и .drawio
            # (GLYPH_DISPLAY_SIZE/GLYPH_TOP_MARGIN), переведённые в дюймы Visio.
            icon_size = GLYPH_DISPLAY_SIZE / VSDX_SCALE
            _add_vsdx_image_overlay(rect_template, shape, rel_id, icon_size, icon_size, GLYPH_TOP_MARGIN / VSDX_SCALE)
        return
    custom_svg = _standalone_custom_svg(icon)
    if custom_svg:
        rel_id = images.rel_id_for(("custom", custom_svg), lambda: _rasterize_custom_icon_png(custom_svg))
        if rel_id is not None:
            _add_vsdx_image_overlay(rect_template, shape, rel_id, NODE_WIDTH / VSDX_SCALE, CUSTOM_ICON_TILE_HEIGHT / VSDX_SCALE, 0.0)


def _add_vsdx_edges(graph: dict, shapes_by_node_id: dict, connector_template) -> None:
    """Коннекторы по рёбрам графа; ребро на узел, которого нет среди фигур, пропускается."""
    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    for edge in graph["edges"]:
        source = shapes_by_node_id.get(edge["source_node_id"])
        target = shapes_by_node_id.get(edge["target_node_id"])
        if source is None or target is None:
            continue
        connector = connector_template.copy()
        source_fraction = _port_anchor_fraction(edge.get("source_interface"), _port_ticks_of(nodes_by_id[edge["source_node_id"]]))
        target_fraction = _port_anchor_fraction(edge.get("target_interface"), _port_ticks_of(nodes_by_id[edge["target_node_id"]]))
        connector.set_start_and_finish(_vsdx_port_anchor(source, source_fraction), _vsdx_port_anchor(target, target_fraction))
        _strip_dangling_glue_formulas(connector)
        connector.text = _vlan_label(edge)
        if not edge.get("is_active", True):
            # Тот же LinePattern=2 (пунктир), что и у рамки группы выше — параллель с
            # stroke-dasharray в .svg и pattern="dashed_medium" в .drawio для
            # is_active=False.
            connector.set_cell_value("LinePattern", "2")


def _clear_vsdx_template(page, template_ids: set) -> None:
    """Убирает со страницы шаблонные фигуры и секцию <Connects>.

    Шаблон media.vsdx несёт демонстрационные "глиняные" связи (<Connects>) между
    СВОИМИ фигурами (RECTANGLE/CONNECTED_SHAPE/...) — теми же, что удаляются циклом
    ниже. Shape.remove() в vsdx удаляет только сам элемент <Shape> и НЕ чистит секцию
    <Connects> — без этого шага на странице остаются ссылки FromSheet/ToSheet на уже
    не существующие ID. Проверено напрямую: с такими висячими ссылками headless
    LibreOffice рендерит лист ПОЛНОСТЬЮ ПУСТЫМ, даже после починки namespace ниже
    (это отдельный, более серьёзный источник находки №1, чем сама библиотека vsdx —
    баг в нашем коде очистки шаблона, а не в vsdx). Наши собственные соединители кладут
    координаты явно через set_start_and_finish и в этой секции не нуждаются, поэтому
    убираем её целиком, а не только осиротевшие записи."""
    from vsdx import namespace as visio_ns

    connects_el = page.xml.getroot().find(f"{visio_ns}Connects")
    if connects_el is not None:
        page.xml.getroot().remove(connects_el)
    for shape in list(page.child_shapes):
        if shape.ID in template_ids:
            shape.remove()


def export_vsdx(graph: dict) -> bytes:
    import vsdx

    template_path = os.path.join(os.path.dirname(vsdx.__file__), "media", "media.vsdx")

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = os.path.join(tmp_dir, "diagram.vsdx")
        shutil.copy(template_path, out_path)

        vf = vsdx.VisioFile(out_path)
        images = _VsdxImages()
        try:
            page = vf.get_page(0)
            page_height = _fit_vsdx_page_to_content(page, graph)  # дюймы; см. target_y в _place_vsdx_node
            template_shapes = list(page.child_shapes)
            template_ids = {s.ID for s in template_shapes}
            rect_template = _ShapeTemplate(next(s for s in template_shapes if "RECTANGLE" in (s.text or "")))
            connector_template = _ShapeTemplate(next(s for s in template_shapes if "STRAIGHT_CONNECTOR" in (s.text or "")))

            shapes_by_node_id = {}
            for node in graph["nodes"]:
                shape = _place_vsdx_node(rect_template, node, page_height)
                _style_vsdx_node(shape, node)
                if node["type"] != "group":
                    _overlay_vsdx_icon(rect_template, shape, node["icon"], images)
                shapes_by_node_id[node["id"]] = shape

            _add_vsdx_edges(graph, shapes_by_node_id, connector_template)
            _clear_vsdx_template(page, template_ids)
            vf.save_vsdx(out_path)
        finally:
            vf.close_vsdx()

        # См. docstring _finalize_vsdx_package: без этого шага результат читается обратно самой
        # vsdx (тесты ниже это проверяют), но открывается ПУСТЫМ листом в стороннем ПО.
        _finalize_vsdx_package(out_path, template_path)
        # После финализации, а не вместо неё — см. docstring _embed_vsdx_category_icons.
        _embed_vsdx_category_icons(out_path, images.pngs)

        with open(out_path, "rb") as fh:
            return fh.read()
