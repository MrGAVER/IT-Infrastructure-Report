"""Настройки аутентификации: переключатель «включена / выключена» и кэш этого флага для middleware.

Не путать с app.config: здесь только строка AuthSettings в БД и её чтение."""

from __future__ import annotations

import time
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ...constants import AuditAction, ErrorCode
from ...models import AuthSettings, User
from ..crud import audit
from .users import lock_active_admins


def get_or_create_auth_settings(session: Session) -> AuthSettings:
    row = session.get(AuthSettings, "singleton")
    if row is not None:
        return row
    row = AuthSettings(id="singleton", enabled=False)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        # Гонка на самом первом запросе к пустой БД: два конкурентных запроса не увидели строку
        # и оба попытались её создать — проигравший просто перечитывает то, что вставил первый.
        session.rollback()
        row = session.get(AuthSettings, "singleton")
    else:
        session.refresh(row)
    return row


# Кэш флага «аутентификация включена» для middleware. Раньше _authorize на КАЖДЫЙ запрос к /api/*
# читал настройки из БД — даже в режиме без аутентификации (по умолчанию), где больше ничего из БД не нужно. Здесь —
# (момент чтения, значение) с коротким TTL. Переключение через set_auth_enabled сбрасывает кэш сразу, поэтому в том же
# процессе оно действует немедленно.
_FLAG_TTL = 2.0
_flag_clock = time.monotonic  # подменяется в тестах
_flag_cache: Optional[tuple[float, bool]] = None
_flag_generation = 0  # растёт при каждом сбросе: читатель, застигнутый переключением посреди чтения, устаревшее значение не сохранит


def auth_enabled_cached(db_session: Session) -> bool:
    """Включена ли аутентификация — из кэша не старше _FLAG_TTL секунд, иначе из БД.

    Компромисс: при нескольких процессах backend за общей БД (серверный вариант) процесс, в котором переключатель не
    нажимали, увидит новое значение с задержкой до _FLAG_TTL — две секунды, после чего сам перечитает БД. Кэшируется только
    сам флаг: токен и пользователь по-прежнему проверяются по БД на каждый запрос, поэтому отзыв сессии (выход, смена
    пароля, деактивация) действует мгновенно."""
    global _flag_cache
    now = _flag_clock()
    cached = _flag_cache
    if cached is not None and now - cached[0] <= _FLAG_TTL:
        return cached[1]
    generation = _flag_generation
    enabled = get_or_create_auth_settings(db_session).enabled
    if generation == _flag_generation:  # за время чтения никто не переключал: значение можно запомнить
        _flag_cache = (now, enabled)
    return enabled


def reset_auth_enabled_cache() -> None:
    """Забывает кэш флага: следующий запрос прочитает его из БД. Вызывается после изменения AuthSettings.enabled."""
    global _flag_cache, _flag_generation
    _flag_generation += 1
    _flag_cache = None


def set_auth_enabled(session: Session, enabled: bool, *, actor: Optional[User] = None) -> AuthSettings:
    settings_row = get_or_create_auth_settings(session)
    if enabled and not settings_row.enabled and len(lock_active_admins(session)) == 0:
        raise HTTPException(
            400,
            {
                "message": "Нельзя включить аутентификацию: сначала создайте хотя бы одного активного пользователя с ролью «Администратор» (раздел «Пользователи» в настройках).",
                "code": ErrorCode.AUTH_REQUIRES_ADMIN,
            },
        )
    if settings_row.enabled != enabled:
        settings_row.enabled = enabled
        session.commit()
        session.refresh(settings_row)
        reset_auth_enabled_cache()  # сразу после commit: в этом процессе переключение действует со следующего же запроса
        who = f" ({actor.username})" if actor else ""
        audit(session, "auth", "singleton", AuditAction.UPDATE, f"Аутентификация {'включена' if enabled else 'выключена'}{who}")
        session.commit()
    return settings_row
