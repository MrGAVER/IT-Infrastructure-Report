"""A-10: очистка каталога отчётов — по возрасту, по количеству файлов и не чаще раза в минуту.

Раньше каталог чистился только по возрасту (30 дней), квоты не было: цикл запросов формирования отчётов от роли viewer (или
любого клиента при выключенной аутентификации) заполнял диск, а проход по каталогу шёл в каждом запросе.

Запуск: pytest backend/tests/test_report_cleanup.py -v
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.services import report_cleanup
from app.services.report_cleanup import AGE_SCAN_INTERVAL_SECONDS, cleanup_before_new_report, cleanup_old_reports

API = "/api/v1"
BACKEND_DIR = Path(__file__).resolve().parent.parent


def _make_reports(directory: Path, count: int, *, prefix: str = "r", suffix: str = ".xlsx", newest_age: float = 0.0, step: float = 10.0) -> list[Path]:
    """count файлов; i-й тем старше, чем меньше i (r00 — самый старый). Возраст в секундах от «сейчас»."""
    now = time.time()
    paths = []
    for i in range(count):
        path = directory / f"{prefix}{i:03d}{suffix}"
        path.write_bytes(b"x")
        age = newest_age + (count - 1 - i) * step
        os.utime(path, (now - age, now - age))
        paths.append(path)
    return paths


def _names(directory: Path, suffix: str = ".xlsx") -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.suffix == suffix)


@pytest.fixture(autouse=True)
def _fresh_throttle(monkeypatch):
    monkeypatch.setattr(report_cleanup, "_last_age_scan", {})


# ---------------------------------------------------------------------------------------------------------------------
# A-05: отчёты журнала аудита лежат в подкаталоге audit/ и подчиняются тем же правилам очистки
# ---------------------------------------------------------------------------------------------------------------------
class TestAuditSubdirectory:
    def test_audit_reports_count_toward_the_quota_together_with_the_root_files(self, tmp_path):
        (tmp_path / "audit").mkdir()
        now = time.time()
        for age, directory, name in [(50, tmp_path, "root_old.xlsx"), (40, tmp_path / "audit", "audit_old.xlsx"), (30, tmp_path, "root_new.xlsx"), (20, tmp_path / "audit", "audit_new.xlsx")]:
            path = directory / name
            path.write_bytes(b"x")
            os.utime(path, (now - age, now - age))
        removed = cleanup_old_reports(tmp_path, max_age_days=30, max_files=2)
        assert removed == 2
        assert _names(tmp_path) == ["root_new.xlsx"] and _names(tmp_path / "audit") == ["audit_new.xlsx"], "самые старые удалены и в корне, и в подкаталоге"

    def test_stale_audit_reports_are_removed_by_age(self, tmp_path):
        (tmp_path / "audit").mkdir()
        stale = tmp_path / "audit" / "Журнал_аудита_старый.xlsx"
        stale.write_bytes(b"x")
        os.utime(stale, (0, 0))
        fresh = tmp_path / "audit" / "Журнал_аудита_свежий.xlsx"
        fresh.write_bytes(b"x")
        assert cleanup_old_reports(tmp_path, max_age_days=30, max_files=0) == 1
        assert not stale.exists() and fresh.exists()

    def test_the_subdirectory_itself_and_foreign_files_in_it_are_left_alone(self, tmp_path):
        audit = tmp_path / "audit"
        audit.mkdir()
        keep = audit / "заметка.txt"
        keep.write_text("не отчёт")
        os.utime(keep, (0, 0))
        _make_reports(audit, 3, newest_age=400 * 86400)
        cleanup_old_reports(tmp_path, max_age_days=30, max_files=0)
        assert audit.is_dir() and keep.exists() and _names(audit) == []

    def test_a_missing_subdirectory_is_not_an_error(self, tmp_path):
        _make_reports(tmp_path, 3)
        assert cleanup_old_reports(tmp_path, max_age_days=30, max_files=2) == 1

    def test_generating_an_audit_report_makes_room_for_it_across_both_directories(self, client, tmp_path, monkeypatch):
        from app.api import reports

        monkeypatch.setattr(reports, "REPORT_DIR", tmp_path)
        monkeypatch.setattr(report_cleanup, "REPORT_MAX_FILES", 3)
        _make_reports(tmp_path, 3)  # квота уже занята файлами корня
        assert client.post("/api/v1/reports/audit-log").status_code == 200
        assert len(list(tmp_path.glob("*.xlsx"))) + len(list((tmp_path / "audit").glob("*.xlsx"))) <= 3


# ---------------------------------------------------------------------------------------------------------------------
# cleanup_old_reports: квота
# ---------------------------------------------------------------------------------------------------------------------
class TestQuota:
    def test_oldest_files_beyond_the_limit_are_removed_even_if_young(self, tmp_path):
        _make_reports(tmp_path, 10)  # все свежие: возраст им не мешает
        removed = cleanup_old_reports(tmp_path, max_age_days=30, max_files=4)
        assert removed == 6
        assert _names(tmp_path) == ["r006.xlsx", "r007.xlsx", "r008.xlsx", "r009.xlsx"], "остались самые новые"

    def test_quota_works_when_age_cleanup_is_disabled(self, tmp_path):
        """REPORT_RETENTION_DAYS=0 («не удалять по возрасту») не отключает квоту."""
        _make_reports(tmp_path, 8, newest_age=400 * 86400)  # все «древние»
        assert cleanup_old_reports(tmp_path, max_age_days=0, max_files=3) == 5
        assert _names(tmp_path) == ["r005.xlsx", "r006.xlsx", "r007.xlsx"]

    def test_age_and_quota_combine(self, tmp_path):
        _make_reports(tmp_path, 3, prefix="old", newest_age=40 * 86400)
        _make_reports(tmp_path, 6, prefix="new")
        removed = cleanup_old_reports(tmp_path, max_age_days=30, max_files=4)
        assert removed == 3 + 2
        assert _names(tmp_path) == ["new002.xlsx", "new003.xlsx", "new004.xlsx", "new005.xlsx"]

    def test_both_limits_disabled_is_a_no_op(self, tmp_path):
        paths = _make_reports(tmp_path, 5, newest_age=400 * 86400)
        assert cleanup_old_reports(tmp_path, max_age_days=0, max_files=0) == 0
        assert all(p.exists() for p in paths)

    def test_limit_not_reached_removes_nothing(self, tmp_path):
        _make_reports(tmp_path, 3)
        assert cleanup_old_reports(tmp_path, max_age_days=30, max_files=3) == 0
        assert len(_names(tmp_path)) == 3

    def test_xlsx_and_docx_count_together_and_foreign_files_do_not(self, tmp_path):
        _make_reports(tmp_path, 3, prefix="a", suffix=".xlsx", newest_age=20)
        _make_reports(tmp_path, 3, prefix="b", suffix=".docx")
        (tmp_path / "notes.txt").write_text("нужная запись")
        (tmp_path / "folder.xlsx").mkdir()  # каталог с «отчётным» именем — не файл отчёта
        removed = cleanup_old_reports(tmp_path, max_age_days=30, max_files=2)
        assert removed == 4
        assert (tmp_path / "notes.txt").exists() and (tmp_path / "folder.xlsx").is_dir()
        assert _names(tmp_path, ".docx") == ["b001.docx", "b002.docx"] and _names(tmp_path, ".xlsx") == ["folder.xlsx"]

    def test_equal_modification_times_are_resolved_by_name(self, tmp_path):
        now = time.time()
        for name in ("c.xlsx", "a.xlsx", "b.xlsx", "d.xlsx"):
            path = tmp_path / name
            path.write_bytes(b"x")
            os.utime(path, (now, now))
        cleanup_old_reports(tmp_path, max_age_days=0, max_files=2)
        assert _names(tmp_path) == ["c.xlsx", "d.xlsx"], "при равном времени раньше удаляются файлы с меньшим именем"

    def test_keep_free_leaves_room_for_the_new_file(self, tmp_path):
        _make_reports(tmp_path, 8)
        assert cleanup_old_reports(tmp_path, max_age_days=0, max_files=5, keep_free=1) == 4
        assert len(_names(tmp_path)) == 4

    def test_keep_free_larger_than_the_limit_empties_the_directory_without_errors(self, tmp_path):
        _make_reports(tmp_path, 3)
        assert cleanup_old_reports(tmp_path, max_age_days=0, max_files=1, keep_free=1) == 3
        assert cleanup_old_reports(tmp_path, max_age_days=0, max_files=1, keep_free=5) == 0
        assert _names(tmp_path) == []

    def test_keep_free_does_not_enable_a_disabled_quota(self, tmp_path):
        _make_reports(tmp_path, 3)
        assert cleanup_old_reports(tmp_path, max_age_days=0, max_files=0, keep_free=1) == 0
        assert len(_names(tmp_path)) == 3

    def test_missing_directory_is_not_an_error(self, tmp_path):
        assert cleanup_old_reports(tmp_path / "нет", max_age_days=30, max_files=5) == 0

    def test_empty_directory(self, tmp_path):
        assert cleanup_old_reports(tmp_path, max_age_days=30, max_files=5) == 0


# ---------------------------------------------------------------------------------------------------------------------
# Сбои файловой системы не ломают формирование отчёта
# ---------------------------------------------------------------------------------------------------------------------
class TestFailures:
    def test_file_removed_by_a_parallel_request_is_not_counted_or_logged(self, tmp_path, monkeypatch, caplog):
        _make_reports(tmp_path, 4)
        original = Path.unlink

        def racing_unlink(self, *args, **kwargs):
            original(self, *args, **kwargs)  # «другой запрос» уже удалил файл...
            raise FileNotFoundError(self)  # ...а наш unlink узнаёт об этом поздно

        monkeypatch.setattr(Path, "unlink", racing_unlink)
        with caplog.at_level(logging.WARNING, logger=report_cleanup.logger.name):
            assert cleanup_old_reports(tmp_path, max_age_days=0, max_files=2) == 0
        assert not [r for r in caplog.records if "Не удалось удалить" in r.getMessage()]

    def test_undeletable_file_is_skipped_with_a_warning(self, tmp_path, monkeypatch, caplog):
        _make_reports(tmp_path, 4)
        original = Path.unlink

        def selective_unlink(self, *args, **kwargs):
            if self.name == "r000.xlsx":
                raise PermissionError("занят другим процессом")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", selective_unlink)
        with caplog.at_level(logging.WARNING, logger=report_cleanup.logger.name):
            removed = cleanup_old_reports(tmp_path, max_age_days=0, max_files=2)
        assert removed == 1, "второй по старшинству файл удалён, исключение не вышло наружу"
        assert any("r000.xlsx" in r.getMessage() for r in caplog.records)
        assert (tmp_path / "r000.xlsx").exists()

    def test_file_that_vanishes_before_stat_is_skipped(self, tmp_path, monkeypatch):
        _make_reports(tmp_path, 4)
        real_modified = report_cleanup._modified
        monkeypatch.setattr(report_cleanup, "_modified", lambda path: None if path.name == "r001.xlsx" else real_modified(path))
        assert cleanup_old_reports(tmp_path, max_age_days=0, max_files=2) == 1
        assert (tmp_path / "r001.xlsx").exists(), "файл без времени изменения не трогаем"


# ---------------------------------------------------------------------------------------------------------------------
# cleanup_before_new_report: возраст — не чаще раза в минуту, квота — всегда
# ---------------------------------------------------------------------------------------------------------------------
class TestThrottle:
    @pytest.fixture()
    def clock(self, monkeypatch):
        state = {"now": 1000.0}
        monkeypatch.setattr(report_cleanup, "_clock", lambda: state["now"])
        monkeypatch.setattr(report_cleanup, "REPORT_RETENTION_DAYS", 30)
        monkeypatch.setattr(report_cleanup, "REPORT_MAX_FILES", 200)
        return state

    def _stale(self, directory: Path, name: str) -> Path:
        path = directory / name
        path.write_bytes(b"x")
        os.utime(path, (0, 0))
        return path

    def test_age_scan_runs_at_most_once_per_interval(self, tmp_path, clock):
        first = self._stale(tmp_path, "first.xlsx")
        assert cleanup_before_new_report(tmp_path) == 1 and not first.exists()

        second = self._stale(tmp_path, "second.xlsx")
        clock["now"] += AGE_SCAN_INTERVAL_SECONDS - 1
        assert cleanup_before_new_report(tmp_path) == 0 and second.exists(), "минуты ещё не прошло"

        clock["now"] += 1
        assert cleanup_before_new_report(tmp_path) == 1 and not second.exists()

    def test_quota_is_enforced_on_every_call_even_between_age_scans(self, tmp_path, clock, monkeypatch):
        monkeypatch.setattr(report_cleanup, "REPORT_MAX_FILES", 3)
        cleanup_before_new_report(tmp_path)  # первый проход (возраст)
        _make_reports(tmp_path, 6)
        clock["now"] += 5
        assert cleanup_before_new_report(tmp_path) == 4, "квота не ждёт минуты: остаётся max_files - 1 под новый файл"
        assert len(_names(tmp_path)) == 2

    def test_directories_are_throttled_independently(self, tmp_path, clock):
        one, two = tmp_path / "one", tmp_path / "two"
        one.mkdir()
        two.mkdir()
        a, b = self._stale(one, "a.xlsx"), self._stale(two, "b.xlsx")
        assert cleanup_before_new_report(one) == 1
        assert cleanup_before_new_report(two) == 1 and not a.exists() and not b.exists()

    def test_disabled_retention_still_enforces_the_quota(self, tmp_path, clock, monkeypatch):
        monkeypatch.setattr(report_cleanup, "REPORT_RETENTION_DAYS", 0)
        monkeypatch.setattr(report_cleanup, "REPORT_MAX_FILES", 5)
        _make_reports(tmp_path, 9, newest_age=400 * 86400)
        assert cleanup_before_new_report(tmp_path) == 5
        assert len(_names(tmp_path)) == 4

    def test_missing_directory_is_not_an_error(self, tmp_path, clock):
        assert cleanup_before_new_report(tmp_path / "нет") == 0


# ---------------------------------------------------------------------------------------------------------------------
# Эндпоинты: 250 отчётов подряд оставляют не больше 200 файлов
# ---------------------------------------------------------------------------------------------------------------------
class TestEndpointsKeepTheQuota:
    @pytest.fixture()
    def report_dir(self, tmp_path, monkeypatch):
        from app.api import report_builder, reports

        monkeypatch.setattr(reports, "REPORT_DIR", tmp_path)
        monkeypatch.setattr(report_builder, "REPORT_DIR", tmp_path)
        return tmp_path

    @pytest.mark.parametrize("retention_days", [30, 0], ids=["retention-30", "retention-disabled"])
    def test_250_reports_in_a_row_leave_at_most_200_files(self, client, report_dir, monkeypatch, retention_days):
        monkeypatch.setattr(report_cleanup, "REPORT_RETENTION_DAYS", retention_days)
        last = None
        for _ in range(250):
            response = client.post(f"{API}/reports/audit-log")
            assert response.status_code == 200, response.text
            last = response.json()["file_name"]
            assert len(_names(report_dir / "audit")) <= 200  # отчёты аудита — в подкаталоге (A-05), квота общая с корнем
        assert len(_names(report_dir / "audit")) == 200, "квота заполнена, но не превышена"
        assert (report_dir / "audit" / last).exists(), "только что созданный отчёт не удаляется"
        assert client.get(f"{API}/reports/audit-log/download/{last}").status_code == 200

    def test_all_three_generating_endpoints_respect_a_small_quota(self, client, report_dir, monkeypatch):
        monkeypatch.setattr(report_cleanup, "REPORT_MAX_FILES", 3)
        monkeypatch.setattr(report_cleanup, "REPORT_RETENTION_DAYS", 0)
        config = {"sheets": [{"title": "Лист1", "columns": [{"width": 25}], "rows": [{"height": 18, "repeat": True, "data_source": {"root_entity": "information-systems"}, "cells": [{"col": 0, "kind": "field", "path": "name"}]}]}]}
        template = client.post(f"{API}/report-templates", json={"name": "Квота А-10", "config": config}).json()["id"]
        for _ in range(3):
            assert client.post(f"{API}/reports/inventory").status_code == 200
            assert client.post(f"{API}/report-templates/{template}/generate").status_code == 200
            assert client.post(f"{API}/reports/audit-log").status_code == 200
            assert len([p for p in report_dir.rglob("*") if p.suffix in {".xlsx", ".docx"}]) <= 3  # корень и audit/ вместе (A-05)

    def test_files_that_are_not_reports_survive_the_quota(self, client, report_dir, monkeypatch):
        monkeypatch.setattr(report_cleanup, "REPORT_MAX_FILES", 2)
        (report_dir / "README.txt").write_text("служебный файл")
        for _ in range(5):
            assert client.post(f"{API}/reports/audit-log").status_code == 200
        assert (report_dir / "README.txt").exists() and len(_names(report_dir / "audit")) == 2


# ---------------------------------------------------------------------------------------------------------------------
# Настройка INFRA_REGISTRY_REPORT_MAX_FILES
# ---------------------------------------------------------------------------------------------------------------------
class TestConfig:
    @staticmethod
    def _load(tmp_path, value: str | None) -> subprocess.CompletedProcess:
        env = {**os.environ, "INFRA_REGISTRY_DATA_DIR": str(tmp_path), "DATABASE_URL": "sqlite:///:memory:", "PYTHONPATH": str(BACKEND_DIR)}
        env.pop("INFRA_REGISTRY_REPORT_MAX_FILES", None)
        if value is not None:
            env["INFRA_REGISTRY_REPORT_MAX_FILES"] = value
        return subprocess.run([sys.executable, "-c", "import app.config as c; print(c.REPORT_MAX_FILES)"], env=env, capture_output=True, text=True, cwd=tmp_path, timeout=120)

    @pytest.mark.parametrize(("value", "expected"), [(None, "200"), ("", "200"), ("   ", "200"), ("50", "50"), ("0", "0")])
    def test_values(self, tmp_path, value, expected):
        result = self._load(tmp_path, value)
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == expected

    @pytest.mark.parametrize("value", ["abc", "-1", "1.5"])
    def test_invalid_value_is_a_clear_startup_error(self, tmp_path, value):
        result = self._load(tmp_path, value)
        assert result.returncode != 0
        assert "INFRA_REGISTRY_REPORT_MAX_FILES" in result.stderr

    def test_default_is_200(self):
        from app.config import REPORT_MAX_FILES

        assert REPORT_MAX_FILES == 200
