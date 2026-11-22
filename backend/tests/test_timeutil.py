"""A-06: единый формат времени — в БД naive UTC, в API ISO 8601 с явным «+00:00».

Раньше созданная в этом запросе запись отдавалась как `…+00:00`, а та же запись при чтении — без смещения, и браузер
показывал журнал аудита, «последний вход» и сессии со сдвигом на часовой пояс пользователя (см. services/timeutil.py).

Запуск: pytest backend/tests/test_timeutil.py -v
PostgreSQL-часть: INFRA_REGISTRY_TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/infra_test pytest backend/tests/test_timeutil.py
"""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.services.timeutil import iso_utc, to_naive_utc, utcnow_naive
from test_auth import _auth_headers, _bootstrap_admin, _login

API = "/api/v1"
UTC_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{6})?\+00:00$")


def _assert_utc_iso(value, field="значение"):
    assert isinstance(value, str) and UTC_ISO.match(value), f"{field}: {value!r} — ожидается ISO 8601 с «+00:00»"


# ---------------------------------------------------------------------------------------------------------------------
# Функции
# ---------------------------------------------------------------------------------------------------------------------
def test_iso_utc_marks_naive_values_as_utc():
    assert iso_utc(datetime(2026, 10, 19, 18, 8, 54, 336386)) == "2026-10-19T18:08:54.336386+00:00"


def test_iso_utc_keeps_utc_values_unchanged():
    assert iso_utc(datetime(2026, 10, 19, 18, 9, 18, 219136, tzinfo=timezone.utc)) == "2026-10-19T18:09:18.219136+00:00"


def test_iso_utc_converts_other_offsets_to_utc():
    minsk = timezone(timedelta(hours=3))
    assert iso_utc(datetime(2026, 10, 19, 21, 0, 0, tzinfo=minsk)) == "2026-10-19T18:00:00+00:00"


def test_iso_utc_leaves_dates_without_time_alone():
    assert iso_utc(date(2026, 10, 19)) == "2026-10-19"


@pytest.mark.parametrize("value", [None, "text", 5, 1.5, True, ["x"], {"a": 1}])
def test_iso_utc_passes_other_values_through(value):
    assert iso_utc(value) == value


def test_naive_and_aware_forms_of_the_same_moment_serialize_identically():
    naive = datetime(2026, 1, 2, 3, 4, 5, 6)
    assert iso_utc(naive) == iso_utc(naive.replace(tzinfo=timezone.utc))


def test_utcnow_naive_is_naive_and_close_to_utc_now():
    value = utcnow_naive()
    assert value.tzinfo is None
    assert abs(value - datetime.now(timezone.utc).replace(tzinfo=None)) < timedelta(seconds=5)


def test_to_naive_utc():
    minsk = timezone(timedelta(hours=3))
    assert to_naive_utc(datetime(2026, 10, 19, 21, 0, tzinfo=minsk)) == datetime(2026, 10, 19, 18, 0)
    already_naive = datetime(2026, 10, 19, 18, 0)
    assert to_naive_utc(already_naive) is already_naive


# ---------------------------------------------------------------------------------------------------------------------
# Модели: в БД не попадают aware-значения
# ---------------------------------------------------------------------------------------------------------------------
def test_models_do_not_use_aware_defaults():
    source = (Path(__file__).resolve().parent.parent / "app" / "models.py").read_text(encoding="utf-8")
    assert "datetime.now(timezone.utc)" not in source, "значения по умолчанию колонок DateTime — только utcnow_naive"


def test_model_defaults_are_naive_before_and_after_reading_back(db_session):
    from app.models import AuthSettings, DeviceCategory

    category = DeviceCategory(name="Категория А-06 naive")
    db_session.add(category)
    db_session.flush()
    assert category.created_at.tzinfo is None and category.updated_at.tzinfo is None, "до чтения из БД"
    db_session.commit()
    db_session.expire_all()
    assert category.created_at.tzinfo is None and category.updated_at.tzinfo is None, "после чтения из БД"

    settings = db_session.get(AuthSettings, "singleton") or AuthSettings(id="singleton", enabled=False)
    db_session.add(settings)
    db_session.commit()
    assert settings.updated_at.tzinfo is None


def test_updated_at_is_refreshed_on_update_with_naive_value(db_session):
    from app.models import DeviceCategory

    category = DeviceCategory(name="Категория А-06 onupdate")
    db_session.add(category)
    db_session.commit()
    category.updated_at = datetime(2000, 1, 1)
    db_session.commit()
    category.description = "изменено"
    db_session.commit()
    db_session.expire_all()
    assert category.updated_at.tzinfo is None
    assert category.updated_at > datetime(2020, 1, 1)


# ---------------------------------------------------------------------------------------------------------------------
# API: и при создании, и при чтении — одинаковый формат
# ---------------------------------------------------------------------------------------------------------------------
def test_generic_resource_has_same_format_on_create_read_list_and_update(client):
    created = client.post(f"{API}/resources/device-categories", json={"name": "Категория А-06"})
    assert created.status_code == 201, created.text
    body = created.json()
    for field in ("created_at", "updated_at"):
        _assert_utc_iso(body[field], f"POST {field}")

    fetched = client.get(f"{API}/resources/device-categories/{body['id']}").json()
    for field in ("created_at", "updated_at"):
        _assert_utc_iso(fetched[field], f"GET {field}")
    assert fetched["created_at"] == body["created_at"], "одно и то же значение при создании и при чтении"

    listed = next(i for i in client.get(f"{API}/resources/device-categories", params={"limit": 500}).json()["items"] if i["id"] == body["id"])
    _assert_utc_iso(listed["created_at"], "list created_at")

    updated = client.put(f"{API}/resources/device-categories/{body['id']}", json={"name": "Категория А-06", "description": "после правки"}).json()
    _assert_utc_iso(updated["updated_at"], "PUT updated_at")


def test_audit_log_entries_carry_the_offset(client):
    client.post(f"{API}/resources/manufacturers", json={"name": "Производитель А-06"})
    items = client.get(f"{API}/resources/audit-log", params={"limit": 5}).json()["items"]
    assert items
    for item in items:
        _assert_utc_iso(item["created_at"], "audit-log created_at")


def test_date_only_columns_are_not_changed():
    from app.models import DeviceCategory, PhysicalDevice
    from app.services.serialization import serialize

    device = PhysicalDevice(oac_certificate_registry_date=date(2026, 10, 19))
    assert serialize(device)["oac_certificate_registry_date"] == "2026-10-19", "поле-дата остаётся «YYYY-MM-DD»"
    category = DeviceCategory(name="x", created_at=datetime(2026, 10, 19, 18, 0))
    assert serialize(category)["created_at"] == "2026-10-19T18:00:00+00:00"


def test_diagram_has_same_format_on_create_and_read(client):
    created = client.post(f"{API}/diagrams", json={"name": "Диаграмма А-06"}).json()
    _assert_utc_iso(created["created_at"], "POST created_at")
    detail = client.get(f"{API}/diagrams/{created['id']}").json()
    _assert_utc_iso(detail["created_at"], "GET created_at")
    _assert_utc_iso(detail["updated_at"], "GET updated_at")
    assert detail["created_at"] == created["created_at"]
    assert all(UTC_ISO.match(d["created_at"]) for d in client.get(f"{API}/diagrams").json())


def test_report_template_and_versions_carry_the_offset(client):
    config = {
        "sheets": [
            {
                "title": "Лист1",
                "columns": [{"width": 25}],
                "rows": [{"height": 18, "repeat": True, "data_source": {"root_entity": "information-systems"}, "cells": [{"col": 0, "kind": "field", "path": "name"}]}],
            }
        ]
    }
    created = client.post(f"{API}/report-templates", json={"name": "Шаблон А-06", "config": config})
    assert created.status_code == 201, created.text
    template = created.json()
    for field in ("created_at", "updated_at"):
        _assert_utc_iso(template[field], f"template {field}")
    client.put(f"{API}/report-templates/{template['id']}", json={"name": "Шаблон А-06", "config": config, "description": "v2"})
    for version in client.get(f"{API}/report-templates/{template['id']}/versions").json():
        _assert_utc_iso(version["created_at"], "version created_at")
    for item in client.get(f"{API}/report-templates").json():
        if item["id"] == template["id"]:
            _assert_utc_iso(item["updated_at"], "list updated_at")


def test_port_sync_rules_carry_the_offset(client):
    rules = client.get(f"{API}/port-sync/rules").json()["items"]
    assert rules
    for rule in rules:
        _assert_utc_iso(rule["created_at"], "rule created_at")
        _assert_utc_iso(rule["updated_at"], "rule updated_at")


# ---------------------------------------------------------------------------------------------------------------------
# Аутентификация: пользователи и сессии
# ---------------------------------------------------------------------------------------------------------------------
def test_serialize_user_and_session_use_the_offset(db_session):
    from app.models import AuthSession, User
    from app.services.auth import serialize_session, serialize_user

    user = User(username="a06", password_hash="x", role="viewer", is_active=True)
    user.last_login_at = datetime(2026, 10, 19, 18, 8, 54, 336386)  # naive UTC — как возвращает БД
    user.created_at = datetime(2026, 10, 19, 18, 0, 0)
    assert serialize_user(user)["last_login_at"] == "2026-10-19T18:08:54.336386+00:00"
    assert serialize_user(user)["created_at"] == "2026-10-19T18:00:00+00:00"
    user.last_login_at = None
    assert serialize_user(user)["last_login_at"] is None

    session_row = AuthSession(token_hash="h", user_id="u", created_at=datetime(2026, 10, 19, 18, 0), expires_at=datetime(2026, 10, 20, 6, 0))
    out = serialize_session(session_row)
    assert out["created_at"] == "2026-10-19T18:00:00+00:00"
    assert out["expires_at"] == "2026-10-20T06:00:00+00:00"


def test_users_and_sessions_endpoints_carry_the_offset(client):
    _bootstrap_admin(client)
    token = _login(client, "admin", "Admin1234")
    headers = _auth_headers(token)

    users = client.get(f"{API}/auth/users", headers=headers).json()
    admin = next(u for u in users if u["username"] == "admin")
    _assert_utc_iso(admin["last_login_at"], "last_login_at")
    _assert_utc_iso(admin["created_at"], "user created_at")

    sessions = client.get(f"{API}/auth/sessions", headers=headers).json()
    assert sessions
    for row in sessions:
        _assert_utc_iso(row["created_at"], "session created_at")
        _assert_utc_iso(row["expires_at"], "session expires_at")


def test_session_expiry_still_works_with_naive_time(client, db_session):
    """Сравнение сроков идёт в naive UTC: просроченная сессия отклоняется, действующая — принимается."""
    from app.models import AuthSession

    _bootstrap_admin(client)
    token = _login(client, "admin", "Admin1234")
    assert client.get(f"{API}/resources/manufacturers", headers=_auth_headers(token)).status_code == 200
    row = db_session.query(AuthSession).one()
    row.expires_at = utcnow_naive() - timedelta(minutes=1)
    db_session.commit()
    assert client.get(f"{API}/resources/manufacturers", headers=_auth_headers(token)).status_code == 401


# ---------------------------------------------------------------------------------------------------------------------
# Фильтр по периоду: время со смещением приводится к UTC
# ---------------------------------------------------------------------------------------------------------------------
def test_range_filter_accepts_values_with_offset_and_without(client, db_session):
    from app.models import AuditLog
    from app.services.crud.generic import _parse_range_datetime

    assert _parse_range_datetime("2026-10-19", end_of_day=False) == datetime(2026, 10, 19)
    assert _parse_range_datetime("2026-10-19", end_of_day=True) == datetime(2026, 10, 19, 23, 59, 59, 999999)
    assert _parse_range_datetime("2026-10-19T18:00:00", end_of_day=False) == datetime(2026, 10, 19, 18, 0)
    assert _parse_range_datetime("2026-10-19T21:00:00+03:00", end_of_day=False) == datetime(2026, 10, 19, 18, 0)
    assert _parse_range_datetime("2026-10-19T18:00:00+00:00", end_of_day=False) == datetime(2026, 10, 19, 18, 0)

    client.post(f"{API}/resources/manufacturers", json={"name": "Производитель А-06 фильтр"})
    entry = db_session.query(AuditLog).order_by(AuditLog.created_at.desc()).first()
    sent_back = iso_utc(entry.created_at)  # то, что клиент получил из API
    items = client.get(f"{API}/resources/audit-log", params={"date_from": sent_back, "limit": 50}).json()["items"]
    assert entry.id in {i["id"] for i in items}, "значение из ответа API, отправленное обратно как граница периода, находит запись"
    later = iso_utc(entry.created_at + timedelta(seconds=5))
    assert entry.id not in {i["id"] for i in client.get(f"{API}/resources/audit-log", params={"date_from": later, "limit": 50}).json()["items"]}


# ---------------------------------------------------------------------------------------------------------------------
# PostgreSQL: сессия БД в UTC
# ---------------------------------------------------------------------------------------------------------------------
def test_engine_connect_args_per_dialect():
    from app.db import engine_connect_args

    assert engine_connect_args("sqlite:///x.db") == {"check_same_thread": False}
    assert engine_connect_args("postgresql+psycopg://u:p@h/db") == {"options": "-c timezone=UTC"}
    assert engine_connect_args("mysql://u:p@h/db") == {}


@pytest.mark.postgres_only
def test_postgres_session_timezone_is_utc_even_when_server_default_differs():
    import sqlalchemy as sa

    from app.db import engine_connect_args

    url = os.environ["INFRA_REGISTRY_TEST_DATABASE_URL"]
    engine = sa.create_engine(url, connect_args=engine_connect_args(url), future=True)
    try:
        with engine.connect() as connection:
            assert connection.execute(sa.text("SHOW timezone")).scalar() == "UTC"
            # серверное «сейчас» в сессии — UTC: совпадает с utcnow_naive() с точностью до секунд
            server_now = connection.execute(sa.text("SELECT CURRENT_TIMESTAMP AT TIME ZONE 'UTC'")).scalar()
            session_now = connection.execute(sa.text("SELECT LOCALTIMESTAMP")).scalar()
        assert abs(server_now - session_now) < timedelta(seconds=2)
        assert abs(session_now - utcnow_naive()) < timedelta(seconds=10)
    finally:
        engine.dispose()
