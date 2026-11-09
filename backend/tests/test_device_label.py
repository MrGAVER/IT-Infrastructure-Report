"""R1-03 код-ревью: одно правило подписи устройства «системное имя, иначе серийный номер».

Раньше правило было записано в семи местах и расходилось: устройство с системным именем из одних пробелов получало разные подписи в
отчёте, диаграмме и SQL-фильтре подключений. Теперь оно живёт в `app/services/device_label.py`:
  • параметризованные тесты функции (None, пустое имя, имя из пробелов, имя с пробелами по краям, нет серийного номера);
  • контрактный тест: Python-версия и SQL-версия дают одинаковую подпись на одной выборке (SQLite, а при
    INFRA_REGISTRY_TEST_DATABASE_URL — и PostgreSQL);
  • сквозной тест: устройство с именем «   » находится поиском по серийному номеру, и подпись в строке подключения — серийный номер;
  • тест-сканер: в backend/app нет копий правила вне нового модуля.

Запуск: pytest backend/tests/test_device_label.py -v
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from migration_support import insert_row
from test_connection_query import _connect, _device, _device_type, _page, _port

from app.models import PhysicalDevice
from app.services.device_label import clean_system_name, device_label, device_label_expr, device_label_from_parts

APP_DIR = Path(__file__).resolve().parents[1] / "app"

# (system_name, serial_number, fallback, ожидаемая подпись)
CASES = [
    ("srv-01", "SN1", "", "srv-01"),
    ("  srv-01  ", "SN1", "", "srv-01"),
    ("имя устройства", "SN1", "", "имя устройства"),
    (None, "SN1", "", "SN1"),
    ("", "SN1", "", "SN1"),
    ("   ", "SN1", "", "SN1"),
    ("", "", "", ""),
    ("", "", "id-1", "id-1"),
    (None, None, "id-1", "id-1"),  # строка SQL-выборки может принести None вместо серийного номера
    ("   ", None, "", ""),
]


@pytest.mark.parametrize(("system_name", "serial_number", "fallback", "expected"), CASES)
def test_device_label_applies_one_rule(system_name, serial_number, fallback, expected):
    device = SimpleNamespace(system_name=system_name, serial_number=serial_number)
    assert device_label(device, fallback=fallback) == expected
    assert device_label_from_parts(system_name, serial_number, fallback=fallback) == expected


@pytest.mark.parametrize("fallback", ["", "—", "id-7"])
def test_missing_device_gives_the_fallback(fallback):
    assert device_label(None, fallback=fallback) == fallback


def test_default_fallback_is_empty_string():
    assert device_label(None) == "" and device_label(SimpleNamespace(system_name=None, serial_number="")) == ""


@pytest.mark.parametrize(("raw", "expected"), [(None, ""), ("", ""), ("   ", ""), (" a ", "a"), ("a b", "a b")])
def test_clean_system_name(raw, expected):
    assert clean_system_name(raw) == expected


# --- Контракт: Python-версия и SQL-версия дают одинаковую подпись ------------------------------------------------------------
def test_sql_and_python_versions_agree_on_one_sample(db_session):
    names_and_serials = [(name, serial) for name, serial, fallback, _ in CASES if serial and not fallback]
    names_and_serials += [("x y", "SN-9"), ("Имя", "SN-10"), (" 00 ", "SN-11")]
    connection = db_session.connection()
    expected: dict[str, str] = {}
    for index, (name, serial) in enumerate(names_and_serials):
        device_id = insert_row(connection, "physical_devices", system_name=name, serial_number=f"{serial}-{index}")
        expected[device_id] = device_label(SimpleNamespace(system_name=name, serial_number=f"{serial}-{index}"))

    rows = db_session.execute(sa.select(PhysicalDevice.id, device_label_expr(PhysicalDevice)).where(PhysicalDevice.id.in_(expected))).all()

    assert len(rows) == len(expected) == len(names_and_serials)
    assert {device_id: label for device_id, label in rows} == expected


def test_sql_version_works_on_an_alias(db_session):
    """Фильтр подключений вызывает правило на алиасах устройств-концов (aliased(PhysicalDevice))."""
    from sqlalchemy.orm import aliased

    insert_row(db_session.connection(), "physical_devices", system_name="   ", serial_number="ALIAS-SER")
    alias = aliased(PhysicalDevice)
    assert db_session.scalar(sa.select(device_label_expr(alias)).where(alias.serial_number == "ALIAS-SER")) == "ALIAS-SER"


# --- Сквозной сценарий: подпись видна и в поиске, и в строке подключения -----------------------------------------------------
@pytest.fixture()
def cable(client) -> str:
    return client.post("/api/v1/resources/connection-types", json={"name": "Витая пара (подпись)"}).json()["id"]


def test_device_with_blank_system_name_is_labelled_by_serial_everywhere(client, cable):
    device_type = _device_type(client)
    blank, = _device(client, device_type, "BLANK-SER-1", [_port("Gi0/1")], system_name="   ")
    named, = _device(client, device_type, "NAMED-SER-2", [_port("Gi0/1")], system_name="sw-named")
    _connect(client, blank, named, cable)

    found = _page(client, q="BLANK-SER")  # SQL-версия: имя из пробелов не должно скрывать серийный номер от поиска
    assert found["total"] == 1
    row = found["items"][0]
    assert row["source_device_name"] == "BLANK-SER-1"  # Python-версия: та же подпись в самой строке
    assert row["destination_device_name"] == "sw-named"


# --- Сканер: копий правила вне модуля больше нет -----------------------------------------------------------------------------
DUPLICATE_PATTERNS = [
    re.compile(r"system_name or [a-z_.]*serial_number"),  # критерий приёмки R1-03 из отчёта
    re.compile(r"\(\w+\.system_name or \"\"\)\.strip\(\) or"),  # вариант с обрезкой (structural_appendix)
    re.compile(r"nullif\([^)]*system_name"),  # SQL-вариант (connection_query)
]


def test_rule_is_not_duplicated_outside_the_module():
    offenders = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if path.name == "device_label.py":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(pattern.search(line) for pattern in DUPLICATE_PATTERNS):
                offenders.append(f"{path.relative_to(APP_DIR)}:{number}: {line.strip()[:110]}")
    assert offenders == [], "правило подписи устройства нужно брать из app/services/device_label.py:\n  " + "\n  ".join(offenders)


# --- Все прежние точки входа дают одну подпись -------------------------------------------------------------------------------
def test_every_former_implementation_agrees_on_a_blank_name():
    from app.reporting import device_label as reporting_label
    from app.services.crud.stack_vlan_settings import device_label as stack_label
    from app.services.structural_appendix import _device_label as appendix_label

    device = SimpleNamespace(system_name="   ", serial_number="SN-BLANK")
    assert {reporting_label(device), stack_label(device), appendix_label(device)} == {"SN-BLANK"}
    assert reporting_label(None) == ""
