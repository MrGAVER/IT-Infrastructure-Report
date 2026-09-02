from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .config import APP_VERSION, CORS_ALLOWED_ORIGINS, FRONTEND_DIR, LEGACY_FRONTEND_DIR
from .api.devices import router as devices_router
from .api.report_builder import router as report_builder_router
from .api.resources import router as resources_router
from .api.system import router as system_router
from .db import SessionLocal
from .services.catalogs import seed_defaults

@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_catalogs_on_startup()
    yield

app = FastAPI(title='РИС — Реестр ИТ-инфраструктуры', version=APP_VERSION, lifespan=lifespan)
# allow_credentials=False: the app doesn't use cookies/auth headers, and combining
# allow_credentials=True with a wildcard origin makes the browser reflect any calling
# origin as trusted, which is unnecessary risk without any actual benefit here.
app.add_middleware(CORSMiddleware, allow_origins=CORS_ALLOWED_ORIGINS, allow_credentials=False, allow_methods=['*'], allow_headers=['*'])
app.include_router(system_router)
app.include_router(devices_router)
app.include_router(resources_router)
app.include_router(report_builder_router)

def seed_catalogs_on_startup():
    session = SessionLocal()
    try:
        seed_defaults(session)
    finally:
        session.close()

# Vue-фронтенд (frontend-vue/dist) — основной UI, см. FRONTEND_DIR в config.py. Vite кладёт
# хэшированные JS/CSS-чанки в assets/ и ссылается на них абсолютными путями '/assets/...'
# (см. frontend-vue/vite.config.ts и собранный dist/index.html) — поэтому отдельный маунт,
# а не переиспользование '/static' (тот закреплён за vanilla-фронтендом, см. ниже).
assets_dir = FRONTEND_DIR / 'assets'
if assets_dir.is_dir():
    app.mount('/assets', StaticFiles(directory=assets_dir), name='vue-assets')

# Vanilla-фронтенд (frontend/) — оставлен доступным на /legacy на переходный период, пока не
# закрыты оставшиеся пробелы нового UI относительно него (см. "Ещё не сделано" во
# frontend-vue/README.md). Путь '/static' не переименован при переходе на Vue, т.к.
# frontend/index.html ссылается на него абсолютными путями independent от того, с какого
# URL был запрошен сам index.html (см. api/system.py:legacy_index).
legacy_static_dir = LEGACY_FRONTEND_DIR / 'static'
if legacy_static_dir.is_dir():
    app.mount('/static', StaticFiles(directory=legacy_static_dir), name='legacy-static')

# SPA-фоллбэк для клиентского роутинга Vue (vue-router в режиме createWebHistory(), см.
# frontend-vue/src/router/index.ts) — прямой переход или обновление страницы на, например,
# '/vms' должны вернуть index.html (а не 404), чтобы роутер сам открыл нужный экран на
# клиенте, ровно как 'try_files $uri /index.html' в типичном nginx-конфиге для SPA.
#
# ВАЖНО: регистрируется САМЫМ ПОСЛЕДНИМ (после всех include_router выше и обоих mount) —
# Starlette проверяет маршруты в порядке регистрации и возвращает первое совпадение, поэтому
# любой более специфичный путь (/api/..., /assets/..., /static/..., /legacy, /icons.svg,
# /favicon.ico — все объявлены раньше) перехватывается им первым, а этот catch-all ловит
# только то, что не подошло ни одному из них. /api/* исключён явно: иначе опечатка в пути API
# или обращение к несуществующему эндпоинту молча превращалось бы в 200 с HTML вместо
# честного 404, маскируя реальную ошибку интеграции.
@app.get('/{full_path:path}', include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path == 'api' or full_path.startswith('api/'):
        raise HTTPException(404, 'Not Found')
    index = FRONTEND_DIR / 'index.html'
    if not index.is_file():
        raise HTTPException(500, f'Файл интерфейса не найден: {index}')
    return FileResponse(index, media_type='text/html; charset=utf-8')
