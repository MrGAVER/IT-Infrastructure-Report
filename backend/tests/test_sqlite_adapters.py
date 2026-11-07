"""Код-ревью (раздел 5, backend, п. 5): явные адаптеры date/datetime для sqlite3 вместо устаревших адаптеров по умолчанию.

Python 3.12 объявил адаптеры sqlite3 по умолчанию устаревшими: каждый параметр date/datetime, переданный драйверу мимо типов SQLAlchemy
(`text()`, `op.execute()` в миграциях), давал DeprecationWarning — за прогон тестов их набиралось больше двух тысяч, и настоящие
предупреждения тонули в этом шуме. ``db.register_sqlite_adapters`` регистрирует те же преобразования явно. Тест фиксирует главное:
формат строки не изменился (значения в уже существующих базах и их сравнение прежние) и предупреждение не возникает.

Запуск: pytest backend/tests/test_sqlite_adapters.py -v
"""
from __future__ import annotations

import sqlite3
import warnings
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text

from app.db import register_sqlite_adapters

# Формат, который давали адаптеры по умолчанию: date.isoformat() и datetime.isoformat(" ").
CASES = [
    pytest.param(datetime(2026, 11, 8, 1, 2, 3, 456789), "2026-11-08 01:02:03.456789", id="datetime с микросекундами"),
    pytest.param(datetime(2026, 11, 8, 1, 2, 3), "2026-11-08 01:02:03", id="datetime без микросекунд"),
    pytest.param(datetime(2026, 11, 8, 1, 2, 3, tzinfo=timezone(timedelta(hours=3))), "2026-11-08 01:02:03+03:00", id="datetime со смещением"),
    pytest.param(date(2026, 11, 8), "2026-11-08", id="date"),
]


@pytest.mark.parametrize(("value", "expected"), CASES)
def test_driver_receives_the_same_string_as_with_the_default_adapters(value, expected):
    connection = sqlite3.connect(":memory:")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error")  # на адаптерах по умолчанию Python 3.12+ здесь было бы DeprecationWarning
            assert connection.execute("SELECT ?", (value,)).fetchone()[0] == expected
    finally:
        connection.close()


@pytest.mark.parametrize(("value", "expected"), CASES)
def test_untyped_sqlalchemy_parameters_take_the_same_path(value, expected):
    # Так значения попадают в драйвер из миграций: text() без типа колонки — SQLAlchemy не преобразует datetime сам.
    engine = create_engine("sqlite://")
    try:
        with engine.connect() as connection, warnings.catch_warnings():
            warnings.simplefilter("error")
            assert connection.execute(text("SELECT :value"), {"value": value}).scalar_one() == expected
    finally:
        engine.dispose()


def test_registration_is_idempotent():
    register_sqlite_adapters()
    register_sqlite_adapters()
    connection = sqlite3.connect(":memory:")
    try:
        assert connection.execute("SELECT ?", (date(2026, 1, 2),)).fetchone()[0] == "2026-01-02"
    finally:
        connection.close()
