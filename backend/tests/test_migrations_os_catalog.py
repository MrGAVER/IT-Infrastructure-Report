"""Миграция c4e8a7d91b20: свободный текст ОС и справочник платформ виртуализации → каталог operating_systems.

Миграция ищет уже созданную запись каталога по тройке (категория, имя, версия). Версия бывает пустой, а в SQL `version = NULL` не
сопоставляет ничего — поэтому для пустой версии нужен `IS NULL`. Прежняя запись `version IS :version` работала только в SQLite и
на PostgreSQL падала синтаксической ошибкой (проверка там — test_migrations_postgres.py). Здесь закрепляется то же поведение на SQLite:
исправление не должно было его изменить.

Гоняется на одноразовой SQLite БД.
Запуск: pytest backend/tests/test_migrations_os_catalog.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.script import ScriptDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))
from migration_support import alembic_config, insert_row, migrate  # noqa: E402

REVISION = "c4e8a7d91b20"


@pytest.fixture()
def database(tmp_path):
    url = f"sqlite:///{tmp_path / 'os_catalog.db'}"
    migrate(url, ScriptDirectory.from_config(alembic_config()).get_revision(REVISION).down_revision)
    engine = sa.create_engine(url)
    yield url, engine
    engine.dispose()


def test_free_text_os_moves_into_the_catalog_and_repeats_share_one_entry(database):
    url, engine = database
    with engine.begin() as connection:
        platform = insert_row(connection, "virtualization_platforms", name="VMware ESXi", vendor="VMware", version="8")
        windows_a = insert_row(connection, "physical_devices", os_name="Windows Server", os_version="2019")
        debian_a = insert_row(connection, "physical_devices", os_name="Debian", os_version=None)
        windows_b = insert_row(connection, "physical_devices", os_name="Windows Server", os_version="2019")
        debian_b = insert_row(connection, "physical_devices", os_name="Debian", os_version=None)
        vm = insert_row(connection, "virtual_machines", os_name="Ubuntu", os_version="22.04", virtualization_platform_id=platform)
    migrate(url, REVISION)
    with engine.connect() as connection:
        devices = {r.id: r.operating_system_id for r in connection.execute(sa.text("SELECT id, operating_system_id FROM physical_devices"))}
        vm_row = connection.execute(
            sa.text("SELECT operating_system_id, hypervisor_os_id FROM virtual_machines WHERE id = :i"), {"i": vm}
        ).one()
        debian_entries = connection.execute(sa.text("SELECT COUNT(*) FROM operating_systems WHERE name = 'Debian'")).scalar_one()
    assert all(devices.values())
    assert devices[windows_a] == devices[windows_b] and devices[debian_a] == devices[debian_b] and devices[windows_a] != devices[debian_a]
    assert debian_entries == 1  # пустая версия сопоставлена с пустой, а не заведена заново
    assert vm_row.operating_system_id is not None and vm_row.hypervisor_os_id is not None


def test_same_name_with_different_versions_stays_separate(database):
    url, engine = database
    with engine.begin() as connection:
        first = insert_row(connection, "physical_devices", os_name="Windows Server", os_version="2019")
        second = insert_row(connection, "physical_devices", os_name="Windows Server", os_version="2022")
        unversioned = insert_row(connection, "physical_devices", os_name="Windows Server", os_version=None)
    migrate(url, REVISION)
    with engine.connect() as connection:
        devices = {r.id: r.operating_system_id for r in connection.execute(sa.text("SELECT id, operating_system_id FROM physical_devices"))}
    assert len({devices[first], devices[second], devices[unversioned]}) == 3


def test_row_with_neither_name_nor_version_gets_no_catalog_entry(database):
    url, engine = database
    with engine.begin() as connection:
        empty = insert_row(connection, "physical_devices", os_name=None, os_version=None)
    migrate(url, REVISION)
    with engine.connect() as connection:
        assert (
            connection.execute(sa.text("SELECT operating_system_id FROM physical_devices WHERE id = :i"), {"i": empty}).scalar_one() is None
        )
