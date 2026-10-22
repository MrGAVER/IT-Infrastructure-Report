from __future__ import annotations
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from .config import DATABASE_URL, DB_POOL_OPTIONS

def _unicode_lower(value):
    return value.lower() if isinstance(value, str) else value


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
    cursor.execute('PRAGMA foreign_keys=ON')
    cursor.close()
    dbapi_connection.create_function('lower', 1, _unicode_lower, deterministic=True)


connect_args = {'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
# Размер пула — только для серверных СУБД: у SQLite (файл или память) свои классы пула, и параметры QueuePool
# для них недопустимы.
pool_options = {} if DATABASE_URL.startswith('sqlite') else DB_POOL_OPTIONS
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True, pool_pre_ping=True, **pool_options)

if DATABASE_URL.startswith('sqlite'):
    @event.listens_for(engine, 'connect')
    def _configure_sqlite(dbapi_connection, connection_record):
        configure_sqlite_connection(dbapi_connection)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
