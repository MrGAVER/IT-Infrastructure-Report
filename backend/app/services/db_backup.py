"""Резервная копия SQLite-БД перед миграцией Alembic — одна реализация для EXE (launcher.py) и Docker (docker-entrypoint.sh).

Часть миграций необратима (удаляет данные, см. README, «Обновление»), а DDL в SQLite нетранзакционен: обновление, оборвавшееся на
середине, оставляет базу в промежуточном состоянии, и без копии вернуться к прежней версии нельзя. Поэтому перед `alembic upgrade head`
старой базы создаётся согласованная копия `<имя БД>.pre-<8 символов ревизии>.<ГГГГММДД-ЧЧММСС>.bak`; хранятся пять последних.

Запуск из командной строки (так точка входа Docker-образа вызывает копирование до миграции):

    python -m app.services.db_backup

Команда берёт адрес БД из app.config (DATABASE_URL или части POSTGRES_*), копирует только SQLite и завершается кодом 1, если копию
сделать не удалось, — тогда `docker-entrypoint.sh` (`set -e`) не доходит до миграции. Для PostgreSQL копию делает оператор средствами
СУБД (pg_dump, профиль `backup` в docker-compose.yml): команда сообщает об этом и ничего не делает. Переменная окружения
INFRA_REGISTRY_SKIP_BACKUP=1 отключает копирование (на свой риск).
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
import sys
import time
from contextlib import closing
from pathlib import Path

from sqlalchemy.engine import make_url

logger = logging.getLogger(__name__)

BACKUPS_TO_KEEP = 5
SKIP_BACKUP_ENV = "INFRA_REGISTRY_SKIP_BACKUP"
_SKIP_VALUES = {"1", "true", "yes"}


class MigrationBackupError(RuntimeError):
    """Не удалось создать резервную копию БД перед миграцией: миграцию без копии не начинаем."""


def backup_skipped_by_environment() -> bool:
    """Оператор осознанно отключил копирование (INFRA_REGISTRY_SKIP_BACKUP = 1/true/yes без учёта регистра); остальные значения не
    отключают."""
    return os.getenv(SKIP_BACKUP_ENV, "").strip().lower() in _SKIP_VALUES


def _backup_pattern(db_path: Path) -> re.Pattern[str]:
    """Маска файлов, которые создаёт и чистит backup_before_migration: `<имя БД>.pre-<8 символов ревизии>.<ГГГГММДД-ЧЧММСС>.bak`.
    Ротация удаляет только такие файлы: чужие `.bak` рядом с базой (в том числе сделанные пользователем) не трогаются."""
    return re.compile(rf"^{re.escape(db_path.stem)}\.pre-[0-9a-z]{{1,8}}\.\d{{8}}-\d{{6}}\.bak$")


def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _database_state(connection: sqlite3.Connection) -> tuple[bool, set[str]]:
    """(есть ли в БД пользовательские таблицы, текущие ревизии alembic). Пустая БД и БД без alembic_version — пустой набор ревизий."""
    tables = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\'")
    }
    revisions: set[str] = set()
    if "alembic_version" in tables:
        revisions = {row[0] for row in connection.execute("SELECT version_num FROM alembic_version") if row[0]}
    return bool(tables - {"alembic_version"}), revisions


def _rotate_backups(db_path: Path, keep: int = BACKUPS_TO_KEEP) -> None:
    """Оставляет `keep` самых новых копий этой БД (по метке времени в имени), остальные удаляет; только файлы по маске."""
    pattern = _backup_pattern(db_path)
    backups = sorted(
        (p for p in db_path.parent.iterdir() if pattern.match(p.name) and p.is_file()), key=lambda p: p.name.split(".")[-2], reverse=True
    )
    for stale in backups[keep:]:
        try:
            stale.unlink()
        except OSError as exc:
            logger.warning("Не удалось удалить старую резервную копию %s: %s", stale, exc)


def backup_before_migration(db_path: Path, cfg) -> Path | None:
    """Резервная копия SQLite-БД перед миграцией; возвращает путь копии или None, если копия не нужна.

    Нужна, только если файл существует, в нём есть таблицы данных и его ревизия alembic не равна head (БД, уже
    актуальная или только что созданная, не копируется — иначе каждый запуск плодил бы копии). Миграции необратимы
    (часть удаляет данные, DDL в SQLite нетранзакционен): пользователь, обновивший EXE (или образ) и получивший ошибку миграции,
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


def sqlite_database_path(database_url: str) -> Path | None:
    """Путь к файлу БД, если адрес указывает на файловую SQLite; для PostgreSQL, `:memory:` и URI-имён (`file:...`) — None.

    Относительный путь остаётся относительным к рабочему каталогу процесса — так его разрешает и сам SQLAlchemy.
    """
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return None
    database = url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return None
    return Path(database)


def _alembic_config():
    """Конфигурация Alembic для чтения head-ревизий. Рядом с пакетом `app` лежат `alembic.ini` и `alembic/`: в исходниках это backend/,
    в Docker-образе — /app (COPY backend/alembic.ini и backend/alembic в Dockerfile)."""
    from alembic.config import Config

    root = Path(__file__).resolve().parents[2]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    return cfg


def main() -> int:
    """Точка входа `python -m app.services.db_backup`: 0 — копия не нужна или сделана, 1 — копию сделать не удалось (миграцию не
    начинать)."""
    if backup_skipped_by_environment():
        print(f"Резервная копия базы пропущена: {SKIP_BACKUP_ENV} задана.")
        return 0
    from ..config import DATABASE_URL

    db_path = sqlite_database_path(DATABASE_URL)
    if db_path is None:
        print("Резервная копия перед миграцией: база не SQLite — копию делает оператор средствами СУБД (README, «Обновление»).")
        return 0
    try:
        backup = backup_before_migration(db_path, _alembic_config())
    except MigrationBackupError as exc:
        print(
            f"ОШИБКА: {exc}\nОсвободите место в томе данных и проверьте права на запись. База не изменена. Запуск без "
            f"резервной копии (на свой риск): переменная окружения {SKIP_BACKUP_ENV}=1.",
            file=sys.stderr,
        )
        return 1
    if backup is not None:
        print(f"Резервная копия базы перед обновлением: {backup}")
    return 0


def configure_output() -> None:
    """Сообщения команды русские и не должны ронять её, когда вывод перенаправлен (файл, канал, служба, CI).

    Если stdout/stderr — не консоль, Python на Windows берёт ANSI-кодировку системы; на английской Windows это cp1252, и первый же `print` с
    кириллицей падает с UnicodeEncodeError (код 1: миграция не стартует из-за сообщения, а не из-за ошибки копии). Для файла и
    канала включаем UTF-8; у консоли кодировку не трогаем, но непредставимое заменяется, а не поднимает исключение. Тот же приём —
    `configure_stdio()` в
    launcher.py (там он выполняется до того, как в sys.path попадёт каталог `backend`, поэтому импортировать его отсюда нельзя).
    Вызывается только из точки входа процесса, а не из `main()`: тесты вызывают `main()` в процессе pytest и не должны менять его
    потоки."""
    for stream in (sys.stdout, sys.stderr):
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        if stream.isatty():
            stream.reconfigure(errors="replace")
        else:
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    configure_output()
    sys.exit(main())
