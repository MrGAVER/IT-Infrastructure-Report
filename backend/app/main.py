from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import ALLOWED_HOSTS, APP_VERSION, CORS_ALLOWED_ORIGINS, DATABASE_URL, FRONTEND_DIR
from .api.audit_log import router as audit_log_router
from .api.auth import router as auth_router
from .api.device_stacks import router as device_stacks_router
from .api.devices import router as devices_router
from .api.diagrams import router as diagrams_router
from .api.frontend_assets import router as frontend_assets_router
from .api.listings import router as listings_router
from .api.port_config import router as port_config_router
from .api.port_sync import router as port_sync_router
from .api.preferences import router as preferences_router
from .api.report_builder import router as report_builder_router
from .api.reports import router as reports_router
from .api.resources import router as resources_router
from .api.system import router as system_router
from .api.vlan import router as vlan_router
from .api.vms import router as vms_router
from .db import SessionLocal
from .services.auth import auth_gate_middleware, get_or_create_auth_settings
from .services.catalogs import seed_defaults
from .services.integrity import ReferencedRecordError
from .services.port_sync_store import ensure_default_rules

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_catalogs_on_startup()
    yield

app = FastAPI(title='РИС — Реестр ИТ-инфраструктуры', version=APP_VERSION, lifespan=lifespan)
# Порядок add_middleware() важен: Starlette оборачивает мидлвари в порядке, ОБРАТНОМ порядку
# регистрации (последний добавленный — самый внешний). auth_gate_middleware иногда завершает запрос
# сам, не вызывая call_next (короткое замыкание на 401/403) — если бы CORSMiddleware оказался ВНУТРИ
# него, эти ответы уходили бы клиенту без CORS-заголовков, и браузер в dev-режиме (Vite на отдельном
# порту, см. CORS_ALLOWED_ORIGINS) показывал бы малопонятную CORS-ошибку вместо настоящих 401/403.
# Поэтому auth_gate_middleware регистрируется ПЕРВЫМ (внутри), а CORS и проверка Host — ПОСЛЕ него
# (снаружи), см. install_http_security().
def install_http_security(app: FastAPI, *, allowed_hosts: list[str], cors_origins: list[str]) -> None:
    """CORS и проверка заголовка Host — внешний слой защиты HTTP (код-ревью, п. 2).

    - Пустой cors_origins — CORS не включается вовсе: чужие origin'ы не получают ни заголовков
      Access-Control-*, ни ответа на preflight, то есть браузер не даст стороннему сайту читать API.
    - allowed_hosts — TrustedHostMiddleware отвечает 400 на любой Host вне списка (защита от
      DNS-rebinding); '*' в списке разрешает любой Host.
    allow_credentials=False: авторизация идёт через заголовок Authorization: Bearer <токен>, а не через
    куки — широкий allow_origins вместе с allow_credentials=True был бы лишним риском без пользы."""
    if cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=False, allow_methods=['*'], allow_headers=['*'])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts or ['localhost', '127.0.0.1'])

app.add_middleware(BaseHTTPMiddleware, dispatch=auth_gate_middleware)
install_http_security(app, allowed_hosts=ALLOWED_HOSTS, cors_origins=CORS_ALLOWED_ORIGINS)
app.include_router(auth_router)
app.include_router(preferences_router)
# Бывший api/system.py (357 строк) разрезан по темам (код-ревью п. 10); адреса эндпоинтов не менялись.
app.include_router(system_router)
app.include_router(listings_router)
app.include_router(vms_router)
app.include_router(vlan_router)
app.include_router(reports_router)
app.include_router(device_stacks_router)
app.include_router(frontend_assets_router)
app.include_router(devices_router)
app.include_router(resources_router)
app.include_router(port_config_router)
app.include_router(port_sync_router)
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
        # Стандартные правила согласования портов: добавляются по устойчивому коду, существующие (в том
        # числе изменённые администратором) не перезаписываются.
        ensure_default_rules(session)
        auth_settings = get_or_create_auth_settings(session)
        _warn_if_insecure_server_config(auth_settings.enabled)
    finally:
        session.close()

def _warn_if_insecure_server_config(auth_enabled: bool) -> None:
    """Приложение официально поддерживает серверное развёртывание (Docker + PostgreSQL, см.
    docker-compose.yml) для нескольких сотрудников, а аутентификация по умолчанию выключена —
    рассчитано на однопользовательский локальный/EXE-сценарий (см. .env.example). В серверном сценарии
    выключенная аутентификация означает, что любой, кто достаёт до порта, имеет полный доступ на
    чтение/запись реестра (первичная настройка при этом защищена, см. services/auth.require_setup_access),
    а явно заданный CORS '*' разрешает это ещё и чужим веб-страницам. Запуск НЕ блокируется — только
    предупреждение в лог; сам DATABASE_URL в сообщение не попадает, чтобы не светить пароль БД в логах."""
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
        raise HTTPException(500, f'Файл интерфейса не найден: {index}. Соберите frontend-vue (npm run build).')
    return FileResponse(index, media_type='text/html; charset=utf-8')
