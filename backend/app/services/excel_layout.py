"""Оформление листов Excel-отчёта: рамки вокруг записей, объединение повторяющихся ячеек и
закрепление шапки.

Модуль не зависит ни от SQLAlchemy, ни от моделей реестра: на вход он получает только готовый
лист openpyxl и описание групп строк, поэтому его можно вызвать из любого генератора отчёта и
проверять на «голом» Workbook. Что именно считать записью (ИС, устройство, ВМ) и какие колонки
повторяются, решает вызывающий код (см. reporting.build_report) — здесь только отрисовка.

Термины:
- группа строк — диапазон (первая, последняя) строк листа, относящихся к одной записи реестра;
  нумерация строк с 1, границы включительно. Запись из одной строки — группа (n, n);
- шапка — первые header_rows строк листа.

Правила оформления:
- вся таблица, включая шапку, получает тонкую сетку;
- шапка и каждая группа строк обводятся рамкой средней толщины, поэтому соседние записи (и шапка
  с данными) визуально отделены друг от друга;
- ячейки заданных колонок внутри группы из нескольких строк объединяются по вертикали, чтобы
  повторяющееся название (например, устройства на листе «Организация подключений») не
  дублировалось в каждой строке;
- шапка закрепляется, чтобы оставаться на экране при прокрутке.
"""
from __future__ import annotations

from typing import Iterable, Optional

from openpyxl.styles import Border, Side

# Тонкая сетка внутри записи и рамка средней толщины вокруг записи/шапки.
THIN_SIDE = Side(style="thin", color="808080")
FRAME_SIDE = Side(style="medium", color="000000")

RowSpan = tuple[int, int]


def single_row_spans(ws, header_rows: int = 1) -> list[RowSpan]:
    """Группы по одной строке на каждую строку данных — для листов, где запись реестра (ИС,
    устройство, ВМ) занимает ровно одну строку."""
    return [(row, row) for row in range(header_rows + 1, ws.max_row + 1)]


def merge_vertical(ws, spans: Iterable[RowSpan], columns: Iterable[int]) -> None:
    """Объединяет по вертикали ячейки колонок columns (номера с 1) внутри каждой группы строк.

    Значение остаётся в верхней ячейке объединения, остальные очищаются (так работает
    openpyxl/Excel). Группа из одной строки не трогается: объединять нечего, а у обычной ячейки
    высота строки подбирается Excel по тексту, у объединённой — нет."""
    columns = tuple(columns)
    for first, last in spans:
        if last <= first:
            continue
        for column in columns:
            ws.merge_cells(start_row=first, end_row=last, start_column=column, end_column=column)


def _with_edges(cell, *, left=None, right=None, top=None, bottom=None) -> None:
    """Подменяет у ячейки только указанные стороны границы, остальные оставляет как были."""
    border = cell.border
    cell.border = Border(
        left=left or border.left, right=right or border.right,
        top=top or border.top, bottom=bottom or border.bottom,
    )


def _frame(ws, first: int, last: int, max_col: int) -> None:
    """Обводит строки first..last по всей ширине листа рамкой FRAME_SIDE.

    Горизонтальные границы прорисовываются с обеих сторон (нижняя граница верхней записи и
    верхняя граница нижней): для общей грани двух ячеек Excel не гарантирует, какое из двух
    описаний он покажет, если они различаются."""
    max_row = ws.max_row
    for column in range(1, max_col + 1):
        _with_edges(ws.cell(row=first, column=column), top=FRAME_SIDE)
        _with_edges(ws.cell(row=last, column=column), bottom=FRAME_SIDE)
        if first > 1:
            _with_edges(ws.cell(row=first - 1, column=column), bottom=FRAME_SIDE)
        if last < max_row:
            _with_edges(ws.cell(row=last + 1, column=column), top=FRAME_SIDE)
    for row in range(first, last + 1):
        _with_edges(ws.cell(row=row, column=1), left=FRAME_SIDE)
        _with_edges(ws.cell(row=row, column=max_col), right=FRAME_SIDE)


def apply_borders(ws, spans: Iterable[RowSpan], header_rows: int = 1) -> None:
    """Тонкая сетка по всему листу и рамка вокруг шапки и каждой группы строк.

    Вызывается ПОСЛЕ merge_vertical: ячейки объединения (MergedCell) тоже получают границу, иначе
    Excel рисует у объединённой области только границу верхней левой ячейки."""
    max_row, max_col = ws.max_row, ws.max_column
    if max_row < 1 or max_col < 1:
        return
    grid = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)
    for row in ws.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_col):
        for cell in row:
            cell.border = grid
    _frame(ws, 1, min(header_rows, max_row), max_col)
    for first, last in spans:
        _frame(ws, first, last, max_col)


def freeze_header(ws, header_rows: int = 1) -> None:
    """Закрепляет строки шапки вверху листа — при прокрутке они остаются на экране."""
    ws.freeze_panes = f"A{header_rows + 1}"


def apply_sheet_layout(ws, *, spans: Optional[list[RowSpan]] = None, merge_columns: Iterable[int] = (),
                        header_rows: int = 1) -> None:
    """Полное оформление листа отчёта: объединение, рамки, закрепление шапки.

    spans — группы строк, относящиеся к одной записи реестра. None — каждая строка данных сама
    запись (листы ИС, устройств, ВМ); пустой список — на листе нет данных, оформляется только
    шапка. merge_columns — колонки (с 1), чьи ячейки объединяются внутри групп из нескольких
    строк."""
    if spans is None:
        spans = single_row_spans(ws, header_rows)
    merge_vertical(ws, spans, merge_columns)
    apply_borders(ws, spans, header_rows)
    freeze_header(ws, header_rows)
