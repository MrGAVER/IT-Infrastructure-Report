"""
Код-ревью r3, A-01: проверки прав в services/auth/guards.py «падают закрытыми».

Флаг request.state.auth_enabled выставляет только шлюз (services/auth/gate.py) и только для /api/*. Если его нет — новый маршрут вне
шлюза, изменённая очерёдность middleware, зависимость вызвана из теста или скрипта, — это значит «шлюз не отработал», а не
«аутентификация выключена». Раньше отсутствие флага трактовалось как «выключена», и защита пропускала запрос: для
require_admin_if_auth_enabled — сразу, для require_admin — дальше по режиму первичной настройки. Теперь без флага отказ (403).

Запуск: pytest backend/tests/test_auth_guards_fail_closed.py -v
"""
from __future__ import annotations

import pytest
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.constants import UserRole
from app.models import User
from app.services.auth.guards import require_admin, require_admin_if_auth_enabled


def _request(*, auth_enabled: bool | None = None, user: User | None = None, client_host: str = "127.0.0.1") -> Request:
    """Request без шлюза: флаг и пользователь появляются в state, только если их передали (None — «шлюз не отработал»)."""
    request = Request({"type": "http", "method": "GET", "path": "/api/v1/probe", "headers": [], "query_string": b"", "client": (client_host, 50000)})
    if auth_enabled is not None:
        request.state.auth_enabled = auth_enabled
    if user is not None:
        request.state.user = user
    return request


def _user(role: str) -> User:
    return User(username=f"{role}-user", role=role)


@pytest.mark.parametrize("guard", [require_admin_if_auth_enabled, require_admin])
def test_missing_flag_denies_instead_of_letting_the_request_through(guard):
    with pytest.raises(HTTPException) as denied:
        guard(_request())
    assert denied.value.status_code == 403


@pytest.mark.parametrize("guard", [require_admin_if_auth_enabled, require_admin])
def test_missing_flag_denies_even_a_direct_localhost_client(guard):
    # Именно этот клиент прошёл бы require_admin по прежнему пути «флага нет → первичная настройка → localhost разрешён».
    with pytest.raises(HTTPException) as denied:
        guard(_request(client_host="127.0.0.1"))
    assert denied.value.status_code == 403


@pytest.mark.parametrize("guard", [require_admin_if_auth_enabled, require_admin])
def test_missing_flag_with_a_viewer_in_state_still_denies(guard):
    with pytest.raises(HTTPException) as denied:
        guard(_request(user=_user(UserRole.VIEWER)))
    assert denied.value.status_code == 403


@pytest.mark.parametrize("guard", [require_admin_if_auth_enabled, require_admin])
def test_enabled_auth_admits_only_an_administrator(guard):
    guard(_request(auth_enabled=True, user=_user(UserRole.ADMIN)))  # не бросает
    for intruder in (None, _user(UserRole.VIEWER)):
        with pytest.raises(HTTPException) as denied:
            guard(_request(auth_enabled=True, user=intruder))
        assert denied.value.status_code == 403


def test_an_explicit_disabled_flag_keeps_the_single_user_mode_working():
    # Однопользовательский режим по умолчанию: шлюз выставил auth_enabled=False — журнал аудита открыт владельцу.
    require_admin_if_auth_enabled(_request(auth_enabled=False))
    # require_admin при выключенной аутентификации передаёт решение первичной настройке: прямой localhost допускается, чужой адрес — нет.
    require_admin(_request(auth_enabled=False, client_host="127.0.0.1"))
    with pytest.raises(HTTPException) as denied:
        require_admin(_request(auth_enabled=False, client_host="203.0.113.7"))
    assert denied.value.status_code == 403


def test_a_route_outside_the_gate_is_closed_not_open():
    """Сценарий из отчёта: маршрут с зависимостью зарегистрирован так, что шлюз его не обслужил (здесь — приложение без middleware)."""
    router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_admin_if_auth_enabled)])

    @router.get("/secret")
    def secret() -> dict:
        return {"leaked": True}

    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/api/v1/secret")
    assert response.status_code == 403
    assert "leaked" not in response.text
