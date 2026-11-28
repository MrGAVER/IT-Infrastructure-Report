from __future__ import annotations

import argparse
import logging
import multiprocessing
import os
import sys
import threading
import time
import webbrowser
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import NoReturn

logger = logging.getLogger(__name__)

DB_FILENAME = "infra_registry.db"
# Через столько секунд после запроса остановки сервер завершается принудительно, если не успел остановиться сам (потеря блокировки базы).
LOCK_LOST_FORCE_EXIT_SECONDS = 15.0
EXIT_CODE_LOCK_LOST = 3


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


class MigrationUpgradeError(Exception):
    """``alembic upgrade head`` завершился ошибкой. Хранит путь к базе и к копии, сделанной перед миграцией (``None`` — копии нет)."""

    def __init__(self, db_path: Path, backup: Path | None, cause: BaseException) -> None:
        self.db_path = db_path
        self.backup = backup
        self.cause = cause
        super().__init__(f"не удалось обновить базу данных {db_path}: {self._cause_text()}")

    def _cause_text(self) -> str:
        return str(self.cause).strip() or type(self.cause).__name__

    def describe(self, skip_backup_env: str) -> str:
        """Текст для пользователя: что случилось и как вернуть прежнюю версию."""
        if self.backup is not None:
            restore = f"Чтобы вернуть прежнюю версию: закройте программу и замените файл {self.db_path} копией {self.backup}."
        else:
            restore = f"Резервной копии нет: база была пустой или копирование отключено ({skip_backup_env}). Обратитесь к администратору."
        return f"Не удалось обновить базу данных {self.db_path}: {self._cause_text()}\n{restore}"


def migrate():
    from alembic import command
    from alembic.config import Config

    from app.services.db_backup import backup_before_migration, backup_skipped_by_environment

    root = bundle_dir()
    alembic_root = root / "alembic" if (root / "alembic").exists() else root / "backend" / "alembic"
    ini_path = root / "alembic.ini" if (root / "alembic.ini").exists() else root / "backend" / "alembic.ini"
    db_path = data_dir() / DB_FILENAME
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(alembic_root))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    backup = None
    if not backup_skipped_by_environment():
        backup = backup_before_migration(db_path, cfg)
        if backup is not None:
            print(f"Резервная копия базы перед обновлением: {backup}")
    try:
        command.upgrade(cfg, "head")
    except Exception as exc:  # граница: любой сбой миграции превращаем в ошибку с путём к копии, ничего не проглатывая
        raise MigrationUpgradeError(db_path, backup, exc) from exc


def migrate_or_fail() -> None:
    """migrate() для main(): сбой миграции или резервной копии — понятная ошибка запуска, а не трассировка.

    Окно консоли EXE при двойном клике закрывается вместе с процессом, поэтому текст ошибки (и путь к копии, откуда вернуть прежнюю версию)
    должен быть выведен и удержан ``fail()``. Сбой копии — миграция не начата, база не изменена; сбой самой миграции — база могла
    измениться частично (DDL в SQLite нетранзакционен), и единственный путь отката — копия, сделанная перед миграцией."""
    from app.services.db_backup import SKIP_BACKUP_ENV, MigrationBackupError

    try:
        migrate()
    except MigrationBackupError as exc:
        fail(
            f"{exc}\nОсвободите место на диске и проверьте права на запись в каталог с базой. База не изменена. "
            f"Запуск без резервной копии (на свой риск): переменная окружения {SKIP_BACKUP_ENV}=1."
        )
    except MigrationUpgradeError as exc:
        fail(exc.describe(SKIP_BACKUP_ENV))


def acquire_instance_lock(db_path: Path, port: int):
    """Берёт «аренду» базы: на одной базе SQLite работает только одна копия приложения — на этом и на других компьютерах.

    Вызывается ДО миграций: вторая копия не должна ни делать резервную копию, ни обновлять базу, которую уже использует первая.
    Возвращает ``InstanceLock`` (его нужно освободить в ``finally``) или ``None``, если проверка отключена переменной окружения.
    Занятая база и неисправный файл блокировки — ``fail()`` с понятным текстом, а не трассировка.
    """
    from app.services.instance_lock import (
        SKIP_LOCK_ENV,
        InstanceAlreadyRunning,
        InstanceLock,
        InstanceLockError,
        LockTiming,
        lock_path_for,
        lock_skipped_by_environment,
    )

    if lock_skipped_by_environment():
        print(f"ВНИМАНИЕ: проверка второй копии отключена ({SKIP_LOCK_ENV}=1). Две копии на одной базе могут испортить данные.")
        return None
    lock = InstanceLock(lock_path_for(db_path), port=port, progress=print)
    try:
        lock.acquire()
    except InstanceAlreadyRunning as exc:
        fail(
            f"{exc}\nНа одной базе может работать только одна копия: закройте её или откройте программу в ней "
            f"(с других компьютеров — по адресу этого компьютера и порту, если в infra_registry.toml разрешён доступ по сети).\n"
            f"Если копия была закрыта аварийно, запустите программу снова: база освободится сама не позже чем через "
            f"{LockTiming().stale_after:g} с."
        )
    except InstanceLockError as exc:
        fail(
            f"{exc}\nЕсли других копий программы нет, закройте её на всех компьютерах и удалите файл {lock.path}. "
            f"Проверку можно отключить на свой риск: переменная окружения {SKIP_LOCK_ENV}=1."
        )
    return lock


def stop_after_lock_loss(
    server,
    reason: str,
    *,
    force_exit_after: float = LOCK_LOST_FORCE_EXIT_SECONDS,
    exit_func=os._exit,
) -> None:
    """Блокировка базы потеряна (её заняла другая копия или пропала сетевая папка): запись в базу нужно прекратить.

    Просит сервер остановиться штатно; если за ``force_exit_after`` секунд он не остановился (например, держат соединения), процесс
    завершается принудительно — продолжать писать в базу рядом с другой копией хуже, чем оборвать запросы.
    """
    logger.critical("%s Сервер останавливается.", reason)
    server.should_exit = True
    watchdog = threading.Timer(force_exit_after, exit_func, args=(EXIT_CODE_LOCK_LOST,))
    watchdog.daemon = True
    watchdog.start()


def serve(app, settings, port: int, instance_lock) -> None:
    """Запускает uvicorn и связывает потерю блокировки базы с остановкой сервера; после остановки по этой причине — ошибка запуска."""
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host=settings.listen_host, port=port, log_level="info"))
    if instance_lock is not None:
        instance_lock.set_on_lost(lambda reason: stop_after_lock_loss(server, reason))
    server.run()
    if instance_lock is not None and instance_lock.lost:
        fail(f"{instance_lock.lost_reason}\nРабота остановлена, чтобы не повредить данные. Запустите программу заново.")


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


def apply_environment(overrides: Mapping[str, str]) -> None:
    """Выставляет переменные окружения, которые ``app.config`` читает при импорте.

    Модуль настроек разбирает окружение один раз, при первом импорте: переменная, выставленная после него, молча не подействует
    (например, доступ по сети остался бы закрытым или, хуже, база оказалась бы не там). Поэтому порядок «сначала окружение, потом
    ``import app.main``» здесь не только описан, но и проверяется: нарушение — ``RuntimeError`` при запуске, а не тихая ошибка настройки."""
    if "app.config" in sys.modules:
        raise RuntimeError("app.config уже импортирован: переменные окружения нужно выставлять до первого импорта приложения")
    os.environ.update(overrides)


def configure_stdio() -> None:
    """Вывод не должен ронять запуск на кириллице, если он перенаправлен.

    Все сообщения этого модуля русские. Когда stdout/stderr — не консоль (`InfraRegistry.exe > log.txt`, служба, планировщик задач, CI),
    Python на Windows берёт кодировку ANSI системы; на английской Windows это cp1252, и `print("Создан файл настроек…")` падает с
    UnicodeEncodeError — EXE не стартует. Для файла и канала включаем UTF-8 (в журнале читаемый текст, а не «?»); у консоли кодировку не
    трогаем, но то, что она показать не может, заменяется, а не поднимает исключение. В сборке без консоли потока может не быть вовсе.
    """
    for stream in (sys.stdout, sys.stderr):
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        if stream.isatty():
            stream.reconfigure(errors="replace")
        else:
            stream.reconfigure(encoding="utf-8", errors="replace")


def fail(message: str) -> NoReturn:
    """Ошибка запуска: в EXE окно консоли закрывается вместе с процессом, поэтому ждём Enter, чтобы текст прочитали."""
    print(f"\nОШИБКА: {message}", file=sys.stderr)
    if getattr(sys, "frozen", False) and sys.stdin is not None and sys.stdin.isatty():
        input("\nНажмите Enter, чтобы закрыть окно...")
    sys.exit(2)


def prepare_environment(settings, root: Path) -> None:
    """Окружение приложения, каталоги данных и первый импорт ``app.config``; любой ожидаемый сбой — ``fail()`` с понятным текстом.

    Окружение выставляется ДО первого импорта app.config (apply_environment проверяет порядок). Единственный UI — собранный
    Vue-фронтенд (см. backend/app/config.py:FRONTEND_DIR), упакован в EXE как данные, см. datas в infra_registry.spec.

    Ожидаемые сбои: нельзя создать каталог данных (нет прав, диск только для чтения) — ``OSError``; значение переменной окружения
    не разобралось при импорте ``app.config`` — ``ValueError`` с именем переменной. Без перехвата пользователь EXE видел бы трассировку,
    а окно консоли закрывалось бы вместе с процессом. ``RuntimeError`` от ``apply_environment`` (нарушен порядок импорта) —
    ошибка программиста, её не прячем."""
    try:
        data = data_dir()
    except OSError as exc:
        fail(
            f"Не удалось создать каталог данных: {exc}\n"
            "Проверьте права на запись или задайте другой каталог переменной окружения INFRA_REGISTRY_DATA_DIR."
        )
    apply_environment(
        {
            "INFRA_REGISTRY_BUNDLE_DIR": str(root),
            "INFRA_REGISTRY_FRONTEND_DIR": str(root / "frontend-vue" / "dist"),
            "INFRA_REGISTRY_DATA_DIR": str(data),
            "DATABASE_URL": f"sqlite:///{data / DB_FILENAME}",
            # Список разрешённых клиентов и имён Host из файла настроек рядом с EXE
            **settings.environment(),
        }
    )
    try:
        from app.config import ensure_data_dirs

        ensure_data_dirs()  # app.config при импорте каталогов не создаёт
    except OSError as exc:
        fail(f"Не удалось создать каталоги приложения: {exc}\nПроверьте права на запись в каталог данных.")
    except ValueError as exc:
        fail(f"Неверное значение настройки: {exc}\nИсправьте переменную окружения или файл настроек рядом с EXE.")


def main():
    configure_stdio()
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

    prepare_environment(settings, root)
    # Блокировка базы — до миграций: вторая копия не должна обновлять базу, которую уже использует первая.
    instance_lock = acquire_instance_lock(data_dir() / DB_FILENAME, port)
    try:
        migrate_or_fail()

        from app.main import app

        if settings.network_access:
            print(f"Доступ по сети разрешён для: {', '.join(settings.allowed_clients)} (порт {port}). Файл настроек: {settings_path}")
        else:
            print(f"Доступ только с этого компьютера. Как открыть доступ другим компьютерам — в файле {settings_path}")

        if settings.open_browser and not args.no_browser:
            threading.Thread(target=lambda: open_browser_when_ready(port), daemon=True).start()
        serve(app, settings, port, instance_lock)
    finally:
        if instance_lock is not None:
            instance_lock.release()


if __name__ == "__main__":
    # Первым делом: экспорт .vsdx рендерится в дочернем процессе (services/vsdx_process.py, запуск spawn). В замороженном EXE дочерний процесс —
    # тот же InfraRegistry.exe; без freeze_support() он запустил бы main() ещё раз, то есть вторую копию приложения. Вне EXE вызов ничего не делает.
    multiprocessing.freeze_support()
    main()
