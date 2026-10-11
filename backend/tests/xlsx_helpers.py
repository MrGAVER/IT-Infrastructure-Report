"""Общие хелперы для тестов Excel-отчётов."""
from __future__ import annotations


def expanded_rows(ws, min_row: int = 1) -> list[tuple]:
    """Значения ячеек листа построчно, где ячейки объединения повторяют значение его верхней
    левой ячейки — «логические» строки таблицы, какими их видит читатель отчёта.

    В регламентированном отчёте данные устройства на листе 'Организация подключений'
    объединены по строкам его портов (services/excel_layout.py); openpyxl при чтении хранит значение
    только в верхней ячейке объединения, у остальных строк блока там None. Объединение — чисто
    визуальное, данные строк не меняет, поэтому тесты содержимого отчёта читают лист через этот
    хелпер, а не через ws.iter_rows(values_only=True)."""
    merged: dict[tuple[int, int], object] = {}
    for rng in ws.merged_cells.ranges:
        value = ws.cell(row=rng.min_row, column=rng.min_col).value
        for row in range(rng.min_row, rng.max_row + 1):
            for column in range(rng.min_col, rng.max_col + 1):
                merged[(row, column)] = value
    return [
        tuple(merged[(c.row, c.column)] if (c.row, c.column) in merged else c.value for c in row)
        for row in ws.iter_rows(min_row=min_row)
    ]
