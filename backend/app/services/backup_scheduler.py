"""Планировщик плановых копий SQLite-БД: фоновая задача приложения, запускаемая из lifespan (``main.py``).

Правило запуска: копия **при старте, если плановых копий нет или последняя старше интервала**, затем каждые
``INFRA_REGISTRY_BACKUP_INTERVAL_HOURS`` часов (по умолчанию 24; 0 — планировщика нет). Работа по таймеру «в 03:00» здесь не годится:
EXE на рабочем месте выключают на ночь, и ночная копия не была бы сделана никогда. Поэтому первое ожидание считается от возраста
последней копии, а не от момента запуска: приложение, которое перезапускают каждый час, не плодит копию на каждом запуске.

Сама копия — ``db_backup.backup_scheduled`` (блокирующая работа с диском, поэтому выполняется в ``asyncio.to_thread``, не задерживая
запросы). Сбой не останавливает планировщик: он пишется в журнал ошибкой, и повтор через час (или через интервал, если он короче) — иначе
сбой в начале суток оставил бы базу без копии до следующих. Задача отменяется при остановке приложения (``stop_backup_scheduler``); копия,
которую уже пишет рабочий поток, дописывается во временный файл и переименовывается целиком или не появляется вовсе.

Политика (интервал, число копий, каталог) — ``services/backup_settings.py``: окружение > «Настройки → Резервные копии» > умолчание;
читается в момент запуска, а не при импорте модуля (тесты подменяют снимок настроек). Администратор меняет её без перезапуска приложения:
``BackupScheduler.restart`` отменяет задачу и запускает новую с новой политикой; правило «копия при запуске, если пора» не даёт такой
перезапуск превратить в лишнюю копию. Для PostgreSQL планировщика нет: копию делает оператор средствами СУБД (README, «Периодические
резервные копии»).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .backup_settings import BackupPolicy, database_file, load_policy_or_environment
from .db_backup import ScheduledBackupError, auto_backup_time, backup_scheduled, latest_auto_backup
from .timeutil import utcnow_naive

logger = logging.getLogger(__name__)

RETRY_AFTER_FAILURE_SECONDS = 3600.0
TASK_NAME = "scheduled-db-backups"


@dataclass(frozen=True)
class BackupAttempt:
    """Итог очередной попытки планировщика (для формы настроек): когда, удалась ли, какая копия создана."""

    at: datetime  # naive UTC
    error: str | None = None  # None — попытка прошла без ошибки
    created: str | None = None  # имя новой копии; None при отсутствии ошибки — копия не понадобилась (база не менялась с прошлой)

    @property
    def ok(self) -> bool:
        return self.error is None


def seconds_until_due(db_path: Path, backup_dir: Path, interval_seconds: float, now: float | None = None) -> float:
    """Через сколько секунд нужна плановая копия: 0 — плановых копий нет или последняя старше интервала."""
    latest = latest_auto_backup(db_path, backup_dir)
    if latest is None:
        return 0.0
    return max(0.0, auto_backup_time(latest) + interval_seconds - (time.time() if now is None else now))


async def run_scheduled_backups(
    db_path: Path, backup_dir: Path, interval_hours: float, keep: int, on_attempt: Callable[[BackupAttempt], None] | None = None
) -> None:
    """Бесконечный цикл плановых копий (см. описание модуля); завершается только отменой задачи. `on_attempt` получает итог каждой
    попытки."""
    interval = interval_hours * 3600
    delay = await asyncio.to_thread(seconds_until_due, db_path, backup_dir, interval)

    def report(attempt: BackupAttempt) -> None:
        if on_attempt is not None:
            on_attempt(attempt)

    while True:
        await asyncio.sleep(delay)
        try:
            created = await asyncio.to_thread(backup_scheduled, db_path, backup_dir, keep)
        except ScheduledBackupError as exc:
            logger.error("Плановая копия базы не создана: %s", exc)
            report(BackupAttempt(utcnow_naive(), error=str(exc)))
            delay = min(interval, RETRY_AFTER_FAILURE_SECONDS)
            continue
        except Exception as exc:  # noqa: BLE001 — непредвиденный сбой не должен молча убить планировщик; он записан с трассировкой
            logger.exception("Плановая копия базы: непредвиденная ошибка")
            report(BackupAttempt(utcnow_naive(), error=f"непредвиденная ошибка: {exc}"))
            delay = min(interval, RETRY_AFTER_FAILURE_SECONDS)
            continue
        if created is not None:
            logger.info("Создана плановая копия базы: %s", created)
        report(BackupAttempt(utcnow_naive(), created=created.name if created is not None else None))
        delay = interval


def start_backup_scheduler(
    policy: BackupPolicy | None = None, on_attempt: Callable[[BackupAttempt], None] | None = None
) -> asyncio.Task | None:
    """Запускает планировщик по политике (по умолчанию — действующей, `load_policy_or_environment`); None — запускать нечего (интервал 0
    или база не файловая SQLite).

    Вызывается из работающего цикла событий: lifespan и `BackupScheduler`."""
    policy = policy or load_policy_or_environment()
    if policy.interval_hours <= 0:
        logger.info("Плановые копии базы выключены (интервал 0).")
        return None
    db_path = database_file()
    if db_path is None:
        logger.debug("Плановые копии средствами приложения — только для файловой SQLite; PostgreSQL копирует оператор.")
        return None
    logger.info("Плановые копии базы: каждые %g ч, хранить %d, каталог %s", policy.interval_hours, policy.keep, policy.directory)
    return asyncio.create_task(
        run_scheduled_backups(db_path, policy.directory, policy.interval_hours, policy.keep, on_attempt), name=TASK_NAME
    )


async def stop_backup_scheduler(task: asyncio.Task | None) -> None:
    """Отменяет задачу планировщика и дожидается её завершения (None — задачи не было)."""
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


class BackupScheduler:
    """Задача планировщика, её перезапуск по новой политике и итог последней попытки. Один экземпляр на приложение
    (`app.state.backup_scheduler`, создаётся в lifespan внутри цикла событий).

    Запуск, перезапуск и остановка выполняются под одной блокировкой: два одновременных сохранения настроек не оставят две задачи,
    а остановка приложения не разминётся с перезапуском."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self.last_attempt: BackupAttempt | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def _record(self, attempt: BackupAttempt) -> None:
        self.last_attempt = attempt

    async def start(self, policy: BackupPolicy | None = None) -> None:
        async with self._lock:
            self._task = start_backup_scheduler(policy, self._record)

    async def restart(self, policy: BackupPolicy) -> None:
        """Применяет новую политику без перезапуска приложения: прежняя задача отменяется, новая стартует по `policy`."""
        async with self._lock:
            await stop_backup_scheduler(self._task)
            self._task = start_backup_scheduler(policy, self._record)

    async def stop(self) -> None:
        async with self._lock:
            await stop_backup_scheduler(self._task)
            self._task = None
