"""Экспорт журнала аудита в Excel.

Отдельный модуль, а не часть reporting.py: это принципиально другая структура данных (плоский
хронологический лог действий с фильтрами по дате/разделу), не многолистовая инвентаризация ИС.
Переиспользует list_resource() (те же фильтры/сортировка, что и в UI раздела «Аудит»); запись —
потоковая (write_only), поэтому setup_sheet/finalize_sheet из reporting.py здесь не применяются:
finalize_sheet обходит все ячейки готового листа, а при потоковой записи он недоступен.
"""

from __future__ import annotations
import unicodedata
from pathlib import Path
from typing import Iterator
from openpyxl import Workbook
from openpyxl.cell import WriteOnlyCell
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session
from ..config import AUDIT_REPORT_SUBDIR
from ..registry import DISPLAY_NAMES
from .computed import local_timestamp_suffix
from .crud import list_resource
from .excel_safety import guard_text_cell

ACTION_LABELS = {"CREATE": "Создание", "UPDATE": "Изменение", "DELETE": "Удаление", "SYNC": "Синхронизация", "LOGIN": "Вход", "LOGIN_FAILED": "Неудачный вход", "LOGOUT": "Выход"}
AUDIT_HEADERS = ["Дата и время", "Пользователь", "IP-адрес", "Раздел", "Идентификатор записи", "Действие", "Подробности"]

# Журнал аудита экспортируется целиком в пределах разумного потолка (а не постранично, как в UI):
# цель экспорта — офлайн-архив для комплаенса, а не то же ограниченное представление, что на экране.
EXPORT_ROW_LIMIT = 100_000
# Строки читаются из БД и пишутся в файл порциями: раньше все до 100 000 записей сначала целиком
# загружались в память списком словарей, а затем ещё раз — в обычную (не потоковую) книгу openpyxl.
EXPORT_PAGE_SIZE = 5_000

# Ширина колонок задаётся заранее (при потоковой записи содержимое листа уже недоступно для подбора по
# самой длинной ячейке, как это делает finalize_sheet у остальных отчётов).
_COLUMN_WIDTHS = [20, 20, 16, 28, 38, 18, 60]


def _audit_rows(session: Session, filters: dict | None, date_from: str | None, date_to: str | None) -> Iterator[dict]:
    """Записи журнала в порядке list_resource (новые первыми) порциями по EXPORT_PAGE_SIZE, не больше EXPORT_ROW_LIMIT."""
    offset = 0
    while offset < EXPORT_ROW_LIMIT:
        limit = min(EXPORT_PAGE_SIZE, EXPORT_ROW_LIMIT - offset)
        items = list_resource("audit-log", session, offset=offset, limit=limit, filters=filters, date_from=date_from, date_to=date_to)["items"]
        yield from items
        if len(items) < limit:
            return
        offset += limit


# Имя файла отчёта журнала аудита начинается с этого префикса. Его читает и скачивание (api/reports.py: файл только для администратора), поэтому
# генератор имени и проверка обязаны брать одну константу — иначе переименование префикса молча сняло бы защиту (R1-05 код-ревью).
# Проверка по имени — второй слой: основной — подкаталог (audit_report_dir), до которого общий эндпоинт скачивания не дотягивается (A-05).
AUDIT_REPORT_PREFIX = "Журнал_аудита_"


def audit_report_dir(report_dir: Path) -> Path:
    """Каталог отчётов журнала аудита внутри каталога отчётов. Единственное место, где он вычисляется: туда пишет генератор, оттуда
    отдаёт отдельный эндпоинт скачивания (только администратору), его же учитывает очистка (services/report_cleanup.py)."""
    return report_dir / AUDIT_REPORT_SUBDIR


def _comparable(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def is_audit_report_name(name: str) -> bool:
    """Это имя файла отчёта журнала аудита? Регистр и форма Unicode не важны: файловые системы Windows и macOS находят файл по имени без
    учёта регистра, и проверка по точному префиксу обходилась бы именем `журнал_аудита_…`."""
    return _comparable(name).startswith(_comparable(AUDIT_REPORT_PREFIX))


def build_audit_log_report(session: Session, report_dir: Path, date_from: str | None = None, date_to: str | None = None, entity_type: str | None = None) -> Path:
    """Формирует .xlsx журнала аудита потоковой записью (Workbook(write_only=True)): память не растёт с числом
    записей. Оформление то же, что у остальных отчётов (жирная центрированная шапка, закреплённая первая
    строка, автофильтр), кроме подбора ширины по содержимому — она фиксирована (_COLUMN_WIDTHS).

    Файл создаётся в подкаталоге audit_report_dir(report_dir), а не в самом report_dir (A-05).

    Пример вызова:
        path = build_audit_log_report(session, REPORT_DIR, date_from="2026-10-01", entity_type="devices")  # REPORT_DIR/audit/Журнал_аудита_….xlsx
    """
    filters = {"entity_type": entity_type} if entity_type else None

    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Журнал аудита")
    for index, width in enumerate(_COLUMN_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
    ws.freeze_panes = "A2"

    header_cells = []
    for title in AUDIT_HEADERS:
        cell = WriteOnlyCell(ws, value=title)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        header_cells.append(cell)
    ws.append(header_cells)

    top_wrapped = Alignment(vertical="top", wrap_text=True)
    count = 0
    for row in _audit_rows(session, filters, date_from, date_to):
        values = [
            row["created_at"],
            row.get("actor_username") or "",
            row.get("actor_ip") or "",
            DISPLAY_NAMES.get(row["entity_type"], row["entity_type"]),
            row["entity_id"],
            ACTION_LABELS.get(row["action"], row["action"]),
            row["details"] or "",
        ]
        cells = []
        for value in values:
            cell = WriteOnlyCell(ws, value=value)
            cell.alignment = top_wrapped
            # details и имя пользователя — текст, который вводил человек; начинающийся с «=» он стал бы формулой в
            # Excel получателя (см. services/excel_safety.py).
            guard_text_cell(cell)
            cells.append(cell)
        ws.append(cells)
        count += 1
    if count:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(AUDIT_HEADERS))}{count + 1}"

    audit_dir = audit_report_dir(report_dir)
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{AUDIT_REPORT_PREFIX}{local_timestamp_suffix()}.xlsx"
    wb.save(path)
    return path
