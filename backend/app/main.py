from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError, OperationalError, ProgrammingError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .config import (
    ALLOWED_CLIENTS,
    ALLOWED_HOSTS,
    APP_VERSION,
    CORS_ALLOWED_ORIGINS,
    DATABASE_URL,
    ENABLE_DOCS,
    FORWARDED_ALLOW_IPS,
    FRONTEND_DIR,
    MAX_REQUEST_BODY_BYTES,
    MIN_DB_PASSWORD_LENGTH,
    MIN_SETUP_TOKEN_LENGTH,
    SETUP_TOKEN,
    weak_db_password,
    weak_setup_token,
)
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
from .services.body_limit import BodySizeLimitMiddleware
from .services.catalogs import seed_defaults
from .services.csrf_guard import SameOriginGuardMiddleware, forwarded_host_trusted
from .services.integrity import ReferencedRecordError
from .services.network_access import (
    ClientAccessMiddleware,
    IpLiteralTrustedHostMiddleware,
    IPNetwork,
    has_remote_clients,
    parse_client_networks,
)
from .services.port_sync_store import ensure_default_rules
from .services.openapi_errors import install_error_formats
from .services.request_errors import request_validation_handler

logger = logging.getLogger(__name__)

# Разобранный INFRA_REGISTRY_ALLOWED_CLIENTS. Неверная запись — ValueError при импорте: приложение не
# должно молча стартовать с «открытым» доступом из-за опечатки в адресе.
ALLOWED_CLIENT_NETWORKS: list[IPNetwork] = parse_client_networks(ALLOWED_CLIENTS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_catalogs_on_startup()
    yield

# Документация API выключена по умолчанию (config.ENABLE_DOCS): None вместо адреса снимает сами маршруты.
app = FastAPI(
    title='РИС — Реестр ИТ-инфраструктуры', version=APP_VERSION, lifespan=lifespan,
    docs_url='/docs' if ENABLE_DOCS else None,
    redoc_url='/redoc' if ENABLE_DOCS else None,
    openapi_url='/openapi.json' if ENABLE_DOCS else None,
)
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
    trust_forwarded_host: bool = False,
    max_body_bytes: int | None = None,
) -> None:
    """CORS, проверка заголовка Host, проверка origin, предел размера тела и список разрешённых клиентов — внешний слой защиты HTTP (код-ревью, п. 2).

    - Пустой cors_origins — CORS не включается вовсе: чужие origin'ы не получают ни заголовков
      Access-Control-*, ни ответа на preflight, то есть браузер не даст стороннему сайту читать API.
    - allowed_hosts — TrustedHostMiddleware отвечает 400 на любой Host вне списка (защита от
      DNS-rebinding); '*' в списке разрешает любой Host. Если разрешены клиенты не только с этого компьютера,
      Host в виде IP-адреса принимается всегда (http://192.168.1.10:8000): подменить его через DNS нельзя,
      а перечислять в настройках адрес сервера было бы лишним шагом.
    - allowed_clients — подсети, с которых принимаются подключения (403 всем остальным). Пустой или None —
      без ограничений по адресу. Фильтр — САМЫЙ внешний слой: чужой адрес не доходит ни до проверки
      Host, ни до аутентификации.
    - SameOriginGuardMiddleware (всегда, при любом режиме аутентификации) — 403 CROSS_ORIGIN_BLOCKED на POST/PUT/PATCH/
      DELETE к /api/ с чужого origin (CSRF: CORS защищает чтение, но не мешает браузеру отправить сам запрос). Origin'ы
      из cors_origins считаются доверенными; X-Forwarded-Host учитывается при trust_forwarded_host. Стоит внутри CORS
      и проверки Host, но снаружи auth_gate_middleware: чужая страница получает отказ раньше, чем 401/обработчик.
    - BodySizeLimitMiddleware (если задан max_body_bytes) — 413 REQUEST_BODY_TOO_LARGE на тело больше предела (F-06 код-ревью main:
      раньше тело любого размера целиком читалось в память). Стоит САМЫМ внутренним из слоёв этой функции: внутри CORS, чтобы 413
      дошёл до браузера на dev-сервере с понятным текстом, а не CORS-ошибкой, и внутри проверок клиента, Host и origin — чужие
      запросы отсекаются раньше. Снаружи auth_gate_middleware: тело больше предела не читается и до проверки входа.
    allow_credentials=False: авторизация идёт через заголовок Authorization: Bearer <токен>, а не через
    куки — широкий allow_origins вместе с allow_credentials=True был бы лишним риском без пользы."""
    if max_body_bytes is not None:
        app.add_middleware(BodySizeLimitMiddleware, max_bytes=max_body_bytes)
    app.add_middleware(SameOriginGuardMiddleware, extra_origins=cors_origins, trust_forwarded_host=trust_forwarded_host)
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
install_http_security(
    app,
    allowed_hosts=ALLOWED_HOSTS,
    cors_origins=CORS_ALLOWED_ORIGINS,
    allowed_clients=ALLOWED_CLIENT_NETWORKS,
    trust_forwarded_host=forwarded_host_trusted(FORWARDED_ALLOW_IPS),
    max_body_bytes=MAX_REQUEST_BODY_BYTES,
)
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

# 422 при ошибке разбора запроса — строкой на русском, как остальные 422 приложения (по умолчанию FastAPI отдаёт список объектов).
app.add_exception_handler(RequestValidationError, request_validation_handler)
# Схема OpenAPI описывает те же ответы, что отдают обработчики: 422 — строкой, 413 — для операций с телом (код-ревью, BE-02).
install_error_formats(app, max_body_bytes=MAX_REQUEST_BODY_BYTES)


@app.exception_handler(ReferencedRecordError)
async def referenced_record_handler(request: Request, exc: ReferencedRecordError) -> JSONResponse:
    """Защита уровня ORM (before_delete, см. services/integrity.py) сработала в обход
    delete_resource() — отдаём тот же 409 с тем же кодом и текстом, а не 500."""
    return JSONResponse(status_code=409, content={'detail': {'code': exc.code, 'message': str(exc)}})


@app.exception_handler(DataError)
async def data_error_handler(request: Request, exc: DataError) -> JSONResponse:
    """Значение не подошло колонке по типу или размеру (на PostgreSQL — строка длиннее VARCHAR(n), число вне диапазона и т. п.)
    и не было поймано раньше: 422 вместо 500, текст драйвера клиенту не показывается (в нём бывают имена таблиц и
    значения). Подробности — в журнале сервера. Проверка типов и длин по метаданным модели (generic CRUD) срабатывает
    раньше и называет поле; это обработчик последней линии для остальных путей записи."""
    logger.warning('DataError при %s %s: %s', request.method, request.url.path, str(exc.orig)[:300] if exc.orig else type(exc).__name__)
    return JSONResponse(status_code=422, content={'detail': 'Ошибка валидации: значение не подходит по типу или размеру.'})


# Первая таблица, к которой обращается старт приложения (seed_defaults читает из неё маркер): если её нет, схема БД не создана.
SCHEMA_PROBE_TABLE = 'catalog_seed_markers'

SCHEMA_NOT_MIGRATED_MESSAGE = (
    f'База данных не инициализирована: в ней нет таблицы {SCHEMA_PROBE_TABLE} — не применены миграции Alembic. '
    'Выполните в каталоге backend команду «alembic upgrade head» и запустите приложение снова. '
    'Docker (команда запуска образа) и EXE (launcher.py) применяют миграции сами, поэтому эта ошибка возможна только '
    'при прямом запуске «uvicorn app.main:app» на пустой или ещё не обновлённой базе.'
)


def _raise_if_schema_not_migrated(session) -> None:
    """Сбой первого же запроса к БД на старте: если причина — схемы нет вовсе (пустая база без миграций), заменяет ошибку драйвера
    («no such table … [SQL: SELECT …]») понятным указанием, что делать. Любую другую причину (недоступная БД, блокировка, права)
    не маскирует — вызывающий пробрасывает исходное исключение."""
    session.rollback()  # на PostgreSQL после ошибки транзакция прервана, и inspector в ней не сработал бы
    if not sa_inspect(session.get_bind()).has_table(SCHEMA_PROBE_TABLE):
        raise RuntimeError(SCHEMA_NOT_MIGRATED_MESSAGE) from None


def seed_catalogs_on_startup():
    session = SessionLocal()
    try:
        try:
            seed_defaults(session)
        except (OperationalError, ProgrammingError):
            _raise_if_schema_not_migrated(session)
            raise
        # Стандартные правила согласования портов: добавляются по устойчивому коду, существующие (в том
        # числе изменённые администратором) не перезаписываются.
        ensure_default_rules(session)
        auth_settings = get_or_create_auth_settings(session)
        _warn_if_insecure_server_config(auth_settings.enabled)
        _warn_if_remote_access_without_auth(auth_settings.enabled)
        _warn_if_weak_secrets()
    finally:
        session.close()

def _warn_if_weak_secrets() -> None:
    """Токен первичной настройки или пароль БД — заглушка из .env.example либо слишком короткое значение (код-ревью, BE-03).

    docker-compose.yml требует лишь непустое значение, поэтому скопированный и не отредактированный .env запускается. Публичная
    заглушка вместо токена даёт право с любого адреса создать администратора и включить аутентификацию, пока она выключена.
    Запуск НЕ блокируется (существующие установки должны продолжать работать) — только предупреждение; само значение в журнал
    не попадает, называется лишь переменная."""
    if weak_setup_token(SETUP_TOKEN):
        logger.warning(
            "INFRA_REGISTRY_SETUP_TOKEN совпадает с заглушкой из .env.example или короче %d символов: зная такое значение, любой, кто "
            "достаёт до порта, может создать администратора и включить аутентификацию. Замените его на длинную случайную строку, "
            "например: openssl rand -hex 24",
            MIN_SETUP_TOKEN_LENGTH,
        )
    if weak_db_password(make_url(DATABASE_URL).password or ""):  # у SQLite пароля нет — пустая строка слабой не считается
        logger.warning(
            "Пароль базы данных (POSTGRES_PASSWORD или пароль в DATABASE_URL) совпадает с заглушкой из .env.example или короче %d "
            "символов. Замените его на свой пароль.",
            MIN_DB_PASSWORD_LENGTH,
        )

def _warn_if_remote_access_without_auth(auth_enabled: bool) -> None:
    """Доступ по сети открыт (в списке клиентов есть адреса не с этого компьютера), а аутентификация
    выключена — значит любой разрешённый адрес читает и меняет весь реестр без входа. Запуск не блокируется:
    администратор сам выбрал список адресов, а включить аутентификацию можно только на самом компьютере
    (services/auth/guards.require_setup_access) — поэтому подсказываем, как это сделать."""
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
    чтение/запись реестра (первичная настройка при этом защищена, см. services/auth/guards.require_setup_access),
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
_DOCS_PATHS = frozenset({'docs', 'redoc', 'openapi.json', 'docs/oauth2-redirect'})


@app.get('/{full_path:path}', include_in_schema=False)
def spa_fallback(full_path: str):
    if full_path == 'api' or full_path.startswith('api/'):
        raise HTTPException(404, 'Not Found')
    if full_path in _DOCS_PATHS:
        # Документация выключена (иначе маршрут ответил бы раньше этого фоллбэка): честный 404, а не 200 с HTML оболочки.
        raise HTTPException(404, 'Not Found')
    index = FRONTEND_DIR / 'index.html'
    if not index.is_file():
        raise HTTPException(500, f'Файл интерфейса не найден: {index}. Соберите frontend-vue (npm run build).')
    return FileResponse(index, media_type='text/html; charset=utf-8')
