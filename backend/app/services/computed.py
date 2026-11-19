"""
Общие вычисления, используемые и в serialization.py (дашборд), и в reporting.py (Excel-отчет).

До этого модуля логика "порт/IP управления устройства с учётом VLAN-управления" была независимо
продублирована в трёх местах: enrich_devices (serialization.py), Лист 2 и Лист 3 (reporting.py) —
с почти одинаковым кодом, который пришлось синхронизировать вручную несколько раз подряд в ходе
разработки (например, добавление VLAN в "Порт управления" дашборда и в Лист 2 отчета делалось как
два отдельных исправления одной и той же логики). Теперь это одна функция.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional, Sequence
from uuid import uuid4


def local_timestamp_suffix() -> str:
    """Суффикс имени файла сгенерированного отчёта: метка времени и короткий случайный хвост
    (`Отчёт_2026-08-15_14-30-00_3fa9c1d2.xlsx`).

    Хвост нужен потому, что секундной метки мало: два пользователя, сформировавшие отчёт в одну
    секунду, перезаписали бы файлы друг друга.

    Намеренно локальное время сервера (datetime.now(), без timezone), а не UTC: это не хранимая
    и не сравниваемая метка времени вроде created_at/updated_at (те хранятся как naive UTC —
    см. TimestampMixin в models.py и services/timeutil.py), а разовое форматирование
    момента генерации файла для человека — в имени файла должно быть то время, которое человек
    увидит на часах в момент скачивания, а не смещённое на часовой пояс UTC значение."""
    return f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{uuid4().hex[:8]}"


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
    management_subinterfaces: Sequence[Any] = (),
    ips_by_subinterface: Optional[dict[str, list[Any]]] = None,
    port_name_by_id: Optional[dict[str, str]] = None,
) -> tuple[list[str], list[str]]:
    """
    Считает порты и IP управления устройства из двух источников: физических интерфейсов с
    is_management=True и VLAN устройства (PhysicalDeviceVLAN) с is_management=True.

    management_interfaces: DeviceInterface-объекты устройства с is_management=True.
    ips_by_interface: dict[interface_id] -> список IPAddress (owner_type="device_interface").
    management_vlan_links: PhysicalDeviceVLAN-объекты устройства с is_management=True.
    vlan_map: dict[vlan_id] -> VLAN (для получения номера/имени VLAN).
    vlan_label_with_name: включать ли имя VLAN в подпись порта ("VLAN 100 — Mgmt") или только
        номер ("VLAN 100") — дашборду нужно первое для наглядности, отчету для строгого поля
        "номер порта" — второе.

    management_subinterfaces / ips_by_subinterface / port_name_by_id (необязательные): подинтерфейсы
        портов с is_management=True — управление может висеть на логическом интерфейсе (например,
        Gi0/0.99 на VLAN управления у маршрутизатора), а не на самом порту. В «порты» такой подинтерфейс
        попадает как «Gi0/0 (подинтерфейс Gi0/0.99)» — внутри своего порта, port_name_by_id даёт имя
        порта-родителя по parent_interface_id, — а его IP добавляются к IP управления. Без этих
        аргументов поведение прежнее.

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
    parent_names = port_name_by_id or {}
    sub_ips = ips_by_subinterface or {}
    # «Gi0/0 (подинтерфейс Gi0/0.99)»; если имя порта-родителя неизвестно — только имя подинтерфейса.
    subinterface_labels = [
        f"{parent_names[sub.parent_interface_id]} (подинтерфейс {sub.name})" if parent_names.get(sub.parent_interface_id) else sub.name
        for sub in management_subinterfaces
    ]
    port_names = [i.name for i in management_interfaces] + subinterface_labels + vlan_labels

    ip_values = [ip_label(ip) for iface in management_interfaces for ip in ips_by_interface.get(iface.id, [])]
    ip_values += [ip_label(ip) for sub in management_subinterfaces for ip in sub_ips.get(sub.id, [])]
    ip_values += [ip_label(x) for x in resolvable_vlan_links if x.ip_address]

    return list(dict.fromkeys(port_names)), list(dict.fromkeys(ip_values))


def port_label_with_subinterfaces(port_name: str, subinterfaces: Sequence[Any], vlan_map: dict[str, Any]) -> str:
    """Подпись порта для отчёта с его подинтерфейсами внутри: `Gi0/0` (подинтерфейсов нет) либо
    `Gi0/0 (подинтерфейсы: Gi0/0.10 [VLAN 10], Gi0/0.20 [VLAN 20])`. Подинтерфейс — логический порт
    своего физического порта, поэтому отдельной строкой не выводится; VLAN в скобках связывает его
    с колонками «VLAN ID / VLAN Name». VLAN, которого нет в справочнике (осиротевшая ссылка), даёт
    подпись без номера, а не ошибку."""
    if not subinterfaces:
        return port_name
    parts = []
    for sub in subinterfaces:
        vlan = vlan_map.get(sub.vlan_id)
        parts.append(f"{sub.name} [VLAN {vlan.vlan_id}]" if vlan else sub.name)
    return f"{port_name} (подинтерфейсы: {', '.join(parts)})"


def subinterface_ip_values(subinterfaces: Sequence[Any], ips_by_subinterface: dict[str, list[Any]]) -> list[str]:
    """IP подинтерфейсов порта с подписью подинтерфейса: `Gi0/0.10: 10.0.10.1/24` — без подписи было бы
    не понять, на каком подинтерфейсе какой адрес."""
    return [f"{sub.name}: {ip_label(ip)}" for sub in subinterfaces for ip in ips_by_subinterface.get(sub.id, [])]
