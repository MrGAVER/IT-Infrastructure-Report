"""A-22: неверный текущий пароль при смене пароля — 422 WRONG_CURRENT_PASSWORD, попытка засчитывается как неудачный вход.

Раньше `change_own_password` отвечал 401: код, которым API сообщает «токен отсутствует или недействителен» (клиент по нему завершает
сессию), поэтому опечатка в поле пароля разлогинивала пользователя. Попытки при этом нигде не учитывались: у кого оказался чужой токен
(общий компьютер, забытая вкладка), тот подбирал пароль владельца через этот эндпоинт без ограничений и без следа в журнале.

Запуск: pytest backend/tests/test_wrong_current_password.py -v
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import AuditLog, User
from app.services import auth as auth_module
from app.services.auth import lockout as lockout_module
from app.services.auth import login as login_module

URL = "/api/v1/auth/me/password"
THRESHOLD = 4


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def admin_token(client, monkeypatch) -> str:
    from app.services.login_throttle import LoginThrottle

    monkeypatch.setattr(lockout_module, "AUTH_MAX_FAILED_ATTEMPTS", THRESHOLD)
    monkeypatch.setattr(login_module, "login_throttle", LoginThrottle(free_attempts=1000))  # троттлинг входа не мешает проверке блокировки
    assert client.post("/api/v1/auth/users", json={"username": "admin", "password": "Admin1234", "role": "admin"}).status_code == 201
    assert client.put("/api/v1/auth/settings", json={"enabled": True}).status_code == 200
    return _login(client, "Admin1234")


def _login(client, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _change(client, token: str, current: str, new: str = "NewPass1234"):
    return client.put(URL, json={"current_password": current, "new_password": new}, headers=_headers(token))


def _user(db_session) -> User:
    db_session.expire_all()
    return db_session.scalars(select(User).where(User.username == "admin")).one()


def _failed_rows(db_session) -> list[AuditLog]:
    db_session.expire_all()
    rows = db_session.scalars(select(AuditLog).where(AuditLog.entity_type == "auth", AuditLog.action == "LOGIN_FAILED").order_by(AuditLog.created_at, AuditLog.id))
    return list(rows)


def test_wrong_current_password_is_422_with_a_code_and_keeps_the_session(client, admin_token):
    response = _change(client, admin_token, "wrong-one1")
    assert response.status_code == 422
    assert response.json()["detail"] == {"message": "Текущий пароль указан неверно.", "code": "WRONG_CURRENT_PASSWORD"}
    assert client.get("/api/v1/auth/me", headers=_headers(admin_token)).status_code == 200, "сессия жива: это не 401"


def test_the_attempt_is_counted_and_written_to_the_audit_log(client, admin_token, db_session):
    assert _user(db_session).failed_attempts == 0
    _change(client, admin_token, "wrong-one1")
    assert _user(db_session).failed_attempts == 1
    (row,) = _failed_rows(db_session)
    assert "Неверный текущий пароль при смене пароля «admin»" in row.details
    assert row.actor_username == "admin" and row.actor_ip == "127.0.0.1"


def test_account_is_locked_after_the_configured_number_of_wrong_values(client, client_factory, admin_token, db_session):
    for _ in range(THRESHOLD):
        assert _change(client, admin_token, "wrong-one1").status_code == 422
    locked = _user(db_session)
    assert locked.locked_until is not None and locked.failed_attempts == 0
    # Вход с адреса, с которого пользователь ещё не входил: со «знакомого» (127.0.0.1, где открыта сессия) блокировка пропускает (A-08)
    stranger = client_factory("203.0.113.9")
    login = stranger.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234"})
    assert login.status_code == 423 and login.json()["detail"]["code"] == "ACCOUNT_LOCKED"
    assert any("учётная запись заблокирована" in row.details for row in _failed_rows(db_session))


def test_locked_account_does_not_check_passwords_through_this_endpoint_either(client, admin_token, db_session):
    for _ in range(THRESHOLD):
        _change(client, admin_token, "wrong-one1")
    attempts_before = len(_failed_rows(db_session))
    for password in ("Admin1234", "wrong-one1"):  # даже верный пароль не принимается, а неверный не получает новых попыток
        response = _change(client, admin_token, password)
        assert response.status_code == 423 and response.json()["detail"]["code"] == "ACCOUNT_LOCKED"
    assert len(_failed_rows(db_session)) == attempts_before
    assert auth_module.verify_password("Admin1234", _user(db_session).password_hash), "пароль не изменился"


def test_correct_current_password_still_changes_it_and_resets_the_counter(client, admin_token, db_session):
    _change(client, admin_token, "wrong-one1")
    assert _user(db_session).failed_attempts == 1
    response = _change(client, admin_token, "Admin1234")
    assert response.status_code == 200, response.text
    assert _user(db_session).failed_attempts == 0
    assert _login(client, "NewPass1234")


def test_weak_new_password_with_a_correct_current_one_is_not_a_failed_attempt(client, admin_token, db_session):
    response = _change(client, admin_token, "Admin1234", new="short")
    assert response.status_code == 422 and response.json()["detail"]["code"] == "WEAK_PASSWORD"
    assert _user(db_session).failed_attempts == 0 and _failed_rows(db_session) == []


def test_failed_login_still_counts_and_logs_the_same_way(client, admin_token, db_session):
    """Общий код учёта неверного пароля для входа и смены: вход ведёт себя как прежде."""
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-one1"})
    assert response.status_code == 401
    assert _user(db_session).failed_attempts == 1
    (row,) = _failed_rows(db_session)
    assert row.details == "Неудачная попытка входа «admin»"
    assert row.actor_username == "admin" and row.actor_ip == "127.0.0.1"
