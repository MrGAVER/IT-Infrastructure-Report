"""
Архив удаляемых записей журнала аудита (services/audit_archive.py и его место в services/audit_retention.py).

Что проверяется: запись удаляется из БД только после того, как её копия записана в файл и сброшена на диск; при сбое архива не удаляется
ничего и очистка считается неудавшейся (срок при этом сохраняется); формат файла (колонки, разделитель, BOM, защита от формул, права);
проход без удаляемых записей файла не создаёт; уборка отчётов архив не трогает; контракт ответа
`PUT /api/v1/audit-log/settings` не меняется.

Запуск: pytest backend/tests/test_audit_archive.py -v
"""

from __future__ import annotations

import csv
import errno
import logging
import os
import stat
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import AuditLog
from app.services import audit_archive, audit_retention
from app.services.audit_archive import ARCHIVE_COLUMNS, ARCHIVE_PREFIX, AuditArchive, AuditArchiveError, audit_archive_dir
from app.services.audit_retention import AUDIT_ENTITY, get_audit_settings, purge_expired_entries, run_scheduled_cleanup, update_retention
from app.services.report_cleanup import cleanup_old_reports
from app.services.timeutil import utcnow_naive

URL = "/api/v1/audit-log/settings"


@pytest.fixture()
def now() -> datetime:
    return utcnow_naive().replace(microsecond=0)


def _entry(created_at: datetime, *, details: str = "запись", entity_id: str = "e", actor_username: str | None = None) -> AuditLog:
    return AuditLog(
        entity_type="devices",
        entity_id=entity_id,
        action="UPDATE",
        details=details,
        created_at=created_at,
        actor_username=actor_username,
    )


def _old(now: datetime, count: int, *, days: int = 100) -> list[AuditLog]:
    return [_entry(now - timedelta(days=days, minutes=index), details=f"старая {index}", entity_id=f"id-{index}") for index in range(count)]


def _seed(session, *entries: AuditLog) -> None:
    session.add_all(entries)
    session.commit()


def _details(session) -> list[str]:
    return sorted(session.scalars(select(AuditLog.details).where(AuditLog.entity_type == "devices")))


def _read_archive(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream, delimiter=";")
        rows = list(reader)
        return list(reader.fieldnames or []), rows


def _archives() -> list[Path]:
    directory = audit_archive_dir()
    return sorted(directory.glob(f"{ARCHIVE_PREFIX}*")) if directory.is_dir() else []


class TestArchiveHoldsExactlyWhatIsDeleted:
    def test_every_removed_entry_is_in_the_file_and_no_other(self, db_session, now):
        _seed(db_session, *_old(now, 5), _entry(now - timedelta(days=1), details="свежая"))
        ids_before = {row.details: row.id for row in db_session.scalars(select(AuditLog))}

        result = purge_expired_entries(db_session, 30, now=now)

        header, rows = _read_archive(result.archive_path)
        assert header == [column.name for column in ARCHIVE_COLUMNS], "в файле все колонки таблицы, включая id"
        assert result.removed == len(rows) == 5
        assert {row["details"]: row["id"] for row in rows} == {f"старая {index}": ids_before[f"старая {index}"] for index in range(5)}
        assert _details(db_session) == ["свежая"]

    def test_the_file_is_written_before_the_batch_is_deleted(self, db_session, now, monkeypatch):
        _seed(db_session, *_old(now, 5))
        seen: list[set[str]] = []
        original = audit_retention._delete_by_ids

        def spy(session, ids):
            (path,) = _archives()
            seen.append({row["id"] for row in _read_archive(path)[1]})  # к моменту DELETE файл уже полон и прочитывается с диска
            assert set(ids) <= seen[-1]
            return original(session, ids)

        monkeypatch.setattr(audit_retention, "_delete_by_ids", spy)

        purge_expired_entries(db_session, 30, now=now, batch_size=2)

        assert [len(ids) for ids in seen] == [2, 4, 5], "каждый пакет попадает в файл до своего удаления; файл один на проход"

    def test_an_entry_that_is_not_in_the_archive_is_never_deleted(self, db_session, now, monkeypatch):
        """Старая запись, появившаяся между чтением пакета и удалением, в архив не попала — значит, и удалена быть не может."""
        _seed(db_session, *_old(now, 3))
        original = AuditArchive.write_batch

        def write_then_insert_a_late_entry(self, rows):
            original(self, rows)
            db_session.add(_entry(now - timedelta(days=200), details="запоздавшая"))
            db_session.flush()

        monkeypatch.setattr(AuditArchive, "write_batch", write_then_insert_a_late_entry)

        result = purge_expired_entries(db_session, 30, now=now)

        assert result.removed == 3
        assert _details(db_session) == ["запоздавшая"]
        assert "запоздавшая" not in result.archive_path.read_text(encoding="utf-8-sig")

    def test_a_run_with_several_batches_makes_one_file(self, db_session, now):
        _seed(db_session, *_old(now, 7))

        result = purge_expired_entries(db_session, 30, now=now, batch_size=3)

        assert result.removed == 7 and len(_archives()) == 1
        assert len(_read_archive(result.archive_path)[1]) == 7

    def test_a_run_with_nothing_to_remove_leaves_no_file_and_no_directory(self, db_session, now):
        _seed(db_session, _entry(now - timedelta(days=1)))

        result = purge_expired_entries(db_session, 30, now=now)

        assert (result.removed, result.archive_path) == (0, None)
        assert not audit_archive_dir().exists()

    def test_two_runs_in_the_same_second_do_not_overwrite_each_other(self, db_session, now):
        _seed(db_session, *_old(now, 2))
        first = purge_expired_entries(db_session, 30, now=now)
        _seed(db_session, *_old(now, 2, days=120))
        second = purge_expired_entries(db_session, 30, now=now)

        assert first.archive_path != second.archive_path
        assert len(_archives()) == 2 and all(len(_read_archive(path)[1]) == 2 for path in _archives())


class TestFailClosed:
    def test_an_unwritable_directory_deletes_nothing(self, db_session, now, tmp_path):
        blocker = tmp_path / "занято"
        blocker.write_text("файл на месте каталога", encoding="utf-8")
        _seed(db_session, *_old(now, 4))

        with pytest.raises(AuditArchiveError):
            purge_expired_entries(db_session, 30, now=now, archive_dir=blocker / "audit")

        assert len(_details(db_session)) == 4

    def test_a_failure_in_a_later_batch_keeps_everything_not_yet_archived(self, db_session, now, monkeypatch):
        # запись 00 — самая старая
        entries = [_entry(now - timedelta(days=100 - index), details=f"запись {index:02d}") for index in range(6)]
        _seed(db_session, *entries)
        original, calls = AuditArchive.write_batch, []

        def fail_on_second_batch(self, rows):
            calls.append(len(rows))
            if len(calls) == 2:
                raise AuditArchiveError("диск полон")
            original(self, rows)

        monkeypatch.setattr(AuditArchive, "write_batch", fail_on_second_batch)

        with pytest.raises(AuditArchiveError):
            purge_expired_entries(db_session, 30, now=now, batch_size=2)
        db_session.rollback()

        assert _details(db_session) == [f"запись {index:02d}" for index in range(2, 6)], "удалён только сохранённый первый пакет"
        (path,) = _archives()
        assert [row["details"] for row in _read_archive(path)[1]] == ["запись 00", "запись 01"]

    def test_a_disk_error_is_reported_as_an_archive_error_with_the_cause(self, tmp_path, monkeypatch):
        def no_space(_descriptor):
            raise OSError(errno.ENOSPC, "No space left on device")

        monkeypatch.setattr(audit_archive.os, "fsync", no_space)
        archive = AuditArchive(tmp_path / "audit", now=utcnow_naive())

        with archive, pytest.raises(AuditArchiveError, match="Записи не удалены") as raised:
            archive.write_batch([tuple(f"v{index}" for index, _ in enumerate(ARCHIVE_COLUMNS))])

        assert isinstance(raised.value.__cause__, OSError) and archive.rows == 0

    def test_a_scheduled_run_does_not_raise_and_is_retried_later(self, db_session, now, tmp_path, monkeypatch, caplog):
        blocker = tmp_path / "занято"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(audit_archive, "audit_archive_dir", lambda: blocker / "audit")
        monkeypatch.setattr(audit_retention, "audit_archive_dir", lambda: blocker / "audit")
        _seed(db_session, *_old(now, 3))
        audit_retention.get_or_create_audit_settings(db_session).retention_days = 30
        db_session.commit()

        with caplog.at_level(logging.ERROR, logger="app.services.audit_retention"):
            assert run_scheduled_cleanup(db_session, now=now) == 0

        assert "Очистка журнала аудита по сроку хранения не выполнена" in caplog.text
        assert len(_details(db_session)) == 3
        assert get_audit_settings(db_session).last_cleanup_at is None, "очистка не засчитана: следующий запуск повторит попытку"

    def test_saving_a_period_keeps_it_when_the_archive_fails(self, db_session, now, tmp_path, monkeypatch):
        blocker = tmp_path / "занято"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(audit_retention, "audit_archive_dir", lambda: blocker / "audit")
        _seed(db_session, *_old(now, 3))

        update = update_retention(db_session, 30, now=now)

        assert (update.removed, update.cleanup_failed) == (0, True)
        assert get_audit_settings(db_session).retention_days == 30
        assert len(_details(db_session)) == 3
        cleanup_records = db_session.scalars(select(AuditLog).where(AuditLog.entity_type == AUDIT_ENTITY))
        assert [e.action for e in cleanup_records] == ["UPDATE"], "записи об очистке нет"


class TestFileFormat:
    def test_values_are_written_as_they_are_except_spreadsheet_formulas(self, db_session, now):
        _seed(db_session, _entry(now - timedelta(days=100), details='=HYPERLINK("http://x")', actor_username="админ;1"))

        result = purge_expired_entries(db_session, 30, now=now)

        row = _read_archive(result.archive_path)[1][0]
        assert row["details"] == '\'=HYPERLINK("http://x")', "ячейка, похожая на формулу, дополнена апострофом"
        assert row["actor_username"] == "админ;1", "разделитель внутри значения экранируется кавычками"
        assert row["actor_ip"] == "", "NULL — пустая ячейка"
        assert row["created_at"].endswith("+00:00")

    def test_the_file_starts_with_a_bom_so_excel_reads_cyrillic(self, db_session, now):
        _seed(db_session, *_old(now, 1))

        result = purge_expired_entries(db_session, 30, now=now)

        assert result.archive_path.read_bytes().startswith(b"\xef\xbb\xbf")
        assert result.archive_path.name.startswith(ARCHIVE_PREFIX) and result.archive_path.suffix == ".csv"

    @pytest.mark.skipif(os.name != "posix", reason="права доступа POSIX")
    def test_the_file_is_readable_only_by_its_owner(self, db_session, now):
        _seed(db_session, *_old(now, 1))

        result = purge_expired_entries(db_session, 30, now=now)

        assert stat.S_IMODE(result.archive_path.stat().st_mode) == 0o600


class TestAuditEntryAndReportCleanup:
    def test_the_cleanup_entry_names_the_archive_file_but_not_the_server_path(self, db_session, now):
        _seed(db_session, *_old(now, 2))
        audit_retention.get_or_create_audit_settings(db_session).retention_days = 30
        db_session.commit()

        run_scheduled_cleanup(db_session, now=now)

        (entry,) = db_session.scalars(select(AuditLog).where(AuditLog.entity_type == AUDIT_ENTITY))
        (path,) = _archives()
        assert f"Копия удалённых записей сохранена в файле {path.name}." in entry.details
        assert str(path.parent) not in entry.details

    def test_the_report_cleanup_never_removes_an_archive(self, db_session, now):
        _seed(db_session, *_old(now, 2))
        path = purge_expired_entries(db_session, 30, now=now).archive_path
        os.utime(path, (0, 0))  # самый старый файл каталога: и по сроку, и по квоте он был бы первым на удаление

        cleanup_old_reports(audit_archive_dir().parent, max_age_days=1, max_files=1)

        assert path.is_file()


class TestHttpContract:
    def test_saving_a_period_archives_the_removed_entries_and_the_response_keeps_its_fields(self, client, db_session, now):
        _seed(db_session, *_old(now, 4, days=400))

        body = client.put(URL, json={"retention_days": 30}).json()

        expected_fields = {
            "retention_days",
            "is_default",
            "default_retention_days",
            "max_retention_days",
            "last_cleanup_at",
            "removed_now",
            "cleanup_failed",
        }
        assert set(body) == expected_fields
        assert (body["removed_now"], body["cleanup_failed"]) == (4, False)
        (path,) = _archives()
        assert len(_read_archive(path)[1]) == 4
