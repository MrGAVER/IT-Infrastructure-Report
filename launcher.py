from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import webbrowser
import urllib.request
from pathlib import Path
from typing import NoReturn


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

    root = bundle_dir()
    alembic_root = root / "alembic" if (root / "alembic").exists() else root / "backend" / "alembic"
    ini_path = root / "alembic.ini" if (root / "alembic.ini").exists() else root / "backend" / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(alembic_root))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{data_dir() / 'infra_registry.db'}")
    command.upgrade(cfg, "head")


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
    parser.add_argument("--license-info", action="store_true", help="вывести имя, IP-адреса и отпечаток этого компьютера (для запроса лицензионного ключа с привязкой) и выйти")
    args = parser.parse_args()

    root = bundle_dir()
    sys.path.insert(0, str(bundle_dir() / "backend"))
    sys.path.insert(0, str(bundle_dir()))

    if args.license_info:
        from app.licensing.context import collect_host_context

        print(json.dumps(collect_host_context().describe(), ensure_ascii=False, indent=2))
        return

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
    os.environ["DATABASE_URL"] = f"sqlite:///{data_dir() / 'infra_registry.db'}"
    # Список разрешённых клиентов и имён Host читает app.config при импорте — выставляем ДО import app.main.
    os.environ.update(settings.environment())

    migrate()

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
