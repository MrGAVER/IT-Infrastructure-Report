"""Тесты аутентификации/авторизации (app/services/auth.py, app/api/auth.py).

Каждый тест получает изолированную in-memory БД (фикстура client/db_session из conftest.py),
поэтому AuthSettings всегда стартует в состоянии по умолчанию: enabled=False.
"""
from __future__ import annotations


def _bootstrap_admin(client, username: str = "admin", password: str = "Admin1234") -> dict:
    """Заводит первого администратора, пока аутентификация ещё выключена (открытый bootstrap,
    см. docstring services/auth.set_auth_enabled) и включает переключатель."""
    r = client.post("/api/v1/auth/users", json={"username": username, "password": password, "role": "admin"})
    assert r.status_code == 201, r.text
    r = client.put("/api/v1/auth/settings", json={"enabled": True})
    assert r.status_code == 200, r.text
    return r.json()


def _login(client, username: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestDisabledByDefault:
    """Однопользовательский режим: без единого вызова /auth/* поведение API не отличается от
    состояния до появления этой фичи — это и есть требование «по умолчанию выключено»."""

    def test_status_reports_disabled(self, client):
        r = client.get("/api/v1/auth/status")
        assert r.status_code == 200
        assert r.json()["enabled"] is False

    def test_resources_open_without_any_token(self, client):
        r = client.get("/api/v1/resources/manufacturers")
        assert r.status_code == 200
        r = client.post("/api/v1/resources/manufacturers", json={"name": "Без токена"})
        assert r.status_code == 201, r.text

    def test_me_reports_no_user(self, client):
        r = client.get("/api/v1/auth/me")
        assert r.status_code == 200
        assert r.json() == {"enabled": False, "user": None}


class TestBootstrapAndToggle:
    def test_creating_first_user_requires_no_token_while_disabled(self, client):
        r = client.post("/api/v1/auth/users", json={"username": "admin", "password": "Admin1234", "role": "admin"})
        assert r.status_code == 201, r.text
        assert r.json()["role"] == "admin"

    def test_enabling_without_any_admin_is_rejected(self, client):
        client.post("/api/v1/auth/users", json={"username": "viewer1", "password": "Viewer1234", "role": "viewer"})
        r = client.put("/api/v1/auth/settings", json={"enabled": True})
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "AUTH_REQUIRES_ADMIN"

    def test_enabling_with_an_admin_succeeds(self, client):
        _bootstrap_admin(client)
        assert client.get("/api/v1/auth/status").json()["enabled"] is True

    def test_admin_can_disable_again(self, client):
        _bootstrap_admin(client)
        token = _login(client, "admin", "Admin1234")
        r = client.put("/api/v1/auth/settings", json={"enabled": False}, headers=_auth_headers(token))
        assert r.status_code == 200
        assert client.get("/api/v1/auth/status").json()["enabled"] is False
        # once disabled, everything is open again, even without a token
        assert client.get("/api/v1/resources/manufacturers").status_code == 200


class TestLoginFlow:
    def test_unknown_username_and_wrong_password_share_message(self, client):
        _bootstrap_admin(client)
        r1 = client.post("/api/v1/auth/login", json={"username": "no-such-user", "password": "whatever1"})
        r2 = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass1"})
        assert r1.status_code == r2.status_code == 401
        assert r1.json()["detail"] == r2.json()["detail"]

    def test_successful_login_grants_access_to_protected_endpoint(self, client):
        _bootstrap_admin(client)
        token = _login(client, "admin", "Admin1234")
        r = client.get("/api/v1/resources/manufacturers", headers=_auth_headers(token))
        assert r.status_code == 200

    def test_missing_token_is_rejected_once_enabled(self, client):
        _bootstrap_admin(client)
        r = client.get("/api/v1/resources/manufacturers")
        assert r.status_code == 401

    def test_account_locks_after_max_failed_attempts(self, client, monkeypatch):
        # Порог — настраиваемая константа (по умолчанию 10), а троттлинг входа по IP (см.
        # services/login_throttle.py) здесь отключён: тест проверяет именно блокировку аккаунта.
        from app.services import auth as auth_module
        from app.services.login_throttle import LoginThrottle

        monkeypatch.setattr(auth_module, "AUTH_MAX_FAILED_ATTEMPTS", 5)
        monkeypatch.setattr(auth_module, "login_throttle", LoginThrottle(free_attempts=1000))
        _bootstrap_admin(client)
        for _ in range(5):
            r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass1"})
            assert r.status_code == 401
        r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "Admin1234"})
        assert r.status_code == 423
        assert r.json()["detail"]["code"] == "ACCOUNT_LOCKED"

    def test_logout_invalidates_the_token(self, client):
        _bootstrap_admin(client)
        token = _login(client, "admin", "Admin1234")
        assert client.post("/api/v1/auth/logout", headers=_auth_headers(token)).status_code == 200
        r = client.get("/api/v1/resources/manufacturers", headers=_auth_headers(token))
        assert r.status_code == 401

    def test_logout_without_a_token_is_a_harmless_no_op(self, client):
        r = client.post("/api/v1/auth/logout")
        assert r.status_code == 200


class TestRoleBasedAccess:
    def _bootstrap_viewer(self, client) -> str:
        _bootstrap_admin(client)
        admin_token = _login(client, "admin", "Admin1234")
        client.post("/api/v1/auth/users", json={"username": "viewer1", "password": "Viewer1234", "role": "viewer"}, headers=_auth_headers(admin_token))
        return _login(client, "viewer1", "Viewer1234")

    def test_viewer_can_read(self, client):
        token = self._bootstrap_viewer(client)
        r = client.get("/api/v1/resources/manufacturers", headers=_auth_headers(token))
        assert r.status_code == 200

    def test_viewer_cannot_write(self, client):
        token = self._bootstrap_viewer(client)
        r = client.post("/api/v1/resources/manufacturers", json={"name": "Viewer Co"}, headers=_auth_headers(token))
        assert r.status_code == 403

    def test_viewer_can_still_log_out(self, client):
        """Единственное исключение из «viewer не пишет» — иначе выйти было бы физически нельзя."""
        token = self._bootstrap_viewer(client)
        r = client.post("/api/v1/auth/logout", headers=_auth_headers(token))
        assert r.status_code == 200

    def test_viewer_cannot_list_users(self, client):
        token = self._bootstrap_viewer(client)
        r = client.get("/api/v1/auth/users", headers=_auth_headers(token))
        assert r.status_code == 403

    def test_admin_can_write(self, client):
        _bootstrap_admin(client)
        token = _login(client, "admin", "Admin1234")
        r = client.post("/api/v1/resources/manufacturers", json={"name": "Admin Co"}, headers=_auth_headers(token))
        assert r.status_code == 201


class TestUserManagement:
    def test_duplicate_username_is_rejected_case_insensitively(self, client):
        _bootstrap_admin(client)
        token = _login(client, "admin", "Admin1234")
        r = client.post("/api/v1/auth/users", json={"username": "Admin", "password": "Other1234", "role": "viewer"}, headers=_auth_headers(token))
        assert r.status_code == 409, r.text
        assert r.json()["detail"]["code"] == "DUPLICATE_USERNAME"

    def test_weak_password_is_rejected(self, client):
        r = client.post("/api/v1/auth/users", json={"username": "admin", "password": "short", "role": "admin"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "WEAK_PASSWORD"

    def test_cannot_delete_the_last_admin(self, client):
        _bootstrap_admin(client)
        token = _login(client, "admin", "Admin1234")
        me = client.get("/api/v1/auth/me", headers=_auth_headers(token)).json()["user"]
        r = client.delete(f"/api/v1/auth/users/{me['id']}", headers=_auth_headers(token))
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "LAST_ADMIN_ACCOUNT"

    def test_cannot_demote_the_last_admin(self, client):
        _bootstrap_admin(client)
        token = _login(client, "admin", "Admin1234")
        me = client.get("/api/v1/auth/me", headers=_auth_headers(token)).json()["user"]
        r = client.put(f"/api/v1/auth/users/{me['id']}", json={"role": "viewer"}, headers=_auth_headers(token))
        assert r.status_code == 400
        assert r.json()["detail"]["code"] == "LAST_ADMIN_ACCOUNT"

    def test_second_admin_allows_demoting_the_first(self, client):
        _bootstrap_admin(client)
        token = _login(client, "admin", "Admin1234")
        me = client.get("/api/v1/auth/me", headers=_auth_headers(token)).json()["user"]
        client.post("/api/v1/auth/users", json={"username": "admin2", "password": "Admin1234", "role": "admin"}, headers=_auth_headers(token))
        r = client.put(f"/api/v1/auth/users/{me['id']}", json={"role": "viewer"}, headers=_auth_headers(token))
        assert r.status_code == 200

    def test_password_change_revokes_existing_sessions(self, client):
        _bootstrap_admin(client)
        old_token = _login(client, "admin", "Admin1234")
        me = client.get("/api/v1/auth/me", headers=_auth_headers(old_token)).json()["user"]
        r = client.put(f"/api/v1/auth/users/{me['id']}", json={"password": "NewPass1234"}, headers=_auth_headers(old_token))
        assert r.status_code == 200
        # old token is dead even though the admin who changed it was the one holding it
        r = client.get("/api/v1/resources/manufacturers", headers=_auth_headers(old_token))
        assert r.status_code == 401
        # new password works
        new_token = _login(client, "admin", "NewPass1234")
        assert client.get("/api/v1/resources/manufacturers", headers=_auth_headers(new_token)).status_code == 200


class TestMe:
    def test_me_reflects_authenticated_user(self, client):
        _bootstrap_admin(client)
        token = _login(client, "admin", "Admin1234")
        r = client.get("/api/v1/auth/me", headers=_auth_headers(token))
        body = r.json()
        assert body["enabled"] is True
        assert body["user"]["username"] == "admin"
        assert body["user"]["role"] == "admin"
        assert "password" not in body["user"] and "password_hash" not in body["user"]


class TestOwnPasswordChange:
    def test_requires_correct_current_password(self, client):
        _bootstrap_admin(client)
        token = _login(client, "admin", "Admin1234")
        r = client.put(
            "/api/v1/auth/me/password",
            json={"current_password": "wrong-one1", "new_password": "NewPass1234"},
            headers=_auth_headers(token),
        )
        # A-22: ошибка в поле формы — 422 с кодом, а не 401 («токен недействителен», по нему клиент завершает сессию)
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "WRONG_CURRENT_PASSWORD"

    def test_weak_new_password_is_rejected(self, client):
        _bootstrap_admin(client)
        token = _login(client, "admin", "Admin1234")
        r = client.put(
            "/api/v1/auth/me/password",
            json={"current_password": "Admin1234", "new_password": "short"},
            headers=_auth_headers(token),
        )
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "WEAK_PASSWORD"

    def test_viewer_can_change_their_own_password(self, client):
        _bootstrap_admin(client)
        admin_token = _login(client, "admin", "Admin1234")
        client.post("/api/v1/auth/users", json={"username": "viewer1", "password": "Viewer1234", "role": "viewer"}, headers=_auth_headers(admin_token))
        viewer_token = _login(client, "viewer1", "Viewer1234")

        r = client.put(
            "/api/v1/auth/me/password",
            json={"current_password": "Viewer1234", "new_password": "NewViewer1234"},
            headers=_auth_headers(viewer_token),
        )
        assert r.status_code == 200, r.text
        assert _login(client, "viewer1", "NewViewer1234")

    def test_keeps_the_calling_session_but_revokes_the_others(self, client):
        _bootstrap_admin(client)
        token_a = _login(client, "admin", "Admin1234")
        token_b = _login(client, "admin", "Admin1234")

        r = client.put(
            "/api/v1/auth/me/password",
            json={"current_password": "Admin1234", "new_password": "NewPass1234"},
            headers=_auth_headers(token_a),
        )
        assert r.status_code == 200, r.text

        # token_a — им же вызвана смена пароля — продолжает работать
        assert client.get("/api/v1/resources/manufacturers", headers=_auth_headers(token_a)).status_code == 200
        # token_b — другая сессия того же пользователя — отозван
        assert client.get("/api/v1/resources/manufacturers", headers=_auth_headers(token_b)).status_code == 401
        # новый пароль подходит для входа, старый — нет
        assert _login(client, "admin", "NewPass1234")


class TestSessions:
    def test_list_marks_the_calling_session_as_current(self, client):
        _bootstrap_admin(client)
        token = _login(client, "admin", "Admin1234")
        r = client.get("/api/v1/auth/sessions", headers=_auth_headers(token))
        sessions = r.json()
        assert len(sessions) == 1
        assert sessions[0]["current"] is True

    def test_second_login_appears_as_a_separate_non_current_session(self, client):
        _bootstrap_admin(client)
        token_a = _login(client, "admin", "Admin1234")
        _login(client, "admin", "Admin1234")

        sessions = client.get("/api/v1/auth/sessions", headers=_auth_headers(token_a)).json()
        assert len(sessions) == 2
        assert sum(1 for s in sessions if s["current"]) == 1

    def test_can_revoke_another_one_of_own_sessions(self, client):
        _bootstrap_admin(client)
        token_a = _login(client, "admin", "Admin1234")
        token_b = _login(client, "admin", "Admin1234")

        sessions = client.get("/api/v1/auth/sessions", headers=_auth_headers(token_a)).json()
        other_session_id = next(s["id"] for s in sessions if not s["current"])

        r = client.delete(f"/api/v1/auth/sessions/{other_session_id}", headers=_auth_headers(token_a))
        assert r.status_code == 204

        assert client.get("/api/v1/resources/manufacturers", headers=_auth_headers(token_a)).status_code == 200
        assert client.get("/api/v1/resources/manufacturers", headers=_auth_headers(token_b)).status_code == 401

    def test_cannot_revoke_someone_elses_session(self, client):
        _bootstrap_admin(client)
        admin_token = _login(client, "admin", "Admin1234")
        client.post("/api/v1/auth/users", json={"username": "viewer1", "password": "Viewer1234", "role": "viewer"}, headers=_auth_headers(admin_token))
        viewer_token = _login(client, "viewer1", "Viewer1234")

        admin_sessions = client.get("/api/v1/auth/sessions", headers=_auth_headers(admin_token)).json()
        admin_session_id = admin_sessions[0]["id"]

        r = client.delete(f"/api/v1/auth/sessions/{admin_session_id}", headers=_auth_headers(viewer_token))
        assert r.status_code == 404
        # админская сессия жива — viewer её не задел
        assert client.get("/api/v1/resources/manufacturers", headers=_auth_headers(admin_token)).status_code == 200

    def test_viewer_can_revoke_own_session_despite_write_restriction(self, client):
        """DELETE — метод записи, но самообслуживание сессий — исключение из проверки роли
        (см. ROLE_CHECK_EXEMPT_PREFIXES), иначе viewer не смог бы разлогинить сам себя на
        другом устройстве."""
        _bootstrap_admin(client)
        admin_token = _login(client, "admin", "Admin1234")
        client.post("/api/v1/auth/users", json={"username": "viewer1", "password": "Viewer1234", "role": "viewer"}, headers=_auth_headers(admin_token))
        token_a = _login(client, "viewer1", "Viewer1234")
        token_b = _login(client, "viewer1", "Viewer1234")

        sessions = client.get("/api/v1/auth/sessions", headers=_auth_headers(token_a)).json()
        other_id = next(s["id"] for s in sessions if not s["current"])

        r = client.delete(f"/api/v1/auth/sessions/{other_id}", headers=_auth_headers(token_a))
        assert r.status_code == 204
        assert client.get("/api/v1/resources/manufacturers", headers=_auth_headers(token_b)).status_code == 401


class TestConcurrencySafety:
    """Правки, актуальные при нескольких процессах backend за одной БД (см. README — серверный
    вариант, Docker + PostgreSQL). in-memory SQLite тестового окружения не воспроизводит реальную
    гонку между процессами (SQLAlchemy StaticPool держит одно физическое соединение — см.
    conftest.py), поэтому здесь проверяется то, что можно проверить синхронно: сам факт, что
    защитный SQL действительно содержит FOR UPDATE на диалекте, где это имеет эффект, и что
    инкремент счётчика — атомарный UPDATE, а не read-modify-write."""

    def test_lock_active_admins_compiles_with_for_update_on_postgres(self):
        from sqlalchemy import select
        from sqlalchemy.dialects import postgresql

        from app.constants import UserRole
        from app.models import User

        stmt = select(User).where(User.role == UserRole.ADMIN, User.is_active.is_(True)).with_for_update()
        compiled = str(stmt.compile(dialect=postgresql.dialect()))
        assert "FOR UPDATE" in compiled.upper()

    def test_failed_attempts_increment_is_a_single_atomic_update_not_read_modify_write(self, db_session):
        """Регрессионный тест на конкретный баг-класс: если кто-то в будущем вернёт
        `user.failed_attempts += 1; session.commit()`, этот тест не поймает саму гонку (нужен
        реальный параллелизм), но зафиксирует, что _increment_failed_attempts всё ещё существует
        и действительно выполняет UPDATE на уровне БД, а не полагается на объект user из другой
        сессии — та же ошибка класса, что была найдена и исправлена в change_own_password."""
        from app.services.auth import _increment_failed_attempts, create_user

        user = create_user(db_session, username="admin", password="Admin1234", role="admin")
        assert user.failed_attempts == 0

        new_value = _increment_failed_attempts(db_session, user.id)

        assert new_value == 1
        db_session.refresh(user)
        assert user.failed_attempts == 1


class TestSessionCleanup:
    def test_cleanup_expired_sessions_removes_only_expired_rows(self, db_session):
        from datetime import datetime, timedelta, timezone

        from app.models import AuthSession
        from app.services.auth import cleanup_expired_sessions, create_user

        user = create_user(db_session, username="admin", password="Admin1234", role="admin")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        db_session.add(AuthSession(token_hash="expired-1", user_id=user.id, expires_at=now - timedelta(hours=1)))
        db_session.add(AuthSession(token_hash="expired-2", user_id=user.id, expires_at=now - timedelta(minutes=1)))
        db_session.add(AuthSession(token_hash="still-valid", user_id=user.id, expires_at=now + timedelta(hours=1)))
        db_session.commit()

        removed = cleanup_expired_sessions(db_session)

        assert removed == 2
        remaining = db_session.query(AuthSession).all()
        assert [row.token_hash for row in remaining] == ["still-valid"]

    def test_new_login_opportunistically_sweeps_other_expired_sessions(self, db_session):
        """create_session (вызывается при каждом логине) сам подчищает чужие просроченные строки
        — не только "свою": см. docstring create_session про причину (без cron, безопасно на
        нескольких процессах, DELETE идемпотентен)."""
        from datetime import datetime, timedelta, timezone

        from app.models import AuthSession
        from app.services.auth import create_session, create_user

        user = create_user(db_session, username="admin", password="Admin1234", role="admin")
        stale = AuthSession(token_hash="stale", user_id=user.id, expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1))
        db_session.add(stale)
        db_session.commit()

        create_session(db_session, user)

        remaining_hashes = [row.token_hash for row in db_session.query(AuthSession).all()]
        assert "stale" not in remaining_hashes
