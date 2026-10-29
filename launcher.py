from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import sys
import threading
import time
import webbrowser
import urllib.request
from contextlib import closing
from pathlib import Path
from typing import NoReturn

logger = logging.getLogger(__name__)

DB_FILENAME = "infra_registry.db"
BACKUPS_TO_KEEP = 5
SKIP_BACKUP_ENV = "INFRA_REGISTRY_SKIP_BACKUP"


class MigrationBackupError(RuntimeError):
    """Не удалось создать резервную копию БД перед миграцией: миграцию без копии не начинаем."""


def bundle_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def app_dir() -> Path:
    """Каталог приложения: рядом с EXE для frozen-сборки, рядом с launcher.py для исходников."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    base = Path(os.getenv("INFRA_REGISTRY_DATA_DIR", str(app_dir()))).expanduser().resolve()
    base.mkdir(parents=True, exist_ok=True)
    return base


def _backup_pattern(db_path: Path) -> re.Pattern[str]:
    """Маска файлов, которые создаёт и чистит backup_before_migration: `<имя БД>.pre-<8 символов ревизии>.<ГГГГММДД-ЧЧММСС>.bak`.
    Ротация удаляет только такие файлы: чужие `.bak` рядом с базой (в том числе сделанные пользователем) не трогаются."""
    return re.compile(rf"^{re.escape(db_path.stem)}\.pre-[0-9a-z]{{1,8}}\.\d{{8}}-\d{{6}}\.bak$")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _database_state(connection: sqlite3.Connection) -> tuple[bool, set[str]]:
    """(есть ли в БД пользовательские таблицы, текущие ревизии alembic). Пустая БД и БД без alembic_version — пустой набор ревизий."""
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'")}
    revisions: set[str] = set()
    if "alembic_version" in tables:
        revisions = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version") if row[0]}
    return bool(tables - {"alembic_version"}), revisions


def _rotate_backups(db_path: Path, keep: int = BACKUPS_TO_KEEP) -> None:
    """Оставляет `keep` самых новых копий этой БД (по метке времени в имени), остальные удаляет; только файлы по маске."""
    pattern = _backup_pattern(db_path)
    backups = sorted((p for p in db_path.parent.iterdir() if pattern.match(p.name) and p.is_file()), key=lambda p: p.name.split(".")[-2], reverse=True)
    for stale in backups[keep:]:
        try:
            stale.unlink()
        except OSError as exc:
            logger.warning("Не удалось удалить старую резервную копию %s: %s", stale, exc)


def backup_before_migration(db_path: Path, cfg) -> Path | None:
    """Резервная копия SQLite-БД перед миграцией; возвращает путь копии или None, если копия не нужна.

    Нужна, только если файл существует, в нём есть таблицы данных и его ревизия alembic не равна head (БД, уже
    актуальная или только что созданная, не копируется — иначе каждый запуск плодил бы копии). Миграции необратимы
    (часть удаляет данные, DDL в SQLite нетранзакционен): пользователь, обновивший EXE и получивший ошибку миграции,
    иначе не смог бы вернуться к прежней версии.

    Копия делается API `sqlite3.Connection.backup`, а не копированием файла: она согласована, даже если БД кем-то открыта.
    Сначала пишется во временный файл и переименовывается в `.bak` — оборванная копия не выглядит готовой. Хранится не
    более BACKUPS_TO_KEEP последних копий (включая новую). При сбое — MigrationBackupError (миграция не запускается).

    Пример:
        backup = backup_before_migration(data_dir() / DB_FILENAME, cfg)   # -> .../infra_registry.pre-3a7c1e5d.20261024-093000.bak
    """
    from alembic.script import ScriptDirectory

    if not db_path.is_file() or db_path.stat().st_size == 0:
        return None
    heads = set(ScriptDirectory.from_config(cfg).get_heads())
    target = db_path.with_name(f"{db_path.stem}.pre-{min(heads)[:8]}.{_timestamp()}.bak")
    temporary = target.with_name(target.name + ".tmp")
    try:
        with closing(sqlite3.connect(db_path)) as source:
            has_data, current = _database_state(source)
            if not has_data or current == heads:
                return None
            with closing(sqlite3.connect(temporary)) as destination:
                source.backup(destination)
        os.replace(temporary, target)
    except (OSError, sqlite3.Error) as exc:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise MigrationBackupError(f"не удалось создать резервную копию базы {db_path} в {target.parent}: {exc}") from exc
    _rotate_backups(db_path)
    return target


def migrate():
    from alembic import command
    from alembic.config import Config

    root = bundle_dir()
    alembic_root = root / "alembic" if (root / "alembic").exists() else root / "backend" / "alembic"
    ini_path = root / "alembic.ini" if (root / "alembic.ini").exists() else root / "backend" / "alembic.ini"
    db_path = data_dir() / DB_FILENAME
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(alembic_root))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    if os.getenv(SKIP_BACKUP_ENV, "").strip().lower() not in {"1", "true", "yes"}:
        backup = backup_before_migration(db_path, cfg)
        if backup is not None:
            print(f"Резервная копия базы перед обновлением: {backup}")
    command.upgrade(cfg, "head")


def migrate_or_fail() -> None:
    """migrate() для main(): сбой резервной копии — понятная ошибка запуска, а не трассировка; миграция при этом не начата."""
    try:
        migrate()
    except MigrationBackupError as exc:
        fail(f"{exc}\nОсвободите место на диске и проверьте права на запись в каталог с базой. База не изменена. "
             f"Запуск без резервной копии (на свой риск): переменная окружения {SKIP_BACKUP_ENV}=1.")


def open_browser_when_ready(port: int):
    url = f"http://127.0.0.1:{port}/"
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status < 500:
                    webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.25)
    webbrowser.open(url)

def load_exe_settings():
    """Настройки из infra_registry.toml рядом с EXE; при отсутствии файла он создаётся со значениями по умолчанию.

    Ошибка в файле не заменяется молча значениями по умолчанию: администратор, открывший доступ по сети,
    должен узнать, что его запись не применилась. Если же файл нельзя СОЗДАТЬ (каталог только для чтения),
    приложение работает с настройками по умолчанию — то есть только локально, как и без файла."""
    from app.services.exe_settings import SETTINGS_FILENAME, ExeSettings, ensure_settings_file, load_settings

    path = app_dir() / SETTINGS_FILENAME
    try:
        if ensure_settings_file(path):
            print(f"Создан файл настроек: {path}")
    except OSError as exc:
        print(f"Не удалось создать файл настроек {path}: {exc}. Используются настройки по умолчанию (доступ только с этого компьютера).")
        return ExeSettings(), path
    return load_settings(path), path


def fail(message: str) -> NoReturn:
    """Ошибка запуска: в EXE окно консоли закрывается вместе с процессом, поэтому ждём Enter, чтобы текст прочитали."""
    print(f"\nОШИБКА: {message}", file=sys.stderr)
    if getattr(sys, "frozen", False) and sys.stdin is not None and sys.stdin.isatty():
        input("\nНажмите Enter, чтобы закрыть окно...")
    sys.exit(2)


def main():
    parser = argparse.ArgumentParser(description="РИС — Реестр ИТ-инфраструктуры")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически")
    parser.add_argument("--port", type=int, default=None, help="порт (по умолчанию — из файла настроек, 8000)")
    args = parser.parse_args()

    root = bundle_dir()
    sys.path.insert(0, str(bundle_dir() / "backend"))
    sys.path.insert(0, str(bundle_dir()))

    from app.services.exe_settings import SETTINGS_FILENAME, SettingsError

    try:
        settings, settings_path = load_exe_settings()
    except SettingsError as exc:
        fail(f"{exc}\nИсправьте файл {app_dir() / SETTINGS_FILENAME} или удалите его (он будет создан заново).")
    port = args.port if args.port is not None else settings.port

    os.environ["INFRA_REGISTRY_BUNDLE_DIR"] = str(root)
    # Единственный UI — собранный Vue-фронтенд (см. backend/app/config.py:FRONTEND_DIR),
    # упакован в EXE как данные, см. datas в infra_registry.spec.
    os.environ["INFRA_REGISTRY_FRONTEND_DIR"] = str(root / 'frontend-vue' / 'dist')
    os.environ["INFRA_REGISTRY_DATA_DIR"] = str(data_dir())
    os.environ["DATABASE_URL"] = f"sqlite:///{data_dir() / DB_FILENAME}"
    # Список разрешённых клиентов и имён Host читает app.config при импорте — выставляем ДО import app.main.
    os.environ.update(settings.environment())

    migrate_or_fail()

    import uvicorn
    from app.main import app

    if settings.network_access:
        print(f"Доступ по сети разрешён для: {', '.join(settings.allowed_clients)} (порт {port}). Файл настроек: {settings_path}")
    else:
        print(f"Доступ только с этого компьютера. Как открыть доступ другим компьютерам — в файле {settings_path}")

    if settings.open_browser and not args.no_browser:
        threading.Thread(target=lambda: open_browser_when_ready(port), daemon=True).start()
    uvicorn.run(app, host=settings.listen_host, port=port, log_level="info")


if __name__ == "__main__":
    main()
