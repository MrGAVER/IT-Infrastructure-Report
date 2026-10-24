"""A-12: резервная копия SQLite-БД перед миграцией (launcher.backup_before_migration).

Раньше EXE при каждом старте сразу выполнял `alembic upgrade head` на пользовательской БД: часть ревизий необратима
(удаляет данные), DDL в SQLite нетранзакционен, и пользователь, обновивший EXE и получивший ошибку миграции, не имел пути
отката. Теперь перед миграцией старой БД создаётся согласованная копия `<имя>.pre-<ревизия>.<время>.bak`, хранятся 5 последних.

Запуск: pytest backend/tests/test_launcher_backup.py -v  (launcher.py лежит в корне репозитория — тест добавляет его в sys.path)
"""
from __future__ import annotations

import importlib
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent
OLD_REVISION = "c4a8f1d6b937"  # старая ревизия цепочки (используется и другими тестами миграций)
DB_NAME = "infra_registry.db"


@pytest.fixture()
def launcher(monkeypatch):
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    sys.modules.pop("launcher", None)
    module = importlib.import_module("launcher")
    yield module
    sys.modules.pop("launcher", None)


def _make_cfg(db_path: Path) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    cfg.attributes["configure_logger"] = False
    return cfg


@pytest.fixture()
def point_alembic_at(monkeypatch):
    """env.py берёт адрес БД из app.config.DATABASE_URL (так же, как в EXE, где его задаёт launcher.main())."""
    import app.config as app_config

    def _point(db_path: Path) -> None:
        monkeypatch.setattr(app_config, "DATABASE_URL", f"sqlite:///{db_path}")

    return _point


@pytest.fixture(scope="module")
def head_revisions() -> set[str]:
    return set(ScriptDirectory.from_config(_make_cfg(Path("unused.db"))).get_heads())


@pytest.fixture(scope="module")
def templates(tmp_path_factory):
    """Готовые БД: на старой ревизии (с одной записью) и на head — миграции дорогие, поэтому один раз на модуль."""
    import app.config as app_config

    root = tmp_path_factory.mktemp("templates")
    patch = pytest.MonkeyPatch()
    try:
        old, head = root / "old.db", root / "head.db"
        for path, revision in ((old, OLD_REVISION), (head, "head")):
            patch.setattr(app_config, "DATABASE_URL", f"sqlite:///{path}")
            command.upgrade(_make_cfg(path), revision)
        with sqlite3.connect(old) as conn:
            conn.execute("INSERT INTO manufacturers (id, name, created_at, updated_at) VALUES ('m-1', 'Производитель А-12', '2026-01-01', '2026-01-01')")
    finally:
        patch.undo()
    return {"old": old, "head": head}


@pytest.fixture()
def old_db(templates, tmp_path) -> Path:
    target = tmp_path / DB_NAME
    shutil.copy(templates["old"], target)
    return target


@pytest.fixture()
def head_db(templates, tmp_path) -> Path:
    target = tmp_path / DB_NAME
    shutil.copy(templates["head"], target)
    return target


def _backups(directory: Path) -> list[str]:
    return sorted(p.name for p in directory.iterdir() if p.suffix == ".bak")


def _dump(path: Path) -> list[str]:
    with sqlite3.connect(path) as conn:
        return list(conn.iterdump())


# ---------------------------------------------------------------------------------------------------------------------
# Когда копия делается
# ---------------------------------------------------------------------------------------------------------------------
class TestWhenBackupIsMade:
    def test_old_revision_gets_a_backup_with_the_same_rows(self, launcher, old_db, tmp_path):
        before = _dump(old_db)
        backup = launcher.backup_before_migration(old_db, _make_cfg(old_db))

        assert backup is not None and backup.parent == tmp_path
        assert launcher._backup_pattern(old_db).match(backup.name), backup.name
        assert backup.name.startswith("infra_registry.pre-") and backup.suffix == ".bak"
        with sqlite3.connect(backup) as conn:
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert conn.execute("SELECT name FROM manufacturers WHERE id = 'm-1'").fetchone() == ("Производитель А-12",)
            assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (OLD_REVISION,)
        assert _dump(backup) == before, "копия — те же таблицы и строки"
        assert _dump(old_db) == before, "исходная БД не тронута"
        assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == [], "временный файл не остаётся"

    def test_head_revision_gets_no_backup(self, launcher, head_db, tmp_path, head_revisions):
        assert launcher.backup_before_migration(head_db, _make_cfg(head_db)) is None
        assert _backups(tmp_path) == []

    @pytest.mark.parametrize("kind", ["missing", "zero-bytes", "no-tables"])
    def test_nothing_to_preserve_means_no_backup(self, launcher, tmp_path, kind):
        db_path = tmp_path / DB_NAME
        if kind == "zero-bytes":
            db_path.write_bytes(b"")
        elif kind == "no-tables":
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE t (x)")
                conn.execute("DROP TABLE t")
        assert launcher.backup_before_migration(db_path, _make_cfg(db_path)) is None
        assert _backups(tmp_path) == []
        assert db_path.exists() == (kind != "missing"), "проверка не создаёт файл БД"

    def test_database_with_tables_but_without_alembic_version_is_backed_up(self, launcher, tmp_path):
        """Старая БД, созданная без alembic (или с потерянной таблицей версий): миграция её изменит — копия нужна."""
        db_path = tmp_path / DB_NAME
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE manufacturers (id TEXT, name TEXT)")
            conn.execute("INSERT INTO manufacturers VALUES ('1', 'Старый')")
        backup = launcher.backup_before_migration(db_path, _make_cfg(db_path))
        assert backup is not None
        with sqlite3.connect(backup) as conn:
            assert conn.execute("SELECT name FROM manufacturers").fetchall() == [("Старый",)]

    def test_only_the_alembic_table_does_not_count_as_data(self, launcher, tmp_path):
        db_path = tmp_path / DB_NAME
        with sqlite3.connect(db_path) as conn:
            conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        assert launcher.backup_before_migration(db_path, _make_cfg(db_path)) is None

    def test_backup_name_carries_the_target_revision_and_the_time(self, launcher, old_db, monkeypatch, head_revisions):
        monkeypatch.setattr(launcher, "_timestamp", lambda: "20261024-093000")
        backup = launcher.backup_before_migration(old_db, _make_cfg(old_db))
        assert backup.name == f"infra_registry.pre-{min(head_revisions)[:8]}.20261024-093000.bak"

    def test_backup_is_consistent_while_another_connection_has_uncommitted_changes(self, launcher, old_db):
        """Копия — через sqlite3.backup, а не копирование файла: незавершённая транзакция в неё не попадает."""
        other = sqlite3.connect(old_db, isolation_level=None)
        try:
            other.execute("BEGIN IMMEDIATE")
            other.execute("INSERT INTO manufacturers (id, name, created_at, updated_at) VALUES ('m-2', 'Не зафиксирована', '2026', '2026')")
            backup = launcher.backup_before_migration(old_db, _make_cfg(old_db))
        finally:
            other.execute("ROLLBACK")
            other.close()
        assert backup is not None
        with sqlite3.connect(backup) as conn:
            assert conn.execute("SELECT id FROM manufacturers ORDER BY id").fetchall() == [("m-1",)]


# ---------------------------------------------------------------------------------------------------------------------
# Ротация
# ---------------------------------------------------------------------------------------------------------------------
class TestRotation:
    def test_keeps_the_five_newest_backups(self, launcher, old_db, tmp_path, monkeypatch):
        stamps = iter(f"2026102{day}-120000" for day in range(1, 8))
        monkeypatch.setattr(launcher, "_timestamp", lambda: next(stamps))
        created = [launcher.backup_before_migration(old_db, _make_cfg(old_db)) for _ in range(7)]
        assert all(created)
        remaining = _backups(tmp_path)
        assert launcher.BACKUPS_TO_KEEP == 5 and len(remaining) == 5
        assert remaining == sorted(p.name for p in created[2:]), "остались пять самых новых, две старейшие удалены"
        assert not created[0].exists() and not created[1].exists() and created[-1].exists()

    def test_only_files_of_this_mask_are_removed(self, launcher, old_db, tmp_path, monkeypatch):
        foreign = [
            tmp_path / "manual_copy.bak",                                  # копия пользователя
            tmp_path / "infra_registry.bak",                               # без метки ревизии/времени
            tmp_path / "infra_registry.pre-12345678.20200101-000000.bak.tmp",  # временный файл, не копия
            tmp_path / "other.pre-12345678.20200101-000000.bak",           # копия другой БД
            tmp_path / "infra_registry.pre-12345678.2020-01-01.bak",       # похоже, но не маска
        ]
        for path in foreign:
            path.write_bytes(b"x")
        (tmp_path / "infra_registry.pre-12345678.20200102-000000.bak").mkdir()  # каталог с «подходящим» именем
        stamps = iter(f"2026102{day}-120000" for day in range(1, 8))
        monkeypatch.setattr(launcher, "_timestamp", lambda: next(stamps))
        for _ in range(7):
            launcher.backup_before_migration(old_db, _make_cfg(old_db))
        assert all(path.exists() for path in foreign)
        assert (tmp_path / "infra_registry.pre-12345678.20200102-000000.bak").is_dir()
        assert old_db.exists()
        ours = [p for p in tmp_path.iterdir() if launcher._backup_pattern(old_db).match(p.name) and p.is_file()]
        assert len(ours) == 5

    def test_a_backup_that_cannot_be_deleted_is_a_warning_not_an_error(self, launcher, old_db, tmp_path, monkeypatch, caplog):
        stamps = iter(f"2026102{day}-120000" for day in range(1, 8))
        monkeypatch.setattr(launcher, "_timestamp", lambda: next(stamps))
        for _ in range(5):
            launcher.backup_before_migration(old_db, _make_cfg(old_db))
        original = Path.unlink

        def stubborn(self, *args, **kwargs):
            if self.name.endswith("20261021-120000.bak"):
                raise PermissionError("занят другим процессом")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", stubborn)
        with caplog.at_level("WARNING", logger=launcher.logger.name):
            assert launcher.backup_before_migration(old_db, _make_cfg(old_db)) is not None
        assert any("20261021-120000.bak" in r.getMessage() for r in caplog.records)


# ---------------------------------------------------------------------------------------------------------------------
# Сбои
# ---------------------------------------------------------------------------------------------------------------------
class TestFailures:
    def test_failed_backup_raises_and_leaves_no_partial_file(self, launcher, old_db, tmp_path, monkeypatch):
        real_connect = sqlite3.connect

        def disk_full(database, *args, **kwargs):
            if str(database).endswith(".tmp"):
                raise sqlite3.OperationalError("database or disk is full")
            return real_connect(database, *args, **kwargs)

        monkeypatch.setattr(launcher.sqlite3, "connect", disk_full)
        before = _dump(old_db)
        with pytest.raises(launcher.MigrationBackupError, match="резервную копию"):
            launcher.backup_before_migration(old_db, _make_cfg(old_db))
        monkeypatch.undo()
        assert _backups(tmp_path) == [] and not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
        assert _dump(old_db) == before

    def test_corrupt_file_is_reported_as_a_backup_error(self, launcher, tmp_path):
        db_path = tmp_path / DB_NAME
        db_path.write_bytes("это не база данных SQLite".encode() * 100)
        with pytest.raises(launcher.MigrationBackupError):
            launcher.backup_before_migration(db_path, _make_cfg(db_path))

    def test_migrate_or_fail_turns_the_error_into_a_clear_exit(self, launcher, monkeypatch, capsys):
        def broken():
            raise launcher.MigrationBackupError("не удалось создать резервную копию базы X: диск заполнен")

        monkeypatch.setattr(launcher, "migrate", broken)
        with pytest.raises(SystemExit) as exit_info:
            launcher.migrate_or_fail()
        assert exit_info.value.code == 2
        error = capsys.readouterr().err
        assert "диск заполнен" in error and "База не изменена" in error and launcher.SKIP_BACKUP_ENV in error


# ---------------------------------------------------------------------------------------------------------------------
# migrate(): копия делается до upgrade
# ---------------------------------------------------------------------------------------------------------------------
class TestMigrateWiring:
    @pytest.fixture()
    def data_dir(self, tmp_path, monkeypatch, point_alembic_at):
        monkeypatch.setenv("INFRA_REGISTRY_DATA_DIR", str(tmp_path))
        monkeypatch.delenv(launcher_env := "INFRA_REGISTRY_SKIP_BACKUP", raising=False)
        point_alembic_at(tmp_path / DB_NAME)
        assert launcher_env
        return tmp_path

    def test_old_database_is_backed_up_then_upgraded_and_the_path_is_printed(self, launcher, templates, data_dir, capsys, head_revisions):
        shutil.copy(templates["old"], data_dir / DB_NAME)
        launcher.migrate()
        backups = _backups(data_dir)
        assert len(backups) == 1
        with sqlite3.connect(data_dir / DB_NAME) as conn:
            assert {r[0] for r in conn.execute("SELECT version_num FROM alembic_version")} == head_revisions, "миграция выполнена"
        with sqlite3.connect(data_dir / backups[0]) as conn:
            assert conn.execute("SELECT version_num FROM alembic_version").fetchone() == (OLD_REVISION,), "копия — до миграции"
        assert str(data_dir / backups[0]) in capsys.readouterr().out

    def test_second_start_on_the_current_database_makes_no_new_backup(self, launcher, templates, data_dir):
        shutil.copy(templates["old"], data_dir / DB_NAME)
        launcher.migrate()
        launcher.migrate()
        assert len(_backups(data_dir)) == 1

    def test_first_start_creates_the_database_without_a_backup(self, launcher, data_dir):
        assert not (data_dir / DB_NAME).exists()
        launcher.migrate()
        assert (data_dir / DB_NAME).is_file() and _backups(data_dir) == []

    def test_backup_failure_prevents_the_migration(self, launcher, templates, data_dir, monkeypatch):
        shutil.copy(templates["old"], data_dir / DB_NAME)
        upgrades = []
        monkeypatch.setattr(command, "upgrade", lambda *args, **kwargs: upgrades.append(args))
        monkeypatch.setattr(launcher, "backup_before_migration", lambda *a, **k: (_ for _ in ()).throw(launcher.MigrationBackupError("нет места")))
        with pytest.raises(launcher.MigrationBackupError):
            launcher.migrate()
        assert upgrades == [], "без копии миграцию не начинаем"

    @pytest.mark.parametrize("value", ["1", "true", "YES"])
    def test_skip_variable_runs_the_migration_without_a_backup(self, launcher, templates, data_dir, monkeypatch, value):
        shutil.copy(templates["old"], data_dir / DB_NAME)
        monkeypatch.setenv(launcher.SKIP_BACKUP_ENV, value)
        launcher.migrate()
        assert _backups(data_dir) == []
        with sqlite3.connect(data_dir / DB_NAME) as conn:
            assert conn.execute("SELECT count(*) FROM alembic_version").fetchone()[0] >= 1

    @pytest.mark.parametrize("value", ["", "0", "no", "off"])
    def test_other_values_do_not_disable_the_backup(self, launcher, templates, data_dir, monkeypatch, value):
        shutil.copy(templates["old"], data_dir / DB_NAME)
        monkeypatch.setenv(launcher.SKIP_BACKUP_ENV, value)
        launcher.migrate()
        assert len(_backups(data_dir)) == 1
