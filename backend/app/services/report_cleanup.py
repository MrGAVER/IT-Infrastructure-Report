"""Очистка каталога сгенерированных отчётов от старых файлов.

Отчёт создаётся по запросу пользователя и нужен, пока его скачивают; каталог REPORT_DIR раньше не
чистился никогда и рос бесконечно (код-ревью, п. 11). Очистка ленивая — вызывается при формировании
нового отчёта, без фонового планировщика (его в приложении нет, а для EXE-режима он был бы лишним).

Удаляются только файлы отчётов (.xlsx/.docx) старше срока; всё остальное в каталоге не трогается.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from ..config import REPORT_RETENTION_DAYS

logger = logging.getLogger(__name__)

REPORT_SUFFIXES = frozenset({".xlsx", ".docx"})


def cleanup_old_reports(report_dir: Path, max_age_days: int = REPORT_RETENTION_DAYS) -> int:
    """Удаляет файлы отчётов старше max_age_days дней и возвращает их число.

    max_age_days <= 0 отключает очистку. Отсутствующий каталог — не ошибка. Файл, который не удалось
    удалить (занят другим процессом, нет прав), пропускается с предупреждением в лог: очистка не
    должна ломать формирование отчёта.

    Пример вызова:
        cleanup_old_reports(REPORT_DIR)                  # срок из INFRA_REGISTRY_REPORT_RETENTION_DAYS
        cleanup_old_reports(REPORT_DIR, max_age_days=7)
    """
    if max_age_days <= 0 or not report_dir.is_dir():
        return 0
    threshold = time.time() - max_age_days * 86400
    removed = 0
    for path in report_dir.iterdir():
        if path.suffix.lower() not in REPORT_SUFFIXES or not path.is_file():
            continue
        try:
            if path.stat().st_mtime < threshold:
                path.unlink()
                removed += 1
        except OSError as exc:
            logger.warning("Не удалось удалить старый отчёт %s: %s", path.name, exc)
    return removed
