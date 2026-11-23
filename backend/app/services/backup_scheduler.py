"""Планировщик плановых копий SQLite-БД: фоновая задача приложения, запускаемая из lifespan (``main.py``).

Правило запуска: копия **при старте, если плановых копий нет или последняя старше интервала**, затем каждые
``INFRA_REGISTRY_BACKUP_INTERVAL_HOURS`` часов (по умолчанию 24; 0 — планировщика нет). Работа по таймеру «в 03:00» здесь не годится:
EXE на рабочем месте выключают на ночь, и ночная копия не была бы сделана никогда. Поэтому первое ожидание считается от возраста
последней копии, а не от момента запуска: приложение, которое перезапускают каждый час, не плодит копию на каждом запуске.

Сама копия — ``db_backup.backup_scheduled`` (блокирующая работа с диском, поэтому выполняется в ``asyncio.to_thread``, не задерживая
запросы). Сбой не останавливает планировщик: он пишется в журнал ошибкой, и повтор через час (или через интервал, если он короче) — иначе
сбой в начале суток оставил бы базу без копии до следующих. Задача отменяется при остановке приложения (``stop_backup_scheduler``); копия,
которую уже пишет рабочий поток, дописывается во временный файл и переименовывается целиком или не появляется вовсе.

Настройки читаются из ``config.settings`` в момент запуска, а не при импорте модуля (тесты подменяют снимок настроек). Для PostgreSQL
планировщика нет: копию делает оператор средствами СУБД (README, «Периодические резервные копии»).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from .. import config
from .db_backup import ScheduledBackupError, auto_backup_time, backup_scheduled, latest_auto_backup, sqlite_database_path

logger = logging.getLogger(__name__)

RETRY_AFTER_FAILURE_SECONDS = 3600.0
TASK_NAME = "scheduled-db-backups"


def seconds_until_due(db_path: Path, backup_dir: Path, interval_seconds: float, now: float | None = None) -> float:
    """Через сколько секунд нужна плановая копия: 0 — плановых копий нет или последняя старше интервала."""
    latest = latest_auto_backup(db_path, backup_dir)
    if latest is None:
        return 0.0
    return max(0.0, auto_backup_time(latest) + interval_seconds - (time.time() if now is None else now))


async def run_scheduled_backups(db_path: Path, backup_dir: Path, interval_hours: float, keep: int) -> None:
    """Бесконечный цикл плановых копий (см. описание модуля); завершается только отменой задачи."""
    interval = interval_hours * 3600
    delay = await asyncio.to_thread(seconds_until_due, db_path, backup_dir, interval)
    while True:
        await asyncio.sleep(delay)
        try:
            created = await asyncio.to_thread(backup_scheduled, db_path, backup_dir, keep)
        except ScheduledBackupError as exc:
            logger.error("Плановая копия базы не создана: %s", exc)
            delay = min(interval, RETRY_AFTER_FAILURE_SECONDS)
            continue
        except Exception:  # noqa: BLE001 — непредвиденный сбой не должен молча убить планировщик; он записан с трассировкой
            logger.exception("Плановая копия базы: непредвиденная ошибка")
            delay = min(interval, RETRY_AFTER_FAILURE_SECONDS)
            continue
        if created is not None:
            logger.info("Создана плановая копия базы: %s", created)
        delay = interval


def start_backup_scheduler() -> asyncio.Task | None:
    """Запускает планировщик по текущим настройкам; None — запускать нечего (интервал 0 или база не файловая SQLite).

    Вызывается из lifespan, внутри работающего цикла событий."""
    settings = config.settings
    if settings.backup_interval_hours <= 0:
        logger.info("Плановые копии базы выключены (INFRA_REGISTRY_BACKUP_INTERVAL_HOURS=0).")
        return None
    db_path = sqlite_database_path(settings.database_url)
    if db_path is None:
        logger.debug("Плановые копии средствами приложения — только для файловой SQLite; PostgreSQL копирует оператор.")
        return None
    logger.info(
        "Плановые копии базы: каждые %g ч, хранить %d, каталог %s",
        settings.backup_interval_hours,
        settings.backup_keep,
        settings.backup_dir,
    )
    return asyncio.create_task(
        run_scheduled_backups(db_path, settings.backup_dir, settings.backup_interval_hours, settings.backup_keep), name=TASK_NAME
    )


async def stop_backup_scheduler(task: asyncio.Task | None) -> None:
    """Отменяет задачу планировщика и дожидается её завершения (None — задачи не было)."""
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
