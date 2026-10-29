"""A-08: блокировка учётной записи не даёт постороннему держать администратора заблокированным.

Раньше после AUTH_MAX_FAILED_ATTEMPTS неудачных входов вход с ЛЮБОГО адреса (в том числе с верным паролем) получал 423 до проверки пароля.
Любой, кто достаёт до /login, мог повторять неверные пароли и держать единственного администратора заблокированным практически
постоянно (троттлинг по паре «IP + логин» замедляет подбор пароля, но не мешает набрать десять неудач). Теперь блокировка отклоняет
вход только с «незнакомых» адресов; адрес, с которого пользователь успешно входил за последние 30 дней, проходит проверку пароля.

Запуск: pytest backend/tests/test_lockout_known_client.py -v
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, AuthSession, User
from app.services import auth as auth_module
from app.services.login_throttle import LoginThrottle
from app.services.timeutil import utcnow_naive

LOGIN = "/api/v1/auth/login"
THRESHOLD = 5
OWNER_ADDRESS = "203.0.113.10"  # адрес, с которого владелец входил
ATTACKER_ADDRESS = "198.51.100.66"
NEW_ADDRESS = "192.0.2.77"  # адрес, с которого владелец ещё не входил


@pytest.fixture()
def setup(client, client_factory, monkeypatch):
    """Администратор создан, аутентификация включена, порог блокировки — THRESHOLD, троттлинг входа не мешает."""
    monkeypatch.setattr(auth_module, "AUTH_MAX_FAILED_ATTEMPTS", THRESHOLD)
    monkeypatch.setattr(auth_module, "login_throttle", LoginThrottle(free_attempts=1000))
    assert client.post("/api/v1/auth/users", json={"username": "admin", "password": "Admin1234", "role": "admin"}).status_code == 201
    assert client.put("/api/v1/auth/settings", json={"enabled": True}).status_code == 200
    return client_factory


def _attempt(client, password: str):
    return client.post(LOGIN, json={"username": "admin", "password": password})


def _lock_from(client, times: int = THRESHOLD):
    for _ in range(times):
        assert _attempt(client, "wrong-pass1").status_code == 401


def _admin(db_session) -> User:
    db_session.expire_all()
    return db_session.scalars(select(User).where(User.username == "admin")).one()


def test_a_attacker_locks_the_account(setup, db_session):
    owner, attacker = setup(OWNER_ADDRESS), setup(ATTACKER_ADDRESS)
    assert _attempt(owner, "Admin1234").status_code == 200
    _lock_from(attacker)
    admin = _admin(db_session)
    assert admin.locked_until is not None and admin.locked_until > utcnow_naive()


def test_b_correct_password_from_an_unfamiliar_address_is_still_locked_out(setup, db_session):
    owner, attacker, newcomer = setup(OWNER_ADDRESS), setup(ATTACKER_ADDRESS), setup(NEW_ADDRESS)
    assert _attempt(owner, "Admin1234").status_code == 200
    _lock_from(attacker)
    response = _attempt(newcomer, "Admin1234")
    assert response.status_code == 423 and response.json()["detail"]["code"] == "ACCOUNT_LOCKED"
    assert _attempt(attacker, "Admin1234").status_code == 423, "и с адреса злоумышленника — тоже"


def test_c_owner_from_a_known_address_gets_in_and_the_lock_is_cleared(setup, db_session):
    owner, attacker = setup(OWNER_ADDRESS), setup(ATTACKER_ADDRESS)
    assert _attempt(owner, "Admin1234").status_code == 200
    _lock_from(attacker)
    response = _attempt(owner, "Admin1234")
    assert response.status_code == 200 and response.json()["token"]
    admin = _admin(db_session)
    assert admin.locked_until is None and admin.failed_attempts == 0
    assert _attempt(setup(NEW_ADDRESS), "Admin1234").status_code == 200, "блокировка снята и для остальных"


def test_d_wrong_password_from_a_known_address_still_counts_and_is_throttled(setup, db_session, monkeypatch):
    owner, attacker = setup(OWNER_ADDRESS), setup(ATTACKER_ADDRESS)
    assert _attempt(owner, "Admin1234").status_code == 200
    _lock_from(attacker)
    assert _admin(db_session).failed_attempts == 0

    response = _attempt(owner, "wrong-pass1")
    assert response.status_code == 401, "пароль проверен, а не отклонён блокировкой (423)"
    assert _admin(db_session).failed_attempts == 1, "неверный пароль с известного адреса увеличивает счётчик"
    failed = [r for r in db_session.scalars(select(AuditLog).where(AuditLog.action == "LOGIN_FAILED"))]
    assert failed and failed[-1].actor_ip == OWNER_ADDRESS

    monkeypatch.setattr(auth_module, "login_throttle", LoginThrottle(free_attempts=1))  # настоящий троттлинг
    assert _attempt(owner, "wrong-pass1").status_code == 401  # бесплатная попытка
    assert _attempt(owner, "wrong-pass1").status_code == 401  # вторая неудача назначает задержку
    throttled = _attempt(owner, "wrong-pass1")
    assert throttled.status_code == 429 and throttled.json()["detail"]["code"] == "TOO_MANY_ATTEMPTS"
    assert "Retry-After" in throttled.headers


def test_brute_force_from_a_known_address_can_relock_the_account(setup, db_session):
    owner, attacker, newcomer = setup(OWNER_ADDRESS), setup(ATTACKER_ADDRESS), setup(NEW_ADDRESS)
    assert _attempt(owner, "Admin1234").status_code == 200
    _lock_from(attacker)
    for _ in range(THRESHOLD):
        assert _attempt(owner, "wrong-pass1").status_code == 401
    assert _admin(db_session).locked_until > utcnow_naive(), "порог снова достигнут — блокировка продлена"
    assert _attempt(newcomer, "Admin1234").status_code == 423


class TestWhatMakesAnAddressKnown:
    def test_a_login_older_than_the_window_does_not_count_and_a_recent_one_does(self, setup, db_session):
        owner, attacker = setup(OWNER_ADDRESS), setup(ATTACKER_ADDRESS)
        assert _attempt(owner, "Admin1234").status_code == 200
        row = db_session.scalars(select(AuditLog).where(AuditLog.action == "LOGIN")).one()
        _lock_from(attacker)

        row.created_at = utcnow_naive() - timedelta(days=auth_module.AUTH_KNOWN_CLIENT_DAYS + 1)
        db_session.commit()
        assert _attempt(owner, "Admin1234").status_code == 423

        row.created_at = utcnow_naive() - timedelta(days=auth_module.AUTH_KNOWN_CLIENT_DAYS - 1)
        db_session.commit()
        assert _attempt(owner, "Admin1234").status_code == 200

    def test_the_memory_outlives_the_sessions(self, setup, db_session):
        """Просроченные сессии удаляются при каждом входе (cleanup_expired_sessions): адрес не должен «забываться» вместе с ними."""
        owner, attacker = setup(OWNER_ADDRESS), setup(ATTACKER_ADDRESS)
        assert _attempt(owner, "Admin1234").status_code == 200
        for row in db_session.scalars(select(AuthSession)):
            row.expires_at = utcnow_naive() - timedelta(hours=1)
        db_session.commit()
        auth_module.cleanup_expired_sessions(db_session)
        assert db_session.scalars(select(AuthSession)).all() == []
        _lock_from(attacker)
        assert _attempt(owner, "Admin1234").status_code == 200

    def test_failed_logins_and_other_users_do_not_make_an_address_known(self, setup, db_session):
        owner, attacker = setup(OWNER_ADDRESS), setup(ATTACKER_ADDRESS)
        token = _attempt(owner, "Admin1234").json()["token"]
        created = owner.post(
            "/api/v1/auth/users", json={"username": "viewer1", "password": "Viewer1234", "role": "viewer"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert created.status_code == 201, created.text
        _lock_from(attacker)  # с адреса злоумышленника — только неудачные входы администратора
        assert _attempt(attacker, "Admin1234").status_code == 423

        # успешный вход ДРУГОГО пользователя с этого адреса делает его знакомым для него, но не для администратора
        assert attacker.post(LOGIN, json={"username": "viewer1", "password": "Viewer1234"}).status_code == 200
        assert _attempt(attacker, "Admin1234").status_code == 423

    def test_unknown_client_address_is_never_known(self, db_session):
        assert auth_module._is_known_client(db_session, "any-user", None, utcnow_naive()) is False
        assert auth_module._is_known_client(db_session, "any-user", "", utcnow_naive()) is False


def test_the_bypass_can_be_switched_off(setup, db_session, monkeypatch):
    monkeypatch.setattr(auth_module, "AUTH_LOCKOUT_KNOWN_CLIENT_BYPASS", False)
    owner, attacker = setup(OWNER_ADDRESS), setup(ATTACKER_ADDRESS)
    assert _attempt(owner, "Admin1234").status_code == 200
    _lock_from(attacker)
    response = _attempt(owner, "Admin1234")
    assert response.status_code == 423 and response.json()["detail"]["code"] == "ACCOUNT_LOCKED"


@pytest.mark.parametrize(("raw", "expected"), [("", True), ("1", True), ("true", True), ("0", False), ("false", False), ("No", False), ("OFF", False)])
def test_environment_variable_parsing(monkeypatch, raw, expected):
    import importlib

    import app.config as config

    monkeypatch.setenv("INFRA_REGISTRY_AUTH_LOCKOUT_KNOWN_CLIENT_BYPASS", raw)
    try:
        reloaded = importlib.reload(config)
        assert reloaded.AUTH_LOCKOUT_KNOWN_CLIENT_BYPASS is expected
    finally:
        monkeypatch.delenv("INFRA_REGISTRY_AUTH_LOCKOUT_KNOWN_CLIENT_BYPASS", raising=False)
        importlib.reload(config)
