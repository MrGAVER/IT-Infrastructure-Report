from __future__ import annotations
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from .config import DATABASE_URL

connect_args = {'check_same_thread': False} if DATABASE_URL.startswith('sqlite') else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True, pool_pre_ping=True)

if DATABASE_URL.startswith('sqlite'):
    # SQLite declares FOREIGN KEY constraints but does not enforce them unless explicitly told to
    # per-connection. Without this, deleting a referenced row (e.g. a device type still used by
    # physical devices) succeeds silently and leaves dangling references elsewhere.
    @event.listens_for(engine, 'connect')
    def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

def get_db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
