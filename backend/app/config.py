from __future__ import annotations
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
APP_DATA_DIR = Path(os.getenv('INFRA_REGISTRY_DATA_DIR', str(BASE_DIR))).expanduser().resolve()
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR = APP_DATA_DIR / 'reports'
REPORT_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv('DATABASE_URL', f'sqlite:///{APP_DATA_DIR / "infra_registry.db"}')
FRONTEND_DIR = Path(os.getenv('INFRA_REGISTRY_FRONTEND_DIR', str(BASE_DIR / 'frontend'))).expanduser().resolve()
APP_VERSION = '2.21.0'
