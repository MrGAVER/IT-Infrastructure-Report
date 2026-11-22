"""
Word-документ «Приложение к структурной схеме» — отрисовка данных structural_appendix.py.

Структура повторяет образец заказчика: заголовок «Приложение к структурной схеме» / «ЕАИС <имя>»,
затем три пронумерованные таблицы («Таблица 1» курсивом над таблицей). У каждой таблицы первая строка —
её название на всю ширину, вторая — шапка колонок; обе повторяются на каждой странице. Объединения
ячеек, как в образце:

- таблица 1: «Линия связи» — на две колонки (устройство — устройство), «Назначение» объединено по
  вертикали на группу строк с одним назначением;
- таблица 2: строка-заголовок устройства (стека) на всю ширину;
- таблица 3: «Место размещения» объединено по вертикали на устройства одного помещения.

Оформление (шрифт Times New Roman, сетка таблиц, поля) выбрано по обычаям делового документа: самого
образца .docx в задаче не было, только его текст, поэтому ширины колонок и кегль — не копия.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional, Sequence

from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from docx.table import Table, _Cell
from sqlalchemy.orm import Session

from .computed import local_timestamp_suffix
from .report_engine import safe_report_filename
from .structural_appendix import AppendixData, collect_structural_appendix

DOCUMENT_TITLE = "Приложение к структурной схеме"
DEFAULT_IS_NAME = "ЕАИС ТО"
MAX_IS_NAME_LENGTH = 100

_FONT = "Times New Roman"
_BODY_PT = 11
_GROUP_ROW_FILL = "EDEDED"

# Ширины колонок (см) под A4 книжной с полями 2,5 / 1,5: суммарно 17 см.
_LINKS_WIDTHS = (6.8, 6.8, 3.4)
_VLAN_WIDTHS = (4.0, 6.0, 7.0)
_EQUIPMENT_WIDTHS = (4.6, 2.8, 3.2, 3.4, 3.0)

# Символы, недопустимые в XML 1.0: python-docx на них падает, а в реестре такой текст возможен (вставка
# из терминала или Excel).
_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


class StructuralAppendixError(ValueError):
    """Ошибка параметров формирования, пригодная для показа пользователю."""


# Ведущее слово «ЕАИС»/«ИС» в имени: заголовки сами добавляют «ЕАИС …» и «… ИС …», поэтому введённое целиком
# «ЕАИС ТО» (так имя показано и в поле по умолчанию) иначе дало бы «ЕАИС ЕАИС ТО». Снимается только слово
# целиком и только если после него что-то осталось («ИСУ» и одиночное «ЕАИС» не трогаются).
_IS_NAME_PREFIX = re.compile(r"^(?:ЕАИС|ИС)\s+(?=\S)", re.IGNORECASE)


def normalize_is_name(raw: Optional[str]) -> str:
    """Короткое имя ИС для заголовков: без лишних пробелов, управляющих символов и ведущего «ЕАИС»/«ИС»,
    1–100 символов. Пустое значение — ошибка, а не молчаливая подстановка: документ без имени ИС выглядел бы
    законченным, но был бы испорчен."""
    name = " ".join(_XML_INVALID.sub("", raw or "").split())
    name = _IS_NAME_PREFIX.sub("", name)
    if not name:
        raise StructuralAppendixError("Укажите короткое имя информационной системы")
    if len(name) > MAX_IS_NAME_LENGTH:
        raise StructuralAppendixError(f"Короткое имя ИС не длиннее {MAX_IS_NAME_LENGTH} символов")
    return name


def _text(value: str) -> str:
    return _XML_INVALID.sub("", value)


# ---------- низкоуровневые помощники над python-docx ----------


def _style_document(doc: DocumentObject) -> None:
    section = doc.sections[0]
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.left_margin, section.right_margin = Cm(2.5), Cm(1.5)
    section.top_margin = section.bottom_margin = Cm(2.0)

    normal = doc.styles["Normal"]
    normal.font.name = _FONT
    normal.font.size = Pt(_BODY_PT)
    rfonts = normal.element.get_or_add_rPr().get_or_add_rFonts()
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), _FONT)  # без eastAsia Word подставит другой шрифт для кириллицы
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.space_before = Pt(0)


def _write(cell: _Cell, text: str, *, bold: bool = False, italic: bool = False, align: int = WD_ALIGN_PARAGRAPH.LEFT) -> None:
    """Заменяет содержимое ячейки; "\n" в тексте — отдельный абзац (несколько IP в одной ячейке)."""
    cell.text = ""
    lines = _text(text).split("\n") if text else [""]
    for index, line in enumerate(lines):
        paragraph = cell.paragraphs[0] if index == 0 else cell.add_paragraph()
        paragraph.alignment = align
        run = paragraph.add_run(line)
        run.bold = bold
        run.italic = italic
    cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER


def _shade(cell: _Cell, fill: str) -> None:
    props = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), fill)
    props.append(shading)


def _row_flag(row, tag: str) -> None:
    props = row._tr.get_or_add_trPr()
    props.append(OxmlElement(tag))


def _keep_row_together(row) -> None:
    _row_flag(row, "w:cantSplit")


def _repeat_row_on_each_page(row) -> None:
    _row_flag(row, "w:tblHeader")


def _caption(doc: DocumentObject, number: int) -> None:
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    paragraph.paragraph_format.space_before = Pt(12 if number > 1 else 6)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.paragraph_format.keep_with_next = True  # подпись не остаётся одна внизу страницы
    paragraph.add_run(f"Таблица {number}").italic = True


def _new_table(doc: DocumentObject, widths: Sequence[float], title: str, header: Sequence[str] = ()) -> Table:
    """Таблица с названием на всю ширину и (необязательно) шапкой из одной ячейки на колонку."""
    table = doc.add_table(rows=1, cols=len(widths))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    for column, width in zip(table.columns, widths):
        column.width = Cm(width)
    for cell, width in zip(table.rows[0].cells, widths):
        cell.width = Cm(width)

    title_row = table.rows[0]
    merged = title_row.cells[0].merge(title_row.cells[-1])
    _write(merged, title, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    _repeat_row_on_each_page(title_row)
    _keep_row_together(title_row)

    if header:
        header_row = _add_row(table, widths)
        for cell, text in zip(header_row.cells, header):
            _write(cell, text, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        _repeat_row_on_each_page(header_row)
    return table


def _add_row(table: Table, widths: Sequence[float]):
    row = table.add_row()
    for cell, width in zip(row.cells, widths):
        cell.width = Cm(width)
    _keep_row_together(row)
    return row


def _merge_vertically(table: Table, column: int, first_row: int, last_row: int, text: str) -> None:
    """Объединяет ячейки колонки с first_row по last_row и пишет текст в объединённую ячейку (текст
    пишется ПОСЛЕ слияния, иначе в ней остались бы пустые абзацы поглощённых ячеек)."""
    top = table.cell(first_row, column)
    merged = top.merge(table.cell(last_row, column)) if last_row > first_row else top
    _write(merged, text)


def _empty_row(table: Table, widths: Sequence[float]) -> None:
    row = _add_row(table, widths)
    merged = row.cells[0].merge(row.cells[-1])
    _write(merged, "Нет данных", italic=True, align=WD_ALIGN_PARAGRAPH.CENTER)


# ---------- таблицы ----------


def _links_table(doc: DocumentObject, data: AppendixData, is_name: str) -> None:
    widths = _LINKS_WIDTHS
    table = _new_table(doc, widths, f"Сведения о назначении линий связи ИС {is_name}")
    header_row = _add_row(table, widths)
    _write(header_row.cells[0].merge(header_row.cells[1]), "Линия связи", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    _write(header_row.cells[2], "Назначение", bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    _repeat_row_on_each_page(header_row)

    if not data.links:
        _empty_row(table, widths)
        return
    start = len(table.rows)  # индекс первой строки данных
    for link in data.links:
        row = _add_row(table, widths)
        _write(row.cells[0], link.left)
        _write(row.cells[1], link.right)
    # Назначение — одна ячейка на группу подряд идущих линий с одинаковым назначением.
    index = 0
    while index < len(data.links):
        end = index
        while end + 1 < len(data.links) and data.links[end + 1].purpose == data.links[index].purpose:
            end += 1
        _merge_vertically(table, 2, start + index, start + end, data.links[index].purpose)
        index = end + 1


def _vlan_table(doc: DocumentObject, data: AppendixData, is_name: str) -> None:
    widths = _VLAN_WIDTHS
    table = _new_table(doc, widths, f"Перечень виртуальных локальных вычислительных сетей (VLAN) ИС {is_name}", ("Идентификатор VLAN", "Имя VLAN", "IP-адресация"))
    if not data.vlan_groups:
        _empty_row(table, widths)
        return
    for group in data.vlan_groups:
        title_row = _add_row(table, widths)
        merged = title_row.cells[0].merge(title_row.cells[-1])
        _write(merged, group.title, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
        _shade(merged, _GROUP_ROW_FILL)
        for vlan in group.rows:
            row = _add_row(table, widths)
            _write(row.cells[0], vlan.vlan_id, align=WD_ALIGN_PARAGRAPH.CENTER)
            _write(row.cells[1], vlan.name)
            _write(row.cells[2], vlan.addressing)


def _equipment_table(doc: DocumentObject, data: AppendixData, is_name: str) -> None:
    widths = _EQUIPMENT_WIDTHS
    table = _new_table(
        doc, widths, f"Перечень телекоммуникационного оборудования ИС {is_name}", ("Наименование оборудования", "Заводской номер", "Системное имя", "IP-адрес управления", "Место размещения")
    )
    if not data.equipment:
        _empty_row(table, widths)
        return
    start = len(table.rows)
    for item in data.equipment:
        row = _add_row(table, widths)
        _write(row.cells[0], item.name)
        _write(row.cells[1], item.serial_number)
        _write(row.cells[2], item.system_name)
        _write(row.cells[3], "\n".join(item.management_ips))
    index = 0
    while index < len(data.equipment):
        end = index
        while end + 1 < len(data.equipment) and data.equipment[end + 1].placement_key == data.equipment[index].placement_key:
            end += 1
        _merge_vertically(table, 4, start + index, start + end, data.equipment[index].placement)
        index = end + 1


# ---------- сборка документа ----------


def render_structural_appendix(data: AppendixData, is_name: str) -> DocumentObject:
    doc = Document()
    _style_document(doc)

    for text in (DOCUMENT_TITLE, f"ЕАИС {is_name}"):
        paragraph = doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_after = Pt(6)
        run = paragraph.add_run(_text(text))
        run.bold = True
        run.font.size = Pt(14)

    for number, table_builder in enumerate((_links_table, _vlan_table, _equipment_table), 1):
        _caption(doc, number)
        table_builder(doc, data, is_name)
    return doc


def build_structural_appendix(session: Session, report_dir: Path, *, is_name: Optional[str], structural_unit_ids: Optional[list[str]] = None) -> Path:
    """Формирует docx в report_dir и возвращает путь к файлу.

    Пример: build_structural_appendix(session, REPORT_DIR, is_name="ЕАИС ТО")  # в заголовках — «ЕАИС ТО», «… ИС ТО»
    Бросает StructuralAppendixError при недопустимом имени ИС."""
    name = normalize_is_name(is_name)
    doc = render_structural_appendix(collect_structural_appendix(session, structural_unit_ids), name)
    report_dir.mkdir(parents=True, exist_ok=True)
    base_name = safe_report_filename(f"{DOCUMENT_TITLE} {name}").replace(" ", "_")
    path = report_dir / f"{base_name}_{local_timestamp_suffix()}.docx"
    doc.save(path)
    return path
