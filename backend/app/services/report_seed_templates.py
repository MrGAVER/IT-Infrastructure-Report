"""
Конфигурация шаблона конструктора отчётов "Регламентированный отчёт (заготовка)" — построена по
структуре 4-листового регламентированного отчёта (backend/app/reporting.py, см. также
"Общее описание приложения" в исходном ТЗ проекта), но выражена через grid-движок конструктора
(services/report_grid.py) — с использованием ТОЛЬКО путей полей по графу связей MODEL_MAP, без
собственной процедурной логики.

Важно: это НЕ побитовая копия регламентированного отчёта, а заготовка для дальнейшей ручной
доработки в конструкторе. Модель путей полей конструктора (см. report_engine.py: путь вида
"a.b[].c", не более одной связи "многие" на путь) принципиально проще, чем ручной Python-код
reporting.py, и не может выразить:
  - фолбэк-цепочки источников (например, привязка ИС к оборудованию: сначала current-модель
    InformationSystemSource, при её отсутствии — устаревшие таблицы is_devices/is_vms/is_containers);
  - объединение полей из НЕСКОЛЬКИХ разных связей в одну колонку (например, "оборудование" в листе 1
    у reporting.py — устройства + их ПО + ВМ + контейнеры + площадки одним списком);
  - фильтрацию ВНУТРИ развёрнутого списка (например, "только интерфейсы с признаком управления" —
    путь конструктора берёт ВСЕ элементы связи, отфильтровать по вложенному полю нельзя);
  - обхода через два "многие"-хопа подряд (например, устройство → интерфейсы → открытые порты:
    OpenPort у которого владелец — полиморфный (owner_type/owner_id), а не внешний ключ, поэтому
    у него в MODEL_MAP вообще нет обратной связи от "устройства"/"ВМ" — открытые порты в принципе
    недостижимы путём поля конструктора);
  - построчную пару "подключено"/"не подключено" с двумя направлениями на одну связь (Лист 3
    reporting.py даёт по строке на каждый физический порт, включая неподключённые; здесь строка —
    одна связь Connection, то есть только зарегистрированные подключения).

Каждое поле ниже — либо точное соответствие оригинальной колонке, либо явно упрощённая замена
(отражено в тексте заголовка ячейки и в TEMPLATE_DESCRIPTION). Оригинальный регламентированный
отчёт (кнопка "Отчёт Excel" на дашборде) этим шаблоном не заменяется и не затрагивается.
"""
from __future__ import annotations

from typing import Any

TEMPLATE_NAME = "Регламентированный отчёт — заготовка (4 листа)"

TEMPLATE_DESCRIPTION = (
    "Заготовка на основе структуры регламентированного отчёта (4 листа — см. кнопку «Отчёт Excel» "
    "на дашборде, она остаётся основным источником для сдачи/проверки и этим шаблоном не "
    "затрагивается). Собрана из путей полей конструктора один в один там, где это возможно; часть "
    "колонок оригинала объединяет несколько связей или фильтрует список по вложенному полю — такая "
    "логика конструктору недоступна, эти места здесь упрощены или отсутствуют (подробности — в "
    "заголовках колонок и в комментарии в начале backend/app/services/report_seed_templates.py). "
    "Лист 3 «Организация подключений» — по одной строке на КАЖДУЮ ЗАРЕГИСТРИРОВАННУЮ связь "
    "(Connection); неподключённые порты, в отличие от оригинала, сюда не попадают. Открытые "
    "транспортные порты недостижимы путём поля конструктора (полиморфная связь у OpenPort) и "
    "оставлены только в оригинальном отчёте. Отредактируйте копию под свои нужды — перетаскивайте "
    "поля, добавляйте фильтры и колонки."
)

_TITLE_STYLE = {"bold": True, "align": "center", "valign": "middle", "bg": "#DCE6FA", "wrap": True}
_HEADER_STYLE = {"bold": True, "align": "center", "valign": "middle", "bg": "#EEF2FF", "wrap": True}
_NOTE_STYLE = {"italic": True, "align": "left", "valign": "middle", "bg": "#FDF6E3", "wrap": True}


def _title_row(n_cols: int, text: str) -> dict[str, Any]:
    return {"height": 26, "repeat": False, "data_source": None,
            "cells": [{"col": 0, "colspan": n_cols, "kind": "static", "text": text, "style": _TITLE_STYLE}]}


def _note_row(n_cols: int, text: str) -> dict[str, Any]:
    return {"height": 34, "repeat": False, "data_source": None,
            "cells": [{"col": 0, "colspan": n_cols, "kind": "static", "text": text, "style": _NOTE_STYLE}]}


def _header_row(headers: list[str]) -> dict[str, Any]:
    return {"height": 46, "repeat": False, "data_source": None, "cells": [
        {"col": i, "kind": "static", "text": h, "style": _HEADER_STYLE} for i, h in enumerate(headers)
    ]}


def _data_row(root_entity: str, columns: list[tuple[str, str]], *, sort_by: str | None = None) -> dict[str, Any]:
    """columns — список (kind, path_or_empty); kind == 'index' не требует path."""
    cells = []
    for i, (kind, path) in enumerate(columns):
        cell: dict[str, Any] = {"col": i, "kind": kind, "style": {"wrap": True, "valign": "top"}}
        if kind == "field":
            cell["path"] = path
            cell["separator"] = "; "
        cells.append(cell)
    return {
        "height": 20, "repeat": True,
        "data_source": {"root_entity": root_entity, "expand": "", "include_empty_expand": True,
                         "filters": [], "sort_by": sort_by or ""},
        "cells": cells,
    }


def _sheet(title: str, note: str, headers: list[str], root_entity: str,
           columns: list[tuple[str, str]], widths: list[int], *, sort_by: str | None = None) -> dict[str, Any]:
    n_cols = len(headers)
    assert len(columns) == n_cols and len(widths) == n_cols, title
    return {
        "title": title,
        "columns": [{"width": w} for w in widths],
        "rows": [
            _title_row(n_cols, f"{title} — по состоянию на {{{{report_date}}}}"),
            _note_row(n_cols, note),
            _header_row(headers),
            _data_row(root_entity, columns, sort_by=sort_by),
        ],
    }


def default_registry_template_config() -> dict[str, Any]:
    """Конфигурация xlsx-шаблона конструктора (config для report_templates.config), проверяется
    report_grid.validate_grid_config() в тесте (test_report_seed_templates.py) и в самой миграции."""

    sheet1 = _sheet(
        "Перечень ИС",
        "Колонки «Устройства/ВМ/Контейнеры» заменяют единую колонку «Оборудование» оригинала "
        "(конструктор не объединяет несколько связей в одну ячейку). «Протокол» и «IP-адрес(а) ИС» "
        "упрощены — без резервных источников оригинала.",
        ["№", "Наименование ИС", "Общее описание", "Назначение использования", "Подразделения",
         "Локализация", "Устройства", "Виртуальные машины", "Контейнеры", "Протокол(ы) взаимодействия",
         "IP-адрес(а) ИС", "СКЗИ применяется", "Средство СКЗИ", "Признак SIEM", "Организация поддержки",
         "Способ поддержки", "Описание процесса функционирования"],
        "information-systems",
        [
            ("index", ""), ("field", "name"), ("field", "description"), ("field", "purpose"),
            ("field", "is_departments[].department.name"), ("field", "localization"),
            ("field", "is_devices[].physical_device.system_name"),
            ("field", "is_vms[].virtual_machine.name"), ("field", "is_containers[].container.name"),
            ("field", "is_protocols[].protocol"), ("field", "is_ips[].ip_address"),
            ("field", "crypto_protection_enabled"), ("field", "crypto_protection_description.name"),
            ("field", "siem_enabled"), ("field", "support_organization.name"),
            ("field", "support_method.name"), ("field", "process_description"),
        ],
        [5, 26, 32, 26, 20, 18, 22, 20, 18, 22, 20, 14, 20, 12, 22, 20, 30],
        sort_by="name",
    )

    sheet2 = _sheet(
        "Инвентаризац. физ. устройств ИС",
        "«Интерфейсы устройства» заменяет колонки «Порт/IP управления» оригинала — конструктор не "
        "умеет отобрать из связи только интерфейсы с признаком «управление», поэтому здесь выводятся "
        "ВСЕ интерфейсы устройства. «Количество портов» оригинала не воспроизведено (нет агрегата-счётчика).",
        ["№", "Наименование производителя", "Модель устройства", "Серийный номер", "Системное имя",
         "Встроенная ОС (название)", "Встроенная ОС (версия)", "Интерфейсы устройства (все)",
         "Признак SIEM", "Адрес расположения", "Здание", "Помещение"],
        "devices",
        [
            ("index", ""), ("field", "manufacturer.name"), ("field", "model.model"),
            ("field", "serial_number"), ("field", "system_name"), ("field", "embedded_os.name"),
            ("field", "embedded_os.version"), ("field", "interfaces[].name"), ("field", "siem_enabled"),
            ("field", "building.address"), ("field", "building.name"), ("field", "room.name"),
        ],
        [5, 20, 20, 20, 22, 20, 14, 26, 12, 26, 20, 20],
        sort_by="system_name",
    )

    sheet3 = _sheet(
        "Организация подключений",
        "Отличается от оригинала по структуре: одна строка на КАЖДУЮ ЗАРЕГИСТРИРОВАННУЮ связь "
        "(Connection) в одном направлении, а не на каждый физический порт — неподключённые порты "
        "сюда не попадают. Открытые транспортные порты недостижимы (полиморфная связь).",
        ["№", "Тип подключения", "Устройство А (вид)", "Устройство А (сист. имя)",
         "Устройство А (серийный номер)", "Порт А", "VLAN ID (порт А)", "Устройство Б (вид)",
         "Устройство Б (сист. имя)", "Устройство Б (серийный номер)", "Порт Б",
         "Назначение линии связи", "Активно"],
        "connections",
        [
            ("index", ""), ("field", "connection_type.name"),
            ("field", "source_interface.physical_device.device_type.name"),
            ("field", "source_interface.physical_device.system_name"),
            ("field", "source_interface.physical_device.serial_number"),
            ("field", "source_interface.name"),
            ("field", "source_interface.interface_vlans[].vlan.vlan_id"),
            ("field", "destination_interface.physical_device.device_type.name"),
            ("field", "destination_interface.physical_device.system_name"),
            ("field", "destination_interface.physical_device.serial_number"),
            ("field", "destination_interface.name"), ("field", "purpose"), ("field", "is_active"),
        ],
        [5, 20, 18, 20, 20, 16, 14, 18, 20, 20, 16, 26, 10],
    )

    sheet4 = _sheet(
        "Организация управления ВМ",
        "«IP-адрес(а) ВМ» объединяет все IP ВМ — оригинал отдельно выделяет IP администрирования "
        "(конструктор не фильтрует список по вложенному признаку «управление»). Открытые порты "
        "недостижимы (полиморфная связь), «Гипервизор» берётся из поля ВМ без резервного источника.",
        ["Название ВМ", "ОС ВМ (название)", "ОС ВМ (версия)", "Контейнеры", "Физическое устройство (хост)",
         "Гипервизор (название)", "Гипервизор (версия)", "Целевое использование", "IP-адрес(а) ВМ",
         "Программные активы"],
        "vms",
        [
            ("field", "name"), ("field", "operating_system.name"), ("field", "operating_system.version"),
            ("field", "containers[].name"), ("field", "physical_device.system_name"),
            ("field", "hypervisor_os.name"), ("field", "hypervisor_os.version"), ("field", "purpose"),
            ("field", "vm_ips[].ip_address"), ("field", "vm_software[].software_asset.name"),
        ],
        [22, 20, 14, 20, 24, 20, 14, 24, 26, 26],
        sort_by="name",
    )

    return {"params": [], "sheets": [sheet1, sheet2, sheet3, sheet4]}
