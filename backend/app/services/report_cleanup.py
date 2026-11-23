"""Очистка каталога сгенерированных отчётов: по возрасту и по количеству файлов.

Отчёт создаётся по запросу пользователя и нужен, пока его скачивают; каталог REPORT_DIR раньше не
чистился никогда и рос бесконечно. Очистка ленивая — вызывается при формировании
нового отчёта, без фонового планировщика (его в приложении нет, а для EXE-режима он был бы лишним).

Два правила, оба касаются только файлов отчётов (.xlsx/.docx) — в корне каталога и в подкаталоге audit/ с отчётами журнала аудита,
остальное не трогается:

* возраст — файлы старше `INFRA_REGISTRY_REPORT_RETENTION_DAYS` (по умолчанию 30 дней) удаляются;
* количество — остаются не более `INFRA_REGISTRY_REPORT_MAX_FILES` (по умолчанию 200) самых новых файлов, остальные
  удаляются независимо от возраста: отчёт может сформировать роль viewer (или любой клиент при выключенной
  аутентификации), и без квоты цикл запросов заполнил бы диск, а срок хранения этому не мешает.

Эндпоинты вызывают `cleanup_before_new_report`: квота проверяется при каждом запросе (достаточно перечислить имена файлов,
каталог ограничен квотой), а проход по возрасту, которому нужен `stat` каждого файла, — не чаще раза в минуту.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from ..config import AUDIT_REPORT_SUBDIR, REPORT_MAX_FILES, REPORT_RETENTION_DAYS

logger = logging.getLogger(__name__)

REPORT_SUFFIXES = frozenset({".xlsx", ".docx"})
AGE_SCAN_INTERVAL_SECONDS = 60

_clock = time.monotonic  # подменяется в тестах
_last_age_scan: dict[str, float] = {}
_scan_lock = threading.Lock()


def _report_files(report_dir: Path) -> list[Path]:
    """Файлы отчётов в корне каталога и в подкаталоге отчётов аудита: квота и возраст считаются по обоим вместе, иначе
    отчёты аудита копились бы мимо REPORT_MAX_FILES. Прочие подкаталоги и сам `audit/` не трогаются."""
    files = [path for path in report_dir.iterdir() if path.suffix.lower() in REPORT_SUFFIXES and path.is_file()]
    audit_dir = report_dir / AUDIT_REPORT_SUBDIR
    if audit_dir.is_dir():
        files.extend(path for path in audit_dir.iterdir() if path.suffix.lower() in REPORT_SUFFIXES and path.is_file())
    return files


def _remove(path: Path) -> bool:
    """Удаляет файл отчёта; True — удалён. Файл, который успел удалить параллельный запрос, — не ошибка; занятый другим
    процессом или без прав — предупреждение в журнал: очистка не должна ломать формирование отчёта."""
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("Не удалось удалить отчёт %s: %s", path.name, exc)
        return False


def _modified(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:  # файл исчез между перечислением и stat
        return None


def cleanup_old_reports(
    report_dir: Path,
    max_age_days: int = REPORT_RETENTION_DAYS,
    max_files: int = REPORT_MAX_FILES,
    *,
    keep_free: int = 0,
) -> int:
    """Удаляет файлы отчётов старше max_age_days дней, затем самые старые сверх max_files; возвращает число удалённых.

    max_age_days <= 0 отключает очистку по возрасту, max_files <= 0 — по количеству (независимо друг от друга). Отсутствующий
    каталог — не ошибка. keep_free оставляет место под новые файлы: при keep_free=1 в каталоге остаётся не более
    max_files - 1 файлов, и после создания одного отчёта квота соблюдена. Порядок «самые старые» — по времени изменения,
    при равенстве — по имени.

    Пример вызова:
        cleanup_old_reports(REPORT_DIR)                                # сроки из настроек
        cleanup_old_reports(REPORT_DIR, max_age_days=7, max_files=50)
        cleanup_old_reports(REPORT_DIR, keep_free=1)                   # перед созданием отчёта
    """
    if (max_age_days <= 0 and max_files <= 0) or not report_dir.is_dir():
        return 0
    removed = 0
    survivors: list[tuple[float, str, Path]] = []
    threshold = time.time() - max_age_days * 86400 if max_age_days > 0 else None
    files = _report_files(report_dir)
    # Время изменения нужно проходу по возрасту всегда, а квоте — только когда файлов больше предела.
    quota = max(max_files - keep_free, 0) if max_files > 0 else None
    need_times = threshold is not None or (quota is not None and len(files) > quota)
    for path in files:
        modified = _modified(path) if need_times else 0.0
        if modified is None:
            continue
        if threshold is not None and modified < threshold:
            removed += _remove(path)
        else:
            survivors.append((modified, path.name, path))
    if quota is not None and len(survivors) > quota:
        survivors.sort(key=lambda item: (item[0], item[1]))
        for _, _, path in survivors[: len(survivors) - quota]:
            removed += _remove(path)
    return removed


def cleanup_before_new_report(report_dir: Path) -> int:
    """Очистка перед созданием отчёта (вызывается эндпоинтами формирования): квота — всегда, возраст — не чаще раза в минуту
    на каталог. Освобождает место под один новый файл, так что после создания в каталоге не больше REPORT_MAX_FILES файлов.
    Лимиты читаются при вызове из настроек модуля (их подменяют тесты)."""
    key = str(report_dir)
    now = _clock()
    with _scan_lock:
        due = key not in _last_age_scan or now - _last_age_scan[key] >= AGE_SCAN_INTERVAL_SECONDS
        if due:
            _last_age_scan[key] = now
    return cleanup_old_reports(
        report_dir,
        max_age_days=REPORT_RETENTION_DAYS if due else 0,
        max_files=REPORT_MAX_FILES,
        keep_free=1,
    )
