"""Общие вспомогательные функции правил: пустые значения, пачки идентификаторов, подписи устройств и стеки."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator
from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import DeviceStackMember, PhysicalDevice
from ..device_label import device_label

T = TypeVar("T")

# Пачка значений в `IN (...)`: SQLite ограничивает число параметров запроса, поэтому длинные списки идентификаторов режем.
CHUNK_SIZE = 500


def is_blank(value: Any) -> bool:
    """Пусто ли значение: None, пустая строка или строка из одних пробелов. Число 0 пустым не считается."""
    return value is None or (isinstance(value, str) and not value.strip())


def chunked(items: Collection[T] | Iterable[T], size: int = CHUNK_SIZE) -> Iterator[list[T]]:
    batch: list[T] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def join_names(names: Iterable[str]) -> str:
    """Имена через запятую без повторов, в алфавитном порядке (результат не зависит от порядка строк в БД)."""
    return ", ".join(sorted(set(names), key=str.casefold))


def device_labels(session: Session, device_ids: Collection[str]) -> dict[str, str]:
    """id устройства → подпись (системное имя, а без него серийный номер) для заданных устройств."""
    labels: dict[str, str] = {}
    for batch in chunked(device_ids):
        for row in session.execute(
            select(PhysicalDevice.id, PhysicalDevice.system_name, PhysicalDevice.serial_number).where(PhysicalDevice.id.in_(batch))
        ):
            labels[row.id] = device_label(row, fallback=row.id)
    return labels


def stack_by_device(session: Session) -> dict[str, str]:
    """id устройства → id его стека. Устройства одного стека — единый логический узел (общие адреса и имя допустимы)."""
    return {
        row.physical_device_id: row.stack_id
        for row in session.execute(select(DeviceStackMember.physical_device_id, DeviceStackMember.stack_id))
    }
