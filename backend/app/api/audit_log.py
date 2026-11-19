from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from ..constants import MAX_PAGE_OFFSET, MAX_SEARCH_LENGTH
from ..db import get_db
from ..models import AuditSettings
from ..schemas import AuditSettingsOut, AuditSettingsSaveOut, AuditSettingsUpdate
from ..services.auth import require_admin_if_auth_enabled
from ..services.audit_query import AuditQuery, list_audit_log
from ..services.audit_retention import get_audit_settings, retention_state, run_scheduled_cleanup_in_own_session, update_retention
from ..services.timeutil import iso_utc

# Записи журнала приложение пишет само (crud.audit()), через API их не изменить. Доступ — только администратору (при включённой
# аутентификации) и ко всему роутеру сразу, включая настройки аудита: новый маршрут здесь не может остаться без проверки роли.
router = APIRouter(prefix='/api/v1', tags=['Audit'], dependencies=[Depends(require_admin_if_auth_enabled)])


@router.get('/audit-log')
def audit_log_page(
    background: BackgroundTasks,
    q: str | None = Query(None, max_length=MAX_SEARCH_LENGTH),
    action: str | None = Query(None, max_length=50),
    entity_type: str | None = Query(None, max_length=100),
    offset: int = Query(0, ge=0, le=MAX_PAGE_OFFSET),
    limit: int = Query(24, ge=1, le=200),
    session: Session = Depends(get_db),
):
    """Страница журнала аудита (новые сверху): поиск по деталям и id записи, фильтры по действию и
    разделу считаются на сервере. `total` — под теми же условиями; `summary` (всего и по действиям)
    и `entity_types` (разделы, встречающиеся в журнале) — по всему журналу.

    Заодно — ленивый запуск очистки по сроку хранения (services/audit_retention.py): срок задан и прошли сутки с прошлой очистки. GET
    данные не удаляет: очистка ставится задачей после ответа и идёт в своей сессии, читателя журнала не задерживает и его страницу не
    ломает. Поэтому первая страница после смены срока ещё показывает не очищенные записи — очистка видна со следующего открытия."""
    page = list_audit_log(session, AuditQuery(q=q, action=action, entity_type=entity_type), offset=offset, limit=limit)
    background.add_task(run_scheduled_cleanup_in_own_session)
    return page


def _settings_fields(row: AuditSettings | None) -> dict[str, object]:
    """Поля ответа настроек (имена и ISO-строки — забота транспорта, поэтому здесь, а не в сервисе)."""
    state = retention_state(row)
    return {
        'retention_days': state.retention_days,
        'is_default': state.is_default,
        'default_retention_days': state.default_retention_days,
        'max_retention_days': state.max_retention_days,
        'last_cleanup_at': iso_utc(state.last_cleanup_at),
    }


@router.get('/audit-log/settings', response_model=AuditSettingsOut)
def read_audit_settings(session: Session = Depends(get_db)) -> AuditSettingsOut:
    """Настройки аудита: действующий срок хранения (0 — не удалять), задан ли он в форме или действует умолчание, когда была очистка."""
    return AuditSettingsOut(**_settings_fields(get_audit_settings(session)))


@router.put('/audit-log/settings', response_model=AuditSettingsSaveOut, response_model_exclude_unset=True)
def update_audit_settings(payload: AuditSettingsUpdate, session: Session = Depends(get_db)) -> AuditSettingsSaveOut:
    """Меняет срок хранения журнала (`retention_days`: 0 — не удалять, null — сбросить к умолчанию, поле не передано — не менять).
    Новый срок сразу применяется: записи старше удаляются; `removed_now` — сколько удалено. Изменение пишется в журнал аудита."""
    patch = payload.model_dump(exclude_unset=True)
    if 'retention_days' not in patch:
        return AuditSettingsSaveOut(**_settings_fields(get_audit_settings(session)))  # removed_now не задан → в ответ не попадает
    update = update_retention(session, patch['retention_days'])
    return AuditSettingsSaveOut(**_settings_fields(update.row), removed_now=update.removed, cleanup_failed=update.cleanup_failed)
