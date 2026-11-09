"""R1-04 код-ревью: `integrity._owner_names` — реестр загрузчиков имён вместо цепочки if/elif.

Функция строила читаемые имена владельцев (ВМ, порт или подинтерфейс устройства, группа портов, ИС) шестью ветвями, цикломатическая
сложность по radon — 24 (худший результат по backend/app); новый тип владельца требовал правки самой функции. Теперь каждый тип — отдельный
загрузчик в реестре `OWNER_NAME_LOADERS`. Тесты фиксируют поведение, которое рефакторинг не имеет права менять:
  • имя владельца каждого типа (в том числе подпись устройства по единому правилу R1-03 и «устройство / порт»);
  • число SQL-запросов: по одному на тип владельца (интерфейс — 2, подинтерфейс — 3), а не по строке;
  • неизвестный тип и несуществующий владелец остаются без имени;
  • каждому типу владельца открытых портов соответствует загрузчик (защита от забытого типа).

Запуск: pytest backend/tests/test_integrity_owner_names.py -v
"""
from __future__ import annotations

import pytest
from migration_support import insert_row

from app.constants import OwnerType
from app.services.crud.owned_rows import _OPEN_PORT_OWNER_LABELS
from app.services.integrity import INFORMATION_SYSTEM_OWNER, INTERFACE_GROUP_OWNER, _owner_names


@pytest.fixture()
def data(db_session):
    """По одной строке каждого вида владельца: две ВМ-подобных не нужны — важно, что запросов по типам, а не по строкам."""
    connection = db_session.connection()
    device = insert_row(connection, "physical_devices", system_name="  srv-01 ", serial_number="SN-1")
    nameless = insert_row(connection, "physical_devices", system_name="   ", serial_number="SN-2")
    broken = insert_row(connection, "physical_devices", system_name=None, serial_number="")  # «грязная» строка: подпись — id
    other = insert_row(connection, "physical_devices", system_name="sw-02", serial_number="SN-3")
    port = insert_row(connection, "device_interfaces", physical_device_id=device, name="Gi0/1")
    port_other = insert_row(connection, "device_interfaces", physical_device_id=other, name="Gi0/2")
    sub = insert_row(connection, "device_subinterfaces", parent_interface_id=port, name="Gi0/1.10")
    sub_other = insert_row(connection, "device_subinterfaces", parent_interface_id=port_other, name="Gi0/2.20")
    return {
        "device": device, "nameless": nameless, "broken": broken, "other": other, "port": port, "port_other": port_other, "sub": sub, "sub_other": sub_other,
        "vm": insert_row(connection, "virtual_machines", name="vm-app"),
        "group": insert_row(connection, "interface_groups", name="Серверные"),
        "system": insert_row(connection, "information_systems", name="ЕАИС ТО"),
    }


def _selects(statements: list[str]) -> int:
    return sum(1 for statement in statements if statement.lstrip().upper().startswith("SELECT"))


@pytest.mark.parametrize(
    ("owner_type", "key", "expected_name", "expected_queries"),
    [
        (OwnerType.VIRTUAL_MACHINE, "vm", "vm-app", 1),
        (INTERFACE_GROUP_OWNER, "group", "Серверные", 1),
        (INFORMATION_SYSTEM_OWNER, "system", "ЕАИС ТО", 1),
        (OwnerType.PHYSICAL_DEVICE, "device", "srv-01", 1),  # имя без пробелов по краям (правило R1-03)
        (OwnerType.PHYSICAL_DEVICE, "nameless", "SN-2", 1),  # имя из пробелов → серийный номер
        (OwnerType.DEVICE_INTERFACE, "port", "srv-01 / Gi0/1", 2),
        (OwnerType.DEVICE_SUBINTERFACE, "sub", "srv-01 / Gi0/1.10", 3),
    ],
)
def test_each_owner_type_gets_its_name_with_a_fixed_number_of_queries(db_session, sql_log, data, owner_type, key, expected_name, expected_queries):
    sql_log.clear()
    names = _owner_names(db_session, {(owner_type, data[key])})
    assert names == {(owner_type, data[key]): expected_name}
    assert _selects(sql_log) == expected_queries


def test_device_without_name_and_serial_is_labelled_by_id(db_session, data):
    assert _owner_names(db_session, {(OwnerType.PHYSICAL_DEVICE, data["broken"])}) == {(OwnerType.PHYSICAL_DEVICE, data["broken"]): data["broken"]}


def test_queries_depend_on_owner_types_not_on_rows(db_session, sql_log, data):
    """Два порта и два подинтерфейса разных устройств — столько же запросов, сколько для одного (2 и 3), а не вдвое больше."""
    sql_log.clear()
    names = _owner_names(
        db_session,
        {(OwnerType.DEVICE_INTERFACE, data["port"]), (OwnerType.DEVICE_INTERFACE, data["port_other"]),
         (OwnerType.DEVICE_SUBINTERFACE, data["sub"]), (OwnerType.DEVICE_SUBINTERFACE, data["sub_other"])},
    )
    assert names == {
        (OwnerType.DEVICE_INTERFACE, data["port"]): "srv-01 / Gi0/1",
        (OwnerType.DEVICE_INTERFACE, data["port_other"]): "sw-02 / Gi0/2",
        (OwnerType.DEVICE_SUBINTERFACE, data["sub"]): "srv-01 / Gi0/1.10",
        (OwnerType.DEVICE_SUBINTERFACE, data["sub_other"]): "sw-02 / Gi0/2.20",
    }
    assert _selects(sql_log) == 2 + 3


def test_all_owner_types_together(db_session, sql_log, data):
    owners = {
        (OwnerType.VIRTUAL_MACHINE, data["vm"]), (INTERFACE_GROUP_OWNER, data["group"]), (INFORMATION_SYSTEM_OWNER, data["system"]),
        (OwnerType.PHYSICAL_DEVICE, data["device"]), (OwnerType.DEVICE_INTERFACE, data["port"]), (OwnerType.DEVICE_SUBINTERFACE, data["sub"]),
    }
    sql_log.clear()
    names = _owner_names(db_session, owners)
    assert names == {
        (OwnerType.VIRTUAL_MACHINE, data["vm"]): "vm-app", (INTERFACE_GROUP_OWNER, data["group"]): "Серверные",
        (INFORMATION_SYSTEM_OWNER, data["system"]): "ЕАИС ТО", (OwnerType.PHYSICAL_DEVICE, data["device"]): "srv-01",
        (OwnerType.DEVICE_INTERFACE, data["port"]): "srv-01 / Gi0/1", (OwnerType.DEVICE_SUBINTERFACE, data["sub"]): "srv-01 / Gi0/1.10",
    }
    assert _selects(sql_log) == 1 + 1 + 1 + 1 + 2 + 3


def test_unknown_owner_type_and_missing_owner_stay_without_a_name(db_session, sql_log, data):
    sql_log.clear()
    assert _owner_names(db_session, {("information_system_source", "x"), ("no-such-type", "y")}) == {}
    assert _selects(sql_log) == 0
    assert _owner_names(db_session, {(OwnerType.VIRTUAL_MACHINE, "missing-id"), (OwnerType.DEVICE_INTERFACE, "missing-port")}) == {}
    assert _owner_names(db_session, set()) == {}


# --- Защита от забытого типа --------------------------------------------------------------------------------------------------
def test_every_open_port_owner_type_has_a_name_loader():
    """Типы владельцев открытых портов — те же, что подписывает форма (`_OPEN_PORT_OWNER_LABELS`), плюс два псевдо-типа отчёта о дублях
    (группа портов и ИС). Добавили тип — добавьте загрузчик в OWNER_NAME_LOADERS, иначе отчёт покажет его без имени."""
    from app.services.integrity import OWNER_NAME_LOADERS

    required = set(_OPEN_PORT_OWNER_LABELS) | {INTERFACE_GROUP_OWNER, INFORMATION_SYSTEM_OWNER}
    assert required <= set(OWNER_NAME_LOADERS), sorted(required - set(OWNER_NAME_LOADERS))
    assert all(callable(loader) for loader in OWNER_NAME_LOADERS.values())
