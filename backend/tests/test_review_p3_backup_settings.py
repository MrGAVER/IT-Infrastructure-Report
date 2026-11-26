"""Настройки плановых копий SQLite в дашборде «Настройки»: политика, API `/api/v1/backup/settings`, перезапуск планировщика.

Что проверяется:
- приоритет значений: окружение > сохранённое в «Настройках» > умолчание; испорченное значение в БД считается не заданным;
- запись: границы значений (422 с именем поля), параметр, заданный окружением, не меняется (409, ничего не сохраняется),
  PostgreSQL — 409, одинаковое значение — ни записи в журнал, ни перезапуска; изменение пишется в журнал аудита со старым и новым значением;
- применение без перезапуска приложения: планировщик отменяется и запускается заново с новой политикой, два перезапуска сразу не оставляют
  двух задач;
- доступ: при включённой аутентификации — только администратору (viewer — 403, аноним — 401);
- статус: последняя копия (имя, размер, время) и итог последней попытки.

Запуск: pytest backend/tests/test_review_p3_backup_settings.py -v
"""

from __future__ import annotations

import asyncio
import dataclasses
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app import config
from app.models import AppPreference, AuditLog
from app.services import backup_scheduler, backup_settings, db_backup
from app.services.backup_settings import BackupPolicy, SettingPinnedByEnvironment, load_policy, update_policy

URL = "/api/v1/backup/settings"
ADMIN_PASSWORD = "Admin1234"
VIEWER_PASSWORD = "Viewer1234"


def _patch_settings(monkeypatch, **changes) -> None:
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, **changes))


def _make_database(path: Path) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE devices (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO devices (name) VALUES ('srv-1')")
    connection.close()
    return path


@pytest.fixture()
def sqlite_setup(monkeypatch, tmp_path) -> dict:
    """Файловая SQLite-БД и каталог копий во временном каталоге; окружение копий не задано (все параметры — умолчания)."""
    database = _make_database(tmp_path / "infra_registry.db")
    backups = tmp_path / "backups"
    _patch_settings(
        monkeypatch,
        database_url=f"sqlite:///{database}",
        backup_dir=backups,
        backup_interval_hours=24.0,
        backup_keep=7,
        backup_from_env=frozenset(),
    )
    return {"database": database, "backups": backups}


def _stored(db_session) -> dict[str, str]:
    rows = db_session.scalars(select(AppPreference).where(AppPreference.key.like("backup.%"))).all()
    return {row.key: row.value for row in rows}


def _audit_details(db_session) -> list[str]:
    rows = db_session.scalars(
        select(AuditLog).where(AuditLog.entity_type == backup_settings.AUDIT_ENTITY).order_by(AuditLog.created_at)
    ).all()
    return [row.details for row in rows]


# ---------------------------------------------------------------------------
# Политика: приоритет источников
# ---------------------------------------------------------------------------
class TestPolicyPriority:
    def test_defaults_when_nothing_is_set(self, db_session, sqlite_setup):
        policy = load_policy(db_session)

        assert (policy.interval_hours, policy.keep) == (24.0, 7)
        assert (policy.interval_source, policy.keep_source, policy.directory_source) == ("default", "default", "default")
        assert policy.directory == sqlite_setup["backups"]

    def test_saved_values_beat_defaults(self, db_session, sqlite_setup):
        update_policy(db_session, {"interval_hours": 6, "keep": 14})

        policy = load_policy(db_session)

        assert (policy.interval_hours, policy.keep) == (6.0, 14)
        assert (policy.interval_source, policy.keep_source) == ("settings", "settings")

    def test_environment_beats_saved_values(self, db_session, sqlite_setup, monkeypatch):
        update_policy(db_session, {"interval_hours": 6, "keep": 14})
        _patch_settings(monkeypatch, backup_keep=30, backup_from_env=frozenset({"keep", "directory"}))

        policy = load_policy(db_session)

        assert (policy.keep, policy.keep_source) == (30, "environment"), "окружение приоритетнее сохранённого"
        assert (policy.interval_hours, policy.interval_source) == (6.0, "settings"), "незаданный окружением параметр берётся из настроек"
        assert policy.directory_source == "environment"

    @pytest.mark.parametrize(
        ("key", "raw"),
        [
            ("backup.interval_hours", "не json"),
            ("backup.interval_hours", "0.5"),  # чаще раза в час — только окружением
            ("backup.interval_hours", "true"),
            ("backup.interval_hours", '"6"'),
            ("backup.keep", "0"),
            ("backup.keep", "999999"),
            ("backup.keep", "7.5"),
            ("backup.keep", "null"),
        ],
    )
    def test_a_damaged_stored_value_counts_as_not_set(self, db_session, sqlite_setup, key, raw, caplog):
        db_session.add(AppPreference(owner="global", key=key, value=raw))
        db_session.commit()

        with caplog.at_level("WARNING", logger="app.services.backup_settings"):
            policy = load_policy(db_session)

        assert (policy.interval_hours, policy.keep) == (24.0, 7)
        assert key in caplog.text, "испорченное значение не молчаливо: оно записано в лог"

    def test_unreadable_database_falls_back_to_environment_and_defaults(self, monkeypatch, sqlite_setup, caplog):
        class Broken:
            def __enter__(self):
                raise OperationalError("SELECT", {}, Exception("no such table: app_preferences"))

            def __exit__(self, *exc):
                return False

        monkeypatch.setattr(backup_settings.app_db, "SessionLocal", lambda: Broken())
        _patch_settings(monkeypatch, backup_interval_hours=12.0, backup_from_env=frozenset({"interval_hours"}))

        with caplog.at_level("ERROR", logger="app.services.backup_settings"):
            policy = backup_settings.load_policy_or_environment()

        assert (policy.interval_hours, policy.interval_source) == (12.0, "environment")
        assert "Не удалось прочитать настройки плановых копий" in caplog.text


# ---------------------------------------------------------------------------
# Политика: запись
# ---------------------------------------------------------------------------
class TestUpdatePolicy:
    def test_saving_writes_one_audit_entry_with_old_and_new_values(self, db_session, sqlite_setup):
        update = update_policy(db_session, {"interval_hours": 6, "keep": 14})

        assert update.changed and (update.policy.interval_hours, update.policy.keep) == (6.0, 14)
        assert _audit_details(db_session) == ["Плановые копии базы — интервал: каждые 24 ч → каждые 6 ч; хранить копий: 7 → 14"]

    def test_zero_interval_is_described_as_switched_off(self, db_session, sqlite_setup):
        update_policy(db_session, {"interval_hours": 0})

        assert load_policy(db_session).interval_hours == 0
        assert _audit_details(db_session) == ["Плановые копии базы — интервал: каждые 24 ч → выключены"]

    def test_the_same_value_changes_nothing(self, db_session, sqlite_setup):
        update_policy(db_session, {"keep": 14})

        again = update_policy(db_session, {"keep": 14})
        nothing = update_policy(db_session, {})

        assert not again.changed and not nothing.changed
        assert len(_audit_details(db_session)) == 1, "повторное сохранение того же значения не засоряет журнал"

    def test_null_resets_to_default_and_removes_the_stored_value(self, db_session, sqlite_setup):
        update_policy(db_session, {"keep": 14})

        update = update_policy(db_session, {"keep": None})

        assert update.changed and update.policy.keep == 7 and update.policy.keep_source == "default"
        assert _stored(db_session) == {}
        assert (
            _audit_details(db_session)[-1] == "Плановые копии базы — хранить копий: 14 → 7 (сброшено к значению по умолчанию: число копий)"
        )
        assert not update_policy(db_session, {"keep": None}).changed, "сбрасывать нечего"

    def test_a_pinned_parameter_is_rejected_and_nothing_else_is_saved(self, db_session, sqlite_setup, monkeypatch):
        _patch_settings(monkeypatch, backup_from_env=frozenset({"keep"}))

        with pytest.raises(SettingPinnedByEnvironment) as caught:
            update_policy(db_session, {"interval_hours": 6, "keep": 14})

        assert caught.value.variable == "INFRA_REGISTRY_BACKUP_KEEP" and "INFRA_REGISTRY_BACKUP_KEEP" in str(caught.value)
        assert _stored(db_session) == {} and _audit_details(db_session) == [], "всё или ничего: интервал тоже не сохранён"

    def test_unknown_parameters_are_refused(self, db_session, sqlite_setup):
        with pytest.raises(ValueError, match="directory"):
            update_policy(db_session, {"directory": "/tmp/x"})


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
class TestApi:
    def test_get_returns_the_effective_policy_and_the_limits(self, client, sqlite_setup):
        body = client.get(URL).json()

        assert body["supported"] is True and body["unsupported_reason"] is None
        assert (body["interval_hours"], body["interval_source"], body["keep"], body["keep_source"]) == (24.0, "default", 7, "default")
        assert (body["default_interval_hours"], body["default_keep"]) == (24.0, 7)
        assert (body["min_interval_hours"], body["max_keep"]) == (1.0, 365)
        assert body["directory"] == str(sqlite_setup["backups"]) and body["directory_source"] == "default"

    def test_put_saves_reports_the_new_policy_and_audits_it(self, client, db_session, sqlite_setup):
        response = client.put(URL, json={"interval_hours": 6, "keep": 14})

        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["interval_hours"], body["interval_source"], body["keep"], body["keep_source"]) == (6.0, "settings", 14, "settings")
        assert client.get(URL).json()["keep"] == 14
        assert len(_audit_details(db_session)) == 1

    def test_a_field_that_is_not_sent_stays_unchanged(self, client, sqlite_setup):
        client.put(URL, json={"interval_hours": 6, "keep": 14})

        body = client.put(URL, json={"keep": 3}).json()

        assert (body["interval_hours"], body["keep"]) == (6.0, 3)

    @pytest.mark.parametrize(
        ("payload", "field"),
        [
            ({"interval_hours": 0.5}, "interval_hours"),  # чаще раза в час — только окружением
            ({"interval_hours": -1}, "interval_hours"),
            ({"interval_hours": 24 * 366 + 1}, "interval_hours"),
            ({"interval_hours": "6"}, "interval_hours"),
            ({"interval_hours": True}, "interval_hours"),
            ({"keep": 0}, "keep"),
            ({"keep": 366}, "keep"),
            ({"keep": "7"}, "keep"),
            ({"keep": 7.5}, "keep"),
            ({"directory": "/tmp/elsewhere"}, "directory"),  # каталог из интерфейса не меняется
        ],
    )
    def test_invalid_values_are_422_naming_the_field(self, client, db_session, sqlite_setup, payload, field):
        response = client.put(URL, json=payload)

        assert response.status_code == 422, response.text
        assert f"«{field}" in response.json()["detail"], "сообщение называет поле"
        assert _stored(db_session) == {}

    def test_zero_interval_switches_the_copies_off(self, client, sqlite_setup):
        body = client.put(URL, json={"interval_hours": 0}).json()

        assert body["interval_hours"] == 0 and body["running"] is False

    def test_a_pinned_parameter_is_409_naming_the_variable(self, client, db_session, sqlite_setup, monkeypatch):
        _patch_settings(monkeypatch, backup_from_env=frozenset({"interval_hours"}), backup_interval_hours=12.0)

        response = client.put(URL, json={"interval_hours": 6})

        assert response.status_code == 409
        assert "INFRA_REGISTRY_BACKUP_INTERVAL_HOURS" in response.json()["detail"]
        body = client.get(URL).json()
        assert (body["interval_hours"], body["interval_source"]) == (12.0, "environment")
        assert _stored(db_session) == {}

    @pytest.mark.parametrize("url", ["sqlite:///:memory:", "postgresql+psycopg://u:p@localhost/db"])
    def test_without_a_sqlite_file_nothing_can_be_saved(self, client, db_session, monkeypatch, url):
        _patch_settings(monkeypatch, database_url=url)

        body = client.get(URL).json()
        response = client.put(URL, json={"keep": 14})

        assert body["supported"] is False and "PostgreSQL" in body["unsupported_reason"]
        assert response.status_code == 409 and "PostgreSQL" in response.json()["detail"]
        assert _stored(db_session) == {}

    def test_the_saved_policy_applies_to_the_next_start_of_the_application(self, client, db_session, sqlite_setup):
        client.put(URL, json={"interval_hours": 6, "keep": 14})

        policy = backup_settings.load_policy_or_environment()

        assert (policy.interval_hours, policy.keep) == (6.0, 14), "настройка переживает перезапуск приложения"


class TestStatus:
    def _wait_for(self, client, key: str) -> dict:
        deadline = time.time() + 15
        while time.time() < deadline:
            body = client.get(URL).json()
            if body[key] is not None:
                return body
            time.sleep(0.05)
        raise AssertionError(f"за 15 с в ответе так и не появилось поле {key}")

    def test_the_startup_copy_is_reported_with_name_size_and_time(self, client_factory, sqlite_setup):
        client = client_factory()

        body = self._wait_for(client, "latest")

        latest = body["latest"]
        assert latest["name"].startswith("infra_registry.auto.") and latest["name"].endswith(".bak")
        assert latest["size_bytes"] == (sqlite_setup["backups"] / latest["name"]).stat().st_size > 0
        assert latest["created_at"].endswith("+00:00"), "время — ISO 8601 UTC, браузер покажет его в местном поясе"
        attempt = self._wait_for(client, "last_attempt")["last_attempt"]
        assert attempt["ok"] is True and attempt["error"] is None and attempt["created"] == latest["name"]
        assert body["running"] is True

    def test_a_failed_attempt_is_reported_with_its_error(self, client_factory, sqlite_setup, monkeypatch):
        def broken(db_path, backup_dir, keep=7):
            raise db_backup.ScheduledBackupError("не удалось создать плановую копию: диск переполнен")

        monkeypatch.setattr(backup_scheduler, "backup_scheduled", broken)
        client = client_factory()

        attempt = self._wait_for(client, "last_attempt")["last_attempt"]

        assert attempt["ok"] is False and "диск переполнен" in attempt["error"] and attempt["created"] is None

    def test_an_unreadable_backup_directory_is_not_an_error_of_the_page(self, client, sqlite_setup, monkeypatch):
        def unavailable(db_path, backup_dir):
            raise PermissionError("сетевой диск отключён")

        monkeypatch.setattr(backup_settings, "latest_auto_backup", unavailable)

        response = client.get(URL)

        assert response.status_code == 200 and response.json()["latest"] is None


# ---------------------------------------------------------------------------
# Применение без перезапуска приложения
# ---------------------------------------------------------------------------
class TestRestart:
    def test_saving_restarts_the_scheduler_with_the_new_policy(self, client_factory, sqlite_setup, monkeypatch):
        started: list[tuple[BackupPolicy | None, asyncio.Task | None]] = []
        real_start = backup_scheduler.start_backup_scheduler

        def spy(policy=None, on_attempt=None):
            task = real_start(policy, on_attempt)
            started.append((policy, task))
            return task

        monkeypatch.setattr(backup_scheduler, "start_backup_scheduler", spy)
        client = client_factory()
        first_task = started[0][1]
        assert first_task is not None and not first_task.done()

        assert client.put(URL, json={"interval_hours": 6, "keep": 14}).status_code == 200

        policy, second_task = started[-1]
        assert len(started) == 2 and (policy.interval_hours, policy.keep) == (6.0, 14)
        assert first_task.cancelled(), "прежняя задача отменена"
        assert second_task is not first_task and not second_task.done()
        assert client.get(URL).json()["running"] is True

    def test_saving_the_same_value_does_not_restart(self, client_factory, sqlite_setup, monkeypatch):
        started: list = []
        real_start = backup_scheduler.start_backup_scheduler
        monkeypatch.setattr(backup_scheduler, "start_backup_scheduler", lambda *a, **k: started.append(1) or real_start(*a, **k))
        client = client_factory()
        client.put(URL, json={"keep": 14})
        before = len(started)

        client.put(URL, json={"keep": 14})
        client.put(URL, json={})

        assert len(started) == before

    def test_switching_off_stops_the_task_and_switching_on_starts_it_again(self, client_factory, sqlite_setup):
        client = client_factory()
        assert client.get(URL).json()["running"] is True

        assert client.put(URL, json={"interval_hours": 0}).json()["running"] is False
        assert client.put(URL, json={"interval_hours": 6}).json()["running"] is True

    def test_two_simultaneous_restarts_leave_exactly_one_task(self, sqlite_setup):
        async def scenario():
            scheduler = backup_scheduler.BackupScheduler()
            policy = backup_settings.environment_policy()
            await scheduler.start(policy)
            tasks = {t for t in asyncio.all_tasks() if t.get_name() == backup_scheduler.TASK_NAME}
            await asyncio.gather(*[scheduler.restart(policy) for _ in range(5)])
            alive = {t for t in asyncio.all_tasks() if t.get_name() == backup_scheduler.TASK_NAME and not t.done()}
            await scheduler.stop()
            return tasks, alive, scheduler.running

        first, alive, running_after_stop = asyncio.run(scenario())

        assert len(first) == 1 and len(alive) == 1, "из пяти одновременных перезапусков живёт одна задача"
        assert running_after_stop is False

    def test_stopping_twice_is_harmless(self, sqlite_setup):
        async def scenario():
            scheduler = backup_scheduler.BackupScheduler()
            await scheduler.start(backup_settings.environment_policy())
            await scheduler.stop()
            await scheduler.stop()
            return scheduler.running

        assert asyncio.run(scenario()) is False


class TestConcurrentCopies:
    def test_scheduled_copies_are_serialised(self, sqlite_setup):
        """Перезапуск планировщика отменяет задачу, но поток копирования доделывает работу: вторая копия не должна идти
        параллельно с первой."""
        finished = threading.Event()

        def copy():
            db_backup.backup_scheduled(sqlite_setup["database"], sqlite_setup["backups"])
            finished.set()

        with db_backup._SCHEDULED_BACKUP_LOCK:  # «первая копия» ещё идёт
            worker = threading.Thread(target=copy)
            worker.start()
            assert not finished.wait(0.3), "вторая копия обязана ждать первую"
        assert finished.wait(15)
        worker.join()
        assert len(list(sqlite_setup["backups"].glob("*.bak"))) == 1


# ---------------------------------------------------------------------------
# Доступ
# ---------------------------------------------------------------------------
def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _login(client, username: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


@pytest.fixture()
def authenticated(client, sqlite_setup) -> tuple[str, str]:
    """Аутентификация включена; возвращает (токен администратора, токен viewer)."""
    created = client.post("/api/v1/auth/users", json={"username": "admin", "password": ADMIN_PASSWORD, "role": "admin"})
    assert created.status_code == 201, created.text
    assert client.put("/api/v1/auth/settings", json={"enabled": True}).status_code == 200
    admin = _login(client, "admin", ADMIN_PASSWORD)
    created = client.post(
        "/api/v1/auth/users", json={"username": "viewer1", "password": VIEWER_PASSWORD, "role": "viewer"}, headers=_headers(admin)
    )
    assert created.status_code == 201, created.text
    return admin, _login(client, "viewer1", VIEWER_PASSWORD)


class TestAccess:
    def test_the_administrator_reads_and_writes(self, client, authenticated):
        admin, _ = authenticated

        assert client.get(URL, headers=_headers(admin)).status_code == 200
        assert client.put(URL, json={"keep": 14}, headers=_headers(admin)).status_code == 200

    def test_a_viewer_gets_403_on_read_and_on_write(self, client, db_session, authenticated):
        _, viewer = authenticated

        read = client.get(URL, headers=_headers(viewer))
        write = client.put(URL, json={"keep": 14}, headers=_headers(viewer))

        assert read.status_code == 403 and "администратору" in read.json()["detail"]
        assert write.status_code == 403
        assert "directory" not in read.text, "в отказе нет данных настроек"
        assert _stored(db_session) == {}

    def test_an_anonymous_client_gets_401(self, client, authenticated):
        assert client.get(URL).status_code == 401
        assert client.put(URL, json={"keep": 14}).status_code == 401

    def test_without_authentication_the_single_user_mode_stays_open(self, client, sqlite_setup):
        assert client.get(URL).status_code == 200
