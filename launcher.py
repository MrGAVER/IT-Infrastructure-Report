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
    if not backup_skipped_by_environment():
        backup = backup_before_migration(db_path, cfg)
        if backup is not None:
            print(f"Резервная копия базы перед обновлением: {backup}")
    command.upgrade(cfg, "head")


def migrate_or_fail() -> None:
    """migrate() для main(): сбой резервной копии — понятная ошибка запуска, а не трассировка; миграция при этом не начата."""
    from app.services.db_backup import SKIP_BACKUP_ENV, MigrationBackupError

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

    # Окружение выставляется ДО первого импорта app.config (apply_environment проверяет порядок). Единственный UI — собранный
    # Vue-фронтенд (см. backend/app/config.py:FRONTEND_DIR), упакован в EXE как данные, см. datas в infra_registry.spec.
    apply_environment(
        {
            "INFRA_REGISTRY_BUNDLE_DIR": str(root),
            "INFRA_REGISTRY_FRONTEND_DIR": str(root / "frontend-vue" / "dist"),
            "INFRA_REGISTRY_DATA_DIR": str(data_dir()),
            "DATABASE_URL": f"sqlite:///{data_dir() / DB_FILENAME}",
            # Список разрешённых клиентов и имён Host из файла настроек рядом с EXE
            **settings.environment(),
        }
    )

    from app.config import ensure_data_dirs

    ensure_data_dirs()  # app.config при импорте каталогов не создаёт
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
    # Первым делом: экспорт .vsdx рендерится в дочернем процессе (services/vsdx_process.py, запуск spawn). В замороженном EXE дочерний процесс —
    # тот же InfraRegistry.exe; без freeze_support() он запустил бы main() ещё раз, то есть вторую копию приложения. Вне EXE вызов ничего не делает.
    multiprocessing.freeze_support()
    main()
