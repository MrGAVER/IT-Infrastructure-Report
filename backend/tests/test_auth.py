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

    def test_account_locks_after_max_failed_attempts(self, client):
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
