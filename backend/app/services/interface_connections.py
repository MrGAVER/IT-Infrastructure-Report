"""Подключения портов, заданные в форме устройства (блок «Порты / интерфейсы»).

Форма устройства сохраняет порты одним атомарным PUT /devices/{id}/interfaces
(services/crud.py:sync_interfaces). У нового порта до этого запроса нет id, а подключение ссылается
именно на id интерфейса, поэтому клиент не может создать подключение отдельным запросом, не
сопоставляя только что созданные порты с черновыми строками формы (имя порта в пределах устройства
не уникально). Подключения создаются здесь же, на сервере: в payload порта необязательный ключ
``connection`` —

* ключа нет — подключения порта не трогаются (старые клиенты API, окно «Управлять портами»);
* ``null`` — порт отключается: его активное подключение удаляется;
* ``{"peer_interface_id", "connection_type_id", "description"}`` — порт подключён к указанному порту
  другого (или этого же, но уже сохранённого) устройства: подключение создаётся, а если у порта уже
  есть активное подключение — обновляется на месте (тип линии, описание, соседний порт).

Подключения обрабатываются ПОСЛЕ записи всех портов (у новых портов уже есть id) и в той же
транзакции: любая ошибка — например, занятый соседний порт (409) — откатывает и порты, и подключения.
Правила допустимости пары портов — те же, что у обычного создания подключения
(services/validation.py:validate_connection). Сверку конфигураций портов (роль, режим, VLAN) эта
операция не блокирует: расхождение, как и при создании подключения другим способом, отображается
в дашборде «Подключения» со статусом «расхождение» до одобрения.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..models import AuditLog, Connection, ConnectionType, DeviceInterface
from .validation import validate_connection

_AUDIT_ENTITY = 'connections'


@dataclass(frozen=True)
class ConnectionSpec:
    """Разобранный и провалидированный по форме элемент payload['interfaces'][i]['connection']."""
    peer_interface_id: str
    connection_type_id: str
    description: str | None


def parse_connection_spec(raw: Any) -> ConnectionSpec | None:
    """Приводит значение ключа ``connection`` к ConnectionSpec; ``None`` — «отключить порт».

    Проверяет только форму данных; существование порта/типа линии и занятость портов проверяет
    sync_interface_connections() — для этого нужна БД.

    >>> parse_connection_spec(None) is None
    True
    >>> parse_connection_spec({'peer_interface_id': 'p1', 'connection_type_id': 't1'}).description is None
    True
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise HTTPException(422, 'Поле connection интерфейса должно быть объектом или null')
    peer_id = raw.get('peer_interface_id')
    if not isinstance(peer_id, str) or not peer_id.strip():
        raise HTTPException(422, 'Для подключения порта выберите соседнее устройство и его порт')
    type_id = raw.get('connection_type_id')
    if not isinstance(type_id, str) or not type_id.strip():
        raise HTTPException(422, 'Для подключения порта выберите тип физической линии связи')
    description = raw.get('description')
    if description is not None and not isinstance(description, str):
        raise HTTPException(422, 'Описание подключения должно быть строкой')
    return ConnectionSpec(peer_id.strip(), type_id.strip(), (description or '').strip() or None)


def connections_of(interface_ids: Sequence[str], session: Session, *, active_only: bool = True) -> list[Connection]:
    """Подключения, в которых участвует хотя бы один из портов, в стабильном порядке.
    ``is_active IS NOT FALSE`` — как в validate_connection: NULL трактуется как «активно»."""
    if not interface_ids:
        return []
    stmt = select(Connection).where(or_(Connection.source_interface_id.in_(interface_ids), Connection.destination_interface_id.in_(interface_ids)))
    if active_only:
        stmt = stmt.where(Connection.is_active.is_not(False))
    return list(session.scalars(stmt.order_by(Connection.created_at, Connection.id)).all())


def _audit(session: Session, entity_id: str, action: str, details: str) -> None:
    session.add(AuditLog(entity_type=_AUDIT_ENTITY, entity_id=entity_id, action=action, details=details))


def sync_interface_connections(requests: Sequence[tuple[DeviceInterface, Any]], session: Session) -> int:
    """Применяет подключения портов из payload формы устройства и возвращает число созданных,
    изменённых и удалённых подключений. Транзакцией (commit/rollback) управляет вызывающая сторона.

    requests — пары (порт, сырое значение ключа connection); порты уже записаны и сброшены в БД
    (flush), поэтому у каждого есть id.

    Пример: sync_interface_connections([(iface, {'peer_interface_id': peer.id, 'connection_type_id': ct.id})], session)
    """
    # Сначала разбираем весь payload (ошибка формы — до любых изменений), затем отключаем порты и
    # только потом подключаем: порт соседа, освобождаемый в этом же запросе, можно занять независимо
    # от порядка строк.
    parsed = [(iface, parse_connection_spec(raw)) for iface, raw in requests]
    changed = 0
    for iface, spec in parsed:
        if spec is not None:
            continue
        active = connections_of([iface.id], session)
        for conn in active:
            session.delete(conn)
            _audit(session, conn.id, AuditAction.DELETE, 'Удаление записи (порт отключён в форме устройства)')
        session.flush()
        changed += len(active)
    for iface, spec in parsed:
        if spec is not None:
            changed += _apply_spec(iface, spec, connections_of([iface.id], session), session)
    return changed


def _apply_spec(iface: DeviceInterface, spec: ConnectionSpec, active: list[Connection], session: Session) -> int:
    if session.get(ConnectionType, spec.connection_type_id) is None:
        raise HTTPException(422, 'Выбранный тип физической линии связи не найден')
    peer = session.get(DeviceInterface, spec.peer_interface_id)
    if peer is None:
        raise HTTPException(422, 'Выбранный порт для подключения не найден')
    if peer.id == iface.id:
        raise HTTPException(422, 'Порт нельзя подключить к самому себе')

    # Подключение к тому же порту — обновляем на месте. Иначе берём первое активное подключение этого
    # порта и переключаем его на новый соседний порт. Если у порта по историческим причинам несколько
    # активных подключений, остальные не трогаем: validate_connection ниже ответит 409, а не удалит
    # данные молча.
    same = next((c for c in active if {c.source_interface_id, c.destination_interface_id} == {iface.id, peer.id}), None)
    target = same or (active[0] if active else None)

    if target is None:
        data = {'source_interface_id': iface.id, 'destination_interface_id': peer.id, 'connection_type_id': spec.connection_type_id, 'is_active': True, 'description': spec.description}
        validate_connection(data, session)
        created = Connection(**data)
        session.add(created)
        session.flush()
        _audit(session, created.id, AuditAction.CREATE, 'Создание записи (из формы устройства)')
        return 1

    # Направление (источник/назначение) существующего подключения не переворачиваем: порт остаётся
    # на той стороне, на которой стоял, меняется только соседний.
    source_id, destination_id = (iface.id, peer.id) if target.source_interface_id == iface.id else (peer.id, iface.id)
    candidate = {'source_interface_id': source_id, 'destination_interface_id': destination_id, 'connection_type_id': spec.connection_type_id, 'is_active': True, 'description': spec.description}
    validate_connection(candidate, session, current_connection_id=target.id)

    changes: list[str] = []
    if (source_id, destination_id) != (target.source_interface_id, target.destination_interface_id):
        changes.append('соседний порт')
    if target.connection_type_id != spec.connection_type_id:
        changes.append('тип линии связи')
    if (target.description or None) != spec.description:
        changes.append('описание')
    if not changes:
        return 0

    if 'соседний порт' in changes:
        target.source_interface_id, target.destination_interface_id = source_id, destination_id
        # Одобрение расхождения относится к конкретной паре портов — новому соседу нужна своя проверка.
        target.port_config_approved_signature = None
    target.connection_type_id = spec.connection_type_id
    target.description = spec.description
    session.flush()
    _audit(session, target.id, AuditAction.UPDATE, 'Изменение записи из формы устройства: ' + ', '.join(changes))
    return 1


def assert_interfaces_not_connected(interfaces: Sequence[DeviceInterface], session: Session) -> None:
    """Бросает 409 с понятным текстом, если у удаляемых портов есть подключения (в том числе
    неактивные — внешний ключ срабатывает на любые).

    Без этой проверки удаление упиралось бы в внешний ключ connections → device_interfaces и
    пользователь видел бы «Нарушение целостности данных: FOREIGN KEY constraint failed». Подключения
    молча не удаляются: порт сначала отключают (кнопка «Отключить» в блоке «Подключение» порта).
    """
    if not interfaces:
        return
    by_id = {i.id: i for i in interfaces}
    connected = {iid for c in connections_of(list(by_id), session, active_only=False) for iid in (c.source_interface_id, c.destination_interface_id) if iid in by_id}
    if connected:
        names = ', '.join(f'«{by_id[i].name}»' for i in sorted(connected, key=lambda x: by_id[x].name))
        raise HTTPException(409, f'Нельзя удалить порт, у которого есть подключение: {names}. Сначала отключите порт (блок «Подключение» в строке порта) и сохраните устройство, либо удалите подключение на экране «Подключения».')
