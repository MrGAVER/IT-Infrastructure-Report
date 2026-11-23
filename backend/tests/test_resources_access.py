"""Доступ к журналу аудита через generic-роутер ресурсов (api/resources.py, ревью 2.158.0, П-1).

Журнал аудита хранит имена пользователей, IP-адреса и неудачные попытки входа, поэтому при включённой
аутентификации он только для администратора (A-23). Выделенный роутер /api/v1/audit-log защищён зависимостью
`require_admin_if_auth_enabled`, но тот же журнал есть в MODEL_MAP и отдавался generic-роутером
/api/v1/resources/audit-log — без проверки роли. Тесты фиксируют, что обходного пути нет ни для списка,
ни для записи по id, ни для описания колонок, и что однопользовательский режим (аутентификация выключена)
и остальные ресурсы для viewer не затронуты.
"""

from __future__ import annotations

import pytest

ADMIN_PASSWORD = "Admin1234"
VIEWER_PASSWORD = "Viewer1234"


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _login(client, username: str, password: str) -> str:
    r = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _enable_auth_with_viewer(client) -> tuple[str, str]:
    """Включает аутентификацию, заводит администратора и viewer; возвращает (токен admin, токен viewer)."""
    r = client.post("/api/v1/auth/users", json={"username": "admin", "password": ADMIN_PASSWORD, "role": "admin"})
    assert r.status_code == 201, r.text
    r = client.put("/api/v1/auth/settings", json={"enabled": True})
    assert r.status_code == 200, r.text
    admin_token = _login(client, "admin", ADMIN_PASSWORD)
    r = client.post(
        "/api/v1/auth/users", json={"username": "viewer1", "password": VIEWER_PASSWORD, "role": "viewer"}, headers=_headers(admin_token)
    )
    assert r.status_code == 201, r.text
    return admin_token, _login(client, "viewer1", VIEWER_PASSWORD)


def _first_audit_entry_id(client, headers: dict | None = None) -> str:
    """id любой записи журнала — для проверки чтения по id (журнал не пуст: заведение пользователей уже в нём)."""
    r = client.get("/api/v1/audit-log", headers=headers or {})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "в журнале аудита должна быть хотя бы одна запись"
    return items[0]["id"]


def _audit_urls(entry_id: str) -> list[str]:
    return [
        "/api/v1/resources/audit-log",
        f"/api/v1/resources/audit-log/{entry_id}",
        "/api/v1/resources/audit-log/schema",
    ]


class TestAuditLogViaGenericRouter:
    def test_viewer_gets_403_on_every_generic_audit_log_route(self, client):
        admin_token, viewer_token = _enable_auth_with_viewer(client)
        entry_id = _first_audit_entry_id(client, _headers(admin_token))
        for url in _audit_urls(entry_id):
            r = client.get(url, headers=_headers(viewer_token))
            assert r.status_code == 403, f"{url}: {r.status_code} {r.text[:200]}"
            # В теле отказа не должно быть данных журнала — только текст ошибки.
            assert "items" not in r.json() and "columns" not in r.json()

    def test_viewer_is_still_denied_on_the_dedicated_audit_route(self, client):
        """Базовая линия: выделенный роутер уже защищён — тест защищает от случайной регрессии при правках."""
        _admin_token, viewer_token = _enable_auth_with_viewer(client)
        assert client.get("/api/v1/audit-log", headers=_headers(viewer_token)).status_code == 403

    def test_anonymous_gets_401_once_authentication_is_enabled(self, client):
        admin_token, _viewer_token = _enable_auth_with_viewer(client)
        entry_id = _first_audit_entry_id(client, _headers(admin_token))
        for url in _audit_urls(entry_id):
            assert client.get(url).status_code == 401, url

    def test_admin_reads_every_generic_audit_log_route(self, client):
        admin_token, _viewer_token = _enable_auth_with_viewer(client)
        entry_id = _first_audit_entry_id(client, _headers(admin_token))
        listing = client.get("/api/v1/resources/audit-log", headers=_headers(admin_token))
        assert listing.status_code == 200 and listing.json()["items"]
        record = client.get(f"/api/v1/resources/audit-log/{entry_id}", headers=_headers(admin_token))
        assert record.status_code == 200 and record.json()["id"] == entry_id
        schema = client.get("/api/v1/resources/audit-log/schema", headers=_headers(admin_token))
        assert schema.status_code == 200 and schema.json()["key"] == "audit-log"

    def test_single_user_mode_keeps_audit_log_open(self, client):
        """Аутентификация выключена (режим по умолчанию): журнал открыт, как и весь реестр."""
        assert client.post("/api/v1/resources/manufacturers", json={"name": "Для журнала"}).status_code == 201
        entry_id = _first_audit_entry_id(client)
        for url in _audit_urls(entry_id):
            assert client.get(url).status_code == 200, url

    def test_missing_audit_entry_is_404_for_admin_and_403_for_viewer(self, client):
        """Проверка роли идёт раньше поиска записи: viewer не может по коду ответа отличить «есть/нет» записи."""
        admin_token, viewer_token = _enable_auth_with_viewer(client)
        url = "/api/v1/resources/audit-log/no-such-entry"
        assert client.get(url, headers=_headers(admin_token)).status_code == 404
        assert client.get(url, headers=_headers(viewer_token)).status_code == 403


class TestOtherResourcesStayReadableForViewer:
    """Защита точечная: остальные ресурсы по-прежнему читает любая роль."""

    @pytest.mark.parametrize("suffix", ["", "/schema"])
    def test_viewer_reads_regular_resource(self, client, suffix):
        _admin_token, viewer_token = _enable_auth_with_viewer(client)
        r = client.get(f"/api/v1/resources/manufacturers{suffix}", headers=_headers(viewer_token))
        assert r.status_code == 200, r.text

    def test_resource_catalog_does_not_advertise_audit_log(self, client):
        _admin_token, viewer_token = _enable_auth_with_viewer(client)
        r = client.get("/api/v1/resources", headers=_headers(viewer_token))
        assert r.status_code == 200
        assert "audit-log" not in {item["key"] for item in r.json()}
