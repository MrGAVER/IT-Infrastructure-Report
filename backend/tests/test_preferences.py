"""Тесты серверных настроек интерфейса (app/services/preferences.py, app/api/preferences.py).

Каждый тест получает изолированную in-memory БД (фикстуры client/db_session из conftest.py), поэтому
аутентификация стартует выключенной: личных настроек на сервере тогда нет (их хранит браузер), а общие
(название организации) работают. Личные настройки проверяются с включённой аутентификацией.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.models import AppPreference, AuditLog, User
from app.services.preferences import require_global_write


def _bootstrap_admin(client) -> str:
    r = client.post("/api/v1/auth/users", json={"username": "admin", "password": "Admin1234", "role": "admin"})
    assert r.status_code == 201, r.text
    assert client.put("/api/v1/auth/settings", json={"enabled": True}).status_code == 200
    return _login(client, "admin", "Admin1234")


def _login(client, username: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _add_viewer(client, admin_token: str, username: str = "viewer1") -> str:
    r = client.post("/api/v1/auth/users", json={"username": username, "password": "Viewer1234", "role": "viewer"}, headers=_headers(admin_token))
    assert r.status_code == 201, r.text
    return _login(client, username, "Viewer1234")


class TestWithoutAuthentication:
    """Аутентификация выключена: пользователей нет, личные настройки хранит браузер, общие — сервер."""

    def test_empty_by_default(self, client):
        r = client.get("/api/v1/preferences")
        assert r.status_code == 200
        assert r.json() == {"global": {}, "user": {}}

    def test_personal_settings_are_not_stored_on_the_server(self, client, db_session):
        r = client.put("/api/v1/preferences/user", json={"color_scheme": "indigo"})
        assert r.status_code == 400
        assert "только для учётных записей" in r.json()["detail"]
        assert db_session.query(AppPreference).count() == 0

    def test_rows_left_by_the_old_anonymous_owner_are_ignored(self, client, db_session):
        db_session.add(AppPreference(owner="anonymous", key="color_scheme", value='"indigo"'))
        db_session.commit()
        assert client.get("/api/v1/preferences").json()["user"] == {}

    def test_global_organization_name_can_be_changed_without_authentication(self, client):
        r = client.put("/api/v1/preferences/global", json={"organization_name": "  ООО «Ромашка»  "})
        assert r.status_code == 200, r.text
        assert r.json()["global"] == {"organization_name": "ООО «Ромашка»"}
        assert client.get("/api/v1/preferences").json()["global"] == {"organization_name": "ООО «Ромашка»"}


class TestPersonalSettings:
    """Личные настройки пользователя с включённой аутентификацией."""

    def test_saved_values_come_back_and_survive_a_new_request(self, client):
        h = _headers(_bootstrap_admin(client))
        r = client.put("/api/v1/preferences/user", json={"color_scheme": "indigo", "device_vlan_collapse_rows": 25}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["user"] == {"color_scheme": "indigo", "device_vlan_collapse_rows": 25}
        assert client.get("/api/v1/preferences", headers=h).json()["user"] == {"color_scheme": "indigo", "device_vlan_collapse_rows": 25}

    def test_omitted_field_is_untouched_and_null_resets_it(self, client):
        h = _headers(_bootstrap_admin(client))
        client.put("/api/v1/preferences/user", json={"color_scheme": "copper", "device_vlan_collapse_rows": 5}, headers=h)
        client.put("/api/v1/preferences/user", json={"device_vlan_collapse_rows": 7}, headers=h)
        assert client.get("/api/v1/preferences", headers=h).json()["user"] == {"color_scheme": "copper", "device_vlan_collapse_rows": 7}

        client.put("/api/v1/preferences/user", json={"color_scheme": None}, headers=h)
        assert client.get("/api/v1/preferences", headers=h).json()["user"] == {"device_vlan_collapse_rows": 7}


class TestPageSizesMerge:
    def test_page_sizes_are_merged_per_list_not_replaced(self, client):
        h = _headers(_bootstrap_admin(client))
        client.put("/api/v1/preferences/user", json={"page_sizes": {"devices": 50}}, headers=h)
        client.put("/api/v1/preferences/user", json={"page_sizes": {"vms": 100}}, headers=h)
        assert client.get("/api/v1/preferences", headers=h).json()["user"]["page_sizes"] == {"devices": 50, "vms": 100}

    def test_null_removes_one_list_and_the_last_removal_drops_the_key(self, client):
        h = _headers(_bootstrap_admin(client))
        client.put("/api/v1/preferences/user", json={"page_sizes": {"devices": 50, "vms": 100}}, headers=h)
        client.put("/api/v1/preferences/user", json={"page_sizes": {"devices": None}}, headers=h)
        assert client.get("/api/v1/preferences", headers=h).json()["user"]["page_sizes"] == {"vms": 100}
        client.put("/api/v1/preferences/user", json={"page_sizes": {"vms": None}}, headers=h)
        assert "page_sizes" not in client.get("/api/v1/preferences", headers=h).json()["user"]

    def test_too_many_lists_are_rejected_without_partial_write(self, client):
        h = _headers(_bootstrap_admin(client))
        client.put("/api/v1/preferences/user", json={"page_sizes": {f"l{i}": 10 for i in range(100)}}, headers=h)
        r = client.put("/api/v1/preferences/user", json={"page_sizes": {"one-more": 10}}, headers=h)
        assert r.status_code == 422
        assert len(client.get("/api/v1/preferences", headers=h).json()["user"]["page_sizes"]) == 100


class TestValidation:
    def test_unknown_key_is_rejected(self, client):
        h = _headers(_bootstrap_admin(client))
        assert client.put("/api/v1/preferences/user", json={"favorite_color": "red"}, headers=h).status_code == 422
        assert client.put("/api/v1/preferences/global", json={"color_scheme": "teal"}, headers=h).status_code == 422

    def test_out_of_range_and_malformed_values_are_rejected(self, client):
        h = _headers(_bootstrap_admin(client))
        for body in (
            {"device_vlan_collapse_rows": 0},
            {"device_vlan_collapse_rows": 1001},
            {"device_vlan_collapse_rows": "много"},
            {"color_scheme": "Teal Dark"},
            {"page_sizes": {"devices": 0}},
            {"page_sizes": {"devices": 1001}},
            {"page_sizes": {"bad id!": 10}},
        ):
            assert client.put("/api/v1/preferences/user", json=body, headers=h).status_code == 422, body
        assert client.get("/api/v1/preferences", headers=h).json()["user"] == {}

    def test_blank_organization_name_is_rejected_but_null_resets_it(self, client):
        client.put("/api/v1/preferences/global", json={"organization_name": "ООО «Х»"})
        assert client.put("/api/v1/preferences/global", json={"organization_name": "   "}).status_code == 422
        client.put("/api/v1/preferences/global", json={"organization_name": None})
        assert client.get("/api/v1/preferences").json()["global"] == {}

    def test_corrupted_stored_value_is_skipped_instead_of_failing_the_request(self, client, db_session):
        h = _headers(_bootstrap_admin(client))
        me = client.get("/api/v1/auth/me", headers=h).json()["user"]["id"]
        db_session.add(AppPreference(owner=f"user:{me}", key="color_scheme", value="{не json"))
        db_session.add(AppPreference(owner=f"user:{me}", key="device_vlan_collapse_rows", value="12"))
        db_session.commit()
        r = client.get("/api/v1/preferences", headers=h)
        assert r.status_code == 200
        assert r.json()["user"] == {"device_vlan_collapse_rows": 12}


class TestAuthenticatedMode:
    def test_requires_a_token(self, client):
        _bootstrap_admin(client)
        assert client.get("/api/v1/preferences").status_code == 401
        assert client.put("/api/v1/preferences/user", json={"color_scheme": "teal"}).status_code == 401

    def test_personal_settings_are_isolated_between_users(self, client):
        admin = _bootstrap_admin(client)
        viewer = _add_viewer(client, admin)
        client.put("/api/v1/preferences/user", json={"color_scheme": "copper", "page_sizes": {"devices": 50}}, headers=_headers(admin))
        client.put("/api/v1/preferences/user", json={"color_scheme": "indigo"}, headers=_headers(viewer))

        assert client.get("/api/v1/preferences", headers=_headers(admin)).json()["user"] == {"color_scheme": "copper", "page_sizes": {"devices": 50}}
        assert client.get("/api/v1/preferences", headers=_headers(viewer)).json()["user"] == {"color_scheme": "indigo"}

    def test_viewer_can_change_own_personal_settings(self, client):
        admin = _bootstrap_admin(client)
        viewer = _add_viewer(client, admin)
        r = client.put("/api/v1/preferences/user", json={"device_vlan_collapse_rows": 30}, headers=_headers(viewer))
        assert r.status_code == 200, r.text
        assert r.json()["user"] == {"device_vlan_collapse_rows": 30}

    def test_viewer_cannot_change_global_settings_but_admin_can_and_everyone_sees_them(self, client):
        admin = _bootstrap_admin(client)
        viewer = _add_viewer(client, admin)
        denied = client.put("/api/v1/preferences/global", json={"organization_name": "Чужое"}, headers=_headers(viewer))
        assert denied.status_code == 403

        ok = client.put("/api/v1/preferences/global", json={"organization_name": "ООО «Ромашка»"}, headers=_headers(admin))
        assert ok.status_code == 200, ok.text
        for token in (admin, viewer):
            assert client.get("/api/v1/preferences", headers=_headers(token)).json()["global"] == {"organization_name": "ООО «Ромашка»"}

    def test_global_change_is_written_to_the_audit_log_with_the_author(self, client, db_session):
        admin = _bootstrap_admin(client)
        client.put("/api/v1/preferences/global", json={"organization_name": "ООО «Ромашка»"}, headers=_headers(admin))
        entry = db_session.query(AuditLog).filter(AuditLog.entity_type == "preferences").one()
        assert "ООО «Ромашка»" in entry.details
        assert entry.actor_username == "admin"

    def test_deleting_a_user_removes_their_personal_settings_only(self, client, db_session):
        admin = _bootstrap_admin(client)
        viewer = _add_viewer(client, admin)
        client.put("/api/v1/preferences/user", json={"color_scheme": "indigo"}, headers=_headers(viewer))
        client.put("/api/v1/preferences/user", json={"color_scheme": "copper"}, headers=_headers(admin))
        viewer_id = next(u["id"] for u in client.get("/api/v1/auth/users", headers=_headers(admin)).json() if u["username"] == "viewer1")

        assert client.delete(f"/api/v1/auth/users/{viewer_id}", headers=_headers(admin)).status_code in (200, 204)

        owners = {row.owner for row in db_session.query(AppPreference).all()}
        assert f"user:{viewer_id}" not in owners
        assert len(owners) == 1  # настройки администратора на месте


class TestRequireGlobalWrite:
    """Проверка прав в сервисе — вторая линия защиты за middleware (тот и так не пускает viewer на PUT /global,
    поэтому через HTTP она не проверяется: её нужно проверять напрямую, иначе она может сломаться незамеченной)."""

    @staticmethod
    def _user(role: str) -> User:
        return User(id="u-1", username="someone", password_hash="x", role=role)

    def test_without_authentication_anyone_may_write(self):
        require_global_write(auth_enabled=False, user=None)

    def test_administrator_may_write(self):
        require_global_write(auth_enabled=True, user=self._user("admin"))

    @pytest.mark.parametrize("user", [None, "viewer"])
    def test_viewer_and_missing_user_are_rejected_with_403(self, user):
        with pytest.raises(HTTPException) as caught:
            require_global_write(auth_enabled=True, user=self._user(user) if user else None)
        assert caught.value.status_code == 403
