"""Серверная выборка подключений для дашборда «Подключения»: поиск, фильтры, статус сверки ролей
портов, пагинация и итоговые счётчики.

Статус сверки (ok / mismatch / approved) вычисляется в SQL тем же правилом, что и
`evaluate_port_config()` в services/port_config.py, — иначе фильтр по статусу, общее число
записей и счётчики пришлось бы считать, вытянув в память ВСЕ подключения (раньше дашборд так и
делал: один запрос на 1000 записей и фильтрация в браузере, а всё, что за пределом 1000, молча
не попадало ни в таблицу, ни в счётчики). Соответствие SQL-выражения и Python-функции проверяет
tests/test_connection_query.py (все комбинации ролей × одобрение × активность).

Пример:
    page = list_connections(session, ConnectionQuery(q="коммутатор", status=PortConfigStatus.MISMATCH), offset=0, limit=25)
    page["total"], page["summary"]["mismatch"], page["items"][0]["port_config_status"]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, String, and_, case, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from ..models import Connection, ConnectionType, DeviceInterface, PhysicalDevice
from .port_config import PORT_ROLE_LABELS, PortConfigStatus, PortRole
from .serialization import enrich_connections

MAX_SEARCH_LENGTH = 200


@dataclass(frozen=True)
class ConnectionQuery:
    """Условия выборки. Пустые значения (None / пустая строка) — «без ограничения»."""

    q: str | None = None
    is_active: bool | None = None
    status: PortConfigStatus | None = None


def _text(value: str) -> ColumnElement[str]:
    # Явно типизированный литерал: в CASE/конкатенации из одних параметров PostgreSQL иначе
    # может не вывести тип.
    return literal(value, type_=String)


def _role_sql(iface: Any) -> ColumnElement[str]:
    """SQL-аналог port_config.role_from_flags()."""
    management, data = iface.is_management.is_(True), iface.is_data_transfer.is_(True)
    return case(
        (and_(management, data), _text(PortRole.MANAGEMENT_DATA.value)),
        (management, _text(PortRole.MANAGEMENT.value)),
        (data, _text(PortRole.DATA.value)),
        else_=_text(PortRole.NONE.value),
    )


class _Joined:
    """Подключение + оба порта + оба устройства + тип линии и выражения над ними. Соединения
    внешние (LEFT JOIN): «осиротевшая» запись (порт удалён в обход внешних ключей) остаётся в
    списке и в итогах — как в GET /resources/connections и enrich_connections(), где такое
    подключение получает статус ok, — а не пропадает из счётчиков из-за INNER JOIN."""

    def __init__(self) -> None:
        self.src = aliased(DeviceInterface)
        self.dst = aliased(DeviceInterface)
        self.src_device = aliased(PhysicalDevice)
        self.dst_device = aliased(PhysicalDevice)
        self.src_role = _role_sql(self.src)
        self.dst_role = _role_sql(self.dst)
        self.status = case(
            (or_(Connection.is_active.is_(False), self.src.id.is_(None), self.dst.id.is_(None)), _text(PortConfigStatus.OK.value)),
            (self.src_role == self.dst_role, _text(PortConfigStatus.OK.value)),
            (Connection.port_config_approved_signature == self.src_role + _text(">") + self.dst_role, _text(PortConfigStatus.APPROVED.value)),
            else_=_text(PortConfigStatus.MISMATCH.value),
        )

    def select(self, *columns: Any):
        return (
            select(*columns)
            .select_from(Connection)
            .outerjoin(self.src, self.src.id == Connection.source_interface_id)
            .outerjoin(self.dst, self.dst.id == Connection.destination_interface_id)
            .outerjoin(self.src_device, self.src_device.id == self.src.physical_device_id)
            .outerjoin(self.dst_device, self.dst_device.id == self.dst.physical_device_id)
            .outerjoin(ConnectionType, ConnectionType.id == Connection.connection_type_id)
        )

    @staticmethod
    def _device_label(device: Any) -> ColumnElement[str]:
        # Как в enrich_connections(): «системное имя, а если не задано — серийный номер».
        return func.coalesce(func.nullif(device.system_name, ""), device.serial_number)

    def conditions(self, query: ConnectionQuery) -> list[ColumnElement[bool]]:
        result: list[ColumnElement[bool]] = []
        needle = (query.q or "").strip().lower()
        if needle:
            def contains(column: Any) -> ColumnElement[bool]:
                return func.lower(column).contains(needle, autoescape=True)  # % и _ из поиска — обычные символы

            # Поиск идёт по тем же полям, что показывает таблица: устройства и порты обеих сторон,
            # тип линии и подпись роли порта («управление», «передача данных»).
            matches = [
                contains(self._device_label(self.src_device)), contains(self.src.name),
                contains(self._device_label(self.dst_device)), contains(self.dst.name),
                contains(ConnectionType.name),
            ]
            roles = [role.value for role in PortRole if needle in PORT_ROLE_LABELS[role].lower()]
            if roles:
                matches += [self.src_role.in_(roles), self.dst_role.in_(roles)]
            result.append(or_(*matches))
        if query.is_active is not None:
            result.append(Connection.is_active.is_(False) if not query.is_active else Connection.is_active.is_not(False))
        if query.status is not None:
            result.append(self.status == query.status.value)
        return result


def list_connections(session: Session, query: ConnectionQuery, *, offset: int, limit: int) -> dict[str, Any]:
    """Страница подключений по условиям + total под теми же условиям + summary по ВСЕМ подключениям.

    Порядок фиксирован (создание, затем id): без второго ключа записи с одинаковым created_at
    могли бы «переезжать» между страницами при листании."""
    joined = _Joined()
    where = joined.conditions(query)
    base = joined.select(Connection).where(*where)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = session.scalars(base.order_by(Connection.created_at, Connection.id).offset(offset).limit(limit)).all()
    return {
        "items": enrich_connections(rows, session),
        "total": total,
        "offset": offset,
        "limit": limit,
        "summary": summarize_connections(session),
    }


def summarize_connections(session: Session) -> dict[str, int]:
    """Счётчики по всем подключениям, независимо от поиска и фильтров: сколько записей в реестре
    вообще и сколько из них требуют внимания. Один запрос."""
    joined = _Joined()
    row = session.execute(
        joined.select(
            func.count(Connection.id),
            func.sum(case((Connection.is_active.is_(False), 0), else_=1)),
            func.sum(case((joined.status == PortConfigStatus.MISMATCH.value, 1), else_=0)),
            func.sum(case((joined.status == PortConfigStatus.APPROVED.value, 1), else_=0)),
        )
    ).one()
    total, active, mismatch, approved = (int(value or 0) for value in row)
    return {"total": total, "active": active, "inactive": total - active, "mismatch": mismatch, "approved": approved}


def select_connection_ids(session: Session, query: ConnectionQuery) -> list[str]:
    """id ВСЕХ подключений под условиями (без пагинации) — для операций «применить ко всем
    найденным», где клиент видит только одну страницу."""
    joined = _Joined()
    stmt = joined.select(Connection.id).where(*joined.conditions(query)).order_by(Connection.created_at, Connection.id)
    return list(session.scalars(stmt).all())
