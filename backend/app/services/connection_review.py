"""Операции проверки конфигураций портов-соседей подключений (дашборд «Подключения»).

Правила определения статуса — в services/port_config.py; здесь только изменяющие данные
операции: задать роль порта, одобрить расхождение (роли, режима порта, VLAN), отозвать одобрение.
Единственная читающая функция — preview_port_config(): форма подключения спрашивает у сервера
статус сверки пары портов ДО сохранения, чтобы правила не дублировались на клиенте. Каждая операция — одна
транзакция с записью в журнал аудита.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence, TypeAlias

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..constants import AuditAction
from ..models import Connection, DeviceInterface
from .connection_query import ConnectionQuery, MAX_SEARCH_LENGTH, select_connection_ids
from .crud import audit
from .port_config import (
    ConfigFacet,
    PORT_ROLE_LABELS,
    PortConfig,
    PortConfigStatus,
    approval_signature,
    config_differences,
    evaluate_port_config,
    port_role,
    role_from_flags,
)
from .port_config_db import load_port_configs
from .port_writes import write_port_role
from .serialization import enrich_connections, enrich_interfaces

_FACET_LABELS = {ConfigFacet.ROLE: "роль", ConfigFacet.MODE: "режим порта", ConfigFacet.VLANS: "VLAN"}

MAX_APPROVE_BATCH = 500
# Сколько подключений обрабатывается за один проход при одобрении «всех найденных»: на каждый
# проход порты подгружаются одним IN-запросом, а у SQLite/psycopg число параметров ограничено.
_APPROVE_CHUNK = 400


def _require_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise HTTPException(422, f"Поле {key} должно быть true или false")
    return value


def set_port_role(interface_id: str, payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """Точечно меняет роль порта (управление / передача данных), не трогая остальные его
    настройки — в отличие от PUT /devices/{id}/interfaces, который синхронизирует устройство
    целиком. Возвращает интерфейс в том же виде, что и GET /resources/interfaces, чтобы клиент
    мог заменить запись в своём кэше.

    IP-адреса порта зеркалируют его is_management (тот же инвариант, что поддерживает
    sync_interfaces), поэтому флаг на адресах обновляется вместе с портом."""
    is_management = _require_bool(payload, "is_management")
    is_data_transfer = _require_bool(payload, "is_data_transfer")
    iface = session.get(DeviceInterface, interface_id)
    if not iface:
        raise HTTPException(404, "Порт не найден")
    before = port_role(iface)
    after = role_from_flags(is_management, is_data_transfer)
    write_port_role(iface, after, session)
    audit(session, "interfaces", iface.id, AuditAction.UPDATE, f"Роль порта «{iface.name}»: {PORT_ROLE_LABELS[before]} → {PORT_ROLE_LABELS[after]}")
    session.commit()
    session.refresh(iface)
    return enrich_interfaces([iface], session)[0]


def _port_payload(interface_id: str, config: PortConfig) -> dict[str, Any]:
    return {"interface_id": interface_id, "role": config.role.value, "mode": config.mode, "vlans": sorted(config.vlans)}


def preview_port_config(
    source_interface_id: str,
    destination_interface_id: str,
    session: Session,
    *,
    connection_id: str | None = None,
    is_active: bool = True,
) -> dict[str, Any]:
    """Статус сверки для пары портов, которую форма ещё не сохранила: те же правила, что у
    дашборда (services/port_config.py), поэтому предупреждение формы и итоговый статус на дашборде
    не могут разойтись.

    Если передан `connection_id` (правка существующего подключения), одобрение берётся с него:
    пара с тем же расхождением, что было одобрено, остаётся «approved» и повторно не спрашивается.
    Без него (новое подключение) возможны только «ok» и «mismatch». Для неактивного подключения —
    всегда «ok», как и на дашборде."""
    ids = [source_interface_id, destination_interface_id]
    interfaces = list(session.scalars(select(DeviceInterface).where(DeviceInterface.id.in_(ids))).all())
    configs = load_port_configs(session, interfaces)
    source, destination = configs.get(source_interface_id), configs.get(destination_interface_id)
    if source is None or destination is None:
        raise HTTPException(404, "Порт не найден")
    approved_signature = None
    if connection_id is not None:
        connection = session.get(Connection, connection_id)
        if connection is None:
            raise HTTPException(404, "Подключение не найдено")
        approved_signature = connection.port_config_approved_signature
    status = evaluate_port_config(source, destination, approved_signature, is_active=is_active)
    return {
        "status": status.value,
        "diff": [f.value for f in config_differences(source, destination)] if is_active else [],
        "source": _port_payload(source_interface_id, source),
        "destination": _port_payload(destination_interface_id, destination),
    }


def _describe(name: str, config: PortConfig) -> str:
    vlans = ", ".join(str(n) for n in sorted(config.vlans)) or "нет"
    return f"«{name}» — {PORT_ROLE_LABELS[config.role]}, режим {config.mode}, VLAN: {vlans}"


def _approve_connections(connections: Sequence[Connection], session: Session) -> tuple[list[Connection], list[str], int]:
    """Одобряет текущее расхождение у переданных подключений (без commit — его делает вызывающий).

    Возвращает (подключения с расхождением, одобренным ранее или в этом вызове; id подключений, у
    которых одобрять нечего; сколько одобрено именно сейчас). Порты и их VLAN подгружаются пакетом."""
    interface_ids = {i for c in connections for i in (c.source_interface_id, c.destination_interface_id)}
    interfaces = list(session.scalars(select(DeviceInterface).where(DeviceInterface.id.in_(interface_ids))).all()) if interface_ids else []
    names = {i.id: i.name for i in interfaces}
    configs = load_port_configs(session, interfaces)
    covered: list[Connection] = []
    skipped: list[str] = []
    newly_approved = 0
    for conn in connections:
        source, destination = configs.get(conn.source_interface_id), configs.get(conn.destination_interface_id)
        if not source or not destination:
            raise HTTPException(422, "У подключения отсутствует один из портов")
        status = evaluate_port_config(source, destination, conn.port_config_approved_signature, is_active=conn.is_active is not False)
        if status is PortConfigStatus.MISMATCH:
            conn.port_config_approved_signature = approval_signature(source, destination)
            facets = ", ".join(_FACET_LABELS[f] for f in config_differences(source, destination))
            audit(
                session,
                "connections",
                conn.id,
                AuditAction.UPDATE,
                f"Одобрено расхождение конфигурации портов ({facets}): {_describe(names[conn.source_interface_id], source)}; {_describe(names[conn.destination_interface_id], destination)}",
            )
            covered.append(conn)
            newly_approved += 1
        elif status is PortConfigStatus.OK:
            skipped.append(conn.id)
        else:  # уже одобрено — состояние не меняем, но клиенту вернём актуальную запись
            covered.append(conn)
    return covered, skipped, newly_approved


def _parse_match(match: Any) -> ConnectionQuery:
    """Условия «одобрить все найденные»: те же q / is_active, что у списка. Статус всегда
    «расхождение» — одобрять есть смысл только их, поэтому клиент его не передаёт."""
    if not isinstance(match, dict):
        raise HTTPException(422, "Поле match должно быть объектом с необязательными q и is_active")
    q, is_active = match.get("q"), match.get("is_active")
    if q is not None and (not isinstance(q, str) or len(q) > MAX_SEARCH_LENGTH):
        raise HTTPException(422, f"Поле match.q должно быть строкой не длиннее {MAX_SEARCH_LENGTH} символов")
    if is_active is not None and not isinstance(is_active, bool):
        raise HTTPException(422, "Поле match.is_active должно быть true, false или null")
    return ConnectionQuery(q=q, is_active=is_active, status=PortConfigStatus.MISMATCH)


@dataclass(frozen=True)
class ApproveByIds:
    """Одобрить перечисленные подключения: уникальные id в порядке прихода."""

    ids: list[str]


@dataclass(frozen=True)
class ApproveByMatch:
    """Одобрить все подключения с расхождением под условиями поиска."""

    query: ConnectionQuery


# Ровно один из двух вариантов: пара «(ids | None, query | None)» позволяла представить и «оба», и «ни одного», а вызывающему коду
# приходилось доказывать компилятору (и интерпретатору, assert-ом), что второй вариант не None.
ApproveSelection: TypeAlias = ApproveByIds | ApproveByMatch


def parse_approve_request(payload: Any) -> ApproveSelection:
    """Разбор тела одобрения — чистая проверка формы, без обращения к БД (её же вызывает модель запроса
    `ApprovePortConfigRequest`, api/port_config_schemas.py, поэтому правила живут только здесь).

    Ровно одно из `connection_ids` / `match`. Возвращает ApproveByIds (уникальные id в порядке прихода) либо ApproveByMatch (условия поиска)."""
    if not isinstance(payload, dict):
        raise HTTPException(422, "Тело запроса должно быть объектом")
    has_ids, has_match = "connection_ids" in payload, "match" in payload
    if has_ids == has_match:
        raise HTTPException(422, "Передайте ровно одно из полей: connection_ids или match")
    if has_match:
        return ApproveByMatch(_parse_match(payload["match"]))
    ids = payload["connection_ids"]
    if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids):
        raise HTTPException(422, "Поле connection_ids должно быть непустым массивом идентификаторов подключений")
    if len(ids) > MAX_APPROVE_BATCH:
        raise HTTPException(422, f"За один запрос можно одобрить не более {MAX_APPROVE_BATCH} подключений")
    return ApproveByIds(list(dict.fromkeys(ids)))


def approve_port_config(payload: dict[str, Any], session: Session) -> dict[str, Any]:
    """Одобряет текущее расхождение конфигурации портов (роль, режим, VLAN) у подключений — двумя способами:

    * `{"connection_ids": [...]}` — у перечисленных (форма подключения и окно проверки одного
      подключения; до MAX_APPROVE_BATCH за запрос). Неизвестный id — 404 без каких-либо изменений.
      В ответе `items` — актуальные записи, чтобы клиент подставил их без перезагрузки.
    * `{"match": {"q": ..., "is_active": ...}}` — у ВСЕХ подключений с расхождением под этими
      условиями поиска, а не только у показанной страницы (клиент страницы видит по одной). `items`
      в этом режиме пустой — записей может быть тысячи, клиент перечитывает страницу сам.

    Идемпотентно и безопасно к гонкам: подключение, у которого расхождения уже нет (роль порта
    успели выровнять) или которое неактивно, пропускается (`skipped_ids`). Всё — одной транзакцией:
    при ошибке не одобряется ничего. `approved_count` — сколько расхождений одобрено именно сейчас."""
    selection = parse_approve_request(payload)

    if isinstance(selection, ApproveByIds):
        unique_ids = selection.ids
        by_id = {c.id: c for c in session.scalars(select(Connection).where(Connection.id.in_(unique_ids))).all()}
        missing = [i for i in unique_ids if i not in by_id]
        if missing:
            raise HTTPException(404, f"Подключение не найдено: {missing[0]}")
        covered, skipped, approved = _approve_connections([by_id[i] for i in unique_ids], session)
        session.commit()
        return {"items": enrich_connections(covered, session), "skipped_ids": skipped, "approved_count": approved}

    ids = select_connection_ids(session, selection.query)
    approved = 0
    for start in range(0, len(ids), _APPROVE_CHUNK):
        chunk = session.scalars(select(Connection).where(Connection.id.in_(ids[start : start + _APPROVE_CHUNK]))).all()
        approved += _approve_connections(chunk, session)[2]
    session.commit()
    return {"items": [], "skipped_ids": [], "approved_count": approved}


def revoke_port_config_approval(connection_id: str, session: Session) -> dict[str, Any]:
    conn = session.get(Connection, connection_id)
    if not conn:
        raise HTTPException(404, "Подключение не найдено")
    if conn.port_config_approved_signature:
        conn.port_config_approved_signature = None
        audit(session, "connections", conn.id, AuditAction.UPDATE, "Отозвано одобрение расхождения конфигурации портов")
        session.commit()
    return enrich_connections([conn], session)[0]
