"""Роутер настроек интерфейса: /api/v1/preferences (см. services/preferences.py).

GET            — личные и общие настройки текущего пользователя (только заданные значения).
PUT /user      — личные настройки (тема, размеры страниц, порог сворачивания); доступны любой роли, включая
                 viewer: это настройки отображения, а не данные реестра (см. ROLE_CHECK_EXEMPT_PATHS).
PUT /global    — общие настройки (название организации); при включённой аутентификации — только администратор.
Поле, которого нет в теле, не меняется; null сбрасывает настройку к умолчанию.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..db import get_db
from ..models import User
from ..schemas import GlobalPreferencesUpdate, UserPreferencesUpdate
from ..services.crud import audit
from ..services.preferences import OWNER_GLOBAL, read_preferences, require_global_write, update_preferences, user_owner

router = APIRouter(prefix="/api/v1/preferences", tags=["Preferences"])


def _current_user(request: Request) -> User | None:
    return getattr(request.state, "user", None)


@router.get("")
def get_preferences(request: Request, session: Session = Depends(get_db)) -> dict:
    return read_preferences(session, _current_user(request))


@router.put("/user")
def update_user_preferences(payload: UserPreferencesUpdate, request: Request, session: Session = Depends(get_db)) -> dict:
    user = _current_user(request)
    update_preferences(session, user_owner(user), payload.model_dump(exclude_unset=True))
    return read_preferences(session, user)


@router.put("/global")
def update_global_preferences(payload: GlobalPreferencesUpdate, request: Request, session: Session = Depends(get_db)) -> dict:
    user = _current_user(request)
    require_global_write(auth_enabled=bool(getattr(request.state, "auth_enabled", False)), user=user)
    patch = payload.model_dump(exclude_unset=True)
    update_preferences(session, OWNER_GLOBAL, patch)
    if "organization_name" in patch:
        name = patch["organization_name"]
        audit(session, "preferences", OWNER_GLOBAL, AuditAction.UPDATE,
              f"Название организации: «{name}»" if name else "Название организации сброшено к значению по умолчанию")
        session.commit()
    return read_preferences(session, user)
