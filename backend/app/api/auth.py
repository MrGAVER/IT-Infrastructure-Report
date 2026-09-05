"""Роутер аутентификации: /api/v1/auth/*.

Публичные без токена (см. services/auth.PUBLIC_API_PATHS): status, login.
Всё остальное защищено ASGI-middleware (main.py:auth_gate_middleware) при AuthSettings.enabled=True;
при enabled=False — открыто целиком, как и весь остальной /api/*, это и есть однопользовательский
режим. /users и /settings дополнительно проверяют роль admin явно (require_admin) — middleware
пропускает viewer'а на безопасные GET-запросы, а список учётных записей viewer'у видеть не должен.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..config import AUTH_SESSION_TTL_HOURS
from ..db import get_db
from ..models import User
from ..schemas import AuthSettingsUpdate, LoginRequest, UserCreateRequest, UserUpdateRequest
from ..services.auth import (
    authenticate,
    create_user,
    delete_user,
    get_or_create_auth_settings,
    list_active_sessions,
    require_admin,
    revoke_session,
    serialize_user,
    set_auth_enabled,
    update_user,
)

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    return header[len("Bearer "):].strip() or None if header.startswith("Bearer ") else None


def _current_user(request: Request) -> User | None:
    return getattr(request.state, "user", None)


@router.get("/status")
def auth_status(session: Session = Depends(get_db)) -> dict:
    """Публичный: нужен экрану логина ДО того, как у клиента появится токен, чтобы решить —
    показывать форму входа или пропускать пользователя сразу (однопользовательский режим)."""
    settings_row = get_or_create_auth_settings(session)
    return {"enabled": settings_row.enabled, "session_ttl_hours": AUTH_SESSION_TTL_HOURS}


@router.post("/login")
def login(payload: LoginRequest, request: Request, session: Session = Depends(get_db)) -> dict:
    user, token = authenticate(session, payload.username, payload.password, request=request)
    return {"token": token, "user": serialize_user(user)}


@router.post("/logout")
def logout(request: Request, session: Session = Depends(get_db)) -> dict:
    """Идемпотентен: вызывающему важен результат «я разлогинен», а не то, был ли токен ещё
    валиден на момент запроса — поэтому нет 401 на отсутствующий/уже недействительный токен."""
    token = _bearer_token(request)
    if token:
        revoke_session(session, token)
    return {"status": "ok"}


@router.get("/me")
def me(request: Request) -> dict:
    user = _current_user(request)
    enabled = bool(getattr(request.state, "auth_enabled", False))
    return {"enabled": enabled, "user": serialize_user(user) if user else None}


@router.get("/sessions")
def my_sessions(request: Request, session: Session = Depends(get_db)) -> list[dict]:
    """Список активных входов ТЕКУЩЕГО пользователя (не всех пользователей) — «где я ещё
    залогинен», без прав администратора это же не требует."""
    user = _current_user(request)
    if user is None:
        raise HTTPException(400, "Аутентификация выключена — сессии не отслеживаются.")
    return [
        {"id": row.id, "created_at": row.created_at.isoformat(), "expires_at": row.expires_at.isoformat(),
         "user_agent": row.user_agent, "ip_address": row.ip_address}
        for row in list_active_sessions(session, user.id)
    ]


@router.put("/settings")
def update_auth_settings(payload: AuthSettingsUpdate, request: Request, session: Session = Depends(get_db)) -> dict:
    require_admin(request)
    settings_row = set_auth_enabled(session, payload.enabled, actor=_current_user(request))
    return {"enabled": settings_row.enabled, "session_ttl_hours": AUTH_SESSION_TTL_HOURS}


@router.get("/users")
def list_users(request: Request, session: Session = Depends(get_db)) -> list[dict]:
    require_admin(request)
    return [serialize_user(u) for u in session.query(User).order_by(User.username).all()]


@router.post("/users", status_code=201)
def create_user_endpoint(payload: UserCreateRequest, request: Request, session: Session = Depends(get_db)) -> dict:
    require_admin(request)
    user = create_user(session, username=payload.username, password=payload.password, role=payload.role)
    return serialize_user(user)


def _get_user_or_404(session: Session, user_id: str) -> User:
    user = session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "Пользователь не найден")
    return user


@router.put("/users/{user_id}")
def update_user_endpoint(user_id: str, payload: UserUpdateRequest, request: Request, session: Session = Depends(get_db)) -> dict:
    require_admin(request)
    user = _get_user_or_404(session, user_id)
    updated = update_user(
        session, user,
        username=payload.username, password=payload.password,
        role=payload.role, is_active=payload.is_active,
    )
    return serialize_user(updated)


@router.delete("/users/{user_id}", status_code=204)
def delete_user_endpoint(user_id: str, request: Request, session: Session = Depends(get_db)) -> None:
    require_admin(request)
    user = _get_user_or_404(session, user_id)
    delete_user(session, user)
