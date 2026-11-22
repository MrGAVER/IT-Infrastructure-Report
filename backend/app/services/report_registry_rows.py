"""
"Виртуальные" сущности конструктора отчётов — 4 плоские, уже полностью посчитанные коллекции
строк, побитово повторяющие вывод регламентированного отчёта (backend/app/reporting.py). В отличие
от обычных сущностей MODEL_MAP (report_meta.py), у них нет соответствующей таблицы в БД: каждая
строка собирается в Python по той же логике, что использует reporting.py, и переиспользует
дословно ТЕ ЖЕ функции (_is_row_values/_device_row_values/_connection_row_values_list/
_vm_row_values) — специально, чтобы вывод конструктора и регламентированного отчёта не могли
разойтись по одной и той же причине, по которой в проекте вообще принято выносить общую логику в
одно место (см. README, "Shared helpers prevent divergence").

Как это соотносится с report_grid.py: с точки зрения grid-движка виртуальная сущность — это ROOT
ENTITY для повторяющейся строки, как и обычная (root_entity в data_source), просто без to_one/
to_many-связей (все значения уже "сплющены" в плоские поля) и без второго пути её найти — эти
сущности не являются целью связи ни от какой другой сущности, а данные строки поставляет функция-
загрузчик вместо SELECT по таблице (см. ReportContext.all_rows() в report_engine.py).

Каждый loader принимает (session, structural_unit_ids) — второй параметр (см. ReportContext) даёт
runtime-фильтр по структурным единицам размещения оборудования (models.StructuralUnit), тот же,
что фильтрует регламентированный отчёт (reporting.build_report): просто передаётся дальше в
_load_report_data() без какой-либо своей логики — фильтрация выполняется там же, где и для
регламентированного отчёта, поэтому вывод этих сущностей не может разойтись с ним и по фильтру
структурных единиц, не только по формату строк.

Порядок вывода строк каждой сущности — тот самый, что и в оригинальном отчёте (в частности, для
"Организация подключений" — уже отсортированный/сгруппированный список из
_connection_row_values_list), поэтому шаблон-заготовка конструктора (report_seed_templates.py)
использует эти сущности БЕЗ дополнительной сортировки в data_source — иначе он мог бы разойтись
с оригинальным порядком строк.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

from sqlalchemy.orm import Session

from ..reporting import (
    _connection_row_values_list,
    _device_row_values,
    _is_row_values,
    _load_report_data,
    _vm_row_values,
)


@dataclass(frozen=True)
class VirtualField:
    name: str
    label: str


@dataclass(frozen=True)
class VirtualEntity:
    key: str
    label: str
    fields: list[VirtualField]
    loader: Callable[[Session, "list[str] | None"], list[Any]]


def _rows_from_values(values_lists: list[list]) -> list[SimpleNamespace]:
    """values_lists — список списков значений в порядке полей соответствующей VirtualEntity.fields
    (см. вызовы ниже) — сворачивает каждый в SimpleNamespace с этими именами полей + служебным id."""
    return [SimpleNamespace(id=str(i), **row) for i, row in enumerate(values_lists)]


def _zip_fields(names: list[str], values: list) -> dict:
    return dict(zip(names, values))


# ---------- Лист 1 "Перечень ИС" ----------

_IS_FIELDS = [
    VirtualField("name", "Наименование информационной системы"),
    VirtualField("description", "Общее описание информационной системы"),
    VirtualField("purpose", "Назначение использования ИС"),
    VirtualField("departments", "Работники/подразделения, использующие ИС"),
    VirtualField("localization", "Локализация ИС"),
    VirtualField("equipment", "Оборудование, ПО, ВМ, контейнеры, площадки размещения"),
    VirtualField("protocols", "Протокол(ы) передачи данных"),
    VirtualField("ip_addresses", "IP-адрес(а) взаимодействия ИС"),
    VirtualField("crypto_protection", "Применение сертифицированных СКЗИ"),
    VirtualField("siem", "Признак получения событий в SIEM"),
    VirtualField("support_organization", "Организация технической поддержки"),
    VirtualField("support_method", "Способ оказания технической поддержки"),
    VirtualField("process_description", "Описание процесса функционирования ИС"),
    VirtualField("physical_server_names", "Название физического сервера"),
    VirtualField("physical_server_ips", "IP-адрес физического сервера"),
    VirtualField("vm_or_container_names", "Наименование ВМ/контейнера"),
    VirtualField("vm_or_container_ips", "IP-адрес ВМ/контейнера"),
]


def _load_is_rows(session: Session, structural_unit_ids: list | None = None) -> list[SimpleNamespace]:
    d = _load_report_data(session, None, structural_unit_ids)
    names = [f.name for f in _IS_FIELDS]
    return _rows_from_values([_zip_fields(names, _is_row_values(obj, d)) for obj in d.systems])


# ---------- Лист 2 "Инвентаризац. физ. устройств ИС" ----------

_DEVICE_FIELDS = [
    VirtualField("manufacturer", "Наименование производителя"),
    VirtualField("model", "Модель устройства"),
    VirtualField("serial_number", "Серийный номер устройства"),
    VirtualField("system_name", "Системное имя устройства"),
    VirtualField("os_version", "Версия операционной системы устройства"),
    VirtualField("management_port", "Номер порта управления устройством"),
    VirtualField("management_ip", "IP-адрес управления устройством"),
    VirtualField("siem", "Признак получения событий в SIEM"),
    VirtualField("port_count", "Количество физических портов устройства"),
    VirtualField("address", "Адрес расположения устройства"),
    VirtualField("building_name", "Наименование здания"),
    VirtualField("room_name", "Помещение размещения устройства"),
]


def _load_device_rows(session: Session, structural_unit_ids: list | None = None) -> list[SimpleNamespace]:
    d = _load_report_data(session, None, structural_unit_ids)
    names = [f.name for f in _DEVICE_FIELDS]
    return _rows_from_values([_zip_fields(names, _device_row_values(dev, d)) for dev in d.devices])


# ---------- Лист 3 "Организация подключений" ----------

_CONNECTION_FIELDS = [
    VirtualField("own_device_type", "Вид физического устройства"),
    VirtualField("own_serial_number", "Серийный номер устройства"),
    VirtualField("own_system_name", "Системное имя устройства"),
    VirtualField("own_os", "ОС физического устройства"),
    VirtualField("own_port_name", "Номер физического/логического порта"),
    VirtualField("own_ip", "IP-адрес порта устройства"),
    VirtualField("own_open_ports", "Перечень открытых портов"),
    VirtualField("own_protocols", "Протокол (технология)"),
    VirtualField("own_vlan_ids", "VLAN ID"),
    VirtualField("own_vlan_names", "VLAN Name"),
    VirtualField("link_type", "Тип физической линии связи"),
    VirtualField("link_purpose", "Назначение линии связи"),
    VirtualField("neighbor_device_type", "Вид соседнего устройства"),
    VirtualField("neighbor_serial_number", "Серийный номер соседнего устройства"),
    VirtualField("neighbor_system_name", "Системное имя соседнего устройства"),
    VirtualField("neighbor_os", "ОС соседнего устройства"),
    VirtualField("neighbor_ip", "IP-адрес порта соседнего устройства"),
]


def _load_connection_rows(session: Session, structural_unit_ids: list | None = None) -> list[SimpleNamespace]:
    d = _load_report_data(session, None, structural_unit_ids)
    names = [f.name for f in _CONNECTION_FIELDS]
    # _connection_row_values_list возвращает строки с номером (№) первым элементом — здесь он не
    # нужен: конструктор нумерует повторяющуюся строку сам (ячейка типа "№ по порядку"), в том же
    # порядке, что уже даёт эта функция.
    return _rows_from_values([_zip_fields(names, row[1:]) for row in _connection_row_values_list(d)])


# ---------- Лист 4 "Организация управления ВМ" ----------

_VM_FIELDS = [
    VirtualField("vm_name", "Название виртуальной машины"),
    VirtualField("vm_os", "ОС виртуальной машины"),
    VirtualField("container_names", "Наименование контейнера"),
    VirtualField("host_device_name", "Наименование физического устройства (хоста)"),
    VirtualField("hypervisor", "Наименование среды виртуализации"),
    VirtualField("purpose", "Целевое использование ВМ/контейнера"),
    VirtualField("ip_addresses", "IP-адрес(а) ВМ/контейнера"),
    VirtualField("open_ports", "Перечень открытых портов"),
    VirtualField("admin_ip", "IP-адрес администрирования"),
    VirtualField("software_assets", "Программные активы"),
]


def _load_vm_rows(session: Session, structural_unit_ids: list | None = None) -> list[SimpleNamespace]:
    d = _load_report_data(session, None, structural_unit_ids)
    names = [f.name for f in _VM_FIELDS]
    return _rows_from_values([_zip_fields(names, _vm_row_values(v, d)) for v in d.vms])


VIRTUAL_ENTITIES: dict[str, VirtualEntity] = {
    e.key: e
    for e in [
        VirtualEntity("registry-is-rows", "Регистр — Перечень ИС (как в регл. отчёте)", _IS_FIELDS, _load_is_rows),
        VirtualEntity("registry-device-rows", "Регистр — Инвентаризация устройств (как в регл. отчёте)", _DEVICE_FIELDS, _load_device_rows),
        VirtualEntity(
            "registry-connection-rows", "Регистр — Организация подключений (как в регл. отчёте)", _CONNECTION_FIELDS, _load_connection_rows
        ),
        VirtualEntity("registry-vm-rows", "Регистр — Управление ВМ (как в регл. отчёте)", _VM_FIELDS, _load_vm_rows),
    ]
}
