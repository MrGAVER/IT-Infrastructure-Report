"""Подключения портов, заданные в форме устройства (блок «Порты / интерфейсы»).

Форма устройства сохраняет порты одним атомарным PUT /devices/{id}/interfaces
(services/crud/interfaces.py:sync_interfaces). У нового порта до этого запроса нет id, а подключение ссылается
именно на id интерфейса, поэтому клиент не может создать подключение отдельным запросом, не
сопоставляя только что созданные порты с черновыми строками формы (имя порта в пределах устройства
не уникально). Подключения создаются здесь же, на сервере: в payload порта необязательный ключ
``connection`` —

* ключа нет — подключения порта не трогаются (старые клиенты API, окно «Управлять портами»);
* ``null`` — порт отключается: его активное подключение удаляется;
* ``{"peer_interface_id", "connection_type_id", "description"}`` — порт подключён к указанному порту
  другого (или этого же, но уже сохранённого) устройства: подключение создаётся, а если у порта уже
  есть активное подключение — обновляется на месте (тип линии, описание, соседний порт);
* ``{"peer_row", "connection_type_id", "description"}`` — то же, но сосед задан НОМЕРОМ элемента в
  этом же массиве ``interfaces`` (с нуля). Так подключаются порты, у которых ещё нет id: новый порт
  к другому новому порту этого же запроса или к уже сохранённому порту этого же устройства. Ровно
  одно из ``peer_interface_id`` / ``peer_row``.

Подключения обрабатываются ПОСЛЕ записи всех портов (у новых портов уже есть id) и в той же
транзакции: любая ошибка — например, занятый соседний порт (409) — откатывает и порты, и подключения.
Правила допустимости пары портов — те же, что у обычного создания подключения
(services/validation.py:validate_connection). Сверку конфигураций портов (роль, режим, VLAN) эта
операция не блокирует: расхождение, как и при создании подключения другим способом, отображается
в дашборде «Подключения» со статусом «расхождение» до одобрения.

Порядок применения (sync_interface_connections): сначала разбирается весь payload, затем
выполняются все отключения, затем строится ПЛАН всех подключений и целиком проверяется (порт не
входит в две разные пары; пара не задана дважды с разными параметрами), и только после этого план
применяется. Благодаря плану порты можно менять местами в одном запросе (A: P→Q, B: Q→P): прежние
порты переставляемых этим же запросом подключений при проверке считаются свободными.

Уникальные индексы активных подключений (uq_connections_source_active, uq_connections_destination_active) не откладываются до конца
транзакции, поэтому перед применением плана подключения, меняющие соседний порт, выключаются (is_active = false), а после применения всех
подключений включаются снова.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..models import AuditLog, Connection, ConnectionType, DeviceInterface
from .validation import lock_interfaces, validate_connection

_AUDIT_ENTITY = "connections"


@dataclass(frozen=True)
class ConnectionSpec:
    """Разобранный и провалидированный по форме элемент payload['interfaces'][i]['connection'].
    Сосед задан ровно одним из полей: id порта либо номером элемента массива interfaces."""

    peer_interface_id: str | None
    peer_row: int | None
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
    >>> parse_connection_spec({'peer_row': 2, 'connection_type_id': 't1'}).peer_row
    2
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise HTTPException(422, "Поле connection интерфейса должно быть объектом или null")
    peer_id, peer_row = raw.get("peer_interface_id"), raw.get("peer_row")
    if peer_id not in (None, "") and peer_row is not None:
        raise HTTPException(422, "Соседний порт задаётся одним из полей: peer_interface_id или peer_row")
    if peer_row is not None:
        # bool — подкласс int: True/False как номер строки — ошибка клиента, а не «строка 1/0».
        if not isinstance(peer_row, int) or isinstance(peer_row, bool) or peer_row < 0:
            raise HTTPException(422, "Поле peer_row должно быть неотрицательным целым числом — номером порта в списке interfaces")
        peer_id = None
    elif not isinstance(peer_id, str) or not peer_id.strip():
        raise HTTPException(422, "Для подключения порта выберите соседнее устройство и его порт")
    else:
        peer_id = peer_id.strip()
    type_id = raw.get("connection_type_id")
    if not isinstance(type_id, str) or not type_id.strip():
        raise HTTPException(422, "Для подключения порта выберите тип физической линии связи")
    description = raw.get("description")
    if description is not None and not isinstance(description, str):
        raise HTTPException(422, "Описание подключения должно быть строкой")
    return ConnectionSpec(peer_id, peer_row, type_id.strip(), (description or "").strip() or None)


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


@dataclass
class _Plan:
    """Одно запланированное подключение: порт ``iface`` — к порту ``peer``. ``target`` — существующее
    активное подключение порта, которое будет изменено (None — создаётся новое)."""

    iface: DeviceInterface
    peer: DeviceInterface
    spec: ConnectionSpec
    target: Connection | None

    @property
    def pair(self) -> frozenset[str]:
        return frozenset((self.iface.id, self.peer.id))


def sync_interface_connections(requests: Sequence[tuple[DeviceInterface, Any]], session: Session, rows: Sequence[DeviceInterface] = ()) -> int:
    """Применяет подключения портов из payload формы устройства и возвращает число созданных,
    изменённых и удалённых подключений. Транзакцией (commit/rollback) управляет вызывающая сторона.

    requests — пары (порт, сырое значение ключа connection); порты уже записаны и сброшены в БД
    (flush), поэтому у каждого есть id. rows — порты ВСЕХ элементов payload['interfaces'] в порядке
    запроса: по ним разрешается ``peer_row``.

    Пример: sync_interface_connections([(iface, {'peer_interface_id': peer.id, 'connection_type_id': ct.id})], session)
    """
    # Сначала разбираем весь payload (ошибка формы — до любых изменений), затем отключаем порты,
    # строим и проверяем план и только потом применяем его: порт соседа, освобождаемый в этом же
    # запросе, можно занять независимо от порядка строк.
    parsed = [(iface, parse_connection_spec(raw)) for iface, raw in requests]
    # На PostgreSQL все порты запроса берутся ОДНИМ упорядоченным захватом до чтения их подключений: план считается из
    # актуального состояния, а два запроса с пересекающимися портами не блокируют друг друга взаимно — без этого validate_connection брал бы
    # порты
    # парами в порядке плана, и запросы с противоположным порядком могли бы упереться друг в друга. Повторная блокировка уже взятых строк
    # мгновенна.
    lock_interfaces(session, _ports_of_request(parsed, rows))
    changed = 0
    for iface, spec in parsed:
        if spec is not None:
            continue
        active = connections_of([iface.id], session)
        for conn in active:
            session.delete(conn)
            _audit(session, conn.id, AuditAction.DELETE, "Удаление записи (порт отключён в форме устройства)")
        session.flush()
        changed += len(active)

    plans = _build_plans([(iface, spec) for iface, spec in parsed if spec is not None], rows, session)
    _assert_plans_consistent(plans)
    # Подключения, которые этот запрос переставляет: их прежние порты при проверке считаются свободными.
    moved_ids = {plan.target.id for plan in plans if plan.target}
    switched_off = _switch_off_moving(plans, session)
    for plan in plans:
        changed += _apply_plan(plan, moved_ids, session)
    _switch_on(switched_off, session)
    return changed


def _new_ends(plan: _Plan) -> tuple[str, str]:
    """(источник, назначение) подключения после применения плана. Направление существующего подключения не переворачивается: порт остаётся
    на той
    стороне, на которой стоял, меняется только соседний; новое подключение идёт от порта к соседу."""
    target = plan.target
    if target is None or target.source_interface_id == plan.iface.id:
        return plan.iface.id, plan.peer.id
    return plan.peer.id, plan.iface.id


def _switch_off_moving(plans: Sequence[_Plan], session: Session) -> list[Connection]:
    """Выключает (is_active = false) подключения, которые этот запрос переставляет на другие порты, и сбрасывает это в БД.

    Уникальные индексы uq_connections_source_active / uq_connections_destination_active не откладываются до конца транзакции, а план
    применяется по одному
    подключению: при обмене соседями (A: P→Q, B: Q→P) в промежутке порт числится за двумя активными подключениями, и индекс отверг бы
    запись. Выключенные строки
    индекс не видит; ``_switch_on`` включает их, когда все стоят на новых местах. Всё происходит в одной транзакции — другие запросы
    промежуточного состояния не видят,
    а при ошибке откат вернёт подключения как были. Подключения, у которых меняются только тип линии или описание, не трогаются."""
    moving = [
        plan.target for plan in plans if plan.target is not None and _new_ends(plan) != (plan.target.source_interface_id, plan.target.destination_interface_id)
    ]
    for connection in moving:
        connection.is_active = False
    if moving:
        session.flush()
    return moving


def _switch_on(connections: Sequence[Connection], session: Session) -> None:
    """Возвращает переставленные подключения в работу; индекс проверяет итоговое состояние
    (конфликт — IntegrityError, его вызывающий код превращает в 409)."""
    for connection in connections:
        connection.is_active = True
    if connections:
        session.flush()


def _ports_of_request(parsed: Sequence[tuple[DeviceInterface, ConnectionSpec | None]], rows: Sequence[DeviceInterface]) -> set[str]:
    """id всех портов запроса: сами порты и их соседи (заданные id либо номером элемента массива interfaces;
    неверный номер — ошибка 422 позже, не здесь)."""
    ids = {iface.id for iface, _ in parsed}
    for _, spec in parsed:
        if spec is None:
            continue
        if spec.peer_interface_id:
            ids.add(spec.peer_interface_id)
        elif spec.peer_row is not None and spec.peer_row < len(rows):
            ids.add(rows[spec.peer_row].id)
    return ids


def _resolve_peer(iface: DeviceInterface, spec: ConnectionSpec, rows: Sequence[DeviceInterface], session: Session) -> DeviceInterface:
    if spec.peer_row is not None:
        if spec.peer_row >= len(rows):
            raise HTTPException(422, f"Порт-сосед не найден: в списке interfaces нет элемента с номером {spec.peer_row}")
        peer = rows[spec.peer_row]
    else:
        peer = session.get(DeviceInterface, spec.peer_interface_id)
        if peer is None:
            raise HTTPException(422, "Выбранный порт для подключения не найден")
    if peer is iface or peer.id == iface.id:
        raise HTTPException(422, "Порт нельзя подключить к самому себе")
    return peer


def _build_plans(specs: Sequence[tuple[DeviceInterface, ConnectionSpec]], rows: Sequence[DeviceInterface], session: Session) -> list[_Plan]:
    plans: list[_Plan] = []
    by_pair: dict[frozenset[str], _Plan] = {}
    for iface, spec in specs:
        if session.get(ConnectionType, spec.connection_type_id) is None:
            raise HTTPException(422, "Выбранный тип физической линии связи не найден")
        peer = _resolve_peer(iface, spec, rows, session)
        plan = _Plan(iface, peer, spec, None)
        earlier = by_pair.get(plan.pair)
        if earlier is not None:
            # Один и тот же кабель описан с обеих сторон (порт A указывает на B, а B — на A): это одно
            # подключение. Параметры должны совпадать, иначе неясно, какой из вариантов верный.
            if (earlier.spec.connection_type_id, earlier.spec.description) != (spec.connection_type_id, spec.description):
                raise HTTPException(422, f"Подключение портов «{iface.name}» и «{peer.name}» задано дважды с разными параметрами")
            continue
        # Подключение к тому же порту — обновляем на месте. Иначе берём первое активное подключение
        # этого порта и переключаем его на нового соседа. Если у порта по историческим причинам
        # несколько активных подключений, остальные не трогаем: validate_connection ответит 409, а
        # не удалит данные молча.
        active = connections_of([iface.id], session)
        same = next((c for c in active if {c.source_interface_id, c.destination_interface_id} == set(plan.pair)), None)
        plan.target = same or (active[0] if active else None)
        by_pair[plan.pair] = plan
        plans.append(plan)
    return plans


def _assert_plans_consistent(plans: Sequence[_Plan]) -> None:
    """Порт может входить только в одно подключение: проверка внутри самого запроса (в БД до применения
    плана этих подключений ещё нет, поэтому validate_connection их не увидит)."""
    claimed: dict[str, _Plan] = {}
    for plan in plans:
        for port in (plan.iface, plan.peer):
            other = claimed.get(port.id)
            if other is not None and other.pair != plan.pair:
                raise HTTPException(
                    409, f"Порт «{port.name}» указан в нескольких подключениях одного запроса — порт может участвовать только в одном подключении."
                )
            claimed[port.id] = plan


def _apply_plan(plan: _Plan, moved_ids: set[str], session: Session) -> int:
    iface, peer, spec, target = plan.iface, plan.peer, plan.spec, plan.target
    if target is None:
        data = {
            "source_interface_id": iface.id,
            "destination_interface_id": peer.id,
            "connection_type_id": spec.connection_type_id,
            "is_active": True,
            "description": spec.description,
        }
        validate_connection(data, session, ignore_connection_ids=moved_ids)
        created = Connection(**data)
        session.add(created)
        session.flush()
        _audit(session, created.id, AuditAction.CREATE, "Создание записи (из формы устройства)")
        return 1

    # Направление (источник/назначение) существующего подключения не переворачиваем: порт остаётся
    # на той стороне, на которой стоял, меняется только соседний.
    source_id, destination_id = _new_ends(plan)
    candidate = {
        "source_interface_id": source_id,
        "destination_interface_id": destination_id,
        "connection_type_id": spec.connection_type_id,
        "is_active": True,
        "description": spec.description,
    }
    validate_connection(candidate, session, current_connection_id=target.id, ignore_connection_ids=moved_ids)

    changes: list[str] = []
    if (source_id, destination_id) != (target.source_interface_id, target.destination_interface_id):
        changes.append("соседний порт")
    if target.connection_type_id != spec.connection_type_id:
        changes.append("тип линии связи")
    if (target.description or None) != spec.description:
        changes.append("описание")
    if not changes:
        return 0

    if "соседний порт" in changes:
        target.source_interface_id, target.destination_interface_id = source_id, destination_id
        # Одобрение расхождения относится к конкретной паре портов — новому соседу нужна своя проверка.
        target.port_config_approved_signature = None
    target.connection_type_id = spec.connection_type_id
    target.description = spec.description
    session.flush()
    _audit(session, target.id, AuditAction.UPDATE, "Изменение записи из формы устройства: " + ", ".join(changes))
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
    connected = {
        iid for c in connections_of(list(by_id), session, active_only=False) for iid in (c.source_interface_id, c.destination_interface_id) if iid in by_id
    }
    if connected:
        names = ", ".join(f"«{by_id[i].name}»" for i in sorted(connected, key=lambda x: by_id[x].name))
        raise HTTPException(
            409,
            f"Нельзя удалить порт, у которого есть подключение: {names}. Сначала отключите порт (блок «Подключение» в "
            "строке порта) и сохраните устройство, либо удалите подключение на экране «Подключения».",
        )
