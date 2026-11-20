"""Тесты на миграцию e4b1c7d9a362 — описание шаблона «Регламентированный отчёт — заготовка» без пути к файлу исходников.

Код-ревью 2.158.0, UI-13: миграция b1f0a2265711 записала в description внутренний путь «backend/app/services/report_registry_rows.py»,
а экран «Шаблоны отчётов» показывает описание как есть. Миграция заменяет описание в report_templates и report_template_versions
только там, где оно дословно равно прежнему тексту; описание, отредактированное пользователем, не трогается; downgrade() возвращает
прежний текст. Работает на настоящей цепочке миграций (файл SQLite), а не на подмене alembic.op.

Запуск: pytest backend/tests/test_migrations_report_template_description.py -v
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

BACKEND_DIR = Path(__file__).resolve().parent.parent
PRE_REVISION = "d5a8c3e7b196"
REVISION = "e4b1c7d9a362"
TEMPLATE_NAME = "Регламентированный отчёт — заготовка (4 листа)"
LEAKED_PATH = "backend/app/services/report_registry_rows.py"

# Текст, который до этой миграции записывала b1f0a2265711 (со ссылкой на файл исходников). Записан здесь отдельной копией, а не
# импортируется из миграции: тест проверяет, что литерал миграции совпадает с историческим текстом дословно, иначе она не нашла бы
# его в уже созданных базах.
OLD_DESCRIPTION = (
    "Точное воспроизведение регламентированного отчёта (4 листа — см. кнопку «Отчёт Excel» на "
    "дашборде) в визуальном редакторе: то же содержимое строк и колонок, но открытое для правки — "
    "перетаскивайте поля, добавляйте фильтры/колонки/листы, меняйте оформление. Кнопка «Отчёт "
    "Excel» остаётся основным источником для сдачи/проверки; оба используют одну и ту же логику "
    "расчёта (backend/app/services/report_registry_rows.py), поэтому расхождений между ними быть "
    "не должно, пока вы не отредактируете этот шаблон в конструкторе — тогда он, конечно, "
    "перестанет быть точной копией: в этом и есть его предназначение — отправная точка для "
    "собственных отчётов на основе тех же данных реестра."
)

pytestmark = pytest.mark.sqlite_only


@pytest.fixture()
def alembic_config(tmp_path, monkeypatch):
    """См. идентичную fixture в test_migrations_interface_sort_order.py."""
    import app.config as app_config

    db_path = tmp_path / "migration_test.db"
    monkeypatch.setattr(app_config, "DATABASE_URL", f"sqlite:///{db_path}")
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    return cfg, db_path


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _description(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT description FROM report_templates WHERE name=?", (TEMPLATE_NAME,)).fetchone()
    assert row is not None, "предусловие: b1f0a2265711 добавила шаблон"
    return row["description"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_old_description(conn: sqlite3.Connection) -> None:
    """Состояние уже развёрнутой базы: описание с путём, как его записывала b1f0a2265711 до исправления константы."""
    conn.execute("UPDATE report_templates SET description=? WHERE name=?", (OLD_DESCRIPTION, TEMPLATE_NAME))


def _add_version(conn: sqlite3.Connection, description: str | None) -> str:
    template_id = conn.execute("SELECT id FROM report_templates WHERE name=?", (TEMPLATE_NAME,)).fetchone()["id"]
    version_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO report_template_versions (id, report_template_id, version_number, name, description, format, config, created_at, updated_at) VALUES (?, ?, 1, ?, ?, 'xlsx', '{}', ?, ?)",
        (version_id, template_id, TEMPLATE_NAME, description, _now(), _now()),
    )
    return version_id


def test_fixture_text_is_the_historical_one_with_the_path():
    assert LEAKED_PATH in OLD_DESCRIPTION


def test_upgrade_replaces_description_with_path_in_existing_database(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    with _connect(db_path) as conn:
        _seed_old_description(conn)
        assert LEAKED_PATH in _description(conn)

    command.upgrade(cfg, REVISION)

    with _connect(db_path) as conn:
        description = _description(conn)
        assert LEAKED_PATH not in description and "report_registry_rows" not in description and ".py" not in description


def test_upgraded_description_equals_the_constant_for_new_installs(alembic_config):
    """Литерал миграции и TEMPLATE_DESCRIPTION из сервиса не расходятся: и обновлённая, и новая база показывают один текст."""
    from app.services.report_seed_templates import TEMPLATE_DESCRIPTION

    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    with _connect(db_path) as conn:
        _seed_old_description(conn)

    command.upgrade(cfg, REVISION)

    with _connect(db_path) as conn:
        assert _description(conn) == TEMPLATE_DESCRIPTION
    assert "backend/" not in TEMPLATE_DESCRIPTION and ".py" not in TEMPLATE_DESCRIPTION


def test_new_install_gets_description_without_path(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, "head")
    with _connect(db_path) as conn:
        description = _description(conn)
        assert LEAKED_PATH not in description and ".py" not in description


def test_upgrade_updates_saved_versions_too(alembic_config):
    """Снимки шаблона хранят свою копию описания: без их обновления восстановление версии вернуло бы путь в интерфейс."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    with _connect(db_path) as conn:
        _seed_old_description(conn)
        old_version = _add_version(conn, OLD_DESCRIPTION)
        custom_version = _add_version(conn, "Моё описание")
        empty_version = _add_version(conn, None)

    command.upgrade(cfg, REVISION)

    with _connect(db_path) as conn:
        by_id = {r["id"]: r["description"] for r in conn.execute("SELECT id, description FROM report_template_versions")}
        assert LEAKED_PATH not in by_id[old_version] and by_id[old_version] == _description(conn)
        assert by_id[custom_version] == "Моё описание"
        assert by_id[empty_version] is None


def test_upgrade_keeps_description_edited_by_user(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    custom = f"{OLD_DESCRIPTION} Дополнение пользователя."
    with _connect(db_path) as conn:
        conn.execute("UPDATE report_templates SET description=? WHERE name=?", (custom, TEMPLATE_NAME))

    command.upgrade(cfg, REVISION)

    with _connect(db_path) as conn:
        assert _description(conn) == custom


def test_upgrade_fixes_description_even_if_template_config_was_edited(alembic_config):
    """Описание не зависит от конфигурации: пользователь мог перестроить шаблон, а описание с путём осталось прежним."""
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    with _connect(db_path) as conn:
        _seed_old_description(conn)
        conn.execute('UPDATE report_templates SET config=\'{"params": [], "sheets": []}\' WHERE name=?', (TEMPLATE_NAME,))

    command.upgrade(cfg, REVISION)

    with _connect(db_path) as conn:
        assert LEAKED_PATH not in _description(conn)
        assert conn.execute("SELECT config FROM report_templates WHERE name=?", (TEMPLATE_NAME,)).fetchone()["config"] == '{"params": [], "sheets": []}'


def test_upgrade_is_noop_when_template_is_already_gone(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    with _connect(db_path) as conn:
        conn.execute("DELETE FROM report_templates WHERE name=?", (TEMPLATE_NAME,))

    command.upgrade(cfg, REVISION)  # не должна падать

    with _connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM report_templates WHERE name=?", (TEMPLATE_NAME,)).fetchone()[0] == 0


def test_downgrade_restores_old_text_and_reupgrade_is_idempotent(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, PRE_REVISION)
    with _connect(db_path) as conn:
        _seed_old_description(conn)
        _add_version(conn, OLD_DESCRIPTION)
    command.upgrade(cfg, REVISION)

    command.downgrade(cfg, PRE_REVISION)

    with _connect(db_path) as conn:
        assert _description(conn) == OLD_DESCRIPTION
        assert conn.execute("SELECT description FROM report_template_versions").fetchone()["description"] == OLD_DESCRIPTION

    command.upgrade(cfg, REVISION)
    command.upgrade(cfg, "head")  # повторный запуск безопасен

    with _connect(db_path) as conn:
        assert LEAKED_PATH not in _description(conn)
        assert conn.execute("SELECT COUNT(*) FROM report_templates WHERE name=?", (TEMPLATE_NAME,)).fetchone()[0] == 1


def test_downgrade_keeps_description_edited_by_user(alembic_config):
    cfg, db_path = alembic_config
    command.upgrade(cfg, REVISION)
    with _connect(db_path) as conn:
        conn.execute("UPDATE report_templates SET description='Своё описание' WHERE name=?", (TEMPLATE_NAME,))

    command.downgrade(cfg, PRE_REVISION)

    with _connect(db_path) as conn:
        assert _description(conn) == "Своё описание"
