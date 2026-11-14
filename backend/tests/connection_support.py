"""
Общие помощники тестов подключений (A-01 код-ревью main @ b375f58): обычные функции и классы, а не фикстуры — каждый тестовый модуль объявляет свою тонкую
фикстуру поверх них (импорт фикстуры из другого тестового модуля линтер считает переопределением, F811).

* make_world(session) — одно устройство с четырьмя портами и тип подключения, всё зафиксировано (его видят другие сессии);
* scratch_database(kind, directory) — пустая база для проверки миграций: файл SQLite ('sqlite') либо временная база на сервере из
  INFRA_REGISTRY_TEST_DATABASE_URL ('postgres'); удаляется при выходе из контекста.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.models import ConnectionType, DeviceCategory, DeviceInterface, DeviceType, PhysicalDevice
from migration_support import migrate


def make_world(session: Session) -> SimpleNamespace:
    """Одно устройство с четырьмя портами и тип подключения; всё зафиксировано, чтобы его видели другие сессии."""
    category = DeviceCategory(name="Сетевое оборудование")
    session.add(category)
    session.flush()
    device_type = DeviceType(name="Коммутатор", category_id=category.id)
    session.add(device_type)
    session.flush()
    device = PhysicalDevice(device_type_id=device_type.id, serial_number="SN-INV", system_name="sw-inv")
    session.add(device)
    session.flush()
    ports = [DeviceInterface(physical_device_id=device.id, name=f"Gi0/{number}") for number in range(1, 5)]
    connection_type = ConnectionType(name="Витая пара")
    session.add_all([*ports, connection_type])
    session.commit()
    return SimpleNamespace(ports=[port.id for port in ports], ifaces=ports, type_id=connection_type.id)


class Database:
    """Пустая база и её адрес; удаляется вместе с каталогом теста (SQLite) или командой DROP DATABASE (PostgreSQL)."""

    def __init__(self, url: str, engine: sa.Engine, cleanup: Callable[[], None] = lambda: None) -> None:
        self.url, self.engine, self._cleanup = url, engine, cleanup

    def migrate(self, revision: str, *, downgrade: bool = False) -> None:
        migrate(self.url, revision, downgrade=downgrade)

    def close(self) -> None:
        self.engine.dispose()
        self._cleanup()


@contextmanager
def scratch_database(kind: str, directory: Path) -> Iterator[Database]:
    if kind == "sqlite":
        url = f"sqlite:///{directory / 'scratch.db'}"
        database = Database(url, sa.create_engine(url))
    else:
        admin = make_url(os.environ["INFRA_REGISTRY_TEST_DATABASE_URL"])
        name = f"infra_migr_{uuid.uuid4().hex[:10]}"
        admin_engine = sa.create_engine(admin.render_as_string(hide_password=False), isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        url = admin.set(database=name).render_as_string(hide_password=False)

        def drop() -> None:
            with admin_engine.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            admin_engine.dispose()

        database = Database(url, sa.create_engine(url), drop)
    try:
        yield database
    finally:
        database.close()
