"""
Политика хранения журнала аудита, A-05 код-ревью main @ b375f58: очистка по сроку (services/audit_retention.py).

Что проверяется: при значении по умолчанию (срок 0) поведение не меняется; очистка не трогает записи не старше границы; удаление идёт пакетами; факт очистки (число
строк и граница) пишется в журнал; ленивый запуск — не чаще раза в сутки и не ломает вызывающего при сбое БД; сохранение срока пишет в журнал и сразу очищает.

Запуск: pytest backend/tests/test_audit_retention.py -v
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.models import AuditLog, AuditSettings
from app.services import audit_retention
from app.services.audit_retention import (
    AUDIT_ENTITY,
    CLEANUP_INTERVAL,
    SYSTEM_ACTOR,
    get_audit_settings,
    purge_expired_entries,
    run_cleanup,
    run_scheduled_cleanup,
    retention_state,
    update_retention,
)
from app.services.timeutil import utcnow_naive


@pytest.fixture()
def now() -> datetime:
    """«Сейчас» теста — реальное время (запись об очистке получает настоящий created_at, и фиксированная дата в прошлом могла бы оказаться новее него)."""
    return utcnow_naive().replace(microsecond=0)


def _entry(created_at: datetime, *, entity_type: str = "devices", details: str = "запись") -> AuditLog:
    return AuditLog(entity_type=entity_type, entity_id="e", action="UPDATE", details=details, created_at=created_at)


def _seed(session, *entries: AuditLog) -> None:
    session.add_all(entries)
    session.commit()


def _old(now: datetime, count: int, *, days: int = 100) -> list[AuditLog]:
    """count записей старше любой границы теста; details различимы, чтобы было видно, какие остались."""
    return [_entry(now - timedelta(days=days, minutes=index), details=f"старая {index}") for index in range(count)]


def _details(session, *, entity_type: str = "devices") -> list[str]:
    return sorted(session.scalars(select(AuditLog.details).where(AuditLog.entity_type == entity_type)))


def _service_entries(session) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).where(AuditLog.entity_type == AUDIT_ENTITY).order_by(AuditLog.created_at, AuditLog.id)))


def _set_retention(session, days: int | None, *, last_cleanup_at: datetime | None = None) -> None:
    row = session.get(AuditSettings, "singleton") or AuditSettings(id="singleton")
    row.retention_days, row.last_cleanup_at = days, last_cleanup_at
    session.add(row)
    session.commit()


class TestDefaultBehaviourIsUnchanged:
    def test_without_settings_nothing_is_deleted_and_no_row_or_entry_is_created(self, db_session, now):
        _seed(db_session, *_old(now, 5, days=5000))

        removed = run_scheduled_cleanup(db_session, now=now)

        assert removed == 0
        assert len(_details(db_session)) == 5
        assert get_audit_settings(db_session) is None, "чтение значений по умолчанию строку настроек не создаёт"
        assert _service_entries(db_session) == []

    def test_retention_zero_stored_in_the_form_deletes_nothing(self, db_session, now):
        _seed(db_session, *_old(now, 3, days=5000))
        _set_retention(db_session, 0)

        assert run_scheduled_cleanup(db_session, now=now) == 0
        assert len(_details(db_session)) == 3

    def test_run_cleanup_without_a_period_reports_nothing_to_do(self, db_session, now):
        assert run_cleanup(db_session, now=now, actor=None) is None

    def test_default_settings_are_serialized_as_not_deleting(self, db_session):
        assert retention_state(get_audit_settings(db_session)) == audit_retention.RetentionState(retention_days=0, is_default=True, default_retention_days=0, max_retention_days=3650, last_cleanup_at=None)

    def test_environment_default_applies_until_the_form_overrides_it(self, db_session, now, monkeypatch):
        monkeypatch.setattr(audit_retention, "AUDIT_RETENTION_DAYS", 30)
        _seed(db_session, *_old(now, 2, days=40), _entry(now - timedelta(days=10), details="свежая"))

        assert run_scheduled_cleanup(db_session, now=now) == 2
        assert _details(db_session) == ["свежая"]

        _set_retention(db_session, 0)  # явный 0 в форме важнее умолчания из окружения
        assert retention_state(get_audit_settings(db_session)).retention_days == 0
        assert retention_state(get_audit_settings(db_session)).is_default is False


class TestLayering:
    def test_the_service_does_not_depend_on_the_transport_layer(self):
        """Сервис не импортирует schemas (слой транспорта) и не собирает JSON ответа: именованные поля и ISO-строки — дело API."""
        import ast
        from pathlib import Path

        tree = ast.parse(Path(audit_retention.__file__).read_text(encoding="utf-8"))
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}

        assert "schemas" not in imported
        assert not hasattr(audit_retention, "serialize_audit_settings")


class TestPurge:
    def test_only_entries_strictly_older_than_the_boundary_are_removed(self, db_session, now):
        cutoff = now - timedelta(days=30)
        _seed(
            db_session,
            _entry(cutoff - timedelta(seconds=1), details="на секунду старше границы"),
            _entry(cutoff, details="ровно на границе"),
            _entry(cutoff + timedelta(seconds=1), details="на секунду новее"),
            _entry(now - timedelta(days=1), details="вчера"),
            _entry(now, details="сейчас"),
        )

        result = purge_expired_entries(db_session, 30, now=now)

        assert (result.removed, result.cutoff, result.complete) == (1, cutoff, True)
        assert _details(db_session) == sorted(["вчера", "ровно на границе", "на секунду новее", "сейчас"])

    def test_deletion_goes_in_batches_and_each_batch_is_its_own_transaction(self, db_session, now, sql_log):
        _seed(db_session, *_old(now, 10), _entry(now, details="свежая"))
        sql_log.clear()

        result = purge_expired_entries(db_session, 30, now=now, batch_size=3)

        deletes = [statement for statement in sql_log if statement.lstrip().upper().startswith("DELETE FROM AUDIT_LOG")]
        assert (result.removed, result.complete) == (10, True)
        assert len(deletes) == 4, "пакеты 3 + 3 + 3 + 1: короткий пакет — последний"
        assert _details(db_session) == ["свежая"]

    def test_a_run_stops_at_the_batch_limit_oldest_first_and_reports_it_is_not_complete(self, db_session, now):
        entries = [_entry(now - timedelta(days=100 - index), details=f"запись {index:02d}") for index in range(10)]  # запись 00 — самая старая
        _seed(db_session, *entries)

        result = purge_expired_entries(db_session, 30, now=now, batch_size=2, max_batches=3)

        assert (result.removed, result.complete) == (6, False)
        assert _details(db_session) == [f"запись {index:02d}" for index in range(6, 10)], "удалены шесть самых старых"

    def test_a_run_that_removes_exactly_the_limit_and_leaves_nothing_is_complete(self, db_session, now):
        _seed(db_session, *_old(now, 6))

        result = purge_expired_entries(db_session, 30, now=now, batch_size=2, max_batches=3)

        assert (result.removed, result.complete) == (6, True)

    @pytest.mark.parametrize("days", [0, -5])
    def test_a_non_positive_period_is_a_programming_error(self, db_session, now, days):
        _seed(db_session, *_old(now, 1))
        with pytest.raises(ValueError, match="не удалять"):
            purge_expired_entries(db_session, days, now=now)
        assert len(_details(db_session)) == 1


class TestCleanupRecordsItselfInTheLog:
    def test_the_entry_has_the_count_the_boundary_and_the_system_as_author(self, db_session, now):
        _seed(db_session, *_old(now, 3), _entry(now, details="свежая"))
        _set_retention(db_session, 30)

        removed = run_scheduled_cleanup(db_session, now=now)

        (entry,) = _service_entries(db_session)
        assert removed == 3
        assert (entry.action, entry.entity_id, entry.actor_username, entry.actor_id) == ("DELETE", "singleton", SYSTEM_ACTOR.username, None)
        assert "удалено записей — 3" in entry.details
        assert f"{now - timedelta(days=30):%d.%m.%Y %H:%M} UTC" in entry.details
        assert "30 дн." in entry.details
        assert "продолжится" not in entry.details

    def test_the_cleanup_entry_is_never_removed_by_the_cleanup_that_wrote_it(self, db_session, now):
        _seed(db_session, *_old(now, 2))
        _set_retention(db_session, 30)

        run_scheduled_cleanup(db_session, now=now)
        run_cleanup(db_session, now=now + timedelta(days=1), actor=None)  # следующий проход (например, после сохранения срока)

        assert len(_service_entries(db_session)) == 1, "запись об очистке свежая и осталась; второй проход ничего не удалил и ничего не дописал"

    def test_a_run_that_removes_nothing_writes_no_entry_but_marks_the_cleanup_time(self, db_session, now):
        _seed(db_session, _entry(now, details="свежая"))
        _set_retention(db_session, 30)

        assert run_scheduled_cleanup(db_session, now=now) == 0

        assert _service_entries(db_session) == []
        assert get_audit_settings(db_session).last_cleanup_at == now

    def test_an_incomplete_run_says_so_and_is_not_marked_as_done(self, db_session, now, monkeypatch):
        monkeypatch.setattr(audit_retention, "BATCH_SIZE", 2)
        monkeypatch.setattr(audit_retention, "MAX_BATCHES_PER_RUN", 2)
        _seed(db_session, *_old(now, 7))
        _set_retention(db_session, 30)

        assert run_scheduled_cleanup(db_session, now=now) == 4

        (entry,) = _service_entries(db_session)
        assert "удалено записей — 4" in entry.details and "Очистка продолжится при следующем запуске." in entry.details
        assert get_audit_settings(db_session).last_cleanup_at is None, "не дочистили — сутки ждать не нужно"
        assert run_scheduled_cleanup(db_session, now=now + timedelta(minutes=1)) == 3, "следующий запуск доберёт остаток сразу"
        assert get_audit_settings(db_session).last_cleanup_at is not None


class TestScheduledRunsAtMostOncePerDay:
    def test_a_second_run_within_a_day_does_nothing_and_a_run_after_a_day_works(self, db_session, now):
        _set_retention(db_session, 30)
        _seed(db_session, *_old(now, 2))
        assert run_scheduled_cleanup(db_session, now=now) == 2

        _seed(db_session, *_old(now, 2, days=60))  # новые просроченные записи появились после очистки
        assert run_scheduled_cleanup(db_session, now=now + CLEANUP_INTERVAL - timedelta(seconds=1)) == 0
        assert len(_details(db_session)) == 2

        assert run_scheduled_cleanup(db_session, now=now + CLEANUP_INTERVAL) == 2
        assert _details(db_session) == []

    def test_the_time_of_the_last_cleanup_is_exposed_to_the_settings_form(self, db_session, now):
        _set_retention(db_session, 30)
        run_scheduled_cleanup(db_session, now=now)

        assert retention_state(get_audit_settings(db_session)).last_cleanup_at == now

    def test_a_database_error_is_logged_and_does_not_reach_the_caller(self, db_session, now, monkeypatch, caplog):
        _set_retention(db_session, 30)

        def broken(*_args, **_kwargs):
            raise OperationalError("DELETE FROM audit_log", {}, Exception("disk I/O error"))

        monkeypatch.setattr(audit_retention, "purge_expired_entries", broken)
        with caplog.at_level(logging.ERROR, logger="app.services.audit_retention"):
            assert run_scheduled_cleanup(db_session, now=now) == 0

        assert "Очистка журнала аудита по сроку хранения не выполнена" in caplog.text
        assert get_audit_settings(db_session).retention_days == 30, "сессия исправна, настройки читаются"
        assert get_audit_settings(db_session).last_cleanup_at is None, "очистка не засчитана: следующий запуск повторит попытку"


class TestScheduledRunNeverRaises:
    """Контракт `run_scheduled_cleanup`: «не бросает» — любой сбой очистки (не только БД) пишется в журнал приложения и возвращает 0."""

    def test_an_overflowing_period_is_logged_and_does_not_escape(self, db_session, now, monkeypatch, caplog):
        # Срок из окружения без верхней границы: now - timedelta(days=10**6) → OverflowError («date value out of range»).
        monkeypatch.setattr(audit_retention, "AUDIT_RETENTION_DAYS", 10**6)

        with caplog.at_level(logging.ERROR, logger="app.services.audit_retention"):
            assert run_scheduled_cleanup(db_session, now=now) == 0

        assert "Очистка журнала аудита по сроку хранения не выполнена" in caplog.text
        assert get_audit_settings(db_session) is None or get_audit_settings(db_session).last_cleanup_at is None, "очистка не засчитана"

    def test_any_unexpected_error_inside_the_purge_is_contained(self, db_session, now, monkeypatch, caplog):
        db_session.add(AuditSettings(id="singleton", retention_days=30))
        db_session.commit()

        def boom(*_args, **_kwargs):
            raise RuntimeError("неожиданный сбой")

        monkeypatch.setattr(audit_retention, "purge_expired_entries", boom)

        with caplog.at_level(logging.ERROR, logger="app.services.audit_retention"):
            assert run_scheduled_cleanup(db_session, now=now) == 0

        assert "неожиданный сбой" in caplog.text


class TestUpdateRetention:
    def test_saving_a_period_writes_the_change_to_the_log_and_cleans_up_at_once(self, db_session, now):
        _seed(db_session, *_old(now, 4), _entry(now, details="свежая"))

        update = update_retention(db_session, 90, now=now)

        assert (update.removed, update.cleanup_failed) == (4, False)
        assert update.row.retention_days == 90
        assert update.row.last_cleanup_at == now
        changed, purged = _service_entries(db_session)
        assert (changed.action, changed.details) == ("UPDATE", "Срок хранения журнала аудита: не ограничен → 90 дн.")
        assert (purged.action, "удалено записей — 4" in purged.details) == ("DELETE", True)
        assert _details(db_session) == ["свежая"]

    def test_the_author_of_the_change_is_the_actor_of_the_request(self, db_session, now):
        from app.services.actor_context import Actor, current_actor

        token = current_actor.set(Actor(user_id="u1", username="admin", ip="10.0.0.5"))
        try:
            update_retention(db_session, 90, now=now)
        finally:
            current_actor.reset(token)

        (changed,) = _service_entries(db_session)
        assert (changed.actor_id, changed.actor_username, changed.actor_ip) == ("u1", "admin", "10.0.0.5")

    def test_saving_the_same_value_changes_nothing(self, db_session, now):
        update_retention(db_session, 90, now=now)
        before = len(_service_entries(db_session))
        _seed(db_session, *_old(now, 2))

        update = update_retention(db_session, 90, now=now)

        assert update.removed == 0
        assert len(_service_entries(db_session)) == before, "повторное сохранение того же срока в журнал не пишется"
        assert len(_details(db_session)) == 2, "и очистку не запускает"

    def test_zero_turns_the_cleanup_off_and_deletes_nothing(self, db_session, now):
        update_retention(db_session, 90, now=now)
        _seed(db_session, *_old(now, 2))

        update = update_retention(db_session, 0, now=now)

        assert update.removed == 0 and len(_details(db_session)) == 2
        assert _service_entries(db_session)[-1].details == "Срок хранения журнала аудита: 90 дн. → не ограничен"

    def test_reset_returns_to_the_default_and_says_so(self, db_session, now):
        update_retention(db_session, 90, now=now)

        update = update_retention(db_session, None, now=now)

        assert update.row.retention_days is None
        assert retention_state(update.row).is_default is True
        assert _service_entries(db_session)[-1].details == "Срок хранения журнала аудита: 90 дн. → не ограничен (сброшен к значению по умолчанию)"

    def test_a_failed_cleanup_keeps_the_saved_period_and_is_reported(self, db_session, now, monkeypatch):
        def broken(*_args, **_kwargs):
            raise OperationalError("DELETE FROM audit_log", {}, Exception("disk I/O error"))

        monkeypatch.setattr(audit_retention, "purge_expired_entries", broken)

        update = update_retention(db_session, 90, now=now)

        assert (update.removed, update.cleanup_failed) == (0, True)
        assert get_audit_settings(db_session).retention_days == 90
        assert [entry.action for entry in _service_entries(db_session)] == ["UPDATE"]
        assert update.cleanup_failed is True
