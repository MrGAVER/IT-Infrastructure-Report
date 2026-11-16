"""
A-02 (код-ревью main @ b375f58): сортировка строк отчёта по «сырому» значению поля, а не по готовой строке.

Раньше `iter_report_rows` сортировал результат `render_field` — текст: VLAN шли как `10, 100, 2, 9`, даты `ДД.ММ.ГГГГ` — не по хронологии, а пустые значения —
первыми (проверка `v is None` была мёртвым кодом: `render_field` возвращает `""`, а не `None`). Теперь ключ строится от `resolve_value`: числа — по значению, даты — по
времени, пустое — в конец; общий движок исправлен в одном месте, поэтому порядок одинаков в документных отчётах (docx) и в xlsx-сетке.

Запуск: pytest backend/tests/test_report_sort.py -v
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import openpyxl
import pytest

from app.models import VLAN, DeviceCategory, DeviceType, PhysicalDevice, VirtualMachine
from app.services.report_engine import ReportContext, _sort_key, iter_report_rows, render_field
from app.services.report_grid import build_xlsx_grid
from app.services.report_render import preview_rows

# (vlan_id, description, created_at): 9 — без описания (None), 100 — с пустым описанием («»).
_VLANS = [
    (100, "", datetime(2026, 2, 1, 10, 0)),
    (9, None, datetime(2026, 1, 15, 9, 30)),
    (10, "d10", datetime(2025, 12, 31, 23, 59)),
    (2, "d2", datetime(2025, 1, 1, 0, 0)),
]


@pytest.fixture()
def vlans(db_session):
    for vlan_id, description, created_at in _VLANS:
        db_session.add(VLAN(vlan_id=vlan_id, name=f"vlan{vlan_id}", description=description, created_at=created_at))
    db_session.commit()
    return db_session


def _ordered(session, entity: str, sort_by: str, path: str) -> list[str]:
    """Значения поля `path` в порядке, в котором строки выдаёт движок при сортировке по `sort_by`."""
    ctx = ReportContext(session)
    return [render_field(ctx, entity, row, path) for row, _, _ in iter_report_rows(ctx, entity, sort_by=sort_by)]


def test_numbers_are_sorted_by_value_not_as_text(vlans):
    # Раньше: ['10', '100', '2', '9'].
    assert _ordered(vlans, "vlans", "vlan_id", "vlan_id") == ["2", "9", "10", "100"]


def test_dates_are_sorted_chronologically(vlans):
    # Раньше (по тексту ДД.ММ.ГГГГ): 01.01.2025, 01.02.2026, 15.01.2026, 31.12.2025.
    assert _ordered(vlans, "vlans", "created_at", "created_at") == [
        "01.01.2025 00:00",
        "31.12.2025 23:59",
        "15.01.2026 09:30",
        "01.02.2026 10:00",
    ]


def test_empty_values_go_last(vlans):
    # Раньше пустые шли первыми: ['', '', 'd10', 'd2']. None и «» — оба «пусто».
    assert _ordered(vlans, "vlans", "description", "description") == ["d10", "d2", "", ""]


def test_sort_by_path_through_to_many_relation_puts_records_without_related_objects_last(db_session):
    """Путь через связь `[]` даёт список значений: сортируем по тому же тексту, что увидит читатель; запись без связанных — пустая, значит последняя."""
    category = DeviceCategory(name="Серверы и СХД")
    db_session.add(category)
    db_session.flush()
    device_type = DeviceType(name="Сервер", category_id=category.id)
    db_session.add(device_type)
    db_session.flush()
    no_vms = PhysicalDevice(device_type_id=device_type.id, serial_number="SN-0", system_name="no-vms")
    late = PhysicalDevice(device_type_id=device_type.id, serial_number="SN-1", system_name="late")
    early = PhysicalDevice(device_type_id=device_type.id, serial_number="SN-2", system_name="early")
    db_session.add_all([no_vms, late, early])
    db_session.flush()
    db_session.add_all(
        [
            VirtualMachine(name="zeta", physical_device_id=late.id),
            VirtualMachine(name="alpha", physical_device_id=early.id),
        ]
    )
    db_session.commit()

    assert _ordered(db_session, "devices", "vms[].name", "system_name") == ["early", "late", "no-vms"]


def test_sort_key_orders_mixed_types_without_type_error():
    """Смешанный столбец (в SQLite колонка с аффинностью INTEGER может хранить и текст) не должен ронять сортировку: типы не сравниваются между собой, а идут по рангу."""
    values = ["b", None, 5, date(2026, 1, 1), "", Decimal("1.5"), datetime(2026, 1, 1, 12, 0), True, "a", []]
    ordered = sorted(values, key=_sort_key)
    # Числа (и bool как число) → даты → строки → пустое (None, «», пустой список — в исходном порядке, сортировка устойчива).
    assert ordered[:3] == [True, Decimal("1.5"), 5]
    assert ordered[3:5] == [date(2026, 1, 1), datetime(2026, 1, 1, 12, 0)]
    assert ordered[5:7] == ["a", "b"]
    assert ordered[7:] == [None, "", []]


def test_docx_table_block_uses_the_same_order(vlans):
    config = {
        "blocks": [
            {
                "type": "table",
                "root_entity": "vlans",
                "sort_by": "vlan_id",
                "columns": [{"header": "VLAN", "source": "field", "path": "vlan_id"}],
            }
        ]
    }
    section = preview_rows(vlans, config)["sections"][0]
    assert [row[0] for row in section["rows"]] == ["2", "9", "10", "100"]


def test_xlsx_grid_uses_the_same_order(vlans, tmp_path):
    config = {
        "sheets": [
            {
                "title": "VLAN",
                "columns": [{"width": 10}, {"width": 10}],
                "rows": [
                    {
                        "height": 18,
                        "repeat": True,
                        "data_source": {"root_entity": "vlans", "sort_by": "vlan_id"},
                        "cells": [
                            {"col": 0, "kind": "field", "path": "vlan_id"},
                            {"col": 1, "kind": "field", "path": "description"},
                        ],
                    }
                ],
            }
        ]
    }
    path = build_xlsx_grid(vlans, config, tmp_path, template_name="sort")
    rows = list(openpyxl.load_workbook(path)["VLAN"].iter_rows(values_only=True))
    # В xlsx числа — настоящие числа, поэтому сортировка «по значению» видна и в самой ячейке.
    assert [row[0] for row in rows] == [2, 9, 10, 100]
