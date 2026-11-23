"""Плановые резервные копии SQLite: сама копия (`db_backup.backup_scheduled`) и планировщик (`services/backup_scheduler.py`).

Копия перед миграцией (`backup_before_migration`) защищает от неудачного обновления, но не от потери данных между обновлениями:
сбой диска, ошибочное массовое удаление, вредоносная правка. Для этого приложение само делает копии по расписанию.

Запуск: pytest backend/tests/test_review_p3_scheduled_backup.py -v
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import sqlite3
import time
from pathlib import Path

import pytest

from app import config
from app.services import backup_scheduler, db_backup
from app.services.db_backup import ScheduledBackupError, auto_backup_time, backup_scheduled, latest_auto_backup

DAY = 24 * 3600


def _make_database(path: Path, rows: int = 3) -> Path:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS devices (id INTEGER PRIMARY KEY, name TEXT)")
        connection.executemany("INSERT INTO devices (name) VALUES (?)", [(f"srv-{i}",) for i in range(rows)])
    connection.close()
    return path


def _touch_database(path: Path, seconds_ahead: float = 10.0) -> None:
    """Имитирует правку базы: время изменения файла сдвигается вперёд (разрешение времени файловой системы не даёт различить правки,
    сделанные в одну и ту же долю секунды)."""
    later = time.time() + seconds_ahead
    os.utime(path, (later, later))


def _names(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir())


@pytest.fixture()
def database(tmp_path) -> Path:
    return _make_database(tmp_path / "infra_registry.db")


@pytest.fixture()
def backup_dir(tmp_path) -> Path:
    return tmp_path / "backups"


@pytest.fixture()
def distinct_timestamps(monkeypatch):
    """Имя копии содержит секунды: две копии за одну секунду получили бы одно имя. Тесту нужны разные."""
    counter = iter(range(1, 1000))
    monkeypatch.setattr(db_backup, "_timestamp", lambda: f"20261124-{next(counter):06d}")


# ---------------------------------------------------------------------------
# backup_scheduled
# ---------------------------------------------------------------------------
class TestBackupScheduled:
    def test_makes_a_consistent_verified_copy_named_by_the_auto_mask(self, database, backup_dir):
        backup = backup_scheduled(database, backup_dir)

        assert backup is not None and backup.parent == backup_dir
        assert backup.name.startswith("infra_registry.auto.") and backup.suffix == ".bak"
        with sqlite3.connect(backup) as copy:
            assert copy.execute("PRAGMA quick_check").fetchone() == ("ok",)
            assert copy.execute("SELECT name FROM devices ORDER BY id").fetchall() == [("srv-0",), ("srv-1",), ("srv-2",)]
        assert _names(backup_dir) == [backup.name], "временный файл не остаётся"

    def test_unchanged_database_is_not_copied_again(self, database, backup_dir, distinct_timestamps):
        first = backup_scheduled(database, backup_dir)

        assert backup_scheduled(database, backup_dir) is None
        assert _names(backup_dir) == [first.name]

    def test_changed_database_gets_a_new_copy_with_the_new_data(self, database, backup_dir, distinct_timestamps):
        first = backup_scheduled(database, backup_dir)
        with sqlite3.connect(database) as connection:
            connection.execute("INSERT INTO devices (name) VALUES ('srv-new')")
        connection.close()
        _touch_database(database)

        second = backup_scheduled(database, backup_dir)

        assert second is not None and second != first
        with sqlite3.connect(second) as copy:
            assert copy.execute("SELECT COUNT(*) FROM devices").fetchone() == (4,)
        assert latest_auto_backup(database, backup_dir) == second

    def test_rotation_keeps_the_newest_and_touches_only_auto_files(self, database, backup_dir, distinct_timestamps):
        backup_dir.mkdir()
        foreign = [
            backup_dir / "infra_registry.pre-3a7c1e5d.20250101-000000.bak",  # копия перед миграцией
            backup_dir / "my_manual_copy.bak",
            backup_dir / "other_db.auto.20250101-000000.bak",  # плановая копия ДРУГОЙ базы
        ]
        for path in foreign:
            path.write_bytes(b"x")
        made = []
        for _ in range(5):
            made.append(backup_scheduled(database, backup_dir, keep=3))
            _touch_database(database, 10 * (len(made) + 1))

        auto = sorted(p.name for p in backup_dir.glob("infra_registry.auto.*.bak"))
        assert auto == sorted(p.name for p in made[-3:]), "остаются три самых новых"
        assert all(path.exists() for path in foreign), "чужие файлы ротация не трогает"

    def test_copy_failing_quick_check_is_removed_and_reported(self, database, backup_dir, monkeypatch):
        real_connect = sqlite3.connect

        class Damaged(sqlite3.Connection):
            def execute(self, sql, *args):
                if sql == "PRAGMA quick_check":
                    return super().execute("SELECT 'row 1 missing from index idx_name'")
                return super().execute(sql, *args)

        monkeypatch.setattr(db_backup.sqlite3, "connect", lambda *a, **k: real_connect(*a, factory=Damaged, **k))

        with pytest.raises(ScheduledBackupError, match="quick_check"):
            backup_scheduled(database, backup_dir)

        assert _names(backup_dir) == [], "негодная копия не остаётся ни под видом .bak, ни как временный файл"
        monkeypatch.undo()
        with sqlite3.connect(database) as source:
            assert source.execute("SELECT COUNT(*) FROM devices").fetchone() == (3,), "исходная база не тронута"

    def test_unwritable_target_is_reported_with_the_path(self, database, tmp_path):
        not_a_directory = tmp_path / "occupied"
        not_a_directory.write_text("файл на месте каталога")

        with pytest.raises(ScheduledBackupError, match="occupied"):
            backup_scheduled(database, not_a_directory)

    def test_missing_or_empty_database_is_not_created_by_the_backup(self, tmp_path, backup_dir):
        missing = tmp_path / "absent.db"
        empty = tmp_path / "empty.db"
        empty.write_bytes(b"")

        assert backup_scheduled(missing, backup_dir) is None
        assert backup_scheduled(empty, backup_dir) is None
        assert not missing.exists() and not backup_dir.exists()

    def test_keep_must_be_positive(self, database, backup_dir):
        with pytest.raises(ValueError, match="keep"):
            backup_scheduled(database, backup_dir, keep=0)

    def test_change_during_the_copy_makes_the_next_run_copy_again(self, database, backup_dir, monkeypatch, distinct_timestamps):
        """Копии выставляется время изменения базы, замеренное ДО копирования: правка, попавшая в базу посреди копирования, делает базу
        «новее» копии, и следующий запуск её не пропустит (иначе новые данные ждали бы следующей правки, которой может и не быть)."""
        real_connect = sqlite3.connect

        class WrittenDuringCopy(sqlite3.Connection):
            def backup(self, target, **kwargs):
                time.sleep(0.02)
                _touch_database(database, seconds_ahead=0)  # база изменилась, пока копия ещё не дописана
                super().backup(target, **kwargs)

        monkeypatch.setattr(db_backup.sqlite3, "connect", lambda *a, **k: real_connect(*a, factory=WrittenDuringCopy, **k))
        backup_scheduled(database, backup_dir)
        monkeypatch.undo()

        assert backup_scheduled(database, backup_dir) is not None

    def test_copy_is_private_to_the_owner_on_posix(self, database, backup_dir):
        """В копии хэши паролей и весь журнал аудита: каталог и файл — только владельцу (на Windows права наследуются от каталога)."""
        backup = backup_scheduled(database, backup_dir)

        if os.name == "posix":
            assert backup_dir.stat().st_mode & 0o777 == 0o700
            assert backup.stat().st_mode & 0o777 == 0o600

    def test_abandoned_temporary_files_are_cleaned_but_fresh_ones_are_kept(self, database, backup_dir, distinct_timestamps):
        backup_dir.mkdir()
        old = backup_dir / "infra_registry.auto.20250101-000000.bak.tmp"
        fresh = backup_dir / "infra_registry.auto.20250102-000000.bak.tmp"
        for path in (old, fresh):
            path.write_bytes(b"partial")
        long_ago = time.time() - 2 * 3600
        os.utime(old, (long_ago, long_ago))

        backup_scheduled(database, backup_dir)

        assert not old.exists() and fresh.exists()

    def test_copy_time_is_read_from_the_name(self, database, backup_dir):
        backup = backup_scheduled(database, backup_dir)

        assert abs(auto_backup_time(backup) - time.time()) < 5


# ---------------------------------------------------------------------------
# Планировщик
# ---------------------------------------------------------------------------
def _fake_copy_named(directory: Path, age_seconds: float) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() - age_seconds))
    path = directory / f"infra_registry.auto.{stamp}.bak"
    path.write_bytes(b"x")
    return path


class TestSecondsUntilDue:
    def test_no_copies_means_due_now(self, database, backup_dir):
        assert backup_scheduler.seconds_until_due(database, backup_dir, DAY) == 0

    def test_recent_copy_waits_for_the_rest_of_the_interval(self, database, backup_dir):
        _fake_copy_named(backup_dir, age_seconds=3600)

        assert DAY - 3600 - 5 < backup_scheduler.seconds_until_due(database, backup_dir, DAY) <= DAY - 3600 + 1

    def test_copy_older_than_the_interval_means_due_now(self, database, backup_dir):
        """EXE выключали на ночь: при запуске последняя копия «старше интервала» — копия делается сразу."""
        _fake_copy_named(backup_dir, age_seconds=DAY + 60)

        assert backup_scheduler.seconds_until_due(database, backup_dir, DAY) == 0

    def test_copies_of_another_database_do_not_count(self, tmp_path, database, backup_dir):
        backup_dir.mkdir()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        (backup_dir / f"other.auto.{stamp}.bak").write_bytes(b"x")

        assert backup_scheduler.seconds_until_due(database, backup_dir, DAY) == 0


class _SchedulerHarness:
    """Прогон планировщика без реального ожидания: `asyncio.sleep` записывает запрошенные паузы и сразу возвращается, а после заданного
    числа пауз задача зависает и отменяется. Саму копию заменяет заглушка со сценарием ответов."""

    def __init__(self, monkeypatch, outcomes: list):
        self.delays: list[float] = []
        self.calls: list[tuple] = []
        self.events: list[str] = []
        self._outcomes = iter(outcomes)
        self._sleeps_wanted = len(outcomes) + 1  # пауза перед каждой копией и ещё одна после последней
        self.finished = asyncio.Event  # заменяется событием внутри цикла событий в run()
        real_sleep = asyncio.sleep
        harness = self

        async def fake_sleep(delay):
            harness.delays.append(delay)
            harness.events.append("sleep")
            if len(harness.delays) >= harness._sleeps_wanted:
                harness.finished.set()
                await real_sleep(3600)  # дальше задача ждёт отмены
            await real_sleep(0)

        def fake_backup(*args):
            harness.calls.append(args)
            harness.events.append("backup")
            outcome = next(harness._outcomes)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        monkeypatch.setattr(backup_scheduler.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(backup_scheduler, "backup_scheduled", fake_backup)

    def run(self, db_path: Path, backup_dir: Path, interval_hours: float = 24, keep: int = 7) -> asyncio.Task:
        async def scenario():
            self.finished = asyncio.Event()
            task = asyncio.create_task(backup_scheduler.run_scheduled_backups(db_path, backup_dir, interval_hours, keep))
            await self.finished.wait()
            await backup_scheduler.stop_backup_scheduler(task)
            return task

        return asyncio.run(scenario())


class TestRunScheduledBackups:
    def test_first_copy_at_start_when_there_are_none_then_every_interval(self, database, backup_dir, monkeypatch):
        harness = _SchedulerHarness(monkeypatch, [Path("a.bak"), Path("b.bak")])

        task = harness.run(database, backup_dir, interval_hours=24, keep=5)

        assert harness.delays == [0, DAY, DAY]
        assert harness.events == ["sleep", "backup", "sleep", "backup", "sleep"]
        assert harness.calls[0] == (database, backup_dir, 5)
        assert task.cancelled()

    def test_recent_copy_postpones_the_first_run(self, database, backup_dir, monkeypatch):
        _fake_copy_named(backup_dir, age_seconds=6 * 3600)
        harness = _SchedulerHarness(monkeypatch, [None])

        harness.run(database, backup_dir, interval_hours=24)

        assert 18 * 3600 - 5 < harness.delays[0] <= 18 * 3600 + 1, "ждём остаток интервала, а не делаем копию на каждом запуске"
        assert harness.delays[1] == DAY

    def test_unchanged_database_just_waits_for_the_next_interval(self, database, backup_dir, monkeypatch, caplog):
        harness = _SchedulerHarness(monkeypatch, [None])

        with caplog.at_level(logging.INFO, logger=backup_scheduler.logger.name):
            harness.run(database, backup_dir)

        assert harness.delays == [0, DAY]
        assert "Создана плановая копия" not in caplog.text

    def test_failure_is_logged_and_retried_within_the_hour_and_the_task_survives(self, database, backup_dir, monkeypatch, caplog):
        harness = _SchedulerHarness(monkeypatch, [ScheduledBackupError("нет места на диске"), Path("ok.bak")])

        with caplog.at_level(logging.INFO, logger=backup_scheduler.logger.name):
            task = harness.run(database, backup_dir, interval_hours=24)

        assert harness.delays == [0, 3600, DAY]
        assert any(r.levelno == logging.ERROR and "нет места на диске" in r.getMessage() for r in caplog.records)
        assert "Создана плановая копия базы: ok.bak" in caplog.text
        assert task.cancelled(), "задача завершилась отменой, а не ошибкой"

    def test_unexpected_error_is_logged_with_traceback_and_does_not_kill_the_task(self, database, backup_dir, monkeypatch, caplog):
        harness = _SchedulerHarness(monkeypatch, [RuntimeError("сюрприз"), None])

        with caplog.at_level(logging.ERROR, logger=backup_scheduler.logger.name):
            harness.run(database, backup_dir)

        assert harness.delays[:2] == [0, 3600]
        assert any(record.exc_info and "сюрприз" in str(record.exc_info[1]) for record in caplog.records)

    def test_retry_is_not_longer_than_a_short_interval(self, database, backup_dir, monkeypatch):
        harness = _SchedulerHarness(monkeypatch, [ScheduledBackupError("x"), None])

        harness.run(database, backup_dir, interval_hours=0.25)

        assert harness.delays == [0, 900, 900]


# ---------------------------------------------------------------------------
# Запуск из lifespan и настройки
# ---------------------------------------------------------------------------
def _settings(monkeypatch, **changes):
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, **changes))


class TestStartBackupScheduler:
    def test_zero_interval_means_no_task(self, monkeypatch, database, tmp_path):
        _settings(monkeypatch, database_url=f"sqlite:///{database}", backup_interval_hours=0, backup_dir=tmp_path / "b")

        async def scenario():
            return backup_scheduler.start_backup_scheduler()

        assert asyncio.run(scenario()) is None

    @pytest.mark.parametrize("url", ["sqlite:///:memory:", "postgresql+psycopg://u:p@localhost/db"])
    def test_non_file_databases_get_no_task(self, monkeypatch, tmp_path, url):
        _settings(monkeypatch, database_url=url, backup_interval_hours=24, backup_dir=tmp_path / "b")

        async def scenario():
            return backup_scheduler.start_backup_scheduler()

        assert asyncio.run(scenario()) is None

    def test_stopping_none_is_a_noop(self):
        asyncio.run(backup_scheduler.stop_backup_scheduler(None))

    def test_lifespan_makes_a_startup_copy_and_stops_the_task_on_shutdown(self, client_factory, monkeypatch, database, tmp_path):
        target = tmp_path / "scheduled"
        _settings(monkeypatch, database_url=f"sqlite:///{database}", backup_interval_hours=24, backup_dir=target)
        tasks_seen: list[asyncio.Task] = []
        real_start = backup_scheduler.start_backup_scheduler

        def spy():
            task = real_start()
            tasks_seen.append(task)
            return task

        from app import main as app_main

        stopped: list = []
        real_stop = backup_scheduler.stop_backup_scheduler

        async def stop_spy(task):
            stopped.append(task)
            await real_stop(task)

        monkeypatch.setattr(app_main, "start_backup_scheduler", spy)
        monkeypatch.setattr(app_main, "stop_backup_scheduler", stop_spy)
        client = client_factory()

        deadline = time.time() + 15
        while time.time() < deadline and latest_auto_backup(database, target) is None:
            time.sleep(0.05)
        assert latest_auto_backup(database, target) is not None, "копия при старте приложения"
        assert len(tasks_seen) == 1 and tasks_seen[0] is not None and not tasks_seen[0].done()

        client.__exit__(None, None, None)
        assert stopped == tasks_seen, "lifespan остановил именно запущенную им задачу"
        assert tasks_seen[0].cancelled(), "задача отменена при остановке приложения"


class TestSettings:
    def test_defaults(self, tmp_path):
        settings = config.Settings.from_env({"INFRA_REGISTRY_DATA_DIR": str(tmp_path)})

        assert (settings.backup_interval_hours, settings.backup_keep) == (24.0, 7)
        assert settings.backup_dir == tmp_path.resolve() / "backups", "по умолчанию — каталог данных, а не папка рядом с файлом БД"

    def test_environment_overrides_including_fractional_interval(self, tmp_path):
        target = tmp_path / "elsewhere"
        settings = config.Settings.from_env(
            {
                "INFRA_REGISTRY_BACKUP_INTERVAL_HOURS": "0.5",
                "INFRA_REGISTRY_BACKUP_KEEP": "30",
                "INFRA_REGISTRY_BACKUP_DIR": str(target),
            }
        )

        assert (settings.backup_interval_hours, settings.backup_keep, settings.backup_dir) == (0.5, 30, target)

    def test_empty_values_mean_defaults_like_other_numbers(self, tmp_path):
        settings = config.Settings.from_env(
            {
                "INFRA_REGISTRY_DATA_DIR": str(tmp_path),
                "INFRA_REGISTRY_BACKUP_INTERVAL_HOURS": "",
                "INFRA_REGISTRY_BACKUP_KEEP": " ",
                "INFRA_REGISTRY_BACKUP_DIR": "",
            }
        )

        assert (settings.backup_interval_hours, settings.backup_keep, settings.backup_dir) == (24.0, 7, tmp_path.resolve() / "backups")

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("INFRA_REGISTRY_BACKUP_INTERVAL_HOURS", "-1"),
            ("INFRA_REGISTRY_BACKUP_INTERVAL_HOURS", "часто"),
            ("INFRA_REGISTRY_BACKUP_KEEP", "0"),
            ("INFRA_REGISTRY_BACKUP_KEEP", "семь"),
            ("INFRA_REGISTRY_BACKUP_DIR", "relative/backups"),
        ],
    )
    def test_invalid_values_stop_startup_naming_the_variable(self, name, value):
        with pytest.raises(ValueError, match=name):
            config.Settings.from_env({name: value})
