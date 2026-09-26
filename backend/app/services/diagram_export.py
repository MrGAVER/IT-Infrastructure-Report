"""
Экспорт диаграммы топологии сети в редактируемые внешние форматы (ТЗ, раздел 9). Все три
экспортёра читают ОДИН и тот же граф (dict вида {"nodes": [...], "edges": [...]}, как возвращает
services.diagram_graph.build_graph) и воспроизводят одну и ту же геометрию (прямоугольник узла,
цвет по дескриптору иконки, засечки портов для shape="switch", подписи) каждый своими средствами
— строковый SVG-шаблон, объектная модель drawpyo, копирование шаблонных фигур vsdx — а не через
сетевые стенсилы конкретного формата (раздел 4.3 ТЗ: "одинаковый вид во всех форматах").

Порядок фактической РЕАЛИЗАЦИИ ниже — .svg, затем .drawio, затем .vsdx, а не .drawio -> .vsdx ->
.svg, как перечислено в разделе 9 ТЗ (drawio там назван основным форматом для первой демонстрации
— этот приоритет не изменился, просто .svg было быстрее и безопаснее реализовать первым, чтобы
сразу проверить геометрию без внешних зависимостей). .vsdx устроен ощутимо иначе, чем ожидалось:
библиотека vsdx — это низкоуровневая работа с XML Element поверх уже СУЩЕСТВУЮЩЕГО файла
(редактирование, а не построение с нуля), без объектной модели уровня drawpyo. Раздел 14 ТЗ уже
заранее допускал ограничения именно у этого формата, поэтому .vsdx ниже воспроизводит геометрию
копированием и перемещением готовых фигур из шаблона (media.vsdx, поставляется вместе с пакетом)
— прямоугольник и прямой соединитель — без отдельных фигур-засечек портов (в отличие от .svg/
.drawio, где каждая засечка — самостоятельный примитив).

Готча .vsdx (см. _finalize_vsdx_package, _strip_dangling_glue_formulas и находку №1 отчёта об
экспорте диаграмм): экспортированный .vsdx читался обратно самой библиотекой vsdx без единой
жалобы (поэтому все тесты, гонявшие файл через vsdx.VisioFile туда и обратно, ничего не
замечали), но открывался ПОЛНОСТЬЮ ПУСТЫМ листом в стороннем ПО — обнаружено и воспроизведено
напрямую headless LibreOffice (soffice --headless --convert-to png), а не по одному лишь
описанию из отчёта. Причин оказалось три одновременно, каждая проверена изолированно
(бисекцией по XML-частям пакета и по шагам самого экспорта): дефект сериализации namespace в
самой vsdx 0.6.1 при ЛЮБОМ save_vsdx() (не только при .copy()); неочищенная секция <Connects> с
висячими ссылками на шаблонные фигуры, которые export_vsdx удаляет; и формулы динамической
"приклейки" коннектора (_WALKGLUE/_XFTRIGGER), скопированные из шаблона дословно и ссылающиеся
на те же удаляемые фигуры по имени ("Sheet.N"). Постобработка результата обязательна для
КАЖДОГО сохранённого .vsdx.
"""
from __future__ import annotations

import io
import os
import re
import shutil
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import quote
from xml.sax.saxutils import escape

NODE_WIDTH = 160
NODE_HEIGHT = 70
CUSTOM_ICON_FALLBACK_COLOR = "#cccccc"
GROUP_FILL_COLOR = "#dddddd"
VSDX_SCALE = 100.0  # пиксели графа -> дюймы Visio (чисто визуальный масштаб)

# Находка №4 отчёта об экспорте диаграмм (Фаза 2, п.4): раньше каждый формат подписывал узлы и
# рёбра шрифтом по умолчанию своего движка рендеринга (браузер для .svg, draw.io/Visio — своим),
# так что один и тот же граф визуально "звучал" по-разному в каждом формате. Calibri — не
# призвольный выбор: это единственный шрифт, который уже фигурирует в таблице шрифтов
# (FaceNames) шаблона media.vsdx, использованного в export_vsdx (см. находку №1, Фаза 1) — то
# есть .vsdx им и так пользуется неявно по умолчанию, без единой правки. Задав то же имя явно в
# .svg/.drawio, приводим все три формата к одному и тому же шрифту, ничем не рискуя в .vsdx.
# Возможности задать per-shape размер шрифта в .vsdx без риска нет — см. README, раздел
# «Известные ограничения»: у библиотеки vsdx нет API для создания Section "Character" с нуля, а
# у шаблонных фигур такой секции нет вовсе, так что 11pt/9pt ниже относятся только к .svg/.drawio.
DIAGRAM_FONT_FAMILY = "Calibri"
DIAGRAM_NODE_FONT_SIZE = 11
DIAGRAM_EDGE_FONT_SIZE = 9

# Находка №5 отчёта (Фаза 3, п.5 "кастомные SVG-иконки"): иконка категории раньше была мелким
# угловым акцентом (14x13, см. историю в diagram_icons.py), теперь — полноценный узнаваемый
# значок по центру верхней части узла, тем же viewBox "0 0 24 24", что и SHAPE_GLYPHS.
GLYPH_DISPLAY_SIZE = 32
GLYPH_TOP_MARGIN = 4


def _vlan_label(edge: dict) -> str:
    return ", ".join(f"VLAN {v['vlan_id']}" for v in edge.get("vlans", []))


def _device_fill_color(icon: dict) -> str:
    """Общая для .drawio и .vsdx логика цвета узла-устройства (группы красятся отдельно, см.
    вызывающий код): цвет категории берём только у сгенерированных иконок — у custom-иконок
    (icon["mode"] == "custom") ключа "color" нет вовсе, там для внешнего вида отвечает
    svg_markup (см. diagram_icons.build_device_icon), поэтому в .drawio/.vsdx, где произвольную
    SVG-разметку не вставить, откатываемся на нейтральный CUSTOM_ICON_FALLBACK_COLOR."""
    if icon.get("mode") == "generated":
        return icon.get("color", CUSTOM_ICON_FALLBACK_COLOR)
    return CUSTOM_ICON_FALLBACK_COLOR


def _port_ticks_of(node: dict) -> int:
    """Число засечек порта у узла — 0 для группы (своих портов не имеет, см.
    diagram_graph.build_group_node) и для узла-устройства без известных интерфейсов."""
    if node["type"] != "device":
        return 0
    return node["icon"].get("port_ticks", 0)


def _port_anchor_fraction(interface_ref: dict | None, port_ticks: int) -> float | None:
    """Доля (0..1) по ширине узла, куда должен упираться конец ребра — тот же расчёт, что и
    _svg_port_ticks/frontend DiagramDeviceNode.vue:tickX (см. находку №2 отчёта об экспорте
    диаграмм, Фаза 2 п.1: "точная привязка ребра к засечке порта"). None означает "у этого конца
    порт не резолвится (группа, custom-иконка или устройство без интерфейсов) — анкерить в центр
    узла, как раньше", а не "порт с индексом 0", поэтому проверяем именно на None, а не на falsy.
    port_index уже гарантированно < port_ticks на уровне графа (см. diagram_graph.GraphContext.
    interface_index) — здесь это не перепроверяется."""
    if not interface_ref or port_ticks <= 0:
        return None
    port_index = interface_ref.get("port_index")
    if port_index is None:
        return None
    return (port_index + 1) / (port_ticks + 1)


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
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
        f'<g fill="rgba(255,255,255,0.9)" color="rgba(255,255,255,0.9)">{glyph}</g></svg>'
    )
    return f"data:image/svg+xml,{quote(svg)}"


# --------------------------------------------------------------------------------------
# .svg
# --------------------------------------------------------------------------------------

def _esc(value) -> str:
    return escape(str(value)) if value not in (None, "") else ""


def _svg_port_ticks(x: float, y: float, width: float, height: float, ticks: int) -> str:
    if ticks <= 0:
        return ""
    spacing = width / (ticks + 1)
    return "".join(
        f'<rect class="port-tick" x="{x + spacing * (i + 1) - 2:.1f}" y="{y + height - 6:.1f}" width="4" height="6" fill="#222222"/>'
        for i in range(ticks)
    )


def _svg_node(node: dict, x: float, y: float) -> str:
    if node["type"] == "group":
        return (
            f'<g class="diagram-node diagram-group" data-node-id="{_esc(node["id"])}">'
            f'<rect x="{x}" y="{y}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" rx="8" '
            f'fill="{GROUP_FILL_COLOR}" stroke="#333333" stroke-width="1.5" stroke-dasharray="4,3"/>'
            f'<text x="{x + NODE_WIDTH / 2}" y="{y + NODE_HEIGHT / 2}" text-anchor="middle" '
            f'font-size="{DIAGRAM_NODE_FONT_SIZE}" font-family="{DIAGRAM_FONT_FAMILY}" fill="#222222">{_esc(node["label"])}</text>'
            f"</g>"
        )

    icon = node["icon"]
    parts = [f'<g class="diagram-node" data-node-id="{_esc(node["id"])}">']
    if icon.get("mode") == "custom" and icon.get("svg_markup"):
        parts.append(f'<g transform="translate({x},{y})">{icon["svg_markup"]}</g>')
    else:
        color = icon.get("color", CUSTOM_ICON_FALLBACK_COLOR)
        parts.append(f'<rect x="{x}" y="{y}" width="{NODE_WIDTH}" height="{NODE_HEIGHT}" rx="8" fill="{color}" stroke="#333333" stroke-width="1.5"/>')
        # Находка №5 отчёта (Фаза 3, п.5): полноценная узнаваемая иконка категории (не мелкий
        # угловой акцент, как в Фазе 2, п.2) по центру верхней части узла — та же разметка
        # (viewBox "0 0 24 24"), что рисует канвас (DiagramDeviceNode.vue), приходит готовой в
        # дескрипторе (icon["glyph"], см. diagram_icons.py:SHAPE_GLYPHS) как фрагмент SVG-разметки
        # (rect/circle/path) БЕЗ жёсткого fill/stroke на дочерних элементах — оба наследуются от
        # обёртки <g>, поэтому один и тот же фрагмент одинаково работает и здесь (белым по цветной
        # заливке узла), и в легенде (Фаза 3, п.1, тёмным по светлому фону).
        glyph = icon.get("glyph")
        if glyph:
            glyph_x = x + (NODE_WIDTH - GLYPH_DISPLAY_SIZE) / 2
            parts.append(
                f'<svg x="{glyph_x}" y="{y + GLYPH_TOP_MARGIN}" width="{GLYPH_DISPLAY_SIZE}" height="{GLYPH_DISPLAY_SIZE}" viewBox="0 0 24 24">'
                f'<g fill="rgba(255,255,255,0.9)" color="rgba(255,255,255,0.9)">{glyph}</g></svg>'
            )
        # Раньше засечки рисовались только при icon["shape"].startswith("switch"): backend уже
        # считает port_ticks для ЛЮБОЙ сгенерированной иконки (см. diagram_graph.py, п.5 —
        # раньше это тоже было ограничено только switch), а видимость в canvas (см.
        # DiagramDeviceNode.vue) завязана просто на "port_ticks > 0", без проверки формы —
        # сервер с несколькими NIC или файрвол с WAN/LAN/DMZ получают засечки точно так же, как
        # коммутатор. Проверка по shape была рассинхронизирована с этим и без явной привязки
        # ребра к засечке (см. _svg_edge ниже) была просто "лишним" рисунком у одной формы —
        # теперь, когда ребро реально целится в конкретную засечку, рисовать её нужно везде, где
        # она есть, иначе привязка у остальных форм будет указывать в пустое место.
        parts.append(_svg_port_ticks(x, y, NODE_WIDTH, NODE_HEIGHT, icon.get("port_ticks", 0)))
    parts.append(
        f'<text x="{x + NODE_WIDTH / 2}" y="{y + NODE_HEIGHT - 8}" text-anchor="middle" '
        f'font-size="{DIAGRAM_NODE_FONT_SIZE}" font-family="{DIAGRAM_FONT_FAMILY}" fill="#ffffff">{_esc(node["label"])}</text>'
    )
    parts.append("</g>")
    return "".join(parts)


def _svg_edge_anchor(node: dict, interface_ref: dict | None) -> tuple[float, float]:
    """Точка на этом конце ребра: если для узла резолвится конкретная засечка порта (находка №2
    отчёта об экспорте) — её координата (та же формула, что _svg_port_ticks), иначе (группа,
    custom-иконка, устройство без интерфейсов) — прежнее поведение, центр узла."""
    x, y = node["x"], node["y"]
    fraction = _port_anchor_fraction(interface_ref, _port_ticks_of(node))
    if fraction is None:
        return (x + NODE_WIDTH / 2, y + NODE_HEIGHT / 2)
    return (x + NODE_WIDTH * fraction, y + NODE_HEIGHT)


def _svg_edge(edge: dict, nodes_by_id: dict) -> str:
    x1, y1 = _svg_edge_anchor(nodes_by_id[edge["source_node_id"]], edge.get("source_interface"))
    x2, y2 = _svg_edge_anchor(nodes_by_id[edge["target_node_id"]], edge.get("target_interface"))
    dash = "" if edge.get("is_active", True) else ' stroke-dasharray="6,4"'
    label_text = _vlan_label(edge)
    label = (
        f'<text x="{(x1 + x2) / 2}" y="{(y1 + y2) / 2}" text-anchor="middle" font-size="{DIAGRAM_EDGE_FONT_SIZE}" font-family="{DIAGRAM_FONT_FAMILY}" fill="#555555">{_esc(label_text)}</text>'
        if label_text
        else ""
    )
    return (
        f'<g class="diagram-edge" data-edge-id="{_esc(edge["id"])}">'
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#666666" stroke-width="1.5"{dash}/>'
        f"{label}</g>"
    )


def export_svg(graph: dict) -> str:
    """Раздел 9 ТЗ: собирается напрямую из графовой модели строковым шаблоном — без
    растеризации и без headless-рендерера, тем же способом, каким drawpyo формирует свой XML."""
    nodes_by_id: dict[str, dict] = {n["id"]: n for n in graph["nodes"]}
    nodes_svg = [_svg_node(node, node["x"], node["y"]) for node in graph["nodes"]]

    edges_svg = [_svg_edge(e, nodes_by_id) for e in graph["edges"] if e["source_node_id"] in nodes_by_id and e["target_node_id"] in nodes_by_id]

    max_x = max((n["x"] for n in graph["nodes"]), default=0) + NODE_WIDTH + 40
    max_y = max((n["y"] for n in graph["nodes"]), default=0) + NODE_HEIGHT + 40
    body = "".join(edges_svg) + "".join(nodes_svg)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {max_x} {max_y}" width="{max_x}" height="{max_y}">'
        f'<rect width="100%" height="100%" fill="#ffffff"/>{body}</svg>'
    )


# --------------------------------------------------------------------------------------
# .drawio (drawpyo)
# --------------------------------------------------------------------------------------

def export_drawio(graph: dict) -> str:
    import drawpyo

    file = drawpyo.File()
    file.file_name = "diagram.drawio"
    page = drawpyo.Page(file=file)

    objects_by_node_id = {}
    for node in graph["nodes"]:
        obj = drawpyo.diagram.Object(page=page, value=node["label"])
        obj.position = (node["x"], node["y"])
        obj.width = NODE_WIDTH
        obj.height = NODE_HEIGHT
        # Визуальный паритет с .svg/канвасом, где у узла и группы rx="8" (скруглённые углы) —
        # без этого .drawio-узлы рисовались строго прямоугольными.
        obj.rounded = 1
        # Находка №4 отчёта (Фаза 2, п.4): явный шрифт вместо дефолтного шрифта draw.io — та же
        # пара family/size, что и в .svg (см. DIAGRAM_FONT_FAMILY выше). text_format — штатный
        # (не самодельный) способ: drawpyo.diagram.Object уже создаёт TextFormat() по умолчанию,
        # и в отличие от style_attributes (которым для Edge приходится подделывать конкретные
        # именованные kwargs) это работает одинаково что для Object, что для Edge.
        obj.text_format.fontFamily = DIAGRAM_FONT_FAMILY
        obj.text_format.fontSize = DIAGRAM_NODE_FONT_SIZE
        if node["type"] == "group":
            obj.fillColor = GROUP_FILL_COLOR
            obj.dashed = 1
        else:
            icon = node["icon"]
            obj.fillColor = _device_fill_color(icon)
            # Раньше — только icon["shape"].startswith("switch"), см. тот же комментарий у
            # _svg_node про рассинхронизацию с port_ticks, который backend считает для ЛЮБОЙ
            # сгенерированной иконки: без этого у остальных форм ребро (см. ниже exitX/entryX)
            # целилось бы в засечку, которой на самой фигуре не видно.
            if icon.get("mode") == "generated":
                glyph = icon.get("glyph")
                if glyph:
                    # Находка №5 отчёта (Фаза 3, п.5): полноценная узнаваемая иконка по центру
                    # верхней части узла (не мелкий угловой акцент 14x13 из Фазы 2, п.2) — та же
                    # позиция/размер, что и в .svg (_svg_node) и на канвасе (DiagramDeviceNode.vue).
                    glyph_obj = drawpyo.diagram.Object(page=page, value="")
                    glyph_obj.position = (node["x"] + (NODE_WIDTH - GLYPH_DISPLAY_SIZE) / 2, node["y"] + GLYPH_TOP_MARGIN)
                    glyph_obj.width = GLYPH_DISPLAY_SIZE
                    glyph_obj.height = GLYPH_DISPLAY_SIZE
                    # apply_style_string() режет по первому "=" — для data URI использовать
                    # нельзя (см. docstring _glyph_data_uri), поэтому выставляем атрибуты стиля
                    # напрямую тем же способом, каким это делает сама apply_style_string.
                    glyph_obj._add_and_set_style_attrib("shape", "image")
                    glyph_obj._add_and_set_style_attrib("image", _glyph_data_uri(glyph))

                ticks = icon.get("port_ticks", 0)
                if ticks:
                    spacing = NODE_WIDTH / (ticks + 1)
                    for i in range(ticks):
                        tick = drawpyo.diagram.Object(page=page, value="")
                        tick.position = (node["x"] + spacing * (i + 1) - 2, node["y"] + NODE_HEIGHT - 6)
                        tick.width = 4
                        tick.height = 6
                        tick.fillColor = "#222222"
        objects_by_node_id[node["id"]] = obj

    nodes_by_id = {n["id"]: n for n in graph["nodes"]}
    for edge in graph["edges"]:
        source = objects_by_node_id.get(edge["source_node_id"])
        target = objects_by_node_id.get(edge["target_node_id"])
        if source is None or target is None:
            continue
        # line_end_*="none" — связь между устройствами не имеет "направления" (в отличие от
        # потока данных), а без явного none drawio.js подставляет свою стрелку по умолчанию;
        # .svg/.vsdx стрелок не рисуют вовсе, этим достигается параллель между форматами.
        # pattern="dashed_medium" — та же семантика, что и stroke-dasharray в .svg для
        # is_active=False (раздел 4.4 ТЗ: неактивная связь размечается визуально, не только
        # цветом в интерактивном канвасе).
        edge_kwargs = {
            "line_end_source": "none",
            "line_end_target": "none",
            "pattern": None if edge.get("is_active", True) else "dashed_medium",
        }
        # Находка №2 отчёта об экспорте (Фаза 2, п.1): "точная привязка ребра к засечке порта" —
        # entryX/entryY (и exitX/exitY) как доля 0-1 от габарита фигуры, mxGraph-конвенция
        # (0,0)=левый верхний угол, (1,1)=правый нижний. Если для конца ребра порт не резолвится
        # (группа/custom-иконка/устройство без интерфейсов) — оставляем как раньше, без entry/exit,
        # drawio.js сам выберет точку автоматической маршрутизации.
        exit_fraction = _port_anchor_fraction(edge.get("source_interface"), _port_ticks_of(nodes_by_id[edge["source_node_id"]]))
        if exit_fraction is not None:
            edge_kwargs["exitX"] = exit_fraction
            edge_kwargs["exitY"] = 1.0
        entry_fraction = _port_anchor_fraction(edge.get("target_interface"), _port_ticks_of(nodes_by_id[edge["target_node_id"]]))
        if entry_fraction is not None:
            edge_kwargs["entryX"] = entry_fraction
            edge_kwargs["entryY"] = 1.0
        edge_obj = drawpyo.diagram.Edge(page=page, source=source, target=target, label=_vlan_label(edge), **edge_kwargs)
        # Находка №4 отчёта (Фаза 2, п.4): тот же явный шрифт, что и у узлов, — для метки связи.
        edge_obj.text_format.fontFamily = DIAGRAM_FONT_FAMILY
        edge_obj.text_format.fontSize = DIAGRAM_EDGE_FONT_SIZE

    return file.xml


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
            root = ET.fromstring(data)
            if root.tag.startswith("{"):
                ET.register_namespace("", root.tag[1:].split("}", 1)[0])
            buf = io.BytesIO()
            ET.ElementTree(root).write(buf, xml_declaration=True, encoding="UTF-8", method="xml")
            entries[part] = buf.getvalue()

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


def export_vsdx(graph: dict) -> bytes:
    import vsdx
    from vsdx import namespace as visio_ns

    template_path = os.path.join(os.path.dirname(vsdx.__file__), "media", "media.vsdx")

    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = os.path.join(tmp_dir, "diagram.vsdx")
        shutil.copy(template_path, out_path)

        vf = vsdx.VisioFile(out_path)
        try:
            page = vf.get_page(0)
            page_height = _fit_vsdx_page_to_content(page, graph)  # дюймы; см. target_y ниже
            template_shapes = list(page.child_shapes)
            template_ids = {s.ID for s in template_shapes}
            rect_template = next(s for s in template_shapes if "RECTANGLE" in (s.text or ""))
            connector_template = next(s for s in template_shapes if "STRAIGHT_CONNECTOR" in (s.text or ""))

            shapes_by_node_id = {}
            for node in graph["nodes"]:
                shape = rect_template.copy()
                shape.text = node["label"]
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
                if node["type"] == "group":
                    # Раздел 4.4 ТЗ: группа должна визуально отличаться от устройства так же,
                    # как в .svg/.drawio (светло-серая заливка + пунктирная рамка), а не только
                    # подписью — иначе на .vsdx-экспорте группу от обычного узла не отличить.
                    shape.fill_color = GROUP_FILL_COLOR
                    shape.set_cell_value("LinePattern", "2")
                else:
                    color = _device_fill_color(node["icon"])
                    shape.fill_color = color
                    shape.line_color = color
                shapes_by_node_id[node["id"]] = shape

            nodes_by_id = {n["id"]: n for n in graph["nodes"]}
            for edge in graph["edges"]:
                source = shapes_by_node_id.get(edge["source_node_id"])
                target = shapes_by_node_id.get(edge["target_node_id"])
                if source is None or target is None:
                    continue
                connector = connector_template.copy()
                source_fraction = _port_anchor_fraction(
                    edge.get("source_interface"), _port_ticks_of(nodes_by_id[edge["source_node_id"]])
                )
                target_fraction = _port_anchor_fraction(
                    edge.get("target_interface"), _port_ticks_of(nodes_by_id[edge["target_node_id"]])
                )
                connector.set_start_and_finish(
                    _vsdx_port_anchor(source, source_fraction), _vsdx_port_anchor(target, target_fraction)
                )
                _strip_dangling_glue_formulas(connector)
                connector.text = _vlan_label(edge)
                if not edge.get("is_active", True):
                    # Тот же LinePattern=2 (пунктир), что и у рамки группы выше — параллель с
                    # stroke-dasharray в .svg и pattern="dashed_medium" в .drawio для
                    # is_active=False.
                    connector.set_cell_value("LinePattern", "2")

            # Шаблон media.vsdx несёт демонстрационные "глиняные" связи (<Connects>) между
            # СВОИМИ фигурами (RECTANGLE/CONNECTED_SHAPE/...) — теми же, что удаляются циклом
            # ниже. Shape.remove() в vsdx удаляет только сам элемент <Shape> и НЕ чистит секцию
            # <Connects> — без этого шага на странице остаются ссылки FromSheet/ToSheet на уже
            # не существующие ID. Проверено напрямую: с такими висячими ссылками headless
            # LibreOffice рендерит лист ПОЛНОСТЬЮ ПУСТЫМ, даже после починки namespace ниже
            # (это отдельный, более серьёзный источник находки №1, чем сама библиотека vsdx —
            # баг в нашем коде очистки шаблона, а не в vsdx). Наши собственные соединители кладут
            # координаты явно через set_start_and_finish и в этой секции не нуждаются, поэтому
            # убираем её целиком, а не только осиротевшие записи.
            connects_el = page.xml.getroot().find(f"{visio_ns}Connects")
            if connects_el is not None:
                page.xml.getroot().remove(connects_el)

            for shape in list(page.child_shapes):
                if shape.ID in template_ids:
                    shape.remove()

            vf.save_vsdx(out_path)
        finally:
            vf.close_vsdx()

        # См. docstring _finalize_vsdx_package: без этого шага результат читается обратно самой
        # vsdx (тесты ниже это проверяют), но открывается ПУСТЫМ листом в стороннем ПО.
        _finalize_vsdx_package(out_path, template_path)

        with open(out_path, "rb") as fh:
            return fh.read()
