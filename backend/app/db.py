from __future__ import annotations
import sqlite3
from datetime import date, datetime
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from .config import DATABASE_URL, DB_POOL_OPTIONS


def _unicode_lower(value):
    return value.lower() if isinstance(value, str) else value


def register_sqlite_adapters() -> None:
    """Явные адаптеры date/datetime для драйвера sqlite3 (стандартные адаптеры sqlite3 объявлены устаревшими в Python 3.12 и
    засоряют журнал предупреждениями).

    Python 3.12 объявил адаптеры по умолчанию устаревшими: каждый параметр date/datetime, переданный драйверу напрямую, мимо типов
    SQLAlchemy (`text()`, `op.execute()` и `bulk_insert` в миграциях), давал DeprecationWarning — тысячи за прогон тестов, — а в
    будущих версиях Python адаптеров по умолчанию не будет. Здесь регистрируются ровно те преобразования, что делали адаптеры по
    умолчанию (ISO 8601; у datetime — пробел между датой и временем), поэтому значения в БД и их сравнение не меняются.
    Регистрация действует на весь процесс и идемпотентна; вызывается при импорте модуля и из alembic/env.py (миграции из командной
    строки приложение не импортируют). Колонки DateTime/Date через типы SQLAlchemy адаптеров не используют и не затронуты."""
    sqlite3.register_adapter(date, date.isoformat)
    sqlite3.register_adapter(datetime, lambda value: value.isoformat(" "))


def configure_sqlite_connection(dbapi_connection) -> None:
    """Настройка каждого нового соединения SQLite (движок приложения и тестовые движки).

    1. FOREIGN KEY: SQLite объявляет внешние ключи, но не проверяет их, пока это не включено
       явно на соединении. Без этого удаление используемой записи (например, типа устройства,
       на который ещё ссылаются устройства) проходит молча и оставляет «висячие» ссылки.
    2. LOWER(): встроенная функция SQLite приводит к нижнему регистру только ASCII —
       LOWER('Коммутатор') возвращает строку без изменений, и поиск `lower(col) LIKE lower(q)` не
       находил кириллицу при другом регистре («коммутатор» ↔ «Коммутатор»). Заменяем её на
       Unicode-aware версию из Python. PostgreSQL корректно приводит регистр сам."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()
    dbapi_connection.create_function("lower", 1, _unicode_lower, deterministic=True)


def engine_connect_args(database_url: str) -> dict:
    """Параметры подключения драйвера. SQLite: соединение используют потоки пула FastAPI. PostgreSQL: часовой пояс сессии —
    UTC. Время в БД хранится как naive UTC (services/timeutil.py), и сессия в другом поясе не должна менять смысл значений:
    это касается серверных значений (`CURRENT_TIMESTAMP`, `now()` в миграциях и SQL) и любых aware-значений, приведённых
    сервером к своему поясу при записи в `timestamp without time zone`."""
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    if database_url.startswith("postgresql"):
        return {"options": "-c timezone=UTC"}
    return {}


register_sqlite_adapters()
connect_args = engine_connect_args(DATABASE_URL)
# Размер пула — только для серверных СУБД: у SQLite (файл или память) свои классы пула, и параметры QueuePool
# для них недопустимы.
pool_options = {} if DATABASE_URL.startswith("sqlite") else DB_POOL_OPTIONS
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True, pool_pre_ping=True, **pool_options)

if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _configure_sqlite(dbapi_connection, connection_record):
        configure_sqlite_connection(dbapi_connection)


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
