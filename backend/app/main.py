from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from .config import APP_VERSION, CORS_ALLOWED_ORIGINS, FRONTEND_DIR
from .api.auth import router as auth_router
from .api.devices import router as devices_router
from .api.report_builder import router as report_builder_router
from .api.resources import router as resources_router
from .api.system import router as system_router
from .db import SessionLocal
from .services.auth import auth_gate_middleware, get_or_create_auth_settings
from .services.catalogs import seed_defaults

@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_catalogs_on_startup()
    yield

app = FastAPI(title='РИС — Реестр ИТ-инфраструктуры', version=APP_VERSION, lifespan=lifespan)
# Порядок add_middleware() ниже осознанный и важен: Starlette оборачивает мидлвари в порядке,
# ОБРАТНОМ порядку регистрации (последний добавленный — самый внешний). auth_gate_middleware
# иногда завершает запрос сам, не вызывая call_next (короткое замыкание на 401/403) — если бы
# CORSMiddleware был зарегистрирован ДО него (т.е. оказался внутри), эти ответы уходили бы
# клиенту без CORS-заголовков, и браузер в dev-режиме (Vite на отдельном порту, см.
# CORS_ALLOWED_ORIGINS) показывал бы малопонятную CORS-ошибку вместо настоящих 401/403.
# Поэтому auth_gate_middleware регистрируется ПЕРВЫМ (окажется внутри), CORS — ВТОРЫМ (снаружи).
app.add_middleware(BaseHTTPMiddleware, dispatch=auth_gate_middleware)
# allow_credentials=False: авторизация идёт через заголовок Authorization: Bearer <токен>, а не
# через куки — комбинация allow_credentials=True с широким allow_origins была бы лишним риском
# без всякой пользы, раз ambient-креденшелов (кук) в этой схеме нет в принципе.
app.add_middleware(CORSMiddleware, allow_origins=CORS_ALLOWED_ORIGINS, allow_credentials=False, allow_methods=['*'], allow_headers=['*'])
app.include_router(auth_router)
app.include_router(system_router)
app.include_router(devices_router)
app.include_router(resources_router)
app.include_router(report_builder_router)

def seed_catalogs_on_startup():
    session = SessionLocal()
    try:
        seed_defaults(session)
        get_or_create_auth_settings(session)
    finally:
        session.close()

# Vue-фронтенд (frontend-vue/dist) — единственный UI, см. FRONTEND_DIR в config.py. Vite кладёт
# хэшированные JS/CSS-чанки в assets/ и ссылается на них абсолютными путями '/assets/...'
# (см. frontend-vue/vite.config.ts и собранный dist/index.html).
assets_dir = FRONTEND_DIR / 'assets'
if assets_dir.is_dir():
    app.mount('/assets', StaticFiles(directory=assets_dir), name='vue-assets')

# SPA-фоллбэк для клиентского роутинга Vue (vue-router в режиме createWebHistory(), см.
# frontend-vue/src/router/index.ts) — прямой переход или обновление страницы на, например,
# '/vms' должны вернуть index.html (а не 404), чтобы роутер сам открыл нужный экран на
# клиенте, ровно как 'try_files $uri /index.html' в типичном nginx-конфиге для SPA.
#
# ВАЖНО: регистрируется САМЫМ ПОСЛЕДНИМ (после всех include_router выше и mount) —
# Starlette проверяет маршруты в порядке регистрации и возвращает первое совпадение, поэтому
# любой более специфичный путь (/api/..., /assets/..., /icons.svg, /favicon.ico — все объявлены
# раньше) перехватывается им первым, а этот catch-all ловит только то, что не подошло ни одному
# из них. /api/* исключён явно: иначе опечатка в пути API или обращение к несуществующему
# эндпоинту молча превращалось бы в 200 с HTML вместо честного 404, маскируя реальную ошибку
# интеграции.
@app.get('/{full_path:path}', include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path == 'api' or full_path.startswith('api/'):
        raise HTTPException(404, 'Not Found')
    index = FRONTEND_DIR / 'index.html'
    if not index.is_file():
        raise HTTPException(500, f'Файл интерфейса не найден: {index}')
    return FileResponse(index, media_type='text/html; charset=utf-8')
