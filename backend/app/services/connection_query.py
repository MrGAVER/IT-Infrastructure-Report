"""Серверная выборка подключений для дашборда «Подключения»: поиск, фильтры, статус сверки
конфигурации портов (роль, режим, VLAN), пагинация и итоговые счётчики.

Статус сверки (ok / mismatch / approved) вычисляется в SQL тем же правилом, что и
`evaluate_port_config()` в services/port_config.py, — иначе фильтр по статусу, общее число
записей и счётчики пришлось бы считать, вытянув в память ВСЕ подключения (раньше дашборд так и
делал: один запрос на 1000 записей и фильтрация в браузере, а всё, что за пределом 1000, молча
не попадало ни в таблицу, ни в счётчики). Соответствие SQL-выражения и Python-функции проверяет
tests/test_connection_query.py (роли × режимы × наборы VLAN × одобрение × активность).

Пример:
    page = list_connections(session, ConnectionQuery(q="коммутатор", status=PortConfigStatus.MISMATCH), offset=0, limit=25)
    page["total"], page["summary"]["mismatch"], page["items"][0]["port_config_status"]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import BigInteger, ColumnElement, String, and_, case, cast, func, literal, or_, select
from sqlalchemy.orm import Session, aliased

from ..models import Connection, ConnectionType, DeviceInterface, DeviceTypeVLAN, InterfaceVLAN, PhysicalDevice, PhysicalDeviceVLAN, VLAN
from .device_label import device_label_expr
from .port_config import (
    DEFAULT_VLAN_MODE,
    FINGERPRINT_AFFINE,
    FINGERPRINT_COUNT_WEIGHT,
    FINGERPRINT_MODULUS,
    FINGERPRINT_SQUARE_ADDENDS,
    PORT_ROLE_LABELS,
    PortConfigStatus,
    PortRole,
    VLAN_MODE_TRUNK,
)
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


def _mode_sql(iface: Any) -> ColumnElement[str]:
    """SQL-аналог port_config_of(): пустой режим — trunk (как server_default колонки)."""
    return func.coalesce(func.nullif(iface.vlan_mode, ""), _text(DEFAULT_VLAN_MODE))


def _vlan_fingerprint_sql(iface: Any) -> ColumnElement[int]:
    """SQL-аналог port_config.vlan_fingerprint() для порта `iface` — коррелированный скалярный
    подзапрос по индексу interface_vlans.interface_id (у порта с «Все VLAN» — по VLAN его устройства, см.
    ниже). Считается лениво: только там, где выражение реально вычисляется (страница без фильтра по
    статусу его не касается). Формулу менять только вместе с Python-версией."""

    def big(value: int) -> ColumnElement[int]:
        return literal(value, type_=BigInteger)  # явный BIGINT: без неявного приведения параметров в PostgreSQL

    # Та же цепочка, что port_config.vlan_hash(). Дубликаты номеров (один тег в двух доменах)
    # схлопывает DISTINCT: хеш инъективен на 1..4094, проверяет tests/test_port_config.py.
    multiplier, offset = FINGERPRINT_AFFINE
    number = VLAN.vlan_id
    shuffled = (number * big(multiplier) + big(offset)) % big(FINGERPRINT_MODULUS)
    for addend in FINGERPRINT_SQUARE_ADDENDS:
        shuffled = (shuffled * shuffled + big(addend)) % big(FINGERPRINT_MODULUS)
    aggregate = func.coalesce(func.sum(shuffled.distinct()), 0) + func.count(number.distinct()) * big(FINGERPRINT_COUNT_WEIGHT)
    chosen = (
        select(aggregate)
        .select_from(InterfaceVLAN)
        .join(VLAN, VLAN.id == InterfaceVLAN.vlan_id)
        .where(InterfaceVLAN.interface_id == iface.id)
        .scalar_subquery()
    )
    # «Все VLAN»: порт хранит только признак, а набор — все VLAN устройства (VLAN типа ∪ VLAN самого устройства,
    # services/port_vlans.py:effective_vlan_ids). Ветка CASE вычисляется только для портов с признаком.
    # Вложенные подзапросы ссылаются на порт `iface` через ДВА уровня select'ов, а автокорреляция SQLAlchemy
    # работает только на один: без явного .correlate(iface) порт попадает в их FROM и перемножается со всеми
    # портами реестра — отпечаток «Все VLAN» тогда один и тот же у любого порта (расхождения не находятся).
    device = aliased(PhysicalDevice)
    own = select(PhysicalDeviceVLAN.vlan_id).where(PhysicalDeviceVLAN.physical_device_id == iface.physical_device_id).correlate(iface)
    typed = (
        select(DeviceTypeVLAN.vlan_id)
        .join(device, device.device_type_id == DeviceTypeVLAN.device_type_id)
        .where(device.id == iface.physical_device_id)
        .correlate(iface)
    )
    every = select(aggregate).select_from(VLAN).where(or_(VLAN.id.in_(own), VLAN.id.in_(typed))).scalar_subquery()
    return case((and_(iface.all_vlans.is_(True), _mode_sql(iface) == _text(VLAN_MODE_TRUNK)), every), else_=chosen)


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
        self.src_mode = _mode_sql(self.src)
        self.dst_mode = _mode_sql(self.dst)
        self.src_vlans = _vlan_fingerprint_sql(self.src)
        self.dst_vlans = _vlan_fingerprint_sql(self.dst)
        # Подпись расхождения — тот же формат, что port_config.approval_signature(): только
        # различающиеся грани, «источник>назначение».
        self.signature = (
            case((self.src_role != self.dst_role, self.src_role + _text(">") + self.dst_role), else_=_text(""))
            + case((self.src_mode != self.dst_mode, _text("|mode:") + self.src_mode + _text(">") + self.dst_mode), else_=_text(""))
            + case(
                (
                    self.src_vlans != self.dst_vlans,
                    _text("|vlan:") + cast(self.src_vlans, String) + _text(">") + cast(self.dst_vlans, String),
                ),
                else_=_text(""),
            )
        )
        configs_match = and_(self.src_role == self.dst_role, self.src_mode == self.dst_mode, self.src_vlans == self.dst_vlans)
        self.status = case(
            (or_(Connection.is_active.is_(False), self.src.id.is_(None), self.dst.id.is_(None)), _text(PortConfigStatus.OK.value)),
            (configs_match, _text(PortConfigStatus.OK.value)),
            # IS NOT NULL первым: у подавляющего большинства подключений одобрения нет, и сравнение подписи (а в ней отпечатки
            # VLAN обоих портов) вычислять незачем — NULL == подпись и так не истина. AND в SQL вычисляется слева направо с
            # прерыванием, поэтому для неодобренных подключений четыре из шести вычислений отпечатка отпадают.
            (
                and_(Connection.port_config_approved_signature.is_not(None), Connection.port_config_approved_signature == self.signature),
                _text(PortConfigStatus.APPROVED.value),
            ),
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

    def conditions(self, query: ConnectionQuery) -> list[ColumnElement[bool]]:
        result: list[ColumnElement[bool]] = []
        needle = (query.q or "").strip().lower()
        if needle:

            def contains(column: Any) -> ColumnElement[bool]:
                return func.lower(column).contains(needle, autoescape=True)  # % и _ из поиска — обычные символы

            # Поиск идёт по тем же полям, что показывает таблица: устройства и порты обеих сторон,
            # тип линии, режим порта (trunk / access) и подпись роли порта («управление»,
            # «передача данных»).
            matches = [
                contains(device_label_expr(self.src_device)),
                contains(self.src.name),
                contains(device_label_expr(self.dst_device)),
                contains(self.dst.name),
                contains(ConnectionType.name),
                contains(self.src_mode),
                contains(self.dst_mode),
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
