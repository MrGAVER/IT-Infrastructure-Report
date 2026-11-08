"""Общие помощники тестов миграций: вставка строк в схему ЛЮБОЙ ревизии (test_migrations_postgres.py,
test_migrations_drop_entity_status.py). Тесты в репозитории самодостаточны, но эта вставка нужна обоим и не зависит от СУБД."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

import app.config as app_config

BACKEND_DIR = Path(__file__).resolve().parent.parent


def alembic_config() -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg


def migrate(url: str, revision: str = "head", *, downgrade: bool = False) -> None:
    """upgrade/downgrade до ревизии на базе `url`. env.py читает app.config.DATABASE_URL при каждом запуске команды — подставляем
    адрес на время миграции."""
    original = app_config.DATABASE_URL
    app_config.DATABASE_URL = url
    try:
        (command.downgrade if downgrade else command.upgrade)(alembic_config(), revision)
    finally:
        app_config.DATABASE_URL = original


def dummy(column_type, name: str):
    if isinstance(column_type, sa.Boolean):
        return False
    if isinstance(column_type, sa.DateTime):
        return datetime.now()
    if isinstance(column_type, sa.Date):
        return date.today()
    if isinstance(column_type, (sa.Integer, sa.Float, sa.Numeric)):
        return 0
    return f"{name}-{uuid.uuid4().hex[:8]}"


def insert_row(connection, table: str, **values) -> str | None:
    """INSERT одной строки; id и обязательные колонки без значения по умолчанию заполняются заглушками, а обязательные
    внешние ключи — новой родительской строкой. Возвращает id вставленной строки."""
    inspector = sa.inspect(connection)
    foreign = {fk["constrained_columns"][0]: fk["referred_table"] for fk in inspector.get_foreign_keys(table) if len(fk["constrained_columns"]) == 1}
    row = dict(values)
    for column in inspector.get_columns(table):
        name = column["name"]
        if name in row:
            continue
        if name == "id":
            row[name] = str(uuid.uuid4())
        elif column["nullable"] or column.get("default") is not None or column.get("autoincrement") is True:
            continue
        elif name in foreign:
            row[name] = insert_row(connection, foreign[name])
        else:
            row[name] = dummy(column["type"], name)
    names = ", ".join(f'"{key}"' for key in row)
    marks = ", ".join(f":{key}" for key in row)
    connection.execute(sa.text(f'INSERT INTO "{table}" ({names}) VALUES ({marks})'), row)
    return row.get("id")
