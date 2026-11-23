"""Крупный синтетический реестр для замера скорости формирования отчёта (A-19): N устройств по M портов, подключения между соседями.

Используется tests/test_report_layout_performance.py. Данные детерминированы (читаемые id, фиксированное время), чтобы файл отчёта
был воспроизводим и «до» и «после» оптимизации можно было сравнить поячеечно."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    Building,
    Connection,
    ConnectionType,
    DeviceCategory,
    DeviceInterface,
    DeviceType,
    InterfaceType,
    Manufacturer,
    PhysicalDevice,
)

T0 = datetime(2026, 1, 1, 12, 0, 0)


def seed_large_registry(session: Session, devices: int, ports_per_device: int, connections: int) -> None:
    session.add_all(
        [
            DeviceCategory(id="cat1", name="Сетевое оборудование"),
            Manufacturer(id="m1", name="Cisco"),
            InterfaceType(id="it1", name="GigabitEthernet"),
            ConnectionType(id="ct1", name="Витая пара"),
            Building(id="b1", name="Корпус 1", address="ул. Первая, 1"),
        ]
    )
    session.flush()
    session.add(DeviceType(id="dt-sw", name="Коммутатор", category_id="cat1"))
    session.flush()
    session.add_all(
        [
            PhysicalDevice(
                id=f"dev{index:04d}",
                device_type_id="dt-sw",
                serial_number=f"SN-{index:05d}",
                system_name=f"SW-{index:04d}",
                building_id="b1",
                manufacturer_id="m1",
            )
            for index in range(devices)
        ]
    )
    session.flush()
    session.add_all(
        [
            DeviceInterface(
                id=f"p{index:04d}-{port:02d}",
                physical_device_id=f"dev{index:04d}",
                name=f"Gi1/0/{port + 1}",
                is_data_transfer=True,
                vlan_mode="trunk",
                interface_type_id="it1",
            )
            for index in range(devices)
            for port in range(ports_per_device)
        ]
    )
    session.flush()
    session.add_all(
        [
            Connection(
                id=f"c{index:04d}",
                source_interface_id=f"p{index:04d}-00",
                destination_interface_id=f"p{(index + 1) % devices:04d}-01",
                connection_type_id="ct1",
                created_at=T0 + timedelta(minutes=index),
            )
            for index in range(connections)
        ]
    )
    session.commit()
