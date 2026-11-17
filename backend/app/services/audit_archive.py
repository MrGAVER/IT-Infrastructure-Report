"""Архив записей журнала аудита, которые удаляет очистка по сроку хранения.

Срок хранения может сменить любой клиент, прошедший сетевые проверки: при выключенной аутентификации (значение по умолчанию) роль не
проверяется. Короткий срок одним запросом стёр бы журнал, а запись о смене срока и записи об очистке сами оказались бы старше границы.
Поэтому удаление и выгрузка неразделимы: пакет записей удаляется из БД только после того, как его копия записана в файл и сброшена на
диск (flush + fsync). Не удалось сохранить архив (диск полон, нет прав) — `AuditArchiveError`, записи остаются в журнале.

Файл и формат.
  * Каталог — `audit/` внутри каталога отчётов (services/audit_export.audit_report_dir), рядом с отчётами журнала аудита; их скачивает
    только администратор (api/reports.py), а общий адрес скачивания этот каталог не читает.
  * Имя — `Архив_журнала_аудита_<UTC: ГГГГ-ММ-ДД_ЧЧ-ММ-СС>Z.csv`, один файл на один проход очистки; создаётся при первой записи,
    поэтому проход, которому нечего удалять, ничего не оставляет. Расширение не `.xlsx`/`.docx`: уборка отчётов
    (services/report_cleanup.py) такие файлы не считает и не удаляет — иначе архив пропал бы по сроку или квоте отчётов.
  * CSV в UTF-8 с BOM, разделитель «;» (так открывает Excel с русскими региональными настройками). Колонки — все колонки таблицы
    `audit_log` (в том числе `id`), время — ISO 8601 с «+00:00». Пустое значение (NULL) записывается пустой ячейкой.
  * Значение, которое Excel принял бы за формулу (начинается с «=», «+», «-», «@»), дополняется ведущим апострофом — правило
    services/excel_safety.py одно на проект. Остальные значения записываются как есть.
  * Файл создаётся с правами 0600: в журнале логины и IP-адреса.
  * Если проход прервался между записью архива и удалением (сбой, остановка процесса), записи остаются в БД и при следующем проходе
    попадут в новый файл: дубли между файлами возможны, их различает `id`.

Пример:
    with AuditArchive(audit_archive_dir(), now=utcnow_naive()) as archive:
        archive.write_batch(rows)    # вернулись — строки уже на диске; только теперь их можно удалять из БД
    archive.path                     # None, если ни одной записи не было
"""

from __future__ import annotations

import csv
import errno
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from .. import config
from ..models import AuditLog
from .audit_export import audit_report_dir
from .excel_safety import needs_text_guard
from .timeutil import iso_utc

logger = logging.getLogger(__name__)

ARCHIVE_PREFIX = "Архив_журнала_аудита_"
ARCHIVE_SUFFIX = ".csv"
ARCHIVE_COLUMNS = tuple(AuditLog.__table__.c)  # порядок колонок в файле; новая колонка модели попадает в архив сама
CSV_DELIMITER = ";"
_MAX_NAME_ATTEMPTS = 100


class AuditArchiveError(RuntimeError):
    """Архив удаляемых записей не сохранён. Очистка в этом случае ничего не удаляет."""


def audit_archive_dir() -> Path:
    """Каталог архивов. Каталог отчётов читается при вызове, а не при импорте: тесты подменяют `config.REPORT_DIR`."""
    return audit_report_dir(config.REPORT_DIR)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = iso_utc(value) if isinstance(value, datetime) else str(value)
    return "'" + text if needs_text_guard(text) else text


def _sync_directory(directory: Path) -> None:
    """Сбрасывает на диск запись о новом файле в каталоге (POSIX). Не везде поддерживается, поэтому сбой не фатален: данные файла уже
    сброшены его собственным fsync, а на Windows каталог сбросить нельзя."""
    if os.name != "posix":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        logger.debug("Не удалось сбросить на диск каталог архива %s", directory, exc_info=True)


class AuditArchive:
    """Файл архива одного прохода очистки. Не потокобезопасен: проход очистки выполняется одним потоком."""

    def __init__(self, directory: Path, *, now: datetime) -> None:
        self._directory = directory
        self._stamp = now
        self._file: Any = None
        self._writer: Any = None
        self.path: Optional[Path] = None
        self.rows = 0

    def __enter__(self) -> "AuditArchive":
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    def write_batch(self, rows: Sequence[Sequence[Any]]) -> None:
        """Дописывает строки (значения в порядке ARCHIVE_COLUMNS) и сбрасывает их на диск. Вернулась без ошибки — строки сохранены."""
        if not rows:
            return
        try:
            if self._file is None:
                self._open()
            self._writer.writerows([_cell(value) for value in row] for row in rows)
            self._file.flush()
            os.fsync(self._file.fileno())
        except (OSError, csv.Error) as exc:
            message = f"Не удалось сохранить архив удаляемых записей журнала аудита в {self._directory}: {exc}. Записи не удалены."
            raise AuditArchiveError(message) from exc
        self.rows += len(rows)

    def close(self) -> None:
        file, self._file = self._file, None
        if file is None:
            return
        try:
            file.close()
        except OSError:  # данные уже сброшены fsync; ошибка закрытия не должна подменять исходное исключение прохода
            logger.warning("Не удалось закрыть файл архива журнала аудита %s", self.path, exc_info=True)

    def _open(self) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        descriptor, path = self._create_exclusive()
        try:
            self._file = os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="")
        except BaseException:
            os.close(descriptor)
            raise
        self.path = path
        self._writer = csv.writer(self._file, delimiter=CSV_DELIMITER)
        self._writer.writerow([column.name for column in ARCHIVE_COLUMNS])
        _sync_directory(self._directory)

    def _create_exclusive(self) -> tuple[int, Path]:
        """Создаёт файл, не затирая существующий (два прохода в одну секунду): занятое имя получает суффикс `_2`, `_3`…"""
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        base = f"{ARCHIVE_PREFIX}{self._stamp:%Y-%m-%d_%H-%M-%S}Z"
        for attempt in range(1, _MAX_NAME_ATTEMPTS + 1):
            path = self._directory / (f"{base}{ARCHIVE_SUFFIX}" if attempt == 1 else f"{base}_{attempt}{ARCHIVE_SUFFIX}")
            try:
                return os.open(path, flags, 0o600), path
            except FileExistsError:
                continue
        raise FileExistsError(errno.EEXIST, f"не подобрано свободное имя файла архива вида {base}*{ARCHIVE_SUFFIX}")
