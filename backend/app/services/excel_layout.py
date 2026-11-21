"""Оформление листов Excel-отчёта: рамки вокруг записей, объединение повторяющихся ячеек,
закрепление шапки, ширина колонок и высота шапки.

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
- шапка закрепляется, чтобы оставаться на экране при прокрутке;
- ширина колонки подбирается по данным, а не по заголовку (заголовки регламентированных форм —
  до 300 символов, и раньше они раздували каждую колонку до максимума); заголовок при этом всегда
  виден целиком: колонка не уже самого длинного слова заголовка и не уже, чем нужно, чтобы шапка
  уложилась в MAX_HEADER_LINES строк, а высота строки шапки равна реальному числу строк
  переноса;
- у объединённого блока строк высота не подбирается приложением автоматически (объединённые
  ячейки в подборе высоты строки не участвуют), поэтому, если значение объединённой ячейки не
  помещается в блок, строки блока растягиваются.

Число строк переноса — оценка (Excel и LibreOffice переносят текст сами): считается жадным
переносом по словам для Calibri 11, с запасом в «безопасную» сторону — лучше лишняя полстроки
свободного места, чем обрезанный заголовок.
"""

from __future__ import annotations

import math
from typing import Iterable, Optional

from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.styles.cell_style import StyleArray
from openpyxl.utils import get_column_letter

# Тонкая сетка внутри записи и рамка средней толщины вокруг записи/шапки.
THIN_SIDE = Side(style="thin", color="808080")
FRAME_SIDE = Side(style="medium", color="000000")

# Шапка: жирный Calibri 11 по центру с переносом. Имя и размер шрифта заданы явно: Font(bold=True)
# без имени LibreOffice рисует другим (засечковым, более широким) шрифтом, и оценка переноса ниже
# к такой шапке неприменима.
HEADER_FONT = Font(name="Calibri", size=11, bold=True)
HEADER_ALIGNMENT = Alignment(horizontal="center", vertical="center", wrap_text=True)

LINE_HEIGHT_PT = 15.0  # высота одной строки текста Calibri 11 в Excel
MAX_ROW_HEIGHT_PT = 409.0  # потолок высоты строки в Excel
MIN_COLUMN_WIDTH = 8  # не уже (в символах) — иначе колонка с «№» или «Да/Нет» теряет читаемость
MAX_COLUMN_WIDTH = 55  # не шире: длинный текст переносится по строкам, а не растягивает колонку
MAX_HEADER_LINES = 8  # шапка не выше стольких строк: колонку с длинным заголовком расширяем
DEFAULT_COLUMN_WIDTH = 8.43  # ширина колонки Excel, если не задана явно

# Модель переноса строк: символов в строке = (ширина колонки − поля) / коэффициент. Параметры подобраны
# по метрикам Calibri 11 (в LibreOffice это Carlito) на заголовках отчёта при разной ширине колонок —
# около тысячи случаев, ни одного занижения числа строк, а завышение — как правило, на одну строку.
# Пробелы и строчные буквы уже «цифры», заглавные шире, поэтому коэффициент не 1.0 — оценка
# сознательно пессимистичнее, чтобы текст не обрезался.
TEXT_WIDTH_FACTOR = 1.05  # обычный текст
BOLD_WIDTH_FACTOR = 1.1  # жирные символы шире обычных
COLUMN_PADDING = 1.5  # поля ячейки внутри ширины колонки (в символах)
FILTER_BUTTON_WIDTH = 2.0  # кнопка автофильтра в ячейке шапки закрывает часть строки (LibreOffice сужает
# под неё текст, в Excel она перекрывает его) — шапке оставляем под неё место

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


def _style_of(cell) -> StyleArray:
    """Массив стиля ячейки (у ещё не оформлявшейся ячейки он создаётся лениво — так же делает присваивание `cell.border = ...`)."""
    if not cell._style:
        cell._style = StyleArray()
    return cell._style


class _FrameEdges:
    """Подмена сторон границы у ячеек с кэшем — без создания и хеширования `Border` на каждую ячейку.

    Рамка касается тысяч ячеек, а различных сочетаний «прежняя граница + одна сторона рамки» всего несколько. Раньше на каждую
    ячейку создавался новый `Border`, который openpyxl хешировал и сравнивал (`IndexedList.add`) — это была основная часть времени
    формирования отчёта. Теперь результат для пары (номер прежней границы, сторона) считается один раз и дальше берётся из
    словаря; номер границы пишется прямо в стиль ячейки (то, что делает присваивание `cell.border`). Границы в таблицу книги
    добавляются в том же порядке и с теми же значениями, что и раньше, поэтому оформление файла не меняется.

    Меняется только указанная сторона, остальные остаются как были."""

    _SIDES = ("left", "right", "top", "bottom")

    def __init__(self, ws) -> None:
        self._borders = ws.parent._borders
        self._cache: dict[tuple[int, str], int] = {}

    def apply(self, cell, edge: str) -> None:
        style = _style_of(cell)
        key = (style.borderId, edge)
        border_id = self._cache.get(key)
        if border_id is None:
            current = self._borders[style.borderId]
            sides = {name: getattr(current, name) for name in self._SIDES}
            sides[edge] = FRAME_SIDE
            border_id = self._borders.add(Border(**sides))
            self._cache[key] = border_id
        style.borderId = border_id


def _frame(ws, first: int, last: int, max_col: int, max_row: int, edges: _FrameEdges) -> None:
    """Обводит строки first..last по всей ширине листа рамкой FRAME_SIDE.

    Горизонтальные границы прорисовываются с обеих сторон (нижняя граница верхней записи и
    верхняя граница нижней): для общей грани двух ячеек Excel не гарантирует, какое из двух
    описаний он покажет, если они различаются.

    max_row — число строк листа, вычисленное вызывающим один раз: `ws.max_row` обходит все ячейки листа."""
    for column in range(1, max_col + 1):
        edges.apply(ws.cell(row=first, column=column), "top")
        edges.apply(ws.cell(row=last, column=column), "bottom")
        if first > 1:
            edges.apply(ws.cell(row=first - 1, column=column), "bottom")
        if last < max_row:
            edges.apply(ws.cell(row=last + 1, column=column), "top")
    for row in range(first, last + 1):
        edges.apply(ws.cell(row=row, column=1), "left")
        edges.apply(ws.cell(row=row, column=max_col), "right")


def apply_borders(ws, spans: Iterable[RowSpan], header_rows: int = 1) -> None:
    """Тонкая сетка по всему листу и рамка вокруг шапки и каждой группы строк.

    Вызывается ПОСЛЕ merge_vertical: ячейки объединения (MergedCell) тоже получают границу, иначе
    Excel рисует у объединённой области только границу верхней левой ячейки."""
    max_row, max_col = ws.max_row, ws.max_column
    if max_row < 1 or max_col < 1:
        return
    grid = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)
    # Одна и та же сетка у всех ячеек: номер границы в таблице книги берём один раз и пишем в стиль напрямую,
    # вместо `cell.border = grid` с хешированием Border на каждую ячейку.
    grid_id = ws.parent._borders.add(grid)
    for row in ws.iter_rows(min_row=1, max_row=max_row, min_col=1, max_col=max_col):
        for cell in row:
            _style_of(cell).borderId = grid_id
    edges = _FrameEdges(ws)
    _frame(ws, 1, min(header_rows, max_row), max_col, max_row, edges)
    for first, last in spans:
        _frame(ws, first, last, max_col, max_row, edges)


def freeze_header(ws, header_rows: int = 1) -> None:
    """Закрепляет строки шапки вверху листа — при прокрутке они остаются на экране."""
    ws.freeze_panes = f"A{header_rows + 1}"


def style_header(ws, header_rows: int = 1) -> None:
    """Шрифт и выравнивание шапки (HEADER_FONT, по центру, с переносом).

    Применять до общего выравнивания данных листа и не затирать его: у ячеек шапки оно другое."""
    for row in ws.iter_rows(min_row=1, max_row=header_rows):
        for cell in row:
            cell.font = HEADER_FONT
            cell.alignment = HEADER_ALIGNMENT


# --------------------------------------------------------------------------------------------
# Размеры: оценка переноса строк, ширина колонок, высота шапки и объединённых блоков
# --------------------------------------------------------------------------------------------


def _padding(filter_button: bool) -> float:
    return COLUMN_PADDING + (FILTER_BUTTON_WIDTH if filter_button else 0.0)


def _factor(bold: bool) -> float:
    return BOLD_WIDTH_FACTOR if bold else TEXT_WIDTH_FACTOR


def text_capacity(width: float, *, bold: bool = False, filter_button: bool = False) -> float:
    """Сколько символов текста помещается в строке ячейки колонки шириной width (в символах).
    bold — жирный шрифт, filter_button — в ячейке кнопка автофильтра."""
    return max(1.0, (width - _padding(filter_button)) / _factor(bold))


def header_capacity(width: float) -> float:
    """text_capacity для ячейки шапки отчёта: жирный шрифт и кнопка автофильтра."""
    return text_capacity(width, bold=True, filter_button=True)


def _paragraph_lines(paragraph: str, capacity: float) -> int:
    lines, used = 1, 0.0
    for word in paragraph.split():
        size = float(len(word))
        if used and used + 1 + size <= capacity:
            used += 1 + size
            continue
        if used:  # слово не влезло в остаток строки — начинается новая
            lines += 1
        while size > capacity:  # слово длиннее строки — приложение режет его по символам
            lines += 1
            size -= capacity
        used = size
    return lines


def wrap_lines(text: str, capacity: float) -> int:
    """Число строк, в которые перенесётся text при вместимости строки capacity символов: жадно по
    словам, явные переводы строки сохраняются. Всегда не меньше 1."""
    return sum(_paragraph_lines(paragraph, capacity) for paragraph in str(text).split("\n"))


def _column_width(ws, column: int) -> float:
    dimension = ws.column_dimensions.get(get_column_letter(column))
    return dimension.width if dimension is not None and dimension.width else DEFAULT_COLUMN_WIDTH


def _text_lines(ws, row: int, column: int, *, header: bool = False) -> int:
    """Сколько строк занимает значение ячейки при текущей ширине её колонки (0 — ячейка пуста)."""
    value = ws.cell(row=row, column=column).value
    if value in (None, ""):
        return 0
    width = _column_width(ws, column)
    return wrap_lines(str(value), header_capacity(width) if header else text_capacity(width))


def _data_width(ws, column: int, header_rows: int) -> int:
    """Ширина колонки по данным: самая длинная строка значения плюс поля, в пределах
    [MIN_COLUMN_WIDTH, MAX_COLUMN_WIDTH]. Заголовок здесь не учитывается."""
    longest = 0
    for (value,) in ws.iter_rows(min_row=header_rows + 1, min_col=column, max_col=column, values_only=True):
        if value not in (None, ""):
            longest = max(longest, max(len(line) for line in str(value).split("\n")))
    return min(max(longest + 2, MIN_COLUMN_WIDTH), MAX_COLUMN_WIDTH)


def header_width(text: str, start: int, *, filter_button: bool = True) -> int:
    """Наименьшая ширина колонки не меньше start, при которой жирный заголовок text виден целиком:
    самое длинное слово не рвётся посередине, а число строк переноса не больше MAX_HEADER_LINES
    (если колонка для этого не упирается в MAX_COLUMN_WIDTH — тогда шапка просто выше).
    filter_button — в ячейке шапки есть кнопка автофильтра (регламентированный отчёт; в шаблонах
    конструктора её нет)."""
    longest_word = max((len(word) for word in str(text).split()), default=0)
    word_width = math.ceil(round(longest_word * _factor(True) + _padding(filter_button), 6))
    width = min(max(start, word_width), MAX_COLUMN_WIDTH)
    while width < MAX_COLUMN_WIDTH and wrap_lines(text, text_capacity(width, bold=True, filter_button=filter_button)) > MAX_HEADER_LINES:
        width += 1
    return width


def fit_column_widths(ws, header_rows: int = 1) -> None:
    """Ширина каждой колонки: по данным, но не уже, чем нужно заголовку (см. _header_width)."""
    for column in range(1, ws.max_column + 1):
        width = _data_width(ws, column, header_rows)
        for row in range(1, header_rows + 1):
            title = ws.cell(row=row, column=column).value
            if title not in (None, ""):
                width = max(width, header_width(str(title), width))
        ws.column_dimensions[get_column_letter(column)].width = width


def fit_header_height(ws, header_rows: int = 1) -> None:
    """Высота каждой строки шапки — по самому длинному заголовку в ней при текущей ширине колонок
    (после fit_column_widths): заголовки не обрезаются."""
    for row in range(1, header_rows + 1):
        lines = max([1] + [_text_lines(ws, row, column, header=True) for column in range(1, ws.max_column + 1)])
        ws.row_dimensions[row].height = min(lines * LINE_HEIGHT_PT, MAX_ROW_HEIGHT_PT)


def fit_sheet_size(ws, header_rows: int = 1) -> None:
    """Ширина колонок и высота шапки. Вызывается, когда лист уже заполнен данными."""
    fit_column_widths(ws, header_rows)
    fit_header_height(ws, header_rows)


def _row_lines(ws, row: int, skip_columns: tuple, max_col: int) -> int:
    """Строк, нужных самой высокой ячейке строки (кроме колонок skip_columns), не меньше 1.

    max_col — число колонок листа, вычисленное вызывающим один раз: `ws.max_column` обходит все ячейки листа."""
    return max([1] + [_text_lines(ws, row, column) for column in range(1, max_col + 1) if column not in skip_columns])


def fit_merged_block_heights(ws, spans: Iterable[RowSpan], columns: Iterable[int]) -> None:
    """Растягивает строки блока, если значение объединённой ячейки не помещается в блок.

    Приложение подбирает высоту строки по её собственным ячейкам, объединённые в подборе не
    участвуют: блок из двух однострочных строк высотой 30 пт обрезал бы объединённый текст в три
    строки. Недостающие строки поровну добавляются к строкам блока; у блоков, где места хватает,
    высоты остаются автоматическими."""
    columns = tuple(columns)
    max_col = ws.max_column  # один раз: свойство обходит все ячейки листа, а группы строк исчисляются сотнями
    for first, last in spans:
        rows = list(range(first, last + 1))
        if len(rows) < 2 or not columns:
            continue
        own = [_row_lines(ws, row, columns, max_col) for row in rows]
        extra = max(_text_lines(ws, first, column) for column in columns) - sum(own)
        if extra <= 0:
            continue
        share, rest = divmod(extra, len(rows))
        for index, (row, lines) in enumerate(zip(rows, own)):
            ws.row_dimensions[row].height = min((lines + share + (index < rest)) * LINE_HEIGHT_PT, MAX_ROW_HEIGHT_PT)


def apply_sheet_layout(ws, *, spans: Optional[list[RowSpan]] = None, merge_columns: Iterable[int] = (), header_rows: int = 1) -> None:
    """Полное оформление листа отчёта: объединение, рамки, закрепление шапки.

    spans — группы строк, относящиеся к одной записи реестра. None — каждая строка данных сама
    запись (листы ИС, устройств, ВМ); пустой список — на листе нет данных, оформляется только
    шапка. merge_columns — колонки (с 1), чьи ячейки объединяются внутри групп из нескольких
    строк. Ширина колонок должна быть уже подобрана (fit_sheet_size): от неё зависит высота
    растянутых объединённых блоков."""
    merge_columns = tuple(merge_columns)
    if spans is None:
        spans = single_row_spans(ws, header_rows)
    merge_vertical(ws, spans, merge_columns)
    fit_merged_block_heights(ws, spans, merge_columns)
    apply_borders(ws, spans, header_rows)
    freeze_header(ws, header_rows)
