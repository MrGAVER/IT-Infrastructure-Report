import pytest

from app.services.excel_safety import excel_safe, excel_safe_row


@pytest.mark.parametrize(
    "value",
    [
        "=HYPERLINK(\"http://evil.example\", \"клик\")",
        "+1+1",
        "-2+3+cmd|' /C calc'!A1",
        "@SUM(1,1)",
    ],
)
def test_excel_safe_escapes_formula_trigger_chars(value):
    result = excel_safe(value)
    assert result == "'" + value
    assert result.startswith("'")


def test_excel_safe_placeholder_dash_is_not_escaped():
    """Одиночный "-" — зарезервированный по всему reporting.py плейсхолдер "нет данных", не
    пользовательский ввод; формулой одиночный дефис быть не может."""
    assert excel_safe("-") == "-"


@pytest.mark.parametrize(
    "value",
    ["Обычное имя устройства", "", "Cisco-2960", "IP: 10.0.0.1"],
)
def test_excel_safe_leaves_plain_text_unchanged(value):
    assert excel_safe(value) == value


@pytest.mark.parametrize("value", [None, 42, 3.14, True])
def test_excel_safe_leaves_non_strings_unchanged(value):
    assert excel_safe(value) is value or excel_safe(value) == value


def test_excel_safe_row_applies_to_every_cell_preserving_position():
    row = [1, "=evil()", "Обычное имя", "-", None]
    assert excel_safe_row(row) == [1, "'=evil()", "Обычное имя", "-", None]
