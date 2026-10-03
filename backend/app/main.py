from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from .config import APP_VERSION, CORS_ALLOWED_ORIGINS, DATABASE_URL, FRONTEND_DIR
from .api.audit_log import router as audit_log_router
from .api.auth import router as auth_router
from .api.devices import router as devices_router
from .api.diagrams import router as diagrams_router
from .api.port_config import router as port_config_router
from .api.report_builder import router as report_builder_router
from .api.resources import router as resources_router
from .api.system import router as system_router
from .db import SessionLocal
from .services.auth import auth_gate_middleware, get_or_create_auth_settings
from .services.catalogs import seed_defaults
from .services.integrity import ReferencedRecordError

logger = logging.getLogger(__name__)

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
app.include_router(port_config_router)
app.include_router(audit_log_router)
app.include_router(report_builder_router)
app.include_router(diagrams_router)

@app.exception_handler(ReferencedRecordError)
async def referenced_record_handler(request: Request, exc: ReferencedRecordError) -> JSONResponse:
    """Защита уровня ORM (before_delete, см. services/integrity.py) сработала в обход
    delete_resource() — отдаём тот же 409 с тем же кодом и текстом, а не 500."""
    return JSONResponse(status_code=409, content={'detail': {'code': exc.code, 'message': str(exc)}})


def seed_catalogs_on_startup():
    session = SessionLocal()
    try:
        seed_defaults(session)
        auth_settings = get_or_create_auth_settings(session)
        _warn_if_insecure_server_config(auth_settings.enabled)
    finally:
        session.close()

def _warn_if_insecure_server_config(auth_enabled: bool) -> None:
    """Код-ревью п.3.3: приложение официально поддерживает серверное развёртывание (Docker +
    PostgreSQL, см. docker-compose.yml) для нескольких сотрудников — но дефолты
    (AuthSettings.enabled=False, CORS_ALLOWED_ORIGINS='*') рассчитаны на однопользовательский
    локальный/EXE-сценарий (см. .env.example). В серверном сценарии та же комбинация означает,
    что любой, кто достаёт до порта, получает полный доступ на чтение/запись без аутентификации
    — это прямо усиливает риски найденных в этом же ревью 3.1/3.2. Запуск НЕ блокируется (те же
    дефолты остаются рабочими и правильными для локального сценария) — только предупреждение в
    лог; сам DATABASE_URL в сообщение не попадает, чтобы не светить пароль БД в логах."""
    if not DATABASE_URL.lower().startswith("postgresql"):
        return
    problems = []
    if not auth_enabled:
        problems.append("аутентификация выключена (AuthSettings.enabled=False)")
    if CORS_ALLOWED_ORIGINS == ["*"]:
        problems.append("CORS разрешён для любого origin (INFRA_REGISTRY_CORS_ORIGINS=*)")
    if problems:
        logger.warning(
            "Небезопасная конфигурация серверного развёртывания на PostgreSQL: %s. "
            "Эти дефолты рассчитаны на локальный однопользовательский сценарий — для сервера, "
            "доступного нескольким сотрудникам, включите аутентификацию (см. раздел "
            "'Аутентификация' в README) и ограничьте INFRA_REGISTRY_CORS_ORIGINS конкретными "
            "адресами.",
            "; ".join(problems),
        )

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
