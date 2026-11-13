"""
Код-ревью, BE-05 (остаток): в боевом коде нет ``assert``.

``assert`` исчезает при запуске интерпретатора с ``-O`` (``PYTHONOPTIMIZE``), поэтому проверка инварианта, на которую рассчитывает код,
в таком запуске молча пропадает. Пять оставшихся мест заменены явными проверками: четыре в ``vlan_mode_cascade`` (сужение типа
``None`` у группы) и одно в ``report_seed_templates`` (число ширин колонок листа). Общий тест ниже не даёт ``assert`` вернуться
в ``backend/app`` и ``backend/alembic``.

Запуск: pytest backend/tests/test_no_assert_in_production_code.py -v
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.services import report_seed_templates
from app.services.vlan_mode_cascade import _Edited, _Loader

BACKEND_DIR = Path(__file__).resolve().parents[1]
PRODUCTION_DIRS = [BACKEND_DIR / "app", BACKEND_DIR / "alembic"]


def _asserts_in(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Assert)]


def test_production_code_has_no_assert_statements():
    found = {
        str(path.relative_to(BACKEND_DIR)): lines
        for directory in PRODUCTION_DIRS
        for path in sorted(directory.rglob("*.py"))
        if (lines := _asserts_in(path))
    }
    assert found == {}, "assert в боевом коде исчезает при `python -O`; нужна явная проверка с понятной ошибкой"


def test_the_scan_really_sees_assert_statements(tmp_path):
    # Страховка самого теста: сканер находит assert, в том числе внутри функции и после `;`.
    sample = tmp_path / "sample.py"
    sample.write_text("def f(x):\n    y = x; assert y\n    return y\n", encoding="utf-8")
    assert _asserts_in(sample) == [2]


def test_a_sheet_with_the_wrong_number_of_widths_is_rejected_with_a_clear_message():
    with pytest.raises(ValueError, match="Лист «Тест»: ширин колонок 2, а заголовков 3"):
        report_seed_templates._sheet("Тест", "registry-vm-rows", ["№", "Имя", "Статус"], widths=[5, 20])


def test_the_default_template_still_builds_all_four_sheets():
    config = report_seed_templates.default_registry_template_config()
    assert [sheet["title"] for sheet in config["sheets"]] == [
        "Перечень ИС", "Инвентаризац. физ. устройств ИС", "Организация подключений", "Организация управления ВМ",
    ]


def test_group_info_of_a_prepared_group_is_returned(db_session):
    loader = _Loader(db_session)
    loader.infos["g1"] = info = object()  # type: ignore[assignment]  # подставка: тест проверяет только выдачу из кэша
    assert loader.group_info("g1") is info


@pytest.mark.parametrize("prepare", [False, True], ids=["not-probed", "probed-and-absent"])
def test_group_info_of_an_unprepared_group_raises_a_lookup_error(db_session, prepare):
    loader = _Loader(db_session)
    if prepare:
        loader.infos["g1"] = None  # managing_group проверил ключ и записал «такой группы нет»
    with pytest.raises(LookupError, match="'g1'"):
        loader.group_info("g1")


def test_build_info_returns_none_for_a_key_known_neither_to_the_database_nor_to_the_draft(db_session):
    loader = _Loader(db_session)
    edited = _Edited(device_id=None, ports={}, groups={})
    assert loader._build_info(edited, "unknown-key") is None
