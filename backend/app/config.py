from __future__ import annotations
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
APP_DATA_DIR = Path(os.getenv('INFRA_REGISTRY_DATA_DIR', str(BASE_DIR))).expanduser().resolve()
APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR = APP_DATA_DIR / 'reports'
REPORT_DIR.mkdir(parents=True, exist_ok=True)
# Сколько дней хранятся сгенерированные отчёты: файл нужен только пока его скачивают, а каталог без
# очистки рос бы бесконечно. 0 — не удалять никогда.
REPORT_RETENTION_DAYS = int(os.getenv('INFRA_REGISTRY_REPORT_RETENTION_DAYS', '30'))


def _database_url() -> str:
    """Адрес базы данных.

    1. DATABASE_URL — готовая строка (внешний сервер, нестандартные параметры). Пароль в ней нужно экранировать самому:
       символ «@», «%xx» и подобные в нём ломают разбор адреса.
    2. Иначе, если задан INFRA_REGISTRY_DB_HOST, адрес PostgreSQL собирается из частей: INFRA_REGISTRY_DB_PORT (5432),
       POSTGRES_USER (infra), POSTGRES_PASSWORD, POSTGRES_DB (infra_registry). Так работает docker-compose.yml: пароль
       берётся из .env как есть, любые символы допустимы, экранирование делает SQLAlchemy.
    3. Иначе — файл SQLite в каталоге данных."""
    explicit = os.getenv('DATABASE_URL', '').strip()
    if explicit:
        return explicit
    host = os.getenv('INFRA_REGISTRY_DB_HOST', '').strip()
    if host:
        from sqlalchemy.engine import URL

        return URL.create(
            'postgresql+psycopg',
            username=os.getenv('POSTGRES_USER', 'infra') or 'infra',
            password=os.getenv('POSTGRES_PASSWORD') or None,
            host=host,
            port=int(os.getenv('INFRA_REGISTRY_DB_PORT') or 5432),
            database=os.getenv('POSTGRES_DB', 'infra_registry') or 'infra_registry',
        ).render_as_string(hide_password=False)
    return f'sqlite:///{APP_DATA_DIR / "infra_registry.db"}'


DATABASE_URL = _database_url()


def _optional_number_env(name: str, cast):
    """Необязательное число из переменной окружения: не задана или пуста — None (остаётся значение SQLAlchemy по
    умолчанию), нечисловое значение — явная ошибка запуска, а не молчаливое игнорирование опечатки."""
    raw = os.getenv(name, '').strip()
    if not raw:
        return None
    try:
        value = cast(raw)
    except ValueError as exc:
        raise ValueError(f'{name}: ожидается число, получено {raw!r}') from exc
    if value < 0:
        raise ValueError(f'{name}: значение не может быть отрицательным ({raw})')
    return value


# Размер пула соединений для серверных СУБД (PostgreSQL): по умолчанию SQLAlchemy берёт 5 + 10 переполнения и ждёт
# соединение 30 с. Каждый API-запрос держит соединение обработчика; при нескольких одновременных пользователях значения
# можно поднять (не больше max_connections сервера БД). Для SQLite не применяется.
DB_POOL_OPTIONS = {
    key: value
    for key, value in {
        'pool_size': _optional_number_env('INFRA_REGISTRY_DB_POOL_SIZE', int),
        'max_overflow': _optional_number_env('INFRA_REGISTRY_DB_MAX_OVERFLOW', int),
        'pool_timeout': _optional_number_env('INFRA_REGISTRY_DB_POOL_TIMEOUT', float),
    }.items()
    if value is not None
}
# Основной UI — собранный Vue-фронтенд (frontend-vue/dist), см. frontend-vue/README.md.
# Каталог появляется только после `npm run build` в frontend-vue — локально при разработке
# из исходников (без сборки) GET '/' отдаст понятную 500-ошибку с указанием отсутствующего
# файла (см. main.py:spa_fallback), а не тихо упадёт. В Docker/PyInstaller-сборке
# каталог собирается/копируется как часть сборки (см. backend/Dockerfile, infra_registry.spec).
FRONTEND_DIR = Path(os.getenv('INFRA_REGISTRY_FRONTEND_DIR', str(BASE_DIR / 'frontend-vue' / 'dist'))).expanduser().resolve()
APP_VERSION = '2.157.0'

def _csv_env(name: str, default: str = '') -> list[str]:
    """Список из переменной окружения через запятую: пробелы и пустые элементы отбрасываются."""
    return [item.strip() for item in os.getenv(name, default).split(',') if item.strip()]


# Интерфейс отдаётся с того же origin (StaticFiles ниже), а API читает токен из заголовка
# Authorization — поэтому по умолчанию CORS ВЫКЛЮЧЕН (пустой список: ни одного чужого origin не
# разрешено). Раньше дефолтом было '*', и любая веб-страница в браузере владельца могла читать и
# менять данные локального приложения. Разрешить конкретные origin'ы нужно только для отдельного
# фронтенда, например dev-сервера Vite: INFRA_REGISTRY_CORS_ORIGINS=http://localhost:5173
CORS_ALLOWED_ORIGINS = _csv_env('INFRA_REGISTRY_CORS_ORIGINS')

# Прокси, которым доверяет uvicorn (его собственная переменная, значение читаем так же). Здесь нужна только для
# проверки происхождения запросов (services/csrf_guard.py): X-Forwarded-Host учитывается лишь за настоящим прокси.
FORWARDED_ALLOW_IPS = _csv_env('FORWARDED_ALLOW_IPS')

# Допустимые значения заголовка Host (защита от DNS-rebinding: страница чужого домена, перенацеленная
# на 127.0.0.1, приходит с чужим Host). По умолчанию — только локальные имена, что верно для
# EXE-режима (слушает 127.0.0.1) и разработки. Для серверного развёртывания добавьте реальное имя
# хоста, например INFRA_REGISTRY_ALLOWED_HOSTS=reestr.corp.local,10.0.0.5; '*' отключает проверку
# (так по умолчанию задано в docker-compose.yml, чтобы обновление не ломало доступ по IP).
ALLOWED_HOSTS = _csv_env('INFRA_REGISTRY_ALLOWED_HOSTS', 'localhost,127.0.0.1')

# Адреса и подсети клиентов, которым разрешено подключаться (через запятую: 192.168.1.15,10.0.5.0/24).
# Пусто — фильтра нет и пускаются все (Docker, запуск из исходников: доступ там ограничивает сетевая
# настройка). EXE-лаунчер всегда задаёт список из файла настроек рядом с EXE (infra_registry.toml), где
# по умолчанию разрешена только петля 127.0.0.0/8, то есть доступ только с того же компьютера.
ALLOWED_CLIENTS = _csv_env('INFRA_REGISTRY_ALLOWED_CLIENTS')

# Токен первичной настройки аутентификации. Пока аутентификация выключена (это значение по
# умолчанию), создавать пользователей и включать её можно только с localhost без прокси-заголовков
# либо — если токен задан — с заголовком X-Setup-Token. Задайте токен, когда приложение стоит за
# обратным прокси или в Docker, где адрес клиента не localhost.
SETUP_TOKEN = os.getenv('INFRA_REGISTRY_SETUP_TOKEN', '')

# Content-Security-Policy для интерфейса и API. Пустая строка отключает заголовок целиком (например,
# если политику выставляет обратный прокси); любое другое значение заменяет политику по умолчанию.
CSP_POLICY = os.getenv(
    'INFRA_REGISTRY_CSP',
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'",
)

# Аутентификация выключаема на уровне данных (AuthSettings.enabled, см. services/auth.py) —
# переменные ниже настраивают её поведение, когда она включена, а не сам факт включения.
AUTH_SESSION_TTL_HOURS = float(os.getenv('INFRA_REGISTRY_SESSION_TTL_HOURS', '12'))
# 10, а не 5: от перебора с одного адреса защищает троттлинг входа (services/login_throttle.py), а
# блокировка учётной записи — запасной рубеж против распределённого подбора; чем она чувствительнее,
# тем проще посторонним держать администратора заблокированным.
AUTH_MAX_FAILED_ATTEMPTS = int(os.getenv('INFRA_REGISTRY_AUTH_MAX_ATTEMPTS', '10'))
AUTH_LOCKOUT_MINUTES = float(os.getenv('INFRA_REGISTRY_AUTH_LOCKOUT_MINUTES', '15'))
AUTH_MIN_PASSWORD_LENGTH = int(os.getenv('INFRA_REGISTRY_AUTH_MIN_PASSWORD_LENGTH', '8'))
