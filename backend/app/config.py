from __future__ import annotations
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable

from .constants import AUDIT_RETENTION_MAX_DAYS

# Переменные окружения как отображение: настройки читаются из os.environ, а тесты и вызывающий код могут передать свой словарь, не меняя процесс.
Environ = Mapping[str, str]


def _environ(env: Environ | None) -> Environ:
    return os.environ if env is None else env


def _number_env(name: str, default: Any, cast: Callable[[str], Any], *, minimum: Any = None, maximum: Any = None, env: Environ | None = None) -> Any:
    """Число из переменной окружения: не задана, пуста или из одних пробелов — ``default``; нечисловое значение или меньше ``minimum`` —
    явная ошибка запуска с ИМЕНЕМ переменной (а не молчаливое игнорирование опечатки и не безымянный ``invalid literal for int()``).

    Пустая строка — обычное дело: так выглядят незаполненные строки в ``.env`` (``VAR=``), а docker-compose передаёт в контейнер пустое
    значение вместо отсутствующего. Раньше такие переменные разбирались «голым» ``int(os.getenv(...))`` и роняли запуск при импорте модуля.
    ``inf`` и ``nan`` у дробных значений — тоже ошибка запуска. ``minimum=None`` / ``maximum=None`` — нижней / верхней границы нет.
    ``env`` — откуда читать (по умолчанию ``os.environ``)."""
    raw = _environ(env).get(name, "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError as exc:
        raise ValueError(f"{name}: ожидается число, получено {raw!r}") from exc
    # float('inf') проходит проверку минимума, а nan — любую; ошибка вылезла бы позже, в рантайме
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{name}: ожидается конечное число, получено {raw!r}")
    if minimum is not None and value < minimum:
        raise ValueError(f"{name}: значение не может быть меньше {minimum} ({raw})")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name}: значение не может быть больше {maximum} ({raw})")
    return value


def _optional_number_env(name: str, cast: Callable[[str], Any], *, env: Environ | None = None) -> Any:
    """Необязательное неотрицательное число: не задано или пусто — None (остаётся значение SQLAlchemy по умолчанию), отрицательное или
    нечисловое — ошибка запуска. Частный случай ``_number_env``."""
    return _number_env(name, None, cast, minimum=0, env=env)


def _csv_env(name: str, default: str = "", *, env: Environ | None = None) -> list[str]:
    """Список из переменной окружения через запятую: пробелы и пустые элементы отбрасываются."""
    return [item.strip() for item in _environ(env).get(name, default).split(",") if item.strip()]


def _flag_env(name: str, *, env: Environ | None = None) -> bool:
    """Булев переключатель из переменной окружения: «1», «true», «yes», «on» (регистр и пробелы не важны) — включено, всё остальное и пусто — выключено."""
    return _environ(env).get(name, "").strip().lower() in {"1", "true", "yes", "on"}


BASE_DIR = Path(__file__).resolve().parents[2]


def _database_url(data_dir: Path | None = None, *, env: Environ | None = None) -> str:
    """Адрес базы данных.

    1. DATABASE_URL — готовая строка (внешний сервер, нестандартные параметры). Пароль в ней нужно экранировать самому:
       символ «@», «%xx» и подобные в нём ломают разбор адреса.
    2. Иначе, если задан INFRA_REGISTRY_DB_HOST, адрес PostgreSQL собирается из частей: INFRA_REGISTRY_DB_PORT (5432),
       POSTGRES_USER (infra), POSTGRES_PASSWORD, POSTGRES_DB (infra_registry). Так работает docker-compose.yml: пароль
       берётся из .env как есть, любые символы допустимы, экранирование делает SQLAlchemy.
    3. Иначе — файл SQLite в каталоге данных (``data_dir``; по умолчанию APP_DATA_DIR)."""
    variables = _environ(env)
    explicit = variables.get("DATABASE_URL", "").strip()
    if explicit:
        return explicit
    host = variables.get("INFRA_REGISTRY_DB_HOST", "").strip()
    if host:
        from sqlalchemy.engine import URL

        return URL.create(
            "postgresql+psycopg",
            username=variables.get("POSTGRES_USER", "infra") or "infra",
            password=variables.get("POSTGRES_PASSWORD") or None,
            host=host,
            port=int(variables.get("INFRA_REGISTRY_DB_PORT") or 5432),
            database=variables.get("POSTGRES_DB", "infra_registry") or "infra_registry",
        ).render_as_string(hide_password=False)
    return f"sqlite:///{(APP_DATA_DIR if data_dir is None else data_dir) / 'infra_registry.db'}"


# Content-Security-Policy для интерфейса и API по умолчанию (переопределяется INFRA_REGISTRY_CSP).
_DEFAULT_CSP_POLICY = "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"


@dataclass(frozen=True, slots=True)
class Settings:
    """Настройки приложения из переменных окружения: неизменяемый снимок, собираемый одним местом (``from_env``).

    Разбор окружения ничего не создаёт на диске: каталоги создаёт ``ensure_data_dirs()`` — при старте приложения (lifespan), в launcher.py и
    в alembic/env.py. Прежние имена ``config.APP_DATA_DIR``, ``config.DATABASE_URL`` и т. д. остались псевдонимами значений этого объекта: на них
    ссылаются десятки модулей, а тесты подменяют их через monkeypatch. Менять настройки в рантайме нельзя и не нужно — для тестов
    ``Settings.from_env({...})`` собирает объект из своего словаря, не трогая ``os.environ``."""

    data_dir: Path
    report_dir: Path
    report_retention_days: int
    audit_retention_days: int
    database_url: str
    report_max_files: int
    db_pool_options: Mapping[str, Any]
    frontend_dir: Path
    cors_allowed_origins: tuple[str, ...]
    forwarded_allow_ips: tuple[str, ...]
    allowed_hosts: tuple[str, ...]
    accept_ip_hosts: bool
    allowed_clients: tuple[str, ...]
    max_request_body_bytes: int
    setup_token: str
    csp_policy: str
    auth_session_ttl_hours: float
    auth_max_failed_attempts: int
    auth_lockout_minutes: float
    auth_min_password_length: int
    auth_lockout_known_client_bypass: bool
    auth_known_client_days: int
    enable_docs: bool

    @classmethod
    def from_env(cls, env: Environ | None = None) -> Settings:
        """Собирает настройки из ``env`` (по умолчанию ``os.environ``). Неверное значение — ``ValueError`` с именем переменной."""
        variables = _environ(env)
        data_dir = Path(variables.get("INFRA_REGISTRY_DATA_DIR", str(BASE_DIR))).expanduser().resolve()
        report_max_files = _optional_number_env("INFRA_REGISTRY_REPORT_MAX_FILES", int, env=variables)
        pool_options = {
            key: value
            for key, value in {
                "pool_size": _optional_number_env("INFRA_REGISTRY_DB_POOL_SIZE", int, env=variables),
                "max_overflow": _optional_number_env("INFRA_REGISTRY_DB_MAX_OVERFLOW", int, env=variables),
                "pool_timeout": _optional_number_env("INFRA_REGISTRY_DB_POOL_TIMEOUT", float, env=variables),
            }.items()
            if value is not None
        }
        return cls(
            data_dir=data_dir,
            report_dir=data_dir / "reports",
            # minimum намеренно не задан: 0 и меньше — не удалять (report_cleanup.py)
            report_retention_days=_number_env("INFRA_REGISTRY_REPORT_RETENTION_DAYS", 30, int, env=variables),
            audit_retention_days=_number_env("INFRA_REGISTRY_AUDIT_RETENTION_DAYS", 0, int, minimum=0, maximum=AUDIT_RETENTION_MAX_DAYS, env=variables),
            database_url=_database_url(data_dir, env=variables),
            report_max_files=200 if report_max_files is None else report_max_files,
            db_pool_options=MappingProxyType(pool_options),
            frontend_dir=Path(variables.get("INFRA_REGISTRY_FRONTEND_DIR", str(BASE_DIR / "frontend-vue" / "dist"))).expanduser().resolve(),
            cors_allowed_origins=tuple(_csv_env("INFRA_REGISTRY_CORS_ORIGINS", env=variables)),
            forwarded_allow_ips=tuple(_csv_env("FORWARDED_ALLOW_IPS", env=variables)),
            allowed_hosts=tuple(_csv_env("INFRA_REGISTRY_ALLOWED_HOSTS", "localhost,127.0.0.1", env=variables)),
            accept_ip_hosts=_flag_env("INFRA_REGISTRY_ACCEPT_IP_HOSTS", env=variables),
            allowed_clients=tuple(_csv_env("INFRA_REGISTRY_ALLOWED_CLIENTS", env=variables)),
            max_request_body_bytes=_number_env("INFRA_REGISTRY_MAX_REQUEST_BODY_BYTES", 2 * 1024 * 1024, int, minimum=0, env=variables),
            setup_token=variables.get("INFRA_REGISTRY_SETUP_TOKEN", ""),
            csp_policy=variables.get("INFRA_REGISTRY_CSP", _DEFAULT_CSP_POLICY),
            auth_session_ttl_hours=_number_env("INFRA_REGISTRY_SESSION_TTL_HOURS", 12.0, float, minimum=0, env=variables),
            auth_max_failed_attempts=_number_env("INFRA_REGISTRY_AUTH_MAX_ATTEMPTS", 10, int, minimum=1, env=variables),
            auth_lockout_minutes=_number_env("INFRA_REGISTRY_AUTH_LOCKOUT_MINUTES", 15.0, float, minimum=0, env=variables),
            auth_min_password_length=_number_env("INFRA_REGISTRY_AUTH_MIN_PASSWORD_LENGTH", 8, int, minimum=1, env=variables),
            auth_lockout_known_client_bypass=variables.get("INFRA_REGISTRY_AUTH_LOCKOUT_KNOWN_CLIENT_BYPASS", "1").strip().lower() not in {"0", "false", "no", "off"},
            auth_known_client_days=_number_env("INFRA_REGISTRY_AUTH_KNOWN_CLIENT_DAYS", 30, int, minimum=0, env=variables),
            enable_docs=_flag_env("INFRA_REGISTRY_ENABLE_DOCS", env=variables),
        )


# Единственный разбор окружения при импорте модуля. Каталоги здесь НЕ создаются (раньше mkdir стоял прямо в теле модуля, и любой скрипт или тест,
# импортировавший app.config, оставлял папки в текущем каталоге): см. ensure_data_dirs().
settings = Settings.from_env()

APP_DATA_DIR = settings.data_dir
REPORT_DIR = settings.report_dir


def ensure_data_dirs(*directories: Path) -> None:
    """Создаёт каталоги данных (без аргументов — APP_DATA_DIR и REPORT_DIR); существующие не трогает.

    Вызывается явно: из lifespan приложения, launcher.py (EXE) и alembic/env.py (миграции из командной строки и из docker-entrypoint.sh,
    где SQLite-файл лежит в каталоге данных). Значения по умолчанию читаются при вызове, а не при импорте: тесты подменяют
    ``config.REPORT_DIR``. Нельзя создать каталог (нет прав, диск только для чтения) — ``OSError`` с путём в тексте, а не молчаливое продолжение."""
    for directory in directories or (APP_DATA_DIR, REPORT_DIR):
        directory.mkdir(parents=True, exist_ok=True)


# Подкаталог REPORT_DIR для отчётов журнала аудита: в них логины, адреса и неудачные входы, поэтому их скачивает только
# администратор, а общий эндпоинт скачивания ищет файлы лишь в корне REPORT_DIR и до этого подкаталога не дотянется. Создаётся при первом отчёте.
AUDIT_REPORT_SUBDIR = "audit"
# Сколько дней хранятся сгенерированные отчёты: файл нужен только пока его скачивают, а каталог без
# очистки рос бы бесконечно. 0 — не удалять никогда.
REPORT_RETENTION_DAYS = settings.report_retention_days
# Срок хранения записей журнала аудита, дней: записи старше удаляются (services/audit_retention.py). 0 — не удалять
# никогда (по умолчанию: журнал аудита нельзя терять молча, решение о ротации принимает владелец). Это значение по умолчанию: администратор
# может задать срок в форме «Настройки аудита» — значение из формы (audit_settings.retention_days) важнее переменной окружения.
AUDIT_RETENTION_DAYS = settings.audit_retention_days

DATABASE_URL = settings.database_url


# Сколько файлов отчётов остаётся в каталоге: отчёт может сформировать любой клиент (роль viewer или вход выключен), и без
# квоты цикл запросов заполнил бы диск; срок хранения (REPORT_RETENTION_DAYS) этому не мешает. Лишние удаляются, самые
# старые первыми, независимо от возраста. 0 — без ограничения по количеству; нечисловое значение — ошибка запуска.
REPORT_MAX_FILES = settings.report_max_files


# Размер пула соединений для серверных СУБД (PostgreSQL): по умолчанию SQLAlchemy берёт 5 + 10 переполнения и ждёт
# соединение 30 с. Каждый API-запрос держит соединение обработчика; при нескольких одновременных пользователях значения
# можно поднять (не больше max_connections сервера БД). Для SQLite не применяется.
DB_POOL_OPTIONS = dict(settings.db_pool_options)
# Основной UI — собранный Vue-фронтенд (frontend-vue/dist), см. frontend-vue/README.md.
# Каталог появляется только после `npm run build` в frontend-vue — локально при разработке
# из исходников (без сборки) GET '/' отдаст понятную 500-ошибку с указанием отсутствующего
# файла (см. main.py:spa_fallback), а не тихо упадёт. В Docker/PyInstaller-сборке
# каталог собирается/копируется как часть сборки (см. backend/Dockerfile, infra_registry.spec).
FRONTEND_DIR = settings.frontend_dir
APP_VERSION = "2.160.0"

# Интерфейс отдаётся с того же origin (StaticFiles ниже), а API читает токен из заголовка
# Authorization — поэтому по умолчанию CORS ВЫКЛЮЧЕН (пустой список: ни одного чужого origin не
# разрешено). Раньше дефолтом было '*', и любая веб-страница в браузере владельца могла читать и
# менять данные локального приложения. Разрешить конкретные origin'ы нужно только для отдельного
# фронтенда, например dev-сервера Vite: INFRA_REGISTRY_CORS_ORIGINS=http://localhost:5173
CORS_ALLOWED_ORIGINS = list(settings.cors_allowed_origins)

# Прокси, которым доверяет uvicorn (его собственная переменная, значение читаем так же). Здесь нужна только для
# проверки происхождения запросов (services/csrf_guard.py): X-Forwarded-Host учитывается лишь за настоящим прокси.
FORWARDED_ALLOW_IPS = list(settings.forwarded_allow_ips)

# Допустимые значения заголовка Host (защита от DNS-rebinding: страница чужого домена, перенацеленная
# на 127.0.0.1, приходит с чужим Host). По умолчанию — только локальные имена, что верно для
# EXE-режима (слушает 127.0.0.1) и разработки. Для серверного развёртывания добавьте реальное имя
# хоста, например INFRA_REGISTRY_ALLOWED_HOSTS=reestr.corp.local; '*' отключает проверку целиком (при выключенной
# аутентификации это открывает реестр чужим веб-страницам через DNS-rebinding, при старте пишется предупреждение).
ALLOWED_HOSTS = list(settings.allowed_hosts)

# Принимать заголовок Host в виде IP-адреса (http://10.0.0.5:8000) независимо от списка ALLOWED_HOSTS. При DNS-rebinding в Host всегда
# стоит имя домена злоумышленника — IP-адрес подменить через DNS нельзя, поэтому такой доступ безопасен и не требует перечислять адрес
# сервера в настройках. Включено в docker-compose.yml (там сервер открывают по адресу компьютера); вне compose по умолчанию выключено:
# запуск из исходников и EXE слушают только 127.0.0.1, а при клиентах из сети IP-адрес принимается и без этого флага (см. main.install_http_security).
ACCEPT_IP_HOSTS = settings.accept_ip_hosts

# Адреса и подсети клиентов, которым разрешено подключаться (через запятую: 192.168.1.15,10.0.5.0/24).
# Пусто — фильтра нет и пускаются все (Docker, запуск из исходников: доступ там ограничивает сетевая
# настройка). EXE-лаунчер всегда задаёт список из файла настроек рядом с EXE (infra_registry.toml), где
# по умолчанию разрешена только петля 127.0.0.0/8, то есть доступ только с того же компьютера.
ALLOWED_CLIENTS = list(settings.allowed_clients)

# Наибольший размер тела запроса, байт (services/body_limit.py): больше — 413 REQUEST_BODY_TOO_LARGE, тело не разбирается. Все тела
# приложения — JSON; самый тяжёлый легитимный запрос — SVG-иконка (длиннее 256 К символов её всё равно пропускает экспорт диаграммы,
# а в JSON с экранированием это до 1,5 МБ) — укладывается с запасом. Если реальный сценарий не проходит, поднимите предел;
# 0 — проверка выключена (тогда защиту должен давать обратный прокси).
MAX_REQUEST_BODY_BYTES = settings.max_request_body_bytes

# Токен первичной настройки аутентификации. Пока аутентификация выключена (это значение по
# умолчанию), создавать пользователей и включать её можно только с localhost без прокси-заголовков
# либо — если токен задан — с заголовком X-Setup-Token. Задайте токен, когда приложение стоит за
# обратным прокси или в Docker, где адрес клиента не localhost. Слабый токен (см. weak_setup_token ниже) не принимается:
# он приравнен к незаданному, то есть остаётся только прямой localhost.
SETUP_TOKEN = settings.setup_token

# Значения-заглушки из .env.example и самые ходовые слабые пароли. docker-compose.yml требует лишь непустое значение, поэтому
# скопированный и не отредактированный .env запускался без возражений, а публичная заглушка вместо токена давала бы право с любого адреса
# создать администратора и включить аутентификацию. Запуск не блокируется (существующие установки продолжают
# работать): при старте в журнал пишется предупреждение (main._warn_if_weak_secrets), а слабый токен установки сервер не принимает
# (services/auth/guards.require_setup_access). Пароль БД только предупреждается.
PLACEHOLDER_SECRETS = frozenset({"change_me", "change_me_long_random_string", "changeme", "password", "secret"})
# Токен из `openssl rand -hex 24` — 48 символов; 16 — нижняя граница, ниже которой перебор по сети уже реалистичен.
MIN_SETUP_TOKEN_LENGTH = 16
# Пароль БД только предупреждается как заведомо слабый: порт БД в compose наружу не публикуется, поэтому планка ниже.
MIN_DB_PASSWORD_LENGTH = 8


def weak_secret(value: str, min_length: int) -> bool:
    """Секрет задан, но это заглушка из .env.example (без учёта регистра и пробелов по краям) или он короче ``min_length``.
    Пустое значение слабым не считается: «не задан» — другой случай, его обрабатывает вызывающий код (токен выключен и т. п.)."""
    return bool(value) and (value.strip().lower() in PLACEHOLDER_SECRETS or len(value) < min_length)


def weak_setup_token(token: str) -> bool:
    """Токен первичной настройки (INFRA_REGISTRY_SETUP_TOKEN) — заглушка или короче MIN_SETUP_TOKEN_LENGTH."""
    return weak_secret(token, MIN_SETUP_TOKEN_LENGTH)


def weak_db_password(password: str) -> bool:
    """Пароль БД (POSTGRES_PASSWORD или пароль из DATABASE_URL) — заглушка или короче MIN_DB_PASSWORD_LENGTH."""
    return weak_secret(password, MIN_DB_PASSWORD_LENGTH)


# Content-Security-Policy для интерфейса и API. Пустая строка отключает заголовок целиком (например,
# если политику выставляет обратный прокси); любое другое значение заменяет политику по умолчанию.
CSP_POLICY = settings.csp_policy

# Аутентификация выключаема на уровне данных (AuthSettings.enabled, см. services/auth/settings.py) —
# переменные ниже настраивают её поведение, когда она включена, а не сам факт включения.
AUTH_SESSION_TTL_HOURS = settings.auth_session_ttl_hours
# 10, а не 5: от перебора с одного адреса защищает троттлинг входа (services/login_throttle.py), а
# блокировка учётной записи — запасной рубеж против распределённого подбора; чем она чувствительнее,
# тем проще посторонним держать администратора заблокированным.
# minimum=1 у порога и длины пароля: 0 блокировал бы вход после первой же ошибки / снимал бы требование к длине пароля (остаются проверки
# «буквы и цифры»).
AUTH_MAX_FAILED_ATTEMPTS = settings.auth_max_failed_attempts
AUTH_LOCKOUT_MINUTES = settings.auth_lockout_minutes
AUTH_MIN_PASSWORD_LENGTH = settings.auth_min_password_length
# Блокировка учётной записи после серии неудачных входов (выше) сама становится оружием: любой, кто достаёт до /login, может
# держать администратора заблокированным, посылая неверные пароли (имена пользователей перечисляются — 423 подтверждает
# существование). Поэтому блокировка отклоняет вход только с «незнакомых» адресов: адрес, с которого этот пользователь уже входил
# успешно за последние AUTH_KNOWN_CLIENT_DAYS дней, проходит проверку пароля, а подбор с него ограничивают счётчик и троттлинг входа.
# За обратным прокси задайте FORWARDED_ALLOW_IPS: иначе у всех клиентов адрес прокси, и «знакомым» окажется любой. 0 — отключить.
AUTH_LOCKOUT_KNOWN_CLIENT_BYPASS = settings.auth_lockout_known_client_bypass
AUTH_KNOWN_CLIENT_DAYS = settings.auth_known_client_days

# Интерактивная документация API (/docs, /redoc, /openapi.json) по умолчанию выключена: она раскрывает полную карту API и
# моделей данных любому посетителю (проверка входа касается только /api/*), а Swagger UI/ReDoc подгружают скрипты с внешнего CDN —
# в закрытом контуре страницы всё равно не работают. Для разработки: INFRA_REGISTRY_ENABLE_DOCS=1 (страницы открыты без входа).
ENABLE_DOCS = settings.enable_docs
