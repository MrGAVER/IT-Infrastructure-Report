"""Экспорт журнала аудита в Excel.

Отдельный модуль, а не часть reporting.py: это принципиально другая структура данных (плоский
хронологический лог действий с фильтрами по дате/разделу), не многолистовая инвентаризация ИС.
Переиспользует list_resource() (те же фильтры/сортировка, что и в UI раздела «Аудит») и
setup_sheet/finalize_sheet из reporting.py, чтобы оформление листа не разъезжалось с остальными
отчётами приложения.
"""
from __future__ import annotations
from pathlib import Path
from uuid import uuid4
from openpyxl import Workbook
from sqlalchemy.orm import Session
from ..registry import DISPLAY_NAMES
from .computed import local_timestamp_suffix
from .crud import list_resource
from .excel_safety import excel_safe_row

ACTION_LABELS = {"CREATE": "Создание", "UPDATE": "Изменение", "DELETE": "Удаление", "SYNC": "Синхронизация", "LOGIN": "Вход", "LOGIN_FAILED": "Неудачный вход", "LOGOUT": "Выход"}
AUDIT_HEADERS = ["Дата и время", "Пользователь", "IP-адрес", "Раздел", "Идентификатор записи", "Действие", "Подробности"]

# Журнал аудита экспортируется целиком в пределах разумного потолка (а не постранично, как в UI):
# цель экспорта — офлайн-архив для комплаенса, а не то же ограниченное представление, что на экране.
EXPORT_ROW_LIMIT = 100_000


def build_audit_log_report(session: Session, report_dir: Path, date_from: str | None = None, date_to: str | None = None, entity_type: str | None = None) -> Path:
    from ..reporting import setup_sheet, finalize_sheet  # локальный импорт: reporting.py не должен знать об audit_export.py

    filters = {"entity_type": entity_type} if entity_type else None
    result = list_resource("audit-log", session, offset=0, limit=EXPORT_ROW_LIMIT, filters=filters, date_from=date_from, date_to=date_to)

    wb = Workbook()
    ws = wb.active
    ws.title = "Журнал аудита"
    setup_sheet(ws, AUDIT_HEADERS)
    for row in result["items"]:
        # excel_safe_row: details и имя пользователя — текст, который вводил человек; начинающийся с «=»
        # он стал бы формулой в Excel получателя (см. services/excel_safety.py).
        ws.append(excel_safe_row([
            row["created_at"],
            row.get("actor_username") or "",
            row.get("actor_ip") or "",
            DISPLAY_NAMES.get(row["entity_type"], row["entity_type"]),
            row["entity_id"],
            ACTION_LABELS.get(row["action"], row["action"]),
            row["details"] or "",
        ]))
    finalize_sheet(ws)

    report_dir.mkdir(parents=True, exist_ok=True)
    # uuid-суффикс: метка времени с точностью до секунды совпала бы у двух одновременных выгрузок, и
    # один пользователь перезаписал бы файл другого.
    path = report_dir / f"Журнал_аудита_{local_timestamp_suffix()}_{uuid4().hex[:8]}.xlsx"
    wb.save(path)
    return path
