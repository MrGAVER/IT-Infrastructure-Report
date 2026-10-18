from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import (
    ALLOWED_CLIENTS, ALLOWED_HOSTS, APP_VERSION, CORS_ALLOWED_ORIGINS, DATABASE_URL, FRONTEND_DIR,
    LICENSE_ENFORCEMENT, LICENSE_FILE, LICENSE_KEY, LICENSE_MODE, LICENSE_STATE_FILE,
)
from .api.audit_log import router as audit_log_router
from .api.auth import router as auth_router
from .api.device_stacks import router as device_stacks_router
from .api.devices import router as devices_router
from .api.diagrams import router as diagrams_router
from .api.frontend_assets import router as frontend_assets_router
from .api.license import router as license_router
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
from .licensing.bootstrap import build_license_manager, validate_mode
from .licensing.middleware import LicenseGateMiddleware
from .services.auth import auth_gate_middleware, get_or_create_auth_settings
from .services.catalogs import seed_defaults
from .services.integrity import ReferencedRecordError
from .services.network_access import (
    ClientAccessMiddleware,
    IpLiteralTrustedHostMiddleware,
    IPNetwork,
    has_remote_clients,
    parse_client_networks,
)
from .services.port_sync_store import ensure_default_rules

logger = logging.getLogger(__name__)

# Разобранный INFRA_REGISTRY_ALLOWED_CLIENTS. Неверная запись — ValueError при импорте: приложение не
# должно молча стартовать с «открытым» доступом из-за опечатки в адресе.
ALLOWED_CLIENT_NETWORKS: list[IPNetwork] = parse_client_networks(ALLOWED_CLIENTS)

# Лицензирование (app/licensing, docs/licensing.md). Неверные настройки — ValueError при импорте, как и для списка клиентов.
LICENSE_GATE_MODE = validate_mode(LICENSE_MODE)
license_manager = build_license_manager(
    key_file=LICENSE_FILE, state_file=LICENSE_STATE_FILE, env_token=LICENSE_KEY, enforcement_setting=LICENSE_ENFORCEMENT,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_catalogs_on_startup()
    _log_license_status()
    yield
    license_manager.flush()

app = FastAPI(title='РИС — Реестр ИТ-инфраструктуры', version=APP_VERSION, lifespan=lifespan)
app.state.license_manager = license_manager
# Порядок add_middleware() важен: Starlette оборачивает мидлвари в порядке, ОБРАТНОМ порядку
# регистрации (последний добавленный — самый внешний). auth_gate_middleware иногда завершает запрос
# сам, не вызывая call_next (короткое замыкание на 401/403) — если бы CORSMiddleware оказался ВНУТРИ
# него, эти ответы уходили бы клиенту без CORS-заголовков, и браузер в dev-режиме (Vite на отдельном
# порту, см. CORS_ALLOWED_ORIGINS) показывал бы малопонятную CORS-ошибку вместо настоящих 401/403.
# Поэтому auth_gate_middleware регистрируется ПЕРВЫМ (внутри), а CORS и проверка Host — ПОСЛЕ него
# (снаружи), см. install_http_security().
def install_http_security(
    app: FastAPI,
    *,
    allowed_hosts: list[str],
    cors_origins: list[str],
    allowed_clients: list[IPNetwork] | None = None,
) -> None:
    """CORS, проверка заголовка Host и список разрешённых клиентов — внешний слой защиты HTTP (код-ревью, п. 2).

    - Пустой cors_origins — CORS не включается вовсе: чужие origin'ы не получают ни заголовков
      Access-Control-*, ни ответа на preflight, то есть браузер не даст стороннему сайту читать API.
    - allowed_hosts — TrustedHostMiddleware отвечает 400 на любой Host вне списка (защита от
      DNS-rebinding); '*' в списке разрешает любой Host. Если разрешены клиенты не только с этого компьютера,
      Host в виде IP-адреса принимается всегда (http://192.168.1.10:8000): подменить его через DNS нельзя,
      а перечислять в настройках адрес сервера было бы лишним шагом.
    - allowed_clients — подсети, с которых принимаются подключения (403 всем остальным). Пустой или None —
      без ограничений по адресу. Фильтр — САМЫЙ внешний слой: чужой адрес не доходит ни до проверки
      Host, ни до аутентификации.
    allow_credentials=False: авторизация идёт через заголовок Authorization: Bearer <токен>, а не через
    куки — широкий allow_origins вместе с allow_credentials=True был бы лишним риском без пользы."""
    if cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_credentials=False, allow_methods=['*'], allow_headers=['*'])
    trusted_hosts = allowed_hosts or ['localhost', '127.0.0.1']
    if allowed_clients and has_remote_clients(allowed_clients):
        app.add_middleware(IpLiteralTrustedHostMiddleware, allowed_hosts=trusted_hosts)
    else:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)
    if allowed_clients:
        app.add_middleware(ClientAccessMiddleware, networks=allowed_clients)

app.add_middleware(BaseHTTPMiddleware, dispatch=auth_gate_middleware)
# Проверка лицензии — СНАРУЖИ auth_gate_middleware (регистрируется позже): запись без лицензии закрыта независимо от роли,
# а её 402 всё равно получает CORS-заголовки, потому что CORS и проверка Host добавляются ещё позже (см. комментарий выше).
if license_manager.enforcement:
    app.add_middleware(LicenseGateMiddleware, manager=license_manager, mode=LICENSE_GATE_MODE)
install_http_security(app, allowed_hosts=ALLOWED_HOSTS, cors_origins=CORS_ALLOWED_ORIGINS, allowed_clients=ALLOWED_CLIENT_NETWORKS)
app.include_router(auth_router)
app.include_router(license_router)
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
        _warn_if_remote_access_without_auth(auth_settings.enabled)
    finally:
        session.close()

def _log_license_status() -> None:
    """Состояние лицензии в журнале при старте: администратор EXE видит его в консоли, не заходя в интерфейс."""
    report = license_manager.report()
    if not license_manager.enforcement:
        logger.info("Проверка лицензии отключена (в сборке нет публичных ключей или INFRA_REGISTRY_LICENSE_ENFORCEMENT=off).")
    elif report.allows_writes:
        payload = report.payload
        logger.info("Лицензия: %s, владелец %s, срок %s.", report.state.value, payload.licensee if payload else "?", report.to_public_dict()["expires_at"] or "бессрочно")
    else:
        logger.warning("Лицензия: %s (%s). %s Режим без лицензии: %s. Активация ключа: POST /api/v1/license (тело {\"key\": \"...\"}).",
                       report.state.value, report.reason or ",".join(report.mismatched) or "-", report.message, LICENSE_GATE_MODE)

def _warn_if_remote_access_without_auth(auth_enabled: bool) -> None:
    """Доступ по сети открыт (в списке клиентов есть адреса не с этого компьютера), а аутентификация
    выключена — значит любой разрешённый адрес читает и меняет весь реестр без входа. Запуск не блокируется:
    администратор сам выбрал список адресов, а включить аутентификацию можно только на самом компьютере
    (services/auth.require_setup_access) — поэтому подсказываем, как это сделать."""
    if auth_enabled or not has_remote_clients(ALLOWED_CLIENT_NETWORKS):
        return
    logger.warning(
        "Доступ по сети открыт, но аутентификация выключена: любой компьютер из списка разрешённых клиентов "
        "может читать и менять реестр без входа. Включите её на этом компьютере: "
        "«Настройки → Аутентификация» (создайте администратора и включите вход)."
    )

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
