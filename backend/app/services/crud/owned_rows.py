"""Синхронизация «собственных» строк владельца: открытые порты, IP-адреса, развёрнутое ПО (устройства, ВМ, интерфейсы)."""
from __future__ import annotations

from typing import Any, Callable
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from ...models import DeployedSoftware, IPAddress, ISProtocol, OpenPort, PhysicalDevice, ProtocolPortCatalog, VirtualMachine, SoftwareAsset
from ...constants import AuditAction, OwnerType
from ..serialization import enrich_open_ports, serialize
from ..integrity import integrity_error_response
from ..validation import validate_ipv4_field, validate_prefix_length_field, validate_unique_open_port_numbers
from .audit_log import audit


# Длина колонки ip_addresses.purpose (models.IPAddress): назначение общего IP группы копируется в неё.
_IP_PURPOSE_MAX_LENGTH = 255


# Длина колонки deployed_software.version (models.DeployedSoftware).
_SOFTWARE_VERSION_MAX_LENGTH = 100


def _resolve_protocol_catalog_entry(catalog_id: Any, session: Session) -> ProtocolPortCatalog:
    """Достаёт запись справочника «Протоколы и порты» по id или кидает понятную 422 — общая точка
    для _validate_open_port_catalog() ниже, чтобы формулировка ошибки не разъезжалась между
    интерфейсами устройства и generic create/update_resource('open-ports') (ВМ)."""
    entry = session.get(ProtocolPortCatalog, catalog_id) if catalog_id else None
    if not entry:
        raise HTTPException(422, 'Не выбрана существующая запись справочника «Протоколы и порты»')
    return entry


_OPEN_PORT_OWNER_LABELS = {OwnerType.VIRTUAL_MACHINE: 'Виртуальная машина', OwnerType.DEVICE_INTERFACE: 'Порт устройства', OwnerType.DEVICE_SUBINTERFACE: 'Подинтерфейс порта', OwnerType.PHYSICAL_DEVICE: 'Устройство'}


def _ensure_port_number_is_free(model: type, owner_filters: list[Any], catalog_id: Any, label: str, session: Session, current_id: str | None) -> None:
    """Общая проверка «номер порта записи справочника ещё не занят другой записью model с теми же
    owner_filters» — для открытых портов (OpenPort, владелец — ВМ/порт) и протоколов ИС (ISProtocol).
    Сверяется только эта запись с остальными (current_id исключается), а не весь список владельца."""
    port = _resolve_protocol_catalog_entry(catalog_id, session).port
    stmt = (select(model.id).join(ProtocolPortCatalog, ProtocolPortCatalog.id == model.protocol_catalog_id)
            .where(*owner_filters, ProtocolPortCatalog.port == port).limit(1))
    if current_id: stmt = stmt.where(model.id != current_id)
    if session.scalar(stmt) is not None:
        raise HTTPException(422, f'{label}: порт {port} уже добавлен — номера открытых портов не должны повторяться')


def _validate_open_port_number_is_free(data: dict[str, Any], session: Session, current_id: str | None = None) -> None:
    """Номер порта новой/изменяемой записи open-ports не должен совпадать с номером другой записи
    ТОГО ЖЕ владельца (ВМ, порт устройства). Сверяется только эта запись с остальными, а не весь
    список владельца: уже существовавшие дубли не мешают добавить корректный порт. Вызывать после
    _validate_open_port_catalog() — он гарантирует, что запись справочника существует."""
    owner_type, owner_id = data.get('owner_type'), data.get('owner_id')
    if not owner_type or not owner_id: return
    _ensure_port_number_is_free(
        OpenPort, [OpenPort.owner_type == owner_type, OpenPort.owner_id == owner_id],
        data.get('protocol_catalog_id'), _OPEN_PORT_OWNER_LABELS.get(owner_type, 'Владелец'), session, current_id,
    )


def _validate_is_protocol_number_is_free(data: dict[str, Any], session: Session, current_id: str | None = None) -> None:
    """То же правило для протоколов передачи данных ИС (is-protocols): номер порта не повторяется
    в пределах одной информационной системы — как у открытых портов ВМ и порта устройства."""
    system_id = data.get('information_system_id')
    if not system_id: return
    _ensure_port_number_is_free(
        ISProtocol, [ISProtocol.information_system_id == system_id],
        data.get('protocol_catalog_id'), 'Информационная система', session, current_id,
    )


def _validate_open_port_catalog(data: dict[str, Any], session: Session) -> None:
    """Правка "справочник — единственный источник правды для порта/протокола": OpenPort.port/
    protocol больше не колонки этой модели вовсе (см. models.OpenPort) — значения читаются join'ом
    к protocol_port_catalogs при КАЖДОМ чтении (services/serialization.py:enrich_open_port(s)), а
    не подставляются один раз при записи, как было раньше (до миграции b7f2c1e5a904). Поэтому
    здесь больше нечего мутировать в data — остаётся только убедиться, что protocol_catalog_id
    ссылается на существующую запись справочника, иначе клиент получит понятную 422 вместо
    IntegrityError на NOT NULL при flush()."""
    _resolve_protocol_catalog_entry(data.get('protocol_catalog_id'), session)


def _sync_owned_rows(model: type, owner_type: str, owner_id: str, items: Any, session: Session, *, normalize: Callable[[dict[str, Any]], dict[str, Any] | None], array_error: str, foreign_id_error: str) -> tuple[int, int, int]:
    """Общая diff-синхронизация вложенных записей с полиморфным владельцем (OpenPort, IPAddress,
    DeployedSoftware: owner_type/owner_id) по присланному списку: элемент с id обновляет существующую
    запись владельца, без id создаёт новую, записи владельца, которых в списке нет, удаляются.

    normalize(item) приводит элемент к значениям колонок (и валидирует их — бросает HTTPException 422)
    либо возвращает None для пустой строки-плейсхолдера формы, которая тихо пропускается.

    Записи не пересоздаются: id и created_at сохраняются, а изменённой считается только запись, у
    которой реально поменялось значение колонки. Транзакцию функция не коммитит — это делает
    вызывающий. Список — полное желаемое состояние, поэтому повтор запроса идемпотентен: записи,
    созданные неудавшейся попыткой и не известные форме по id, при повторе удалятся как лишние.
    Возвращает (создано, изменено, удалено)."""
    if not isinstance(items, list): raise HTTPException(422, array_error)
    old_rows = session.scalars(select(model).where(model.owner_type == owner_type, model.owner_id == owner_id)).all()
    old_map = {x.id: x for x in old_rows}; seen: set[str] = set()
    created = updated = 0
    for item in items:
        if not isinstance(item, dict): continue
        new_values = normalize(item)
        if new_values is None: continue
        row_id = item.get('id')
        if row_id:
            row = old_map.get(row_id)
            if not row: raise HTTPException(422, foreign_id_error)
            if row_id in seen: raise HTTPException(422, 'Одна и та же запись указана в списке несколько раз')
            seen.add(row_id)
            if any(getattr(row, key) != value for key, value in new_values.items()): updated += 1
        else:
            row = model(owner_type=owner_type, owner_id=owner_id); session.add(row); created += 1
        for key, value in new_values.items(): setattr(row, key, value)
    stale_rows = [row for row in old_rows if row.id not in seen]
    for stale_row in stale_rows: session.delete(stale_row)
    return created, updated, len(stale_rows)


def sync_owner_open_ports(owner_type: str, owner_id: str, open_ports: Any, session: Session, *, owner_label: str, array_error: str, foreign_id_error: str) -> tuple[int, int, int]:
    """Открытые порты владельца (ВМ или порт устройства) по присланному списку, см. _sync_owned_rows.
    Уникальность номеров проверяется по списку целиком (validate_unique_open_port_numbers), а не по
    записям в БД поочерёдно, поэтому обмен номерами между двумя строками за один запрос допустим.
    Строка без выбранной записи справочника (пустой плейсхолдер формы) пропускается."""
    if not isinstance(open_ports, list): raise HTTPException(422, array_error)
    validate_unique_open_port_numbers((p.get('protocol_catalog_id') for p in open_ports if isinstance(p, dict)), session, owner_label)

    def normalize(port_data: dict[str, Any]) -> dict[str, Any] | None:
        # Пользователь нажал "+ Открытый порт", но ещё ничего не выбрал (см. addRow() в OpenPortListEditor.vue).
        if not port_data.get('protocol_catalog_id'): return None
        _validate_open_port_catalog(port_data, session)
        return {
            'protocol_catalog_id': port_data['protocol_catalog_id'],
            'transport_protocol': port_data.get('transport_protocol') or 'TCP',
            'description': port_data.get('description') or None,
        }

    return _sync_owned_rows(OpenPort, owner_type, owner_id, open_ports, session, normalize=normalize, array_error=array_error, foreign_id_error=foreign_id_error)


def sync_owner_ip_addresses(owner_type: str, owner_id: str, ip_addresses: Any, session: Session, *, array_error: str, foreign_id_error: str) -> tuple[int, int, int]:
    """IP-адреса владельца (ВМ) по присланному списку, см. _sync_owned_rows. Те же проверки, что у
    generic create/update ресурса ip-addresses (_validate_ip_address_entry): формат IPv4 и префикс
    0-32 — плюс длина назначения (колонка ограничена _IP_PURPOSE_MAX_LENGTH). Строка без адреса
    (пустой плейсхолдер формы) пропускается."""
    def normalize(ip_data: dict[str, Any]) -> dict[str, Any] | None:
        ip_address = str(ip_data.get('ip_address') or '').strip()
        if not ip_address: return None
        validate_ipv4_field(ip_address, 'IP-адрес')
        prefix_length = ip_data.get('prefix_length')
        validate_prefix_length_field(prefix_length, 'Префикс IP-адреса')
        purpose = ip_data.get('purpose') or None
        if purpose is not None and len(str(purpose)) > _IP_PURPOSE_MAX_LENGTH:
            raise HTTPException(422, f'Назначение IP-адреса не должно превышать {_IP_PURPOSE_MAX_LENGTH} символов')
        return {
            'ip_address': ip_address,
            'prefix_length': None if prefix_length in (None, '') else int(prefix_length),
            'purpose': purpose,
            'is_management': bool(ip_data.get('is_management')),
        }

    return _sync_owned_rows(IPAddress, owner_type, owner_id, ip_addresses, session, normalize=normalize, array_error=array_error, foreign_id_error=foreign_id_error)


def sync_owner_deployed_software(owner_type: str, owner_id: str, deployed_software: Any, session: Session, *, array_error: str, foreign_id_error: str) -> tuple[int, int, int]:
    """Развёрнутое ПО владельца (ВМ) по присланному списку, см. _sync_owned_rows. Записи каталога
    программных активов проверяются одним запросом на весь список: несуществующий актив — понятный
    422, а не IntegrityError по внешнему ключу. Строка без выбранного актива (пустой плейсхолдер
    формы) пропускается."""
    if not isinstance(deployed_software, list): raise HTTPException(422, array_error)
    asset_ids = {i['software_asset_id'] for i in deployed_software if isinstance(i, dict) and i.get('software_asset_id')}
    known_ids = set(session.scalars(select(SoftwareAsset.id).where(SoftwareAsset.id.in_(asset_ids))).all()) if asset_ids else set()
    if asset_ids - known_ids: raise HTTPException(422, 'Программный актив не найден в справочнике')

    def normalize(software_data: dict[str, Any]) -> dict[str, Any] | None:
        if not software_data.get('software_asset_id'): return None
        version = software_data.get('version') or None
        if version is not None and len(str(version)) > _SOFTWARE_VERSION_MAX_LENGTH:
            raise HTTPException(422, f'Версия ПО не должна превышать {_SOFTWARE_VERSION_MAX_LENGTH} символов')
        return {'software_asset_id': software_data['software_asset_id'], 'version': version}

    return _sync_owned_rows(DeployedSoftware, owner_type, owner_id, deployed_software, session, normalize=normalize, array_error=array_error, foreign_id_error=foreign_id_error)


def _sync_owner_collection(owner_model: type, entity: str, not_found: str, owner_id: str, session: Session, *, label: str, sync: Callable[[Any], tuple[int, int, int]], load: Callable[[Any], list[dict[str, Any]]]) -> dict[str, Any]:
    """Общий каркас атомарной синхронизации одного вложенного списка владельца (ВМ или физического
    устройства: порты, IP-адреса, ПО): владелец существует (404 с текстом not_found), список
    применяется одной транзакцией (любая ошибка откатывает весь запрос), запись в журнал аудита
    (сущность entity — слаг ресурса) пишется только если что-то реально изменилось. Ответ:
    {'items': [...]} — сохранённые записи списка."""
    owner = session.get(owner_model, owner_id)
    if not owner: raise HTTPException(404, not_found)
    try:
        created, updated, removed = sync(owner)
        if created or updated or removed:
            audit(session, entity, owner.id, AuditAction.UPDATE, f'{label}: добавлено {created}, изменено {updated}, удалено {removed}')
        session.commit()
    except HTTPException:
        session.rollback(); raise
    except IntegrityError as exc:
        session.rollback(); raise integrity_error_response(entity, exc) from exc
    return {'items': load(owner)}


def _sync_vm_collection(vm_id: str, session: Session, *, label: str, sync: Callable[[VirtualMachine], tuple[int, int, int]], load: Callable[[VirtualMachine], list[dict[str, Any]]]) -> dict[str, Any]:
    """Список ВМ (порты, IP-адреса, ПО) — см. _sync_owner_collection."""
    return _sync_owner_collection(VirtualMachine, 'vms', 'Виртуальная машина не найдена', vm_id, session, label=label, sync=sync, load=load)


def sync_vm_open_ports(vm_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """PUT /api/v1/vms/{vm_id}/open-ports — атомарная синхронизация открытых портов ВМ (форма ВМ,
    VMFormModal.vue): порты с id обновляются, без id создаются, отсутствующие в списке удаляются (см.
    sync_owner_open_ports) — вместо прежнего «удалить все и создать заново» при каждом сохранении.
    Ключ open_ports обязателен: его отсутствие — 422, а не молчаливое удаление всех портов.

    Ответ: {'items': [...]} — порты ВМ по возрастанию номера порта."""
    def load(vm: VirtualMachine) -> list[dict[str, Any]]:
        rows = session.scalars(
            select(OpenPort)
            .join(ProtocolPortCatalog, OpenPort.protocol_catalog_id == ProtocolPortCatalog.id)
            .where(OpenPort.owner_type == OwnerType.VIRTUAL_MACHINE, OpenPort.owner_id == vm.id)
            .order_by(ProtocolPortCatalog.port, OpenPort.transport_protocol)
        ).all()
        return enrich_open_ports(rows, session)

    return _sync_vm_collection(
        vm_id, session, label='Открытые порты', load=load,
        sync=lambda vm: sync_owner_open_ports(
            OwnerType.VIRTUAL_MACHINE, vm.id, payload.get('open_ports'), session,
            owner_label=f'ВМ «{vm.name}»',
            array_error='Поле open_ports должно быть массивом',
            foreign_id_error='Открытый порт не принадлежит выбранной виртуальной машине',
        ),
    )


def sync_vm_ip_addresses(vm_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """PUT /api/v1/vms/{vm_id}/ip-addresses — то же для IP-адресов ВМ (ключ ip_addresses, см.
    sync_owner_ip_addresses). Ответ: {'items': [...]} — IP-адреса ВМ по возрастанию адреса."""
    def load(vm: VirtualMachine) -> list[dict[str, Any]]:
        rows = session.scalars(select(IPAddress).where(IPAddress.owner_type == OwnerType.VIRTUAL_MACHINE, IPAddress.owner_id == vm.id).order_by(IPAddress.ip_address, IPAddress.id)).all()
        return [serialize(row) for row in rows]

    return _sync_vm_collection(
        vm_id, session, label='IP-адреса', load=load,
        sync=lambda vm: sync_owner_ip_addresses(
            OwnerType.VIRTUAL_MACHINE, vm.id, payload.get('ip_addresses'), session,
            array_error='Поле ip_addresses должно быть массивом',
            foreign_id_error='IP-адрес не принадлежит выбранной виртуальной машине',
        ),
    )


def sync_vm_deployed_software(vm_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """PUT /api/v1/vms/{vm_id}/deployed-software — то же для программных активов ВМ (ключ
    deployed_software, см. sync_owner_deployed_software). Ответ: {'items': [...]} — записи ПО ВМ."""
    def load(vm: VirtualMachine) -> list[dict[str, Any]]:
        rows = session.scalars(select(DeployedSoftware).where(DeployedSoftware.owner_type == OwnerType.VIRTUAL_MACHINE, DeployedSoftware.owner_id == vm.id).order_by(DeployedSoftware.created_at, DeployedSoftware.id)).all()
        return [serialize(row) for row in rows]

    return _sync_vm_collection(
        vm_id, session, label='Программные активы', load=load,
        sync=lambda vm: sync_owner_deployed_software(
            OwnerType.VIRTUAL_MACHINE, vm.id, payload.get('deployed_software'), session,
            array_error='Поле deployed_software должно быть массивом',
            foreign_id_error='Запись о ПО не принадлежит выбранной виртуальной машине',
        ),
    )


def sync_device_deployed_software(device_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """PUT /api/v1/devices/{device_id}/deployed-software — атомарная синхронизация программных активов
    физического устройства (форма устройства, DeviceFormModal.vue) тем же способом, что и у ВМ (см.
    sync_vm_deployed_software): записи с id обновляются, без id создаются, отсутствующие в списке
    удаляются. Ключ deployed_software обязателен: его отсутствие — 422, а не молчаливое удаление всего ПО.
    Ответ: {'items': [...]} — записи ПО устройства."""
    def load(device: PhysicalDevice) -> list[dict[str, Any]]:
        rows = session.scalars(select(DeployedSoftware).where(DeployedSoftware.owner_type == OwnerType.PHYSICAL_DEVICE, DeployedSoftware.owner_id == device.id).order_by(DeployedSoftware.created_at, DeployedSoftware.id)).all()
        return [serialize(row) for row in rows]

    return _sync_owner_collection(
        PhysicalDevice, 'devices', 'Физическое устройство не найдено', device_id, session, label='Программные активы', load=load,
        sync=lambda device: sync_owner_deployed_software(
            OwnerType.PHYSICAL_DEVICE, device.id, payload.get('deployed_software'), session,
            array_error='Поле deployed_software должно быть массивом',
            foreign_id_error='Запись о ПО не принадлежит выбранному физическому устройству',
        ),
    )
