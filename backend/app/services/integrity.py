"""Защита ссылочной целостности для связей, у которых нет настоящего FOREIGN KEY на уровне БД.

Контекст (п.3 предложений по итогам переработки БД, миграция 944bd490d967): InformationSystemSource.
owner_id ссылается на устройство/ВМ/контейнер в зависимости от source_type, а OpenPort/
DeployedSoftware/IPAddress — на владельца в зависимости от owner_type. Одна колонка не может быть
FK сразу на несколько таблиц, поэтому раньше вся защита держалась на одном месте —
services/crud.py:delete_resource(). Любой новый путь удаления в обход него молча оставлял бы в БД
«висячие» ссылки. Здесь собраны пять уровней защиты, от прикладного к БД:

1. assert_deletable() (crud.py) — единая точка проверки «можно ли удалить», её вызывает
   delete_resource(); любой новый путь удаления должен звать её же.
2. before_delete на PhysicalDevice/VirtualMachine/Container (register_delete_guards ниже) —
   срабатывает на любое ORM-удаление, даже в обход delete_resource().
3. Триггеры БД (миграция 5b1e7c94a2d8) — последний рубеж: срабатывают и на прямой SQL.
4. find_orphaned_owner_references() — диагностика: находит уже существующие «висячие» ссылки
   (GET /api/v1/integrity и тест целостности).
5. tests/test_deletion_guards.py — статическая проверка исходников: новый путь прямого удаления
   в app/ без явного разрешения роняет тест.

Ограничения (осознанные):
- before_delete не видит массовое Core-удаление (delete(PhysicalDevice)...) — его ловит только
  триггер БД и статический тест из п.5.
- Если в одной транзакции удаляются и источник ИС, и его владелец, источник нужно удалить и
  сделать flush() РАНЬШЕ владельца — порядок DELETE между не связанными через relationship()
  таблицами SQLAlchemy не гарантирует, а проверка (и ORM, и триггер) смотрит на состояние БД в
  момент удаления владельца.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from ..constants import ErrorCode, OwnerType, SourceType
from ..models import (
    Container, DeployedSoftware, DeviceInterface, IPAddress, InformationSystemSource, OpenPort,
    PhysicalDevice, VirtualMachine,
)
from ..registry import DISPLAY_NAMES

# resource_key (см. registry.MODEL_MAP) → значение InformationSystemSource.source_type, которое
# соответствует этому типу владельца (source_type играет роль owner_type).
SOURCE_TYPE_BY_RESOURCE: dict[str, str] = {
    'devices': SourceType.DEVICE, 'vms': SourceType.VM, 'containers': SourceType.CONTAINER,
}
SOURCE_TYPE_BY_MODEL: dict[type, str] = {
    PhysicalDevice: SourceType.DEVICE, VirtualMachine: SourceType.VM, Container: SourceType.CONTAINER,
}


class ReferencedRecordError(Exception):
    """Запись нельзя удалить: на неё ссылаются другие данные. Поднимается защитой уровня ORM
    (before_delete) — в HTTP-слое превращается в 409 (см. обработчик в main.py), в тех же
    коде и формулировке, что и HTTPException из delete_resource()."""

    code = ErrorCode.REFERENCED_BY_OTHER_RECORDS

    def __init__(self, refs: list[tuple[str, int]]):
        self.refs = refs
        super().__init__(format_referenced_message(refs))


def format_referenced_message(refs: list[tuple[str, int]]) -> str:
    """Единая формулировка 409 «запись используется в других данных» — для generic FK-ссылок,
    для owner_id-ссылок источников ИС и для ORM-защиты (чтобы текст не разъезжался)."""
    details = ', '.join(f'{name}: {count}' for name, count in refs)
    return f'Нельзя удалить: запись используется в других данных ({details}).'


def count_source_references(bind: Any, source_type: str, owner_id: str) -> int:
    """Сколько строк information_system_sources ссылаются на владельца. bind — Session или
    Connection (у обоих есть .scalar), поэтому одна функция обслуживает и прикладную проверку,
    и before_delete, которому доступно только соединение."""
    return bind.scalar(
        select(func.count()).select_from(InformationSystemSource)
        .where(InformationSystemSource.source_type == source_type, InformationSystemSource.owner_id == owner_id)
    ) or 0


def source_reference_refs(resource: str, item_id: str, bind: Any) -> list[tuple[str, int]]:
    """refs в формате (название, количество), как у crud._find_referencing_counts(); пусто, если
    resource не может быть владельцем источника ИС или ссылок нет."""
    source_type = SOURCE_TYPE_BY_RESOURCE.get(resource)
    if source_type is None:
        return []
    count = count_source_references(bind, source_type, item_id)
    return [(DISPLAY_NAMES['is-sources'], count)] if count else []


def _guard_before_delete(mapper, connection, target) -> None:
    source_type = SOURCE_TYPE_BY_MODEL.get(type(target))
    if source_type is None:
        return
    count = count_source_references(connection, source_type, target.id)
    if count:
        raise ReferencedRecordError([(DISPLAY_NAMES['is-sources'], count)])


def register_delete_guards() -> None:
    """Вешает before_delete на модели, на которые может ссылаться InformationSystemSource.
    Идемпотентна: повторный вызов (например, при повторном импорте модуля в тестах) не дублирует
    слушателя."""
    for model in SOURCE_TYPE_BY_MODEL:
        if not event.contains(model, 'before_delete', _guard_before_delete):
            event.listen(model, 'before_delete', _guard_before_delete)


register_delete_guards()


# --- Диагностика: уже существующие «висячие» ссылки -------------------------------------------

# owner_type → модель-владелец для OpenPort/DeployedSoftware/IPAddress.
_OWNER_MODEL_BY_TYPE: dict[str, type] = {
    OwnerType.PHYSICAL_DEVICE: PhysicalDevice,
    OwnerType.VIRTUAL_MACHINE: VirtualMachine,
    OwnerType.DEVICE_INTERFACE: DeviceInterface,
    OwnerType.INFORMATION_SYSTEM_SOURCE: InformationSystemSource,
}
_POLYMORPHIC_CHILD_MODELS: tuple[type, ...] = (OpenPort, DeployedSoftware, IPAddress)


def find_orphaned_owner_references(session: Session) -> list[dict[str, Any]]:
    """Находит записи, у которых owner_id указывает на несуществующего владельца, по ВСЕМ
    четырём моделям без настоящего FK: OpenPort, DeployedSoftware, IPAddress (owner_type/
    owner_id) и InformationSystemSource (source_type/owner_id). Записи с неизвестным
    owner_type тоже попадают в результат (reason='unknown_owner_type'): значение, которого нет
    в OwnerType, — тот же класс дефекта.

    Только чтение, ничего не исправляет. Пустой список — целостность в порядке."""
    orphans: list[dict[str, Any]] = []

    for child in _POLYMORPHIC_CHILD_MODELS:
        for owner_type, owner_model in _OWNER_MODEL_BY_TYPE.items():
            rows = session.execute(
                select(child.id, child.owner_id)
                .where(child.owner_type == owner_type, ~child.owner_id.in_(select(owner_model.id)))
            ).all()
            orphans.extend(
                {'table': child.__tablename__, 'id': r.id, 'owner_type': owner_type, 'owner_id': r.owner_id, 'reason': 'owner_missing'}
                for r in rows
            )
        rows = session.execute(
            select(child.id, child.owner_type, child.owner_id).where(child.owner_type.not_in(list(_OWNER_MODEL_BY_TYPE)))
        ).all()
        orphans.extend(
            {'table': child.__tablename__, 'id': r.id, 'owner_type': r.owner_type, 'owner_id': r.owner_id, 'reason': 'unknown_owner_type'}
            for r in rows
        )

    for owner_model, source_type in SOURCE_TYPE_BY_MODEL.items():
        rows = session.execute(
            select(InformationSystemSource.id, InformationSystemSource.owner_id)
            .where(
                InformationSystemSource.source_type == source_type,
                InformationSystemSource.owner_id.is_not(None),
                ~InformationSystemSource.owner_id.in_(select(owner_model.id)),
            )
        ).all()
        orphans.extend(
            {'table': InformationSystemSource.__tablename__, 'id': r.id, 'owner_type': source_type, 'owner_id': r.owner_id, 'reason': 'owner_missing'}
            for r in rows
        )
    return orphans
