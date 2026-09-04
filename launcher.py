from __future__ import annotations

import argparse
import os
import sys
import threading
import time
import webbrowser
import urllib.request
from pathlib import Path


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

def main():
    parser = argparse.ArgumentParser(description="РИС — Реестр ИТ-инфраструктуры")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер автоматически")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    root = bundle_dir()
    os.environ["INFRA_REGISTRY_BUNDLE_DIR"] = str(root)
    # Единственный UI — собранный Vue-фронтенд (см. backend/app/config.py:FRONTEND_DIR),
    # упакован в EXE как данные, см. datas в infra_registry.spec.
    os.environ["INFRA_REGISTRY_FRONTEND_DIR"] = str(root / 'frontend-vue' / 'dist')
    os.environ["INFRA_REGISTRY_DATA_DIR"] = str(data_dir())
    os.environ["DATABASE_URL"] = f"sqlite:///{data_dir() / 'infra_registry.db'}"
    sys.path.insert(0, str(bundle_dir() / "backend"))
    sys.path.insert(0, str(bundle_dir()))

    migrate()

    import uvicorn
    from app.main import app

    if not args.no_browser:
        threading.Thread(target=lambda: open_browser_when_ready(args.port), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
