"""A-23 (вариант «разрешить», решение владельца продукта): POST-запросы, не меняющие реестр, доступны роли viewer.

`POST /reports/structural-appendix` только формирует файл (как `/reports/inventory`), а `POST /port-sync/preview` по докстрингу
«ничего не записывает». Остальные POST и подобные пути у viewer по-прежнему закрыты (403)."""
from __future__ import annotations


def _admin_and_viewer(client) -> tuple[dict, dict]:
    assert client.post("/api/v1/auth/users", json={"username": "admin", "password": "Admin1234", "role": "admin"}).status_code == 201
    assert client.put("/api/v1/auth/settings", json={"enabled": True}).status_code == 200
    admin = _headers(client, "admin", "Admin1234")
    assert client.post("/api/v1/auth/users", json={"username": "viewer1", "password": "Viewer1234", "role": "viewer"}, headers=admin).status_code == 201
    return admin, _headers(client, "viewer1", "Viewer1234")


def _headers(client, username: str, password: str) -> dict:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_viewer_can_build_the_structural_appendix(client):
    admin, viewer = _admin_and_viewer(client)
    for headers in (admin, viewer):
        response = client.post("/api/v1/reports/structural-appendix", json={}, headers=headers)
        assert response.status_code == 200, response.text
        assert response.json()["file_name"].endswith(".docx")


def test_viewer_can_preview_port_sync_without_writing(client):
    admin, viewer = _admin_and_viewer(client)
    for headers in (admin, viewer):
        assert client.post("/api/v1/port-sync/preview", json={}, headers=headers).status_code == 200


def test_viewer_still_cannot_apply_port_sync_or_change_rules(client):
    _admin, viewer = _admin_and_viewer(client)
    assert client.post("/api/v1/port-sync/apply", json={}, headers=viewer).status_code == 403
    assert client.post("/api/v1/port-sync/preview/extra", json={}, headers=viewer).status_code == 403
    assert client.post("/api/v1/reports/structural-appendix/extra", headers=viewer).status_code == 403


def test_anonymous_still_needs_a_token(client):
    _admin_and_viewer(client)
    assert client.post("/api/v1/reports/structural-appendix", json={}).status_code == 401
    assert client.post("/api/v1/port-sync/preview", json={}).status_code == 401
