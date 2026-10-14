"""Защита ссылочной целостности для связей, у которых нет настоящего FOREIGN KEY на уровне БД.

Контекст (п.3 предложений по итогам переработки БД, миграция 944bd490d967): InformationSystemSource.
owner_id ссылается на устройство/ВМ/контейнер в зависимости от source_type, а OpenPort/
DeployedSoftware/IPAddress — на владельца в зависимости от owner_type. Одна колонка не может быть
FK сразу на несколько таблиц, поэтому раньше вся защита держалась на одном месте —
services/crud/deletion.py:delete_resource(). Любой новый путь удаления в обход него молча оставлял бы в БД
«висячие» ссылки. Здесь собраны пять уровней защиты, от прикладного к БД:

1. assert_deletable() (crud/) — единая точка проверки «можно ли удалить», её вызывает
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

import logging
from typing import Any

from fastapi import HTTPException
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..constants import ErrorCode, OwnerType, SourceType
from ..models import (
    Container, DeployedSoftware, DeviceInterface, DeviceSubinterface, DeviceTypeVLAN, IPAddress, InformationSystem,
    InformationSystemSource, InterfaceGroup, InterfaceGroupOpenPort, InterfaceGroupSubinterface, ISProtocol, OpenPort, PhysicalDevice,
    PhysicalDeviceVLAN, ProtocolPortCatalog, VLAN, VirtualMachine,
)
from ..registry import DISPLAY_NAMES
from .port_vlans import allowed_vlan_ids_by_device, effective_group_vlan_ids, effective_vlan_ids

logger = logging.getLogger(__name__)

# Имя уникального индекса слота стойки (миграция b5d2f8a1c673, models.PhysicalDevice.__table_args__).
RACK_SLOT_INDEX = "uq_device_rack_slot"


def integrity_error_response(resource: str, exc: IntegrityError) -> HTTPException:
    """409 для нарушения ограничения БД БЕЗ текста исходной ошибки.

    Раньше клиенту уходило `str(exc.orig)[:300]` — имена таблиц, колонок и ограничений (код-ревью, п. 8).
    Теперь детали пишутся только в лог сервера, а клиент получает общий код INTEGRITY_ERROR. Исключение —
    гонка за слот в стойке: два параллельных запроса прошли проверку «слот свободен», а второй упёрся в
    уникальный индекс; это ожидаемый исход, и для него есть понятный код RACK_POSITION_OCCUPIED.

    Вызывающий сам откатывает сессию; функция только строит исключение (`raise ... from exc`).
    """
    detail_text = str(exc.orig)
    logger.warning("Нарушение целостности данных в ресурсе %s: %s", resource, detail_text)
    lowered = detail_text.lower()
    if RACK_SLOT_INDEX in lowered or ("rack_position" in lowered and "unique" in lowered):
        return HTTPException(409, detail={
            "code": ErrorCode.RACK_POSITION_OCCUPIED,
            "message": "Позиция в стойке уже занята другим устройством (возможно, его только что сохранил другой пользователь). Обновите данные и повторите.",
        })
    return HTTPException(409, detail={"code": ErrorCode.INTEGRITY_ERROR, "message": "Нарушение целостности данных: операция противоречит существующим записям."})

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
    OwnerType.DEVICE_SUBINTERFACE: DeviceSubinterface,
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


# Владелец у открытых портов ГРУППЫ — не полиморфный OpenPort.owner_type, а отдельная таблица с
# настоящим FK (InterfaceGroupOpenPort.group_id); в отчёте о дублях помечается этим псевдо-типом.
INTERFACE_GROUP_OWNER = 'interface_group'
# Протоколы передачи данных ИС (ISProtocol) — открытые порты информационной системы; тоже отдельная
# таблица с настоящим FK (information_system_id), в отчёте — этот псевдо-тип.
INFORMATION_SYSTEM_OWNER = 'information_system'


def find_duplicate_open_port_numbers(session: Session) -> list[dict[str, Any]]:
    """Находит владельцев (ВМ, порты устройств, группы портов, информационные системы), у которых один и тот же НОМЕР порта
    добавлен несколько раз — дубликаты, появившиеся до правила уникальности (см. services/
    validation.py:validate_unique_open_port_numbers). Каждый такой владелец и номер — одна запись:
    {'owner_type', 'owner_id', 'owner_name', 'port', 'count'}; owner_name — None, если владельца уже нет.

    Только чтение, ничего не исправляет. Пустой список — повторов нет (можно не опасаться, что
    сохранение формы упрётся в 422 из-за старых данных). Запросов по числу ТИПОВ владельцев (не строк).
    """
    port_count = func.count(OpenPort.id)
    owned = session.execute(
        select(OpenPort.owner_type, OpenPort.owner_id, ProtocolPortCatalog.port, port_count.label('n'))
        .join(ProtocolPortCatalog, ProtocolPortCatalog.id == OpenPort.protocol_catalog_id)
        .group_by(OpenPort.owner_type, OpenPort.owner_id, ProtocolPortCatalog.port)
        .having(port_count > 1)
    ).all()
    group_count = func.count(InterfaceGroupOpenPort.id)
    grouped = session.execute(
        select(InterfaceGroupOpenPort.group_id, ProtocolPortCatalog.port, group_count.label('n'))
        .join(ProtocolPortCatalog, ProtocolPortCatalog.id == InterfaceGroupOpenPort.protocol_catalog_id)
        .group_by(InterfaceGroupOpenPort.group_id, ProtocolPortCatalog.port)
        .having(group_count > 1)
    ).all()

    protocol_count = func.count(ISProtocol.id)
    protocols = session.execute(
        select(ISProtocol.information_system_id, ProtocolPortCatalog.port, protocol_count.label('n'))
        .join(ProtocolPortCatalog, ProtocolPortCatalog.id == ISProtocol.protocol_catalog_id)
        .group_by(ISProtocol.information_system_id, ProtocolPortCatalog.port)
        .having(protocol_count > 1)
    ).all()

    found = (
        [(r.owner_type, r.owner_id, r.port, r.n) for r in owned]
        + [(INTERFACE_GROUP_OWNER, r.group_id, r.port, r.n) for r in grouped]
        + [(INFORMATION_SYSTEM_OWNER, r.information_system_id, r.port, r.n) for r in protocols]
    )
    names = _owner_names(session, {(t, i) for t, i, _, _ in found})
    result = [
        {'owner_type': t, 'owner_id': i, 'owner_name': names.get((t, i)), 'port': port, 'count': n}
        for t, i, port, n in found
    ]
    return sorted(result, key=lambda d: (d['owner_type'], d['owner_name'] or '', d['port']))


def find_stale_subinterfaces(session: Session, vlan_id: str | None = None) -> list[dict[str, Any]]:
    """Находит подинтерфейсы на VLAN, который их устройству больше не разрешён: VLAN не назначен устройству
    (PhysicalDeviceVLAN) и не разрешён его типом (DeviceTypeVLAN) — ровно тот набор допустимых VLAN, по которому
    sync_interfaces проверяет подинтерфейсы при сохранении. Каждая запись — один подинтерфейс:
    {'subinterface_id', 'subinterface_name', 'port_id', 'port_name', 'device_id', 'device_name', 'vlan_id',
    'vlan_number', 'vlan_name'}; vlan_id — id записи справочника VLAN, vlan_number — номер VLAN (802.1Q).

    Такие подинтерфейсы возникают, когда VLAN снимают с устройства, убирают из его типа или переносят в другой
    домен: подинтерфейс — самостоятельная запись со своими IP и открытыми портами, поэтому система не удаляет его
    молча (в отличие от связей VLAN с портами и группами), а следующее сохранение формы устройства требует выбрать
    другой VLAN или удалить подинтерфейс. Эта диагностика показывает все такие случаи по реестру сразу.

    vlan_id — ограничить поиск одним VLAN (так перечень для журнала аудита при переносе VLAN в другой домен
    строится тем же кодом, что и общий отчёт). Только чтение. Запросов — константа, не зависит от числа строк.
    Порядок: устройство, порт, подинтерфейс."""
    query = (
        select(
            DeviceSubinterface.id.label('subinterface_id'), DeviceSubinterface.name.label('subinterface_name'),
            DeviceSubinterface.vlan_id, DeviceInterface.id.label('port_id'), DeviceInterface.name.label('port_name'),
            PhysicalDevice.id.label('device_id'), PhysicalDevice.device_type_id, PhysicalDevice.system_name, PhysicalDevice.serial_number,
            VLAN.vlan_id.label('vlan_number'), VLAN.name.label('vlan_name'),
        )
        .join(DeviceInterface, DeviceInterface.id == DeviceSubinterface.parent_interface_id)
        .join(PhysicalDevice, PhysicalDevice.id == DeviceInterface.physical_device_id)
        .join(VLAN, VLAN.id == DeviceSubinterface.vlan_id)
    )
    if vlan_id is not None:
        query = query.where(DeviceSubinterface.vlan_id == vlan_id)
    rows = session.execute(query).all()
    if not rows:
        return []

    # Допустимые пары считаем только по VLAN, на которых реально есть подинтерфейсы (подзапрос, а не список id:
    # так не упереться в предел числа параметров SQL при большом реестре).
    used_vlans = select(DeviceSubinterface.vlan_id)
    if vlan_id is not None:
        used_vlans = used_vlans.where(DeviceSubinterface.vlan_id == vlan_id)
    assigned = {(r.physical_device_id, r.vlan_id) for r in session.execute(
        select(PhysicalDeviceVLAN.physical_device_id, PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.vlan_id.in_(used_vlans)))}
    by_type = {(r.device_type_id, r.vlan_id) for r in session.execute(
        select(DeviceTypeVLAN.device_type_id, DeviceTypeVLAN.vlan_id).where(DeviceTypeVLAN.vlan_id.in_(used_vlans)))}

    stale = [
        {
            'subinterface_id': r.subinterface_id, 'subinterface_name': r.subinterface_name,
            'port_id': r.port_id, 'port_name': r.port_name,
            'device_id': r.device_id, 'device_name': r.system_name or r.serial_number or r.device_id,
            'vlan_id': r.vlan_id, 'vlan_number': r.vlan_number, 'vlan_name': r.vlan_name,
        }
        for r in rows
        if (r.device_id, r.vlan_id) not in assigned and (r.device_type_id, r.vlan_id) not in by_type
    ]
    return sorted(stale, key=lambda d: (d['device_name'], d['port_name'], d['subinterface_name']))


def find_off_port_subinterfaces(session: Session) -> list[dict[str, Any]]:
    """Находит подинтерфейсы на VLAN, который разрешён устройству, но НЕ выбран на их порту: VLAN подинтерфейса обязан быть
    одним из VLAN порта (у порта с «Все VLAN» — любым VLAN устройства), и sync_interfaces проверяет это при сохранении
    (crud/subinterfaces.py:validate_device_subinterfaces). Такие подинтерфейсы остаются от времени до этого правила либо
    после правки VLAN порта отдельным действием (окно порта, согласование портов, каскад режима): подинтерфейс — самостоятельная
    запись со своими IP и открытыми портами, система не удаляет его молча, а следующее сохранение формы устройства требует
    выбрать другой VLAN подинтерфейса, вернуть VLAN порту или удалить подинтерфейс.

    Подинтерфейсы на VLAN, которого нет и у самого устройства, сюда не входят — их показывает find_stale_subinterfaces (не
    дублируем одно и то же в двух списках). Запись — как в find_stale_subinterfaces. Только чтение; запросов — константа от
    числа порций. Порядок: устройство, порт, подинтерфейс."""
    rows = session.execute(
        select(
            DeviceSubinterface.id.label('subinterface_id'), DeviceSubinterface.name.label('subinterface_name'),
            DeviceSubinterface.vlan_id, DeviceInterface.id.label('port_id'), DeviceInterface.name.label('port_name'),
            PhysicalDevice.id.label('device_id'), PhysicalDevice.system_name, PhysicalDevice.serial_number,
            VLAN.vlan_id.label('vlan_number'), VLAN.name.label('vlan_name'),
        )
        .join(DeviceInterface, DeviceInterface.id == DeviceSubinterface.parent_interface_id)
        .join(PhysicalDevice, PhysicalDevice.id == DeviceInterface.physical_device_id)
        .join(VLAN, VLAN.id == DeviceSubinterface.vlan_id)
    ).all()
    if not rows:
        return []
    allowed = allowed_vlan_ids_by_device({r.device_id for r in rows}, session)
    on_port = effective_vlan_ids(session, [r.port_id for r in rows])
    found = [
        {
            'subinterface_id': r.subinterface_id, 'subinterface_name': r.subinterface_name,
            'port_id': r.port_id, 'port_name': r.port_name,
            'device_id': r.device_id, 'device_name': r.system_name or r.serial_number or r.device_id,
            'vlan_id': r.vlan_id, 'vlan_number': r.vlan_number, 'vlan_name': r.vlan_name,
        }
        for r in rows
        if r.vlan_id in allowed.get(r.device_id, set()) and r.vlan_id not in on_port.get(r.port_id, set())
    ]
    return sorted(found, key=lambda d: (d['device_name'], d['port_name'], d['subinterface_name']))


def find_stale_group_subinterfaces(session: Session, vlan_id: str | None = None) -> list[dict[str, Any]]:
    """Находит подинтерфейсы ГРУПП портов (шаблоны, models.InterfaceGroupSubinterface) на VLAN, которого у группы больше нет:
    VLAN не входит в VLAN группы (у группы с «Все VLAN» — в VLAN её устройства). Шаблон обязан лежать на VLAN группы — это
    проверяет сохранение группы (crud/interface_group_subinterfaces.py:normalize_group_subinterfaces).

    Такие шаблоны возникают, когда VLAN снимают с устройства, убирают из его типа или переносят в другой домен: связи VLAN с
    группой при этом снимаются сами, а шаблон — запись со своими IP и открытыми портами — остаётся. Система его не удаляет
    молча; следующее сохранение формы устройства требует выбрать другой VLAN шаблона, вернуть VLAN группе или удалить шаблон.
    Каждая запись — один шаблон: {'subinterface_id', 'group_id', 'group_name', 'device_id', 'device_name', 'vlan_id',
    'vlan_number', 'vlan_name'}. vlan_id — ограничить поиск одним VLAN (перечень для журнала аудита при переносе VLAN в
    другой домен). Только чтение. Порядок: устройство, группа, номер VLAN."""
    query = (
        select(
            InterfaceGroupSubinterface.id.label('subinterface_id'), InterfaceGroupSubinterface.vlan_id,
            InterfaceGroup.id.label('group_id'), InterfaceGroup.name.label('group_name'),
            PhysicalDevice.id.label('device_id'), PhysicalDevice.system_name, PhysicalDevice.serial_number,
            VLAN.vlan_id.label('vlan_number'), VLAN.name.label('vlan_name'),
        )
        .join(InterfaceGroup, InterfaceGroup.id == InterfaceGroupSubinterface.group_id)
        .join(PhysicalDevice, PhysicalDevice.id == InterfaceGroup.physical_device_id)
        .join(VLAN, VLAN.id == InterfaceGroupSubinterface.vlan_id)
    )
    if vlan_id is not None:
        query = query.where(InterfaceGroupSubinterface.vlan_id == vlan_id)
    rows = session.execute(query).all()
    if not rows:
        return []
    group_ids = {r.group_id for r in rows}
    groups = session.scalars(select(InterfaceGroup).where(InterfaceGroup.id.in_(group_ids))).all() if len(group_ids) < 400 else session.scalars(select(InterfaceGroup)).all()
    on_group = effective_group_vlan_ids(groups, session)
    stale = [
        {
            'subinterface_id': r.subinterface_id, 'group_id': r.group_id, 'group_name': r.group_name,
            'device_id': r.device_id, 'device_name': r.system_name or r.serial_number or r.device_id,
            'vlan_id': r.vlan_id, 'vlan_number': r.vlan_number, 'vlan_name': r.vlan_name,
        }
        for r in rows
        if r.vlan_id not in on_group.get(r.group_id, set())
    ]
    return sorted(stale, key=lambda d: (d['device_name'], d['group_name'], d['vlan_number']))


def _owner_names(session: Session, owners: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """Читаемые имена владельцев для отчёта о дублях — по одному запросу на тип владельца."""
    ids_by_type: dict[str, set[str]] = {}
    for owner_type, owner_id in owners:
        ids_by_type.setdefault(owner_type, set()).add(owner_id)

    def device_label(device: PhysicalDevice) -> str:
        return device.system_name or device.serial_number or device.id

    names: dict[tuple[str, str], str] = {}
    for owner_type, ids in ids_by_type.items():
        if owner_type == OwnerType.VIRTUAL_MACHINE:
            names.update({(owner_type, r.id): r.name for r in session.execute(select(VirtualMachine.id, VirtualMachine.name).where(VirtualMachine.id.in_(ids)))})
        elif owner_type == INTERFACE_GROUP_OWNER:
            names.update({(owner_type, r.id): r.name for r in session.execute(select(InterfaceGroup.id, InterfaceGroup.name).where(InterfaceGroup.id.in_(ids)))})
        elif owner_type == INFORMATION_SYSTEM_OWNER:
            names.update({(owner_type, r.id): r.name for r in session.execute(select(InformationSystem.id, InformationSystem.name).where(InformationSystem.id.in_(ids)))})
        elif owner_type == OwnerType.PHYSICAL_DEVICE:
            names.update({(owner_type, d.id): device_label(d) for d in session.scalars(select(PhysicalDevice).where(PhysicalDevice.id.in_(ids)))})
        elif owner_type == OwnerType.DEVICE_INTERFACE:
            interfaces = session.scalars(select(DeviceInterface).where(DeviceInterface.id.in_(ids))).all()
            devices = {d.id: d for d in session.scalars(select(PhysicalDevice).where(PhysicalDevice.id.in_({i.physical_device_id for i in interfaces})))}
            for iface in interfaces:
                device = devices.get(iface.physical_device_id)
                names[(owner_type, iface.id)] = f'{device_label(device)} / {iface.name}' if device else iface.name
        elif owner_type == OwnerType.DEVICE_SUBINTERFACE:
            subinterfaces = session.scalars(select(DeviceSubinterface).where(DeviceSubinterface.id.in_(ids))).all()
            parents = {i.id: i for i in session.scalars(select(DeviceInterface).where(DeviceInterface.id.in_({s.parent_interface_id for s in subinterfaces})))}
            devices = {d.id: d for d in session.scalars(select(PhysicalDevice).where(PhysicalDevice.id.in_({p.physical_device_id for p in parents.values()})))}
            for sub in subinterfaces:
                parent = parents.get(sub.parent_interface_id)
                device = devices.get(parent.physical_device_id) if parent else None
                names[(owner_type, sub.id)] = f'{device_label(device)} / {sub.name}' if device else sub.name
    return names
