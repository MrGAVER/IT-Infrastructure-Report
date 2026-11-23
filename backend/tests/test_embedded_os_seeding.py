"""
Тесты на баг сидинга EmbeddedOperatingSystem (services/catalogs.py:_seed_operating_systems):
SONiC в EMBEDDED_OS_DEFAULTS задан с version='' (пустая строка), но хранится как version=None
(version or None при создании) — сравнение "уже существует?" на следующем запуске сверяло
сырое '' с уже сохранённым None и не находило совпадения, поэтому SONiC заводился заново при
каждом старте приложения. У остальных записей справочника версия непустая, поэтому баг был
виден только на этой одной.

Запуск: pip install -r backend/requirements-dev.txt && pytest backend/tests/test_embedded_os_seeding.py -v
"""

from __future__ import annotations

from sqlalchemy import select

from app.models import EmbeddedOperatingSystem
from app.services.catalogs import seed_defaults


def test_seed_defaults_does_not_duplicate_sonic_on_repeated_runs(db_session):
    """Регрессия: без фикса третий запуск (как и любой последующий) добавлял ещё одну запись
    SONiC поверх уже накопленных — количество росло без ограничений."""
    for _ in range(3):
        seed_defaults(db_session)
        db_session.commit()

    sonic_rows = db_session.scalars(select(EmbeddedOperatingSystem).where(EmbeddedOperatingSystem.name == "SONiC")).all()
    assert len(sonic_rows) == 1
    assert sonic_rows[0].version is None


def test_seed_defaults_is_idempotent_for_every_embedded_os_entry(db_session):
    """Не только SONiC — общая проверка, что повторный сид не плодит дублей ни для одной записи
    справочника (версия непуста у большинства, но проверяем без исключений)."""
    for _ in range(3):
        seed_defaults(db_session)
        db_session.commit()

    rows = db_session.scalars(select(EmbeddedOperatingSystem)).all()
    keys = [(r.name, r.version) for r in rows]
    assert len(keys) == len(set(keys)), f"найдены дубли: {keys}"


def test_seed_defaults_sonic_has_no_version_stored(db_session):
    """version='' в EMBEDDED_OS_DEFAULTS должен нормализоваться в None при сохранении — тот же
    принцип, что и у остальных полей с необязательной версией в проекте (пустая строка как
    'версия не указана' в БД не хранится)."""
    seed_defaults(db_session)
    db_session.commit()
    sonic = db_session.scalar(select(EmbeddedOperatingSystem).where(EmbeddedOperatingSystem.name == "SONiC"))
    assert sonic is not None
    assert sonic.version is None
