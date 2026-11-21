"""
Тесты на backend/app/services/report_seed_templates.py — конфигурацию шаблона конструктора
отчётов, построенную на "виртуальных" сущностях report_registry_rows.py (точное воспроизведение
регламентированного 4-листового отчёта — см. подробности в report_seed_templates.py), и на
data-миграцию alembic/versions/b1f0a2265711_seed_report_builder_template.py, которая добавляет
этот шаблон в report_templates при обновлении.

Этот файл — структурная валидация конфигурации и поведение самой миграции (идемпотентность,
безопасный откат). Точная эквивалентность содержимого с оригинальным отчётом на реальных данных —
отдельный, более сильный тест: test_report_registry_rows.py::ExactParityTestCase.

Запуск: python3 -m unittest discover -s backend/tests -v
Требует sqlalchemy/openpyxl/alembic (как test_report_grid.py) — при их отсутствии тесты пропускаются.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
ALEMBIC_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"

try:
    sys.path.insert(0, str(APP_DIR.parent))
    from sqlalchemy import create_engine

    from app.models import Base
    from app.services.report_engine import ReportBuilderError
    from app.services.report_meta import build_entity_metadata
    from app.services.report_seed_templates import (
        TEMPLATE_DESCRIPTION,
        TEMPLATE_NAME,
        default_registry_template_config,
    )

    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False


def _load_migration_module():
    """Импортирует файл миграции по пути — у него нет package-имени (стандартный alembic-модуль
    версии), поэтому используем importlib вместо обычного import."""
    path = ALEMBIC_VERSIONS_DIR / "b1f0a2265711_seed_report_builder_template.py"
    spec = importlib.util.spec_from_file_location("seed_migration_b1f0a2265711", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/openpyxl не установлены в этом окружении")
class DefaultRegistryTemplateConfigTestCase(unittest.TestCase):
    """Структурная валидация — без обращения к БД (та же проверка, что при сохранении шаблона
    через API конструктора)."""

    def test_passes_validate_grid_config(self):
        from app.services.report_grid import validate_grid_config

        cfg = default_registry_template_config()
        try:
            validate_grid_config(build_entity_metadata(), cfg)
        except ReportBuilderError as e:
            self.fail(f"Конфигурация шаблона-заготовки не проходит validate_grid_config(): {e}")

    def test_four_sheets_in_original_order(self):
        cfg = default_registry_template_config()
        titles = [s["title"] for s in cfg["sheets"]]
        self.assertEqual(
            titles,
            [
                "Перечень ИС",
                "Инвентаризац. физ. устройств ИС",
                "Организация подключений",
                "Организация управления ВМ",
            ],
        )

    def test_is_pure_function_no_shared_mutable_state(self):
        """Два вызова не должны возвращать общие вложенные списки/словари — иначе правка одного
        сгенерированного шаблона в памяти (например, в тесте на миграцию) исказила бы другой."""
        cfg1 = default_registry_template_config()
        cfg2 = default_registry_template_config()
        cfg1["sheets"][0]["rows"][0]["cells"][0]["text"] = "испорчено"
        self.assertNotEqual(cfg1["sheets"][0]["rows"][0]["cells"][0]["text"], cfg2["sheets"][0]["rows"][0]["cells"][0]["text"])

    def test_every_header_fits_in_its_column(self):
        """Заголовки регламентированной формы — жирные, до 300 символов; в колонках по 20-30 символов они
        занимали 15-25 строк и обрезались. Ширина колонок шаблона подогнана под заголовки: ни одно слово
        не рвётся посередине, а шапка не выше MAX_HEADER_LINES строк."""
        from app.services.excel_layout import MAX_COLUMN_WIDTH, MAX_HEADER_LINES, text_capacity, wrap_lines

        for sheet in default_registry_template_config()["sheets"]:
            header_cells = sheet["rows"][0]["cells"]
            for cell, column in zip(header_cells, sheet["columns"]):
                width, text = column["width"], cell["text"]
                capacity = text_capacity(width, bold=True)
                self.assertGreaterEqual(capacity, max(len(word) for word in text.split()), f"{sheet['title']}: {text[:30]}")
                if width < MAX_COLUMN_WIDTH:
                    self.assertLessEqual(wrap_lines(text, capacity), MAX_HEADER_LINES, f"{sheet['title']}: {text[:30]}")

    def test_widths_never_shrink_below_the_data_minimum(self):
        """Заданная вручную ширина — минимум под данные: подгонка под заголовки только расширяет колонки."""
        from app.services.excel_layout import MAX_COLUMN_WIDTH

        manual = {"Перечень ИС": [5, 26, 32, 26, 24, 18, 42, 30, 30, 16, 12, 24, 20, 30, 30, 24, 26, 26], "Организация управления ВМ": [22, 20, 20, 24, 20, 28, 22, 32, 20, 32]}
        for sheet in default_registry_template_config()["sheets"]:
            if sheet["title"] in manual:
                for column, minimum in zip(sheet["columns"], manual[sheet["title"]]):
                    self.assertGreaterEqual(column["width"], minimum)
                    self.assertLessEqual(column["width"], max(minimum, MAX_COLUMN_WIDTH))

    def test_description_mentions_original_report_is_unaffected(self):
        # Ключевое требование: пользователь не должен подумать, что этот шаблон заменяет собой
        # регламентированный отчёт (кнопка "Отчёт Excel" на дашборде) — см. описание задачи.
        self.assertIn("Отчёт Excel", TEMPLATE_DESCRIPTION)
        self.assertTrue(TEMPLATE_NAME)


@unittest.skipUnless(DEPS_AVAILABLE, "sqlalchemy/openpyxl не установлены в этом окружении")
class SeedMigrationTestCase(unittest.TestCase):
    """Data-миграция b1f0a2265711: идемпотентная вставка + осторожный откат (не удаляет строку,
    если пользователь успел отредактировать шаблон после апгрейда)."""

    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.migration = _load_migration_module()

    def _table_rows(self, conn):
        return conn.execute(self.migration._report_templates.select()).mappings().all()

    def test_upgrade_inserts_exactly_one_row_and_is_idempotent(self):
        with self.engine.begin() as conn:
            self.migration.op = _FakeOp(conn)
            self.migration.upgrade()
            rows = self._table_rows(conn)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["name"], TEMPLATE_NAME)
            self.assertEqual(json.loads(rows[0]["config"]), default_registry_template_config())

            self.migration.upgrade()  # повторный прогон не должен дублировать строку
            rows_again = self._table_rows(conn)
            self.assertEqual(len(rows_again), 1)

    def test_downgrade_removes_unedited_row(self):
        with self.engine.begin() as conn:
            self.migration.op = _FakeOp(conn)
            self.migration.upgrade()
            self.migration.downgrade()
            self.assertEqual(len(self._table_rows(conn)), 0)

    def test_downgrade_preserves_row_edited_by_user(self):
        with self.engine.begin() as conn:
            self.migration.op = _FakeOp(conn)
            self.migration.upgrade()
            conn.execute(self.migration._report_templates.update().values(config=json.dumps({"sheets": [], "params": []})))
            self.migration.downgrade()
            rows = self._table_rows(conn)
            self.assertEqual(len(rows), 1, "отредактированный пользователем шаблон не должен удаляться откатом")


class _FakeOp:
    """Минимальная замена alembic.op для юнит-теста миграции на голом sqlalchemy-соединении —
    настоящий alembic.op требует активный MigrationContext, который в проекте поднимается только
    через сам `alembic upgrade`/`downgrade` (уже проверено вручную при разработке, см. историю
    ветки); здесь достаточно только двух методов, которые использует эта конкретная миграция."""

    def __init__(self, conn):
        self._conn = conn

    def get_bind(self):
        return self._conn

    def bulk_insert(self, table, rows):
        self._conn.execute(table.insert(), rows)

    def execute(self, stmt):
        self._conn.execute(stmt)


if __name__ == "__main__":
    unittest.main()
