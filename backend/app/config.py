from __future__ import annotations
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
APP_DATA_DIR = Path(os.getenv('INFRA_REGISTRY_DATA_DIR', str(BASE_DIR))).expanduser().resolve()
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR = APP_DATA_DIR / 'reports'
REPORT_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.getenv('DATABASE_URL', f'sqlite:///{APP_DATA_DIR / "infra_registry.db"}')
# Основной UI — собранный Vue-фронтенд (frontend-vue/dist), см. frontend-vue/README.md.
# Каталог появляется только после `npm run build` в frontend-vue — локально при разработке
# из исходников (без сборки) GET '/' отдаст понятную 500-ошибку с указанием отсутствующего
# файла (см. api/system.py:frontend_index), а не тихо упадёт. В Docker/PyInstaller-сборке
# каталог собирается/копируется как часть сборки (см. backend/Dockerfile, infra_registry.spec).
FRONTEND_DIR = Path(os.getenv('INFRA_REGISTRY_FRONTEND_DIR', str(BASE_DIR / 'frontend-vue' / 'dist'))).expanduser().resolve()
# Старый vanilla-фронтенд (frontend/) — оставлен доступным на /legacy на переходный период,
# пока не закрыты оставшиеся пробелы в новом UI относительно него (см. "Ещё не сделано" в
# frontend-vue/README.md). В отличие от FRONTEND_DIR ничего собирать не нужно — эти файлы
# как были обычным HTML/JS/CSS без сборки, так и остаются.
LEGACY_FRONTEND_DIR = Path(os.getenv('INFRA_REGISTRY_LEGACY_FRONTEND_DIR', str(BASE_DIR / 'frontend'))).expanduser().resolve()
APP_VERSION = '2.45.0'

# Frontend is served from the same origin (StaticFiles mount below), and the app currently
# does not use cookies/auth headers, so CORS is only relevant when a separate frontend origin
# calls this API directly (e.g. local development on a different port). Comma-separated list
# of allowed origins, e.g. "http://localhost:5173,http://127.0.0.1:5173". Defaults to '*' for
# the common single-user/local-network deployment; set explicitly for anything more exposed.
CORS_ALLOWED_ORIGINS = [o.strip() for o in os.getenv('INFRA_REGISTRY_CORS_ORIGINS', '*').split(',') if o.strip()]

# Guards demo/test-data seeding endpoint (POST /api/v1/seed/test). Enabled by default because
# it's a visible, regularly used "Заполнить тестовыми данными" button on the Dashboard in the
# single-user local/EXE deployment. For a shared multi-user server deployment where this button
# shouldn't be exposed, set INFRA_REGISTRY_ENABLE_TEST_DATA=0 to disable the endpoint.
ENABLE_TEST_DATA_ENDPOINT = os.getenv('INFRA_REGISTRY_ENABLE_TEST_DATA', '1').lower() in ('1', 'true', 'yes')
