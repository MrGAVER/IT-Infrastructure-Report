"""Код-ревью Н-10: число сессий одного пользователя ограничено.

Сессия живёт фиксированные 12 часов, а каждый вход создаёт новую строку auth_sessions. Скрипт, входящий снова и снова, копил бы
тысячи строк и раздувал список «Мои сессии». Теперь при входе сверх MAX_SESSIONS_PER_USER удаляются самые старые сессии
ЭТОГО пользователя; чужие сессии и самая свежая (только что выданная) остаются.

Запуск: pytest backend/tests/test_review_p1_session_limit.py -v
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.constants import MAX_SESSIONS_PER_USER
from app.models import AuthSession, User
from app.services.auth import login as login_module
from app.services.auth.sessions import _hash_token, _trim_user_sessions, create_session
from app.services.login_throttle import LoginThrottle
from app.services.timeutil import utcnow_naive

LOGIN = "/api/v1/auth/login"


@pytest.fixture()
def users(client, db_session, monkeypatch):
    """Два администратора; троттлинг входа не мешает серии входов."""
    monkeypatch.setattr(login_module, "login_throttle", LoginThrottle(free_attempts=10_000))
    for name in ("alice", "bob"):
        assert client.post("/api/v1/auth/users", json={"username": name, "password": "Passw0rd123", "role": "admin"}).status_code == 201
    assert client.put("/api/v1/auth/settings", json={"enabled": True}).status_code == 200
    return {name: db_session.scalars(select(User).where(User.username == name)).one() for name in ("alice", "bob")}


def _count(db_session, user: User) -> int:
    db_session.expire_all()
    return db_session.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user.id)) or 0


def _login(client, username: str) -> str:
    response = client.post(LOGIN, json={"username": username, "password": "Passw0rd123"})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _seed(db_session, user: User, count: int) -> list[str]:
    """`count` сессий пользователя с возрастающим created_at; возвращает хеши токенов от старой к новой."""
    base = utcnow_naive() - timedelta(hours=5)
    hashes = []
    for index in range(count):
        token_hash = _hash_token(f"seed-{user.username}-{index}")
        db_session.add(
            AuthSession(
                token_hash=token_hash,
                user_id=user.id,
                created_at=base + timedelta(minutes=index),
                expires_at=utcnow_naive() + timedelta(hours=6),
            )
        )
        hashes.append(token_hash)
    db_session.commit()
    return hashes


def _alive(db_session, hashes: list[str]) -> list[str]:
    db_session.expire_all()
    present = set(db_session.scalars(select(AuthSession.token_hash).where(AuthSession.token_hash.in_(hashes))).all())
    return [h for h in hashes if h in present]


def test_the_limit_is_twenty():
    assert MAX_SESSIONS_PER_USER == 20


def test_logins_below_the_limit_are_untouched(client, db_session, users):
    seeded = _seed(db_session, users["alice"], MAX_SESSIONS_PER_USER - 1)
    _login(client, "alice")
    assert _count(db_session, users["alice"]) == MAX_SESSIONS_PER_USER
    assert _alive(db_session, seeded) == seeded


def test_the_oldest_sessions_go_when_the_limit_is_exceeded(client, db_session, users):
    seeded = _seed(db_session, users["alice"], MAX_SESSIONS_PER_USER + 5)  # уже сверх предела, как до введения ограничения
    token = _login(client, "alice")

    assert _count(db_session, users["alice"]) == MAX_SESSIONS_PER_USER
    assert _alive(db_session, seeded) == seeded[-(MAX_SESSIONS_PER_USER - 1) :], "остаются самые новые, самые старые удалены"
    assert _hash_token(token) in db_session.scalars(select(AuthSession.token_hash)).all(), "только что выданная сессия на месте"


def test_a_repeated_login_never_grows_the_table_past_the_limit(client, db_session, users):
    for _ in range(MAX_SESSIONS_PER_USER + 7):
        _login(client, "alice")
    assert _count(db_session, users["alice"]) == MAX_SESSIONS_PER_USER


def test_the_newly_issued_token_works_after_trimming(client, db_session, users):
    _seed(db_session, users["alice"], MAX_SESSIONS_PER_USER)
    token = _login(client, "alice")
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["user"]["username"] == "alice"


def test_other_users_sessions_are_not_touched(client, db_session, users):
    bobs = _seed(db_session, users["bob"], MAX_SESSIONS_PER_USER)
    _seed(db_session, users["alice"], MAX_SESSIONS_PER_USER)
    _login(client, "alice")
    assert _alive(db_session, bobs) == bobs
    assert _count(db_session, users["bob"]) == MAX_SESSIONS_PER_USER


def test_trim_with_a_non_positive_keep_removes_nothing_unexpectedly(db_session, users):
    """keep=0 — «не оставлять ничего», отрицательное значение не должно ломать запрос смещением < 0."""
    _seed(db_session, users["alice"], 3)
    assert _trim_user_sessions(db_session, users["alice"].id, keep=-5) == 3
    db_session.commit()
    assert _count(db_session, users["alice"]) == 0


def test_create_session_keeps_the_limit_without_going_through_http(db_session, users):
    _seed(db_session, users["alice"], MAX_SESSIONS_PER_USER)
    create_session(db_session, users["alice"])
    assert _count(db_session, users["alice"]) == MAX_SESSIONS_PER_USER
