"""Серверные настройки интерфейса (models.AppPreference): личные у пользователя и общие для всех.

Раньше тема, название организации, размеры страниц и порог сворачивания блока «VLAN устройства» жили в
localStorage браузера — на другом компьютере и после очистки браузера всё возвращалось к умолчаниям. Здесь
они хранятся на сервере. Сервис ничего не знает про HTTP: владельца (owner) определяет роутер
(api/preferences.py), набор допустимых ключей и значений задают схемы (schemas.*PreferencesUpdate).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..constants import UserRole
from ..models import AppPreference, User
from ..schemas import PAGE_SIZES_MAX_LISTS

logger = logging.getLogger(__name__)

OWNER_GLOBAL = "global"

GLOBAL_KEYS = ("organization_name",)
USER_KEYS = ("color_scheme", "device_vlan_collapse_rows", "page_sizes")
# Ключи-словари сливаются с сохранённым значением (null у элемента убирает его), остальные — заменяются.
MERGED_MAP_KEYS = frozenset({"page_sizes"})


def user_owner(user: User) -> str:
    """Владелец личных настроек — пользователь. При выключенной аутентификации пользователя нет, и личные
    настройки на сервере не хранятся (они остаются в localStorage браузера)."""
    return user_owner_by_id(user.id)


def require_global_write(*, auth_enabled: bool, user: Optional[User]) -> None:
    """Общие настройки (название организации) меняет администратор. При выключенной аутентификации реестр
    открыт целиком и ролей нет — менять может любой, как и всё остальное; требовать здесь «доступ к первичной
    настройке» (localhost/токен установки) значило бы закрыть безобидное название организации для обычной
    удалённой работы без аутентификации."""
    if auth_enabled and (user is None or user.role != UserRole.ADMIN):
        raise HTTPException(403, "Общие настройки может менять только администратор.")


def _decode(row: AppPreference) -> Any:
    return json.loads(row.value)


def _read_owner(session: Session, owner: str, keys: tuple[str, ...]) -> dict[str, Any]:
    rows = session.scalars(select(AppPreference).where(AppPreference.owner == owner, AppPreference.key.in_(keys))).all()
    result: dict[str, Any] = {}
    for row in rows:
        try:
            result[row.key] = _decode(row)
        except ValueError:
            # Значение испорчено вручную в БД: это только настройка отображения, из-за неё не стоит ронять
            # весь запрос — ключ просто считается не заданным (клиент подставит значение по умолчанию).
            logger.warning("Настройка %s/%s не разобрана как JSON — пропущена", owner, row.key)
    return result


def read_preferences(session: Session, user: Optional[User]) -> dict[str, dict[str, Any]]:
    """{'global': {...}, 'user': {...}} — только заданные значения; умолчания подставляет клиент. Без
    пользователя (аутентификация выключена) личной части на сервере нет — она пустая."""
    return {
        "global": _read_owner(session, OWNER_GLOBAL, GLOBAL_KEYS),
        "user": _read_owner(session, user_owner(user), USER_KEYS) if user is not None else {},
    }


def update_preferences(session: Session, owner: str, patch: dict[str, Any]) -> None:
    """Применяет частичное изменение (ключи, которых нет в patch, не трогаются). None сбрасывает настройку
    к умолчанию — запись удаляется. Ключи-словари (MERGED_MAP_KEYS) сливаются с сохранённым значением.
    Коммитит сам: вызывается ровно из эндпоинтов настроек."""
    existing = {
        row.key: row
        for row in session.scalars(select(AppPreference).where(AppPreference.owner == owner, AppPreference.key.in_(list(patch)))).all()
    }
    for key, value in patch.items():
        row = existing.get(key)
        if key in MERGED_MAP_KEYS and value is not None:
            value = _merge_map(row, value, key)
        if value is None or value == {}:
            if row is not None:
                session.delete(row)
            continue
        encoded = json.dumps(value, ensure_ascii=False)
        if row is None:
            session.add(AppPreference(owner=owner, key=key, value=encoded))
        else:
            row.value = encoded
    session.commit()


def _merge_map(row: Optional[AppPreference], changes: dict[str, Any], key: str) -> dict[str, Any]:
    try:
        current = _decode(row) if row is not None else {}
    except ValueError:
        current = {}
    if not isinstance(current, dict):
        current = {}
    merged = dict(current)
    for item, item_value in changes.items():
        if item_value is None:
            merged.pop(item, None)
        else:
            merged[item] = item_value
    if len(merged) > PAGE_SIZES_MAX_LISTS:
        raise HTTPException(422, f"Настройка «{key}» хранит не больше {PAGE_SIZES_MAX_LISTS} элементов.")
    return merged


def delete_user_preferences(session: Session, user_id: str) -> None:
    """Личные настройки удаляемого пользователя (внешнего ключа с каскадом у owner нет, см. models.AppPreference)."""
    session.execute(delete(AppPreference).where(AppPreference.owner == user_owner_by_id(user_id)))


def user_owner_by_id(user_id: str) -> str:
    return f"user:{user_id}"
