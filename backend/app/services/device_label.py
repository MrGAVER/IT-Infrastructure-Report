"""Единое правило подписи физического устройства: системное имя, а если его нет — серийный номер.

Правило раньше было написано заново в семи местах (отчёты, диаграмма, SQL-фильтр подключений, диагностика целостности, каскад
VLAN, синхронизация портов…) и расходилось в мелочах: имя из одних пробелов где-то считалось именем, где-то нет; при отсутствии
имени и серийного номера одни места отдавали пустую строку, другие — id. Одно и то же устройство получало разные подписи в
диаграмме, отчёте и поиске.

Что считается подписью:
  1. системное имя без пробелов по краям, если после обрезки оно не пустое;
  2. иначе серийный номер;
  3. иначе `fallback` (по умолчанию пустая строка; диагностика целостности передаёт id устройства).
Серийный номер обязателен в модели и в API (`min_length=1`), поэтому п. 3 достижим только для `None` и для «грязных» старых строк;
параметр оставлен, потому что `None` и диагностика данных — штатные случаи, а не гипотетические.

Обрезаются именно обычные пробелы. Это сознательно: SQL-версия (`device_label_expr`) использует `TRIM`, а он и в SQLite, и в
PostgreSQL убирает по умолчанию только пробел; `str.strip()` убрал бы ещё табуляцию и неразрывный пробел, и подписи в Python и в SQL
разошлись бы на таких именах. Контрактный тест (`test_device_label.py`) сверяет обе версии на одной выборке.

Пример:
    >>> device_label(SimpleNamespace(system_name="  srv-01 ", serial_number="SN1"))
    'srv-01'
    >>> device_label_from_parts("   ", "SN1")
    'SN1'
    >>> device_label(None, fallback="—")
    '—'
    # SQL: select(PhysicalDevice.id).where(device_label_expr(PhysicalDevice).contains("srv"))
"""
from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import ColumnElement, func

_BLANK = " "  # какие символы обрезаются по краям имени; должно совпадать с поведением SQL TRIM (см. docstring модуля)


class HasDeviceNames(Protocol):
    """Всё, что имеет системное имя и серийный номер: модель PhysicalDevice, строка результата SQL, namespace в тестах."""

    system_name: str | None
    serial_number: str | None


def clean_system_name(system_name: str | None) -> str:
    """Системное имя без пробелов по краям; пустая строка, если имени нет или оно состоит из одних пробелов."""
    return (system_name or "").strip(_BLANK)


def device_label_from_parts(system_name: str | None, serial_number: str | None, *, fallback: str = "") -> str:
    """Подпись по отдельным значениям — для мест, где объекта устройства нет (строки SQL-выборок, словари)."""
    return clean_system_name(system_name) or serial_number or fallback


def device_label(device: HasDeviceNames | None, *, fallback: str = "") -> str:
    """Единое правило подписи устройства; для `None` (устройство не найдено) возвращает `fallback`."""
    if device is None:
        return fallback
    return device_label_from_parts(device.system_name, device.serial_number, fallback=fallback)


def device_label_expr(model: Any) -> ColumnElement[str]:
    """То же правило для SQL (поиск, фильтры, сортировка); `model` — PhysicalDevice или его алиас (`aliased(PhysicalDevice)`).

    TRIM и NULLIF одинаково работают в SQLite и PostgreSQL. Запасного значения нет: серийный номер NOT NULL."""
    return func.coalesce(func.nullif(func.trim(model.system_name), ""), model.serial_number)
