"""
Общие вычисления, используемые и в serialization.py (дашборд), и в reporting.py (Excel-отчет).

До этого модуля логика "порт/IP управления устройства с учётом VLAN-управления" была независимо
продублирована в трёх местах: enrich_devices (serialization.py), Лист 2 и Лист 3 (reporting.py) —
с почти одинаковым кодом, который пришлось синхронизировать вручную несколько раз подряд в ходе
разработки (например, добавление VLAN в "Порт управления" дашборда и в Лист 2 отчета делалось как
два отдельных исправления одной и той же логики). Теперь это одна функция.
"""
from __future__ import annotations
from typing import Any


def ip_label(ip: Any) -> str:
    """Единое форматирование IP-адреса с префиксом (CIDR), если он задан."""
    return f"{ip.ip_address}/{ip.prefix_length}" if ip.prefix_length is not None else ip.ip_address


def device_management_ports_and_ips(
    management_interfaces: list[Any],
    ips_by_interface: dict[str, list[Any]],
    management_vlan_links: list[Any],
    vlan_map: dict[str, Any],
    *,
    vlan_label_with_name: bool = True,
) -> tuple[list[str], list[str]]:
    """
    Считает порты и IP управления устройства из двух источников: физических интерфейсов с
    is_management=True и VLAN устройства (PhysicalDeviceVLAN) с is_management=True.

    management_interfaces: DeviceInterface-объекты устройства с is_management=True.
    ips_by_interface: dict[interface_id] -> список InterfaceIP.
    management_vlan_links: PhysicalDeviceVLAN-объекты устройства с is_management=True.
    vlan_map: dict[vlan_id] -> VLAN (для получения номера/имени VLAN).
    vlan_label_with_name: включать ли имя VLAN в подпись порта ("VLAN 100 — Mgmt") или только
        номер ("VLAN 100") — дашборду нужно первое для наглядности, отчету для строгого поля
        "номер порта" — второе.

    Возвращает (port_names, ip_values) — списки строк без дублей, с сохранением порядка появления.
    """
    # Ссылка на VLAN, которого больше нет в справочнике (осиротевшая запись) — не должна давать
    # ни подпись порта, ни IP; раньше (до консолидации) IP-часть по ошибке не делала эту проверку,
    # и такая ссылка молча добавляла "ничей" IP без соответствующей подписи порта.
    resolvable_vlan_links = [x for x in management_vlan_links if x.vlan_id in vlan_map]

    if vlan_label_with_name:
        vlan_labels = [f"VLAN {vlan_map[x.vlan_id].vlan_id} — {vlan_map[x.vlan_id].name}" for x in resolvable_vlan_links]
    else:
        vlan_labels = [f"VLAN {vlan_map[x.vlan_id].vlan_id}" for x in resolvable_vlan_links]
    port_names = [i.name for i in management_interfaces] + vlan_labels

    ip_values = [ip_label(ip) for iface in management_interfaces for ip in ips_by_interface.get(iface.id, [])]
    ip_values += [ip_label(x) for x in resolvable_vlan_links if x.ip_address]

    return list(dict.fromkeys(port_names)), list(dict.fromkeys(ip_values))
