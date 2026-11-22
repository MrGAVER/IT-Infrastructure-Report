"""Миграция b3f7a2c91d54: удаление поля status у физических устройств, информационных систем и виртуальных машин.

Главный риск удаления — сохранённые шаблоны конструктора отчётов: резолвер пути берёт `getattr(obj, name, None)`, поэтому
после удаления колонки фильтр `status = active` молча отсёк бы ВСЕ строки. Миграция переписывает шаблоны (и историю версий)
до удаления колонок. Здесь проверяются: чистая функция переписывания, данные до и после на настоящей базе, откат и повторный запуск.

Гоняется на одноразовой SQLite БД (PostgreSQL — в test_migrations_postgres.py).
Запуск: pytest backend/tests/test_migrations_drop_entity_status.py -v
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory
from alembic.config import Config

sys.path.insert(0, str(Path(__file__).resolve().parent))
from migration_support import insert_row  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
PRE_REVISION = "e9b4c2a7d136"
REVISION = "b3f7a2c91d54"

_spec = importlib.util.spec_from_file_location("drop_entity_status_migration", BACKEND_DIR / "alembic" / "versions" / "b3f7a2c91d54_drop_entity_status_field.py")
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)
strip = migration.strip_status_paths

GRID = {
    "sheets": [
        {
            "title": "ИС",
            "columns": [{"width": 22}, {"width": 30}],
            "rows": [
                {"height": 22, "repeat": False, "cells": [{"col": 0, "kind": "static", "text": "Отчёт"}]},
                {
                    "height": 18,
                    "repeat": True,
                    "data_source": {"root_entity": "information-systems", "expand": None, "filters": [{"path": "status", "op": "eq", "value": "active"}, {"path": "siem_enabled", "op": "is_true"}], "sort_by": "name"},
                    "cells": [{"col": 0, "kind": "index"}, {"col": 1, "kind": "field", "path": "name", "separator": "; "}, {"col": 2, "kind": "field", "path": "status", "separator": "; ", "style": {"bold": True}, "colspan": 2}],
                },
            ],
        }
    ]
}

DOCX = {
    "blocks": [
        {"type": "heading", "text": "Устройства"},
        {
            "type": "table",
            "root_entity": "devices",
            "filters": [{"path": "status", "op": "ne", "value": "retired"}],
            "sort_by": "status",
            "columns": [{"header": "Имя", "source": "field", "path": "system_name"}, {"header": "Состояние", "source": "field", "path": "status"}],
        },
        {"type": "table", "root_entity": "devices", "columns": [{"header": "Состояние", "source": "field", "path": "status"}]},
    ]
}


class TestStripStatusPaths:
    def test_config_without_status_is_returned_equal_and_unchanged(self):
        config = {"sheets": [{"rows": [{"cells": [{"col": 0, "kind": "field", "path": "name"}]}]}], "x": ["status-like", {"path": "status_text"}]}
        result, changed = strip(config)
        assert (result, changed) == (config, False)

    def test_input_is_never_mutated(self):
        original = copy.deepcopy(GRID)
        strip(GRID)
        assert GRID == original

    def test_status_filter_is_removed_and_other_filters_stay(self):
        result, changed = strip(GRID)
        source = result["sheets"][0]["rows"][1]["data_source"]
        assert changed and source["filters"] == [{"path": "siem_enabled", "op": "is_true"}]
        assert source["sort_by"] == "name"

    def test_status_field_cell_becomes_an_empty_static_cell_keeping_geometry_and_style(self):
        cells = strip(GRID)[0]["sheets"][0]["rows"][1]["cells"]
        assert cells[2] == {"col": 2, "kind": "static", "text": "", "style": {"bold": True}, "colspan": 2}
        assert cells[1] == {"col": 1, "kind": "field", "path": "name", "separator": "; "}  # остальные ячейки не тронуты

    def test_sort_by_status_is_reset_to_null(self):
        table = strip(DOCX)[0]["blocks"][1]
        assert table["sort_by"] is None and table["filters"] == []

    def test_table_column_with_status_is_dropped_when_others_remain(self):
        assert strip(DOCX)[0]["blocks"][1]["columns"] == [{"header": "Имя", "source": "field", "path": "system_name"}]

    def test_the_only_column_is_replaced_by_an_empty_static_one_not_dropped(self):
        assert strip(DOCX)[0]["blocks"][2]["columns"] == [{"header": "Состояние", "source": "static", "value": ""}]

    @pytest.mark.parametrize("path", ["status", "physical_device.status", "vms[].status", " status ", "information_system.vms[].status"])
    def test_status_through_relations_counts_as_the_removed_field(self, path):
        config = {"filters": [{"path": path, "op": "eq", "value": "x"}]}
        assert strip(config) == ({"filters": []}, True)

    @pytest.mark.parametrize("path", ["status_text", "statuses", "name", "port_config.status_note", "mystatus", ""])
    def test_similar_looking_paths_are_not_touched(self, path):
        config = {"filters": [{"path": path, "op": "eq", "value": "x"}]}
        assert strip(config) == (config, False)

    def test_second_pass_changes_nothing(self):
        once, _ = strip(GRID)
        assert strip(once) == (once, False)


@pytest.fixture()
def database(tmp_path, monkeypatch):
    """Одноразовая SQLite: env.py читает app.config.DATABASE_URL при каждом запуске команды (см. test_migrations_diagram.py)."""
    import app.config as app_config

    path = tmp_path / "status_migration.db"
    monkeypatch.setattr(app_config, "DATABASE_URL", f"sqlite:///{path}")
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    engine = sa.create_engine(f"sqlite:///{path}")
    yield cfg, engine
    engine.dispose()


def _columns(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def _seed_old_schema(engine):
    with engine.begin() as connection:
        device = insert_row(connection, "physical_devices", serial_number="SN-1", system_name="SW-1", status="retired")
        system = insert_row(connection, "information_systems", name="ИС-1", status="planned")
        vm = insert_row(connection, "virtual_machines", name="vm-1", status="stopped")
        grid = insert_row(connection, "report_templates", name="Сетка со статусом", format="xlsx", config=json.dumps(GRID, ensure_ascii=False))
        docx = insert_row(connection, "report_templates", name="Документ со статусом", format="docx", config=json.dumps(DOCX, ensure_ascii=False))
        clean_config = json.dumps({"sheets": [{"rows": []}]}, ensure_ascii=False, indent=2)
        clean = insert_row(connection, "report_templates", name="Без статуса", format="xlsx", config=clean_config)
        broken = insert_row(connection, "report_templates", name="Не JSON", format="xlsx", config="{это не json")
        version = insert_row(connection, "report_template_versions", report_template_id=grid, version_number=1, name="Сетка со статусом", format="xlsx", config=json.dumps(GRID, ensure_ascii=False))
    return {"device": device, "system": system, "vm": vm, "grid": grid, "docx": docx, "clean": clean, "clean_config": clean_config, "broken": broken, "version": version}


def _config(engine, table, row_id):
    with engine.connect() as connection:
        return connection.execute(sa.text(f"SELECT config FROM {table} WHERE id = :i"), {"i": row_id}).scalar_one()


class TestMigrationOnADatabase:
    def test_old_schema_has_the_status_columns_the_migration_removes(self, database):
        cfg, engine = database
        command.upgrade(cfg, PRE_REVISION)
        assert all("status" in _columns(engine, table) for table in ("physical_devices", "information_systems", "virtual_machines"))

    def test_columns_are_dropped_and_the_rest_of_every_row_survives(self, database):
        cfg, engine = database
        command.upgrade(cfg, PRE_REVISION)
        ids = _seed_old_schema(engine)
        command.upgrade(cfg, REVISION)

        assert not any("status" in _columns(engine, table) for table in ("physical_devices", "information_systems", "virtual_machines"))
        with engine.connect() as connection:
            assert connection.execute(sa.text("SELECT serial_number, system_name FROM physical_devices WHERE id = :i"), {"i": ids["device"]}).one() == ("SN-1", "SW-1")
            assert connection.execute(sa.text("SELECT name FROM information_systems WHERE id = :i"), {"i": ids["system"]}).scalar_one() == "ИС-1"
            assert connection.execute(sa.text("SELECT name FROM virtual_machines WHERE id = :i"), {"i": ids["vm"]}).scalar_one() == "vm-1"
            assert connection.execute(sa.text("PRAGMA foreign_key_check")).all() == []  # таблицы не пересобирались — ссылки целы

    def test_saved_templates_lose_every_reference_to_the_removed_field(self, database):
        cfg, engine = database
        command.upgrade(cfg, PRE_REVISION)
        ids = _seed_old_schema(engine)
        command.upgrade(cfg, REVISION)

        grid = json.loads(_config(engine, "report_templates", ids["grid"]))
        assert grid == strip(GRID)[0] and "status" not in json.dumps(grid)
        docx = json.loads(_config(engine, "report_templates", ids["docx"]))
        assert docx == strip(DOCX)[0] and "status" not in json.dumps(docx)

    def test_version_history_is_rewritten_too(self, database):
        cfg, engine = database
        command.upgrade(cfg, PRE_REVISION)
        ids = _seed_old_schema(engine)
        command.upgrade(cfg, REVISION)
        assert json.loads(_config(engine, "report_template_versions", ids["version"])) == strip(GRID)[0]

    def test_templates_without_status_and_non_json_configs_are_left_byte_for_byte(self, database):
        cfg, engine = database
        command.upgrade(cfg, PRE_REVISION)
        ids = _seed_old_schema(engine)
        command.upgrade(cfg, REVISION)
        assert _config(engine, "report_templates", ids["clean"]) == ids["clean_config"]
        assert _config(engine, "report_templates", ids["broken"]) == "{это не json"

    def test_rewritten_templates_still_pass_the_builders_own_validation(self, database):
        """Результат должен быть сохраняемым: тот же validate_config, что при сохранении шаблона в конструкторе."""
        from app.services.report_engine import validate_config
        from app.services.report_meta import build_entity_metadata

        meta = build_entity_metadata()
        assert "status" not in {f["name"] for f in meta["devices"]["fields"]}  # поле больше не предлагается конструктором
        validate_config(meta, "docx", strip(DOCX)[0])

    def test_rewriting_templates_a_second_time_changes_nothing(self, database):
        cfg, engine = database
        command.upgrade(cfg, PRE_REVISION)
        ids = _seed_old_schema(engine)
        command.upgrade(cfg, REVISION)
        before = {key: _config(engine, "report_templates", ids[key]) for key in ("grid", "docx", "clean", "broken")}
        with engine.begin() as connection:
            migration._rewrite_templates(connection)
        assert {key: _config(engine, "report_templates", ids[key]) for key in before} == before

    def test_alembic_does_not_apply_the_revision_twice(self, database):
        cfg, engine = database
        command.upgrade(cfg, REVISION)
        command.upgrade(cfg, "head")
        command.upgrade(cfg, "head")  # повторный накат на голову — холостой ход, ревизия не применяется заново
        head = ScriptDirectory.from_config(cfg).get_current_head()  # последующие ревизии цепочки не ломают тест
        with engine.connect() as connection:
            assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == head

    def test_downgrade_brings_the_columns_back_empty_with_the_old_defaults(self, database):
        cfg, engine = database
        command.upgrade(cfg, PRE_REVISION)
        ids = _seed_old_schema(engine)
        command.upgrade(cfg, REVISION)
        command.downgrade(cfg, PRE_REVISION)
        assert all("status" in _columns(engine, table) for table in ("physical_devices", "information_systems", "virtual_machines"))
        with engine.connect() as connection:
            assert connection.execute(sa.text("SELECT status FROM physical_devices WHERE id = :i"), {"i": ids["device"]}).scalar_one() is None
            assert connection.execute(sa.text("SELECT status FROM information_systems WHERE id = :i"), {"i": ids["system"]}).scalar_one() == "active"
            assert connection.execute(sa.text("SELECT status FROM virtual_machines WHERE id = :i"), {"i": ids["vm"]}).scalar_one() == "active"

    def test_too_old_sqlite_stops_with_a_clear_message(self, database, monkeypatch):
        cfg, engine = database
        command.upgrade(cfg, PRE_REVISION)
        monkeypatch.setattr(migration.sqlite3, "sqlite_version_info", (3, 34, 0))
        monkeypatch.setattr(migration.sqlite3, "sqlite_version", "3.34.0")
        with pytest.raises(RuntimeError, match="SQLite 3.35"):
            command.upgrade(cfg, REVISION)


# ----- сквозная проверка: отчёт по шаблону, который до миграции ссылался на status -----------------------------------------------
# Раньше проверялись только преобразование JSON и validate_config. Здесь шаблон проходит настоящую миграцию, а затем по нему строятся
# настоящие файлы xlsx и docx из ORM-сессии на мигрированной базе.

E2E_GRID = {
    "sheets": [
        {
            "title": "ИС",
            "columns": [{"width": 6}, {"width": 30}, {"width": 18}],
            "rows": [
                {"height": 20, "repeat": False, "cells": [{"col": 0, "kind": "static", "text": "№", "colspan": 1}, {"col": 1, "kind": "static", "text": "Наименование"}, {"col": 2, "kind": "static", "text": "Состояние"}]},
                {
                    "height": 18,
                    "repeat": True,
                    "data_source": {"root_entity": "information-systems", "expand": None, "filters": [{"path": "status", "op": "eq", "value": "active"}, {"path": "siem_enabled", "op": "is_true"}], "sort_by": "status"},
                    "cells": [{"col": 0, "kind": "index"}, {"col": 1, "kind": "field", "path": "name"}, {"col": 2, "kind": "field", "path": "status"}],
                },
            ],
        }
    ]
}

E2E_DOCX = {
    "blocks": [
        {"type": "heading", "text": "Устройства", "level": 1},
        {
            "type": "table",
            "root_entity": "devices",
            "filters": [{"path": "status", "op": "ne", "value": "retired"}],
            "sort_by": "status",
            "columns": [{"header": "Имя", "source": "field", "path": "system_name"}, {"header": "Состояние", "source": "field", "path": "status"}],
        },
    ]
}


def _xlsx_names(path) -> list[str]:
    from openpyxl import load_workbook

    sheet = load_workbook(path).active
    return [row[1] for row in sheet.iter_rows(min_row=2, values_only=True) if row[1]]


def _docx_cells(path) -> list[list[str]]:
    from docx import Document

    return [[cell.text for cell in row.cells] for row in Document(str(path)).tables[0].rows]


@pytest.fixture()
def migrated_reports(database, tmp_path):
    """Старая схема с ИС и устройствами в разных состояниях и двумя шаблонами со status → миграция → (ORM-сессия, id шаблонов, каталог отчётов)."""
    from sqlalchemy.orm import sessionmaker

    cfg, engine = database
    command.upgrade(cfg, PRE_REVISION)
    with engine.begin() as connection:
        for name, status, siem in (("ИС-A", "active", True), ("ИС-B", "planned", True), ("ИС-C", "retired", True), ("ИС-D", "active", False)):
            insert_row(connection, "information_systems", name=name, status=status, siem_enabled=siem)
        for serial, status in (("SN-1", "retired"), ("SN-2", "active")):
            insert_row(connection, "physical_devices", serial_number=serial, system_name=f"SW-{serial[-1]}", status=status)
        grid = insert_row(connection, "report_templates", name="Сетка со статусом", format="xlsx", config=json.dumps(E2E_GRID, ensure_ascii=False))
        docx = insert_row(connection, "report_templates", name="Документ со статусом", format="docx", config=json.dumps(E2E_DOCX, ensure_ascii=False))
    command.upgrade(cfg, REVISION)
    with sessionmaker(bind=engine)() as session:
        yield session, {"grid": grid, "docx": docx}, tmp_path / "reports"


class TestReportsBuiltAfterMigration:
    def test_xlsx_from_a_migrated_template_shows_every_record_the_remaining_filters_allow(self, migrated_reports, database):
        from app.services.report_grid import build_xlsx_grid, validate_grid_config
        from app.services.report_meta import build_entity_metadata

        session, ids, report_dir = migrated_reports
        config = json.loads(_config(database[1], "report_templates", ids["grid"]))
        validate_grid_config(build_entity_metadata(), config)  # результат миграции сохраняем тем же правилам, что и в конструкторе
        path = build_xlsx_grid(session, config, report_dir, template_name="Сетка")
        # фильтр «status = active» исчез, фильтр «SIEM» остался: A, B, C — в отчёте, D (без SIEM) — нет
        assert sorted(_xlsx_names(path)) == ["ИС-A", "ИС-B", "ИС-C"]

    def test_the_same_template_without_the_rewrite_would_silently_produce_an_empty_report(self, migrated_reports):
        """Обоснование миграции: резолвер пути берёт getattr(obj, name, None), поэтому фильтр по удалённой колонке отсекает ВСЕ строки."""
        from app.services.report_grid import build_xlsx_grid

        session, _, report_dir = migrated_reports
        assert _xlsx_names(build_xlsx_grid(session, E2E_GRID, report_dir, template_name="Без переписывания")) == []

    def test_docx_from_a_migrated_template_has_every_device_and_no_status_column(self, migrated_reports, database):
        from app.services.report_render import build_docx

        session, ids, report_dir = migrated_reports
        config = json.loads(_config(database[1], "report_templates", ids["docx"]))
        rows = _docx_cells(build_docx(session, config, report_dir, template_name="Документ"))
        assert rows[0] == ["Имя"] and sorted(r[0] for r in rows[1:]) == ["SW-1", "SW-2"]  # «ne retired» исчез — вернулось и списанное устройство

    def test_the_same_docx_template_without_the_rewrite_keeps_a_blank_column_and_a_filter_that_filters_nothing(self, migrated_reports):
        """Для Word последствия мягче, чем для «eq»-фильтра в Excel: «ne retired» по пустому значению пропускает всё, колонка «Состояние» — пустая."""
        from app.services.report_render import build_docx

        session, _, report_dir = migrated_reports
        rows = _docx_cells(build_docx(session, E2E_DOCX, report_dir, template_name="Без переписывания"))
        assert rows[0] == ["Имя", "Состояние"] and sorted(rows[1:]) == [["SW-1", ""], ["SW-2", ""]]
