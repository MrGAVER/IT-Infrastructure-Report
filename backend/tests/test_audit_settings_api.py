"""
Настройки аудита по HTTP, A-05 код-ревью main @ b375f58: GET/PUT /api/v1/audit-log/settings, разграничение прав и ленивый запуск
очистки при открытии журнала.

Права: при включённой аутентификации настройки (как и сам журнал) — только администратору, viewer получает 403 и на чтение, и на
запись, без токена — 401; пока аутентификация выключена, пользователь один и настройки открыты (как журнал). Доступ задан на весь
роутер журнала, поэтому ниже
проверяются все его маршруты.

Запуск: pytest backend/tests/test_audit_settings_api.py -v
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import AuditLog, AuditSettings
from app.services.timeutil import utcnow_naive
from test_resources_access import _enable_auth_with_viewer, _headers

URL = "/api/v1/audit-log/settings"
LOG_URL = "/api/v1/audit-log"


def _seed_old(session, count: int, *, days: int = 400) -> None:
    now = utcnow_naive()
    session.add_all(
        AuditLog(
            entity_type="devices",
            entity_id=f"old-{index}",
            action="UPDATE",
            details=f"старая {index}",
            created_at=now - timedelta(days=days, minutes=index),
        )
        for index in range(count)
    )
    session.commit()


def _device_entries(session) -> int:
    return len(session.scalars(select(AuditLog.id).where(AuditLog.entity_type == "devices")).all())


def _service_entries(client, headers: dict | None = None) -> list[dict]:
    page = client.get(LOG_URL, params={"entity_type": "audit-settings", "limit": 200}, headers=headers)
    assert page.status_code == 200, page.text
    return page.json()["items"]


class TestResponseContract:
    """У ответов настроек есть схема (response_model), а форма JSON побайтно прежняя — на неё опирается фронтенд (api/types/audit.ts)."""

    def test_get_response_is_byte_for_byte_the_documented_shape(self, client):
        response = client.get(URL)

        expected = '{"retention_days":0,"is_default":true,"default_retention_days":0,"max_retention_days":3650,"last_cleanup_at":null}'
        assert response.text == expected

    def test_put_response_keeps_the_field_order_and_adds_the_cleanup_result_last(self, client):
        response = client.put(URL, json={"retention_days": 90})

        assert list(response.json()) == [
            "retention_days",
            "is_default",
            "default_retention_days",
            "max_retention_days",
            "last_cleanup_at",
            "removed_now",
            "cleanup_failed",
        ]

    def test_put_without_a_period_answers_like_get_without_the_cleanup_result(self, client):
        client.put(URL, json={"retention_days": 90})

        response = client.put(URL, json={})

        # срока в теле нет — сохранять нечего: ответ как у GET, без removed_now и cleanup_failed
        assert response.text == client.get(URL).text

    def test_the_contract_is_described_in_openapi(self, client):
        from app.main import app

        paths = app.openapi()["paths"]["/api/v1/audit-log/settings"]
        responses = {method: paths[method]["responses"]["200"] for method in ("get", "put")}
        refs = {method: found["content"]["application/json"]["schema"].get("$ref", "") for method, found in responses.items()}

        assert refs == {"get": "#/components/schemas/AuditSettingsOut", "put": "#/components/schemas/AuditSettingsSaveOut"}


class TestReadAndWrite:
    def test_defaults_do_not_delete_anything(self, client):
        response = client.get(URL)

        assert response.status_code == 200
        assert response.json() == {
            "retention_days": 0,
            "is_default": True,
            "default_retention_days": 0,
            "max_retention_days": 3650,
            "last_cleanup_at": None,
        }

    def test_saved_period_is_returned_and_remembered(self, client):
        response = client.put(URL, json={"retention_days": 90})

        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["retention_days"], body["is_default"], body["removed_now"], body["cleanup_failed"]) == (90, False, 0, False)
        assert client.get(URL).json()["retention_days"] == 90

    def test_saving_removes_old_entries_at_once_and_reports_how_many(self, client, db_session):
        _seed_old(db_session, 7)

        body = client.put(URL, json={"retention_days": 30}).json()

        assert body["removed_now"] == 7
        assert body["last_cleanup_at"] is not None
        assert _device_entries(db_session) == 0

    def test_the_change_and_the_cleanup_are_visible_in_the_log(self, client, db_session):
        _seed_old(db_session, 2)
        client.put(URL, json={"retention_days": 30})

        details = sorted(entry["details"] for entry in _service_entries(client))

        assert details == sorted(
            [
                "Срок хранения журнала аудита: не ограничен → 30 дн.",
                next(text for text in details if text.startswith("Очистка журнала по сроку хранения (30 дн.): удалено записей — 2")),
            ]
        )

    def test_null_resets_to_the_default_and_a_missing_field_changes_nothing(self, client):
        client.put(URL, json={"retention_days": 90})

        assert client.put(URL, json={}).json()["retention_days"] == 90
        reset = client.put(URL, json={"retention_days": None})

        assert reset.status_code == 200
        assert (reset.json()["retention_days"], reset.json()["is_default"]) == (0, True)

    @pytest.mark.parametrize("days", [0, 1, 3650])
    def test_boundary_values_are_accepted(self, client, days):
        assert client.put(URL, json={"retention_days": days}).json()["retention_days"] == days

    @pytest.mark.parametrize(
        "payload",
        [
            {"retention_days": -1},
            {"retention_days": 3651},
            {"retention_days": "30"},
            {"retention_days": 30.5},
            {"retention_days": True},
            {"retention_days": [30]},
            {"retention": 30},
        ],
    )
    def test_invalid_values_are_rejected_and_nothing_changes(self, client, db_session, payload):
        _seed_old(db_session, 3)
        client.put(URL, json={"retention_days": 0})

        response = client.put(URL, json=payload)

        assert response.status_code == 422, response.text
        assert client.get(URL).json()["retention_days"] == 0
        assert _device_entries(db_session) == 3, "при отказе ничего не удалено"


class TestAccessRights:
    ROUTES = [("GET", LOG_URL), ("GET", URL), ("PUT", URL)]

    @staticmethod
    def _call(client, method: str, url: str, headers: dict | None = None):
        return client.request(method, url, json={"retention_days": 1} if method == "PUT" else None, headers=headers)

    @pytest.mark.parametrize(("method", "url"), ROUTES)
    def test_anonymous_gets_401_once_authentication_is_enabled(self, client, method, url):
        _enable_auth_with_viewer(client)

        assert self._call(client, method, url).status_code == 401

    @pytest.mark.parametrize(("method", "url"), ROUTES)
    def test_viewer_gets_403_on_every_route_of_the_audit_router(self, client, method, url):
        _admin_token, viewer_token = _enable_auth_with_viewer(client)

        assert self._call(client, method, url, _headers(viewer_token)).status_code == 403

    def test_viewer_cannot_change_the_period_or_trigger_a_purge(self, client, db_session):
        admin_token, viewer_token = _enable_auth_with_viewer(client)
        _seed_old(db_session, 4)

        assert client.put(URL, json={"retention_days": 1}, headers=_headers(viewer_token)).status_code == 403

        assert client.get(URL, headers=_headers(admin_token)).json()["retention_days"] == 0
        assert _device_entries(db_session) == 4
        assert db_session.get(AuditSettings, "singleton") is None, "отказ не оставил следов в настройках"

    def test_admin_reads_and_changes_the_settings_and_is_named_in_the_log(self, client):
        admin_token, _viewer_token = _enable_auth_with_viewer(client)
        headers = _headers(admin_token)

        assert client.get(URL, headers=headers).status_code == 200
        assert client.put(URL, json={"retention_days": 365}, headers=headers).json()["retention_days"] == 365

        (entry,) = _service_entries(client, headers)
        assert (entry["actor_username"], entry["details"]) == ("admin", "Срок хранения журнала аудита: не ограничен → 365 дн.")

    def test_without_authentication_the_settings_are_open_like_the_log(self, client):
        assert client.get(URL).status_code == 200
        assert client.put(URL, json={"retention_days": 30}).status_code == 200


class TestCleanupOnOpeningTheLog:
    def test_opening_the_log_runs_a_due_cleanup_after_the_response_in_the_name_of_the_system(self, client, db_session):
        _seed_old(db_session, 5)
        db_session.add(AuditSettings(id="singleton", retention_days=30))
        db_session.commit()

        client.get(LOG_URL, params={"limit": 200})  # страница читается до очистки; сама очистка идёт задачей после ответа
        page = client.get(LOG_URL, params={"limit": 200}).json()

        assert not [item for item in page["items"] if item["entity_type"] == "devices"], "просроченные записи удалены"
        (entry,) = [item for item in page["items"] if item["entity_type"] == "audit-settings"]
        assert entry["actor_username"] == "система" and "удалено записей — 5" in entry["details"]

    def test_the_page_is_read_before_the_cleanup_and_the_cleanup_is_only_queued(self, db_session, client_factory):
        """GET не удаляет данные внутри запроса: очистка ставится в фоновые задачи (после ответа, со своей сессией)."""
        from fastapi import BackgroundTasks

        from app.api.audit_log import audit_log_page

        _seed_old(db_session, 5)
        db_session.add(AuditSettings(id="singleton", retention_days=30))
        db_session.commit()
        background = BackgroundTasks()

        page = audit_log_page(q=None, action=None, entity_type=None, offset=0, limit=200, background=background, session=db_session)

        assert page["summary"]["total"] == 5 and _device_entries(db_session) == 5, "в самом запросе ничего не удалено"
        assert len(background.tasks) == 1
        task = background.tasks[0]
        task.func(*task.args, **task.kwargs)
        assert _device_entries(db_session) == 0

    def test_with_the_default_setting_opening_the_log_deletes_nothing(self, client, db_session):
        _seed_old(db_session, 5, days=5000)

        page = client.get(LOG_URL, params={"limit": 200}).json()

        assert page["summary"]["total"] == 5
        assert db_session.get(AuditSettings, "singleton") is None

    def test_a_viewer_opening_the_log_does_not_trigger_anything(self, client, db_session):
        _admin_token, viewer_token = _enable_auth_with_viewer(client)
        db_session.add(AuditSettings(id="singleton", retention_days=30))
        _seed_old(db_session, 3)

        assert client.get(LOG_URL, headers=_headers(viewer_token)).status_code == 403

        assert _device_entries(db_session) == 3, "проверка роли идёт раньше очистки"

    def test_the_server_starts_and_the_log_opens_when_the_period_overflows(self, client_factory, monkeypatch):
        """Срок из окружения вне допустимого диапазона не должен ронять ни запуск сервера (lifespan), ни чтение журнала."""
        from app.services import audit_retention

        monkeypatch.setattr(audit_retention, "AUDIT_RETENTION_DAYS", 10**6)

        client = client_factory()  # вход в lifespan: cleanup_audit_log_on_startup()

        assert client.get(LOG_URL).status_code == 200

    def test_the_server_start_runs_a_due_cleanup(self, db_session, client_factory):
        from app import main as app_main

        _seed_old(db_session, 3)
        db_session.add(AuditSettings(id="singleton", retention_days=30))
        db_session.commit()

        app_main.cleanup_audit_log_on_startup()

        assert _device_entries(db_session) == 0
