"""Правила подключений (лист 3 отчёта «Организация подключений»): назначение линии, повторное использование порта, концы подключения.

Проверяются только активные подключения: неактивное в отчёт не попадает и порт не занимает (уникальность портов в БД тоже только по
активным). Объект находки — подключение; его имя собирается из устройств и портов обоих концов.
"""

from __future__ import annotations

import ipaddress
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ...constants import OwnerType
from ...models import Connection, DeviceInterface, DeviceSubinterface, IPAddress
from ._support import chunked, device_labels
from .engine import RuleSpec, rule
from .model import Category, Finding, Severity

ENTITY = "connection"
PORT_ENTITY = "device_interface"


@dataclass(frozen=True, slots=True)
class End:
    """Один конец подключения: порт, его устройство и есть ли у порта назначение (сам порт или любой его подинтерфейс)."""

    port_id: str
    port_name: str
    device_id: str
    device_name: str
    has_purpose: bool

    @property
    def title(self) -> str:
        return f"{self.device_name} ({self.port_name})"

    def port_ref(self) -> dict[str, str]:
        """Порт для `details`: по паре (тип, id) отпечаток узнаёт его, а имя — подпись и переименование проблему не меняет."""
        return {"entity_type": PORT_ENTITY, "entity_id": self.port_id, "name": self.title}


@dataclass(frozen=True, slots=True)
class Link:
    id: str
    source: End
    destination: End

    @property
    def ends(self) -> tuple[End, End]:
        return (self.source, self.destination)

    @property
    def name(self) -> str:
        return f"{self.source.title} ↔ {self.destination.title}"


def load_links(session: Session) -> list[Link]:
    """Активные подключения с обоими концами. Число запросов постоянно: порты, их подинтерфейсы и устройства читаются пачками."""
    rows = session.execute(
        select(Connection.id, Connection.source_interface_id, Connection.destination_interface_id)
        .where(Connection.is_active.is_(True))
        .order_by(Connection.id)
    ).all()
    port_ids = {port_id for row in rows for port_id in (row.source_interface_id, row.destination_interface_id)}
    ports: dict[str, tuple[str, str, bool]] = {}
    for batch in chunked(port_ids):
        for row in session.execute(
            select(
                DeviceInterface.id,
                DeviceInterface.name,
                DeviceInterface.physical_device_id,
                DeviceInterface.is_management,
                DeviceInterface.is_data_transfer,
            ).where(DeviceInterface.id.in_(batch))
        ):
            ports[row.id] = (row.name, row.physical_device_id, bool(row.is_management or row.is_data_transfer))
    with_sub_purpose: set[str] = set()
    for batch in chunked(port_ids):
        with_sub_purpose.update(
            session.scalars(
                select(DeviceSubinterface.parent_interface_id).where(
                    DeviceSubinterface.parent_interface_id.in_(batch),
                    or_(DeviceSubinterface.is_management, DeviceSubinterface.is_data_transfer),
                )
            )
        )
    labels = device_labels(session, {device_id for _, device_id, _ in ports.values()})

    def end(port_id: str) -> End:
        name, device_id, has_purpose = ports[port_id]
        return End(port_id, name, device_id, labels.get(device_id, device_id), has_purpose or port_id in with_sub_purpose)

    return [Link(row.id, end(row.source_interface_id), end(row.destination_interface_id)) for row in rows]


@rule("connection_without_purpose", "У подключения не указано назначение линии связи", Severity.WARNING, Category.COMPLETENESS, sheet=3)
def check_without_purpose(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Назначение («передача данных», «управление активами») отчёт берёт из флагов порта и его подинтерфейсов; без них в столбце «-»."""
    for link in load_links(session):
        lacking = [end for end in link.ends if not end.has_purpose]
        if lacking:
            where = ", ".join(f"порта {end.title}" for end in lacking)
            yield spec.finding(
                ENTITY,
                link.id,
                link.name,
                f"{link.name}: не указано назначение линии связи у {where}.",
                ports=[end.port_ref() for end in lacking],
            )


@rule("connection_port_in_several_connections", "Порт участвует в нескольких подключениях", Severity.ERROR, Category.CONSISTENCY, sheet=3)
def check_shared_port(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """К одному порту ведёт один кабель. База не даёт повторить порт на одной и той же стороне, но порт может быть источником одного
    подключения и назначением другого — отчёт тогда описывает его двумя разными линиями."""
    links = load_links(session)
    uses = Counter(end.port_id for link in links for end in link.ends)
    for link in links:
        shared = [end for end in link.ends if uses[end.port_id] > 1]
        if shared:
            where = ", ".join(end.title for end in shared)
            yield spec.finding(
                ENTITY,
                link.id,
                link.name,
                f"{link.name}: порт {where} указан ещё в одном подключении.",
                ports=[end.port_ref() for end in shared],
            )


@rule("connection_ends_on_same_device", "Оба конца подключения на одном устройстве", Severity.WARNING, Category.CONSISTENCY, sheet=3)
def check_same_device(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Кабель между двумя портами одного устройства (петля) почти всегда ошибка ввода; осознанную петлю можно одобрить."""
    for link in load_links(session):
        if link.source.device_id == link.destination.device_id:
            yield spec.finding(
                ENTITY,
                link.id,
                link.name,
                f"{link.name}: оба конца подключения на одном устройстве — {link.source.device_name}.",
                device=link.source.device_id,
            )


def _network(address: str, prefix: int | None) -> ipaddress.IPv4Network | ipaddress.IPv6Network | None:
    """Сеть адреса или None, если маски нет или адрес не разбирается (повреждённые адреса ловит правило invalid_ip)."""
    if prefix is None:
        return None
    try:
        return ipaddress.ip_network(f"{address.strip()}/{prefix}", strict=False)
    except ValueError:
        return None


@rule(
    "connection_ends_in_different_subnets",
    "IP-адреса концов подключения в разных подсетях",
    Severity.WARNING,
    Category.CONSISTENCY,
    sheet=3,
)
def check_different_subnets(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Если у обоих портов подключения есть IP с маской, но ни одной общей сети — линия L3 настроена с ошибкой в адресе или маске.
    Порты без адреса (L2) и порты, у которых хоть один адрес без маски, не оцениваются: судить не по чему. Сравниваются адреса самих
    портов, адреса подинтерфейсов — нет."""
    links = load_links(session)
    port_ids = {end.port_id for link in links for end in link.ends}
    addresses: dict[str, list[tuple[str, int | None]]] = defaultdict(list)
    for batch in chunked(port_ids):
        for row in session.execute(
            select(IPAddress.owner_id, IPAddress.ip_address, IPAddress.prefix_length).where(
                IPAddress.owner_type == OwnerType.DEVICE_INTERFACE, IPAddress.owner_id.in_(batch)
            )
        ):
            addresses[row.owner_id].append((row.ip_address, row.prefix_length))
    for link in links:
        sides = [addresses.get(end.port_id, []) for end in link.ends]
        if not all(sides):
            continue
        nets = [{_network(address, prefix) for address, prefix in side} for side in sides]
        if any(None in side for side in nets) or nets[0] & nets[1]:
            continue
        text = [", ".join(sorted(f"{address}/{prefix}" for address, prefix in side)) for side in sides]
        yield spec.finding(
            ENTITY,
            link.id,
            link.name,
            f"{link.name}: адреса концов в разных подсетях ({text[0]} и {text[1]}).",
            addresses={"source": text[0], "destination": text[1]},
        )
