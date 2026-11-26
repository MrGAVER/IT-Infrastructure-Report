"""Настройки плановых копий SQLite: GET/PUT /api/v1/backup/settings (раздел «Настройки → Резервные копии»).

Только администратору (если аутентификация включена): в ответе — путь к каталогу копий и текст ошибок копирования с путями. Роль проверяет
зависимость роутера целиком, поэтому новый маршрут здесь не может остаться без проверки. Меняются интервал и число копий; каталог задаёт
оператор окружением и только показывается (services/backup_settings.py). Сохранённая политика применяется сразу: планировщик отменяется
и запускается заново, перезапуск приложения не нужен.
"""

from __future__ import annotations

from anyio import from_thread
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..constants import (
    BACKUP_DEFAULT_INTERVAL_HOURS,
    BACKUP_DEFAULT_KEEP,
    BACKUP_MAX_INTERVAL_HOURS,
    BACKUP_MAX_KEEP,
    BACKUP_MIN_INTERVAL_HOURS,
)
from ..db import get_db
from ..schemas import BackupAttemptOut, BackupLatestOut, BackupSettingsOut, BackupSettingsUpdate
from ..services.auth import require_admin_for_backup_settings
from ..services.backup_scheduler import BackupScheduler
from ..services.backup_settings import (
    UNSUPPORTED_REASON,
    BackupPolicy,
    SettingPinnedByEnvironment,
    database_file,
    latest_backup,
    load_policy,
    update_policy,
)
from ..services.timeutil import iso_utc

router = APIRouter(prefix="/api/v1/backup", tags=["Backup"], dependencies=[Depends(require_admin_for_backup_settings)])


def _scheduler(request: Request) -> BackupScheduler | None:
    """Планировщик приложения; None — lifespan не запускался (клиент без `with` в тестах): перезапускать нечего."""
    return getattr(request.app.state, "backup_scheduler", None)


def _settings_out(request: Request, policy: BackupPolicy) -> BackupSettingsOut:
    scheduler = _scheduler(request)
    supported = database_file() is not None
    latest = latest_backup(policy.directory)
    attempt = scheduler.last_attempt if scheduler is not None else None
    return BackupSettingsOut(
        supported=supported,
        unsupported_reason=None if supported else UNSUPPORTED_REASON,
        interval_hours=policy.interval_hours,
        interval_source=policy.interval_source,
        keep=policy.keep,
        keep_source=policy.keep_source,
        default_interval_hours=BACKUP_DEFAULT_INTERVAL_HOURS,
        default_keep=BACKUP_DEFAULT_KEEP,
        min_interval_hours=BACKUP_MIN_INTERVAL_HOURS,
        max_interval_hours=BACKUP_MAX_INTERVAL_HOURS,
        max_keep=BACKUP_MAX_KEEP,
        directory=str(policy.directory),
        directory_source=policy.directory_source,
        running=scheduler.running if scheduler is not None else False,
        latest=BackupLatestOut(name=latest.name, size_bytes=latest.size_bytes, created_at=iso_utc(latest.created_at)) if latest else None,
        last_attempt=(
            BackupAttemptOut(at=iso_utc(attempt.at), ok=attempt.ok, created=attempt.created, error=attempt.error) if attempt else None
        ),
    )


@router.get("/settings", response_model=BackupSettingsOut)
def read_backup_settings(request: Request, session: Session = Depends(get_db)) -> BackupSettingsOut:
    """Действующая политика плановых копий и откуда взято каждое значение, последняя копия (время, размер) и итог последней попытки."""
    return _settings_out(request, load_policy(session))


@router.put("/settings", response_model=BackupSettingsOut)
def update_backup_settings(payload: BackupSettingsUpdate, request: Request, session: Session = Depends(get_db)) -> BackupSettingsOut:
    """Меняет интервал (`interval_hours`: 0 — выключить) и/или число хранимых копий (`keep`); null — сбросить к умолчанию, поле
    не передано — не менять. Параметр, заданный окружением, не меняется (409). Изменение пишется в журнал аудита и сразу
    применяется к планировщику. Для PostgreSQL и базы не в файле — 409: копии там делает оператор СУБД."""
    if database_file() is None:
        raise HTTPException(409, UNSUPPORTED_REASON)
    try:
        update = update_policy(session, payload.model_dump(exclude_unset=True))
    except SettingPinnedByEnvironment as exc:
        raise HTTPException(409, str(exc)) from exc
    except IntegrityError as exc:  # два администратора впервые сохранили один и тот же ключ одновременно
        session.rollback()
        raise HTTPException(409, "Настройки копий только что изменил другой пользователь: обновите страницу и повторите.") from exc
    scheduler = _scheduler(request)
    if update.changed and scheduler is not None:
        from_thread.run(scheduler.restart, update.policy)  # цикл событий сервера: эндпоинт синхронный и работает в потоке пула
    return _settings_out(request, update.policy)
