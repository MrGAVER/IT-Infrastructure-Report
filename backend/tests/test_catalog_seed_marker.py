"""Баг: стандартные значения справочников восстанавливались при каждом перезапуске приложения.

seed_defaults() на старте добавлял любую отсутствующую по имени стандартную запись — в том числе
удалённую или переименованную администратором. Теперь стартовое сидирование выполняется один раз
(маркер в catalog_seed_markers), а явное «восстановить стандартные значения» (POST /api/v1/seed,
seed_defaults(force=True)) по-прежнему возвращает всё.

Запуск: pytest backend/tests/test_catalog_seed_marker.py -v
"""
from __future__ import annotations

import ast
from pathlib import Path

from sqlalchemy import func, select

from app.models import (
    Building,
    CatalogSeedMarker,
    ConnectionType,
    InterfaceSpeed,
    Manufacturer,
    ProtocolPortCatalog,
)
from app.services.catalogs import DEFAULT_CATALOGS_SEED_MARKER, seed_defaults

API = "/api/v1"
MIGRATION = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "e4c8a1d7b350_catalog_seed_markers.py"


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_first_run_seeds_and_sets_marker(db_session):
    assert seed_defaults(db_session) is True
    assert db_session.get(CatalogSeedMarker, DEFAULT_CATALOGS_SEED_MARKER) is not None
    assert _count(db_session, Manufacturer) > 0 and _count(db_session, Building) == 1


def test_second_run_is_skipped(db_session):
    seed_defaults(db_session)
    assert seed_defaults(db_session) is False


def test_deleted_default_values_are_not_restored_on_next_start(db_session):
    seed_defaults(db_session)
    speed = db_session.scalar(select(InterfaceSpeed).where(InterfaceSpeed.name == "1 Gbps"))
    conn_type = db_session.scalar(select(ConnectionType).where(ConnectionType.name == "Витая пара"))
    cisco = db_session.scalar(select(Manufacturer).where(Manufacturer.name == "Cisco"))
    for obj in (speed, conn_type, cisco):
        db_session.delete(obj)
    db_session.commit()

    seed_defaults(db_session)  # «перезапуск приложения»

    names = lambda model: {x.name for x in db_session.scalars(select(model)).all()}  # noqa: E731
    assert "1 Gbps" not in names(InterfaceSpeed)
    assert "Витая пара" not in names(ConnectionType)
    assert "Cisco" not in names(Manufacturer)


def test_renamed_default_value_is_not_duplicated_on_next_start(db_session):
    seed_defaults(db_session)
    cisco = db_session.scalar(select(Manufacturer).where(Manufacturer.name == "Cisco"))
    cisco.name = "Cisco Systems"
    db_session.commit()

    seed_defaults(db_session)

    names = {x.name for x in db_session.scalars(select(Manufacturer)).all()}
    assert "Cisco Systems" in names and "Cisco" not in names


def test_emptied_singleton_catalog_stays_empty(db_session):
    """«Главный офис» заводился при ПУСТОМ справочнике — после удаления единственного здания он
    возвращался при каждом старте."""
    seed_defaults(db_session)
    for building in db_session.scalars(select(Building)).all():
        db_session.delete(building)
    db_session.commit()

    seed_defaults(db_session)

    assert _count(db_session, Building) == 0


def test_force_restores_deleted_defaults(db_session):
    seed_defaults(db_session)
    db_session.delete(db_session.scalar(select(Manufacturer).where(Manufacturer.name == "Cisco")))
    db_session.commit()

    assert seed_defaults(db_session, force=True) is True

    assert db_session.scalar(select(Manufacturer).where(Manufacturer.name == "Cisco")) is not None
    assert _count(db_session, CatalogSeedMarker) == 1  # маркер не дублируется


def test_user_records_survive_forced_reseed(db_session):
    seed_defaults(db_session)
    db_session.add(Manufacturer(name="Собственный вендор"))
    db_session.commit()

    seed_defaults(db_session, force=True)

    assert db_session.scalar(select(Manufacturer).where(Manufacturer.name == "Собственный вендор")) is not None


def test_seed_endpoint_restores_defaults_deleted_earlier(client):
    """POST /api/v1/seed — явное действие пользователя, маркер на него не распространяется."""
    items = client.get(f"{API}/resources/protocol-port-catalog", params={"limit": 1000}).json()["items"]
    ssh = next(x for x in items if x["port"] == 22 and x["protocol_type"] == "SSH")
    assert client.delete(f"{API}/resources/protocol-port-catalog/{ssh['id']}").status_code in (200, 204)

    assert client.post(f"{API}/seed").status_code == 200

    items = client.get(f"{API}/resources/protocol-port-catalog", params={"limit": 1000}).json()["items"]
    assert any(x["port"] == 22 and x["protocol_type"] == "SSH" for x in items)


def test_application_restart_does_not_restore_deleted_default(client, db_session):
    """Сквозной сценарий из баг-репорта: удалили стандартную запись → перезапуск приложения
    (lifespan вызывает seed_catalogs_on_startup) → запись не вернулась."""
    from app import main as app_main

    items = client.get(f"{API}/resources/protocol-port-catalog", params={"limit": 1000}).json()["items"]
    ssh = next(x for x in items if x["port"] == 22 and x["protocol_type"] == "SSH")
    assert client.delete(f"{API}/resources/protocol-port-catalog/{ssh['id']}").status_code in (200, 204)

    app_main.seed_catalogs_on_startup()

    db_session.expire_all()
    assert db_session.scalar(select(ProtocolPortCatalog).where(ProtocolPortCatalog.port == 22, ProtocolPortCatalog.protocol_type == "SSH")) is None


def test_marker_name_matches_migration_constant():
    """Миграция не импортирует код приложения — имя маркера продублировано, тест не даёт им разойтись."""
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    values = {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)
    }
    assert values["DEFAULT_CATALOGS_SEED_MARKER"] == DEFAULT_CATALOGS_SEED_MARKER
