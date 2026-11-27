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
from ..port_config import VLAN_MODE_ACCESS
from ..port_vlans import effective_vlan_ids
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
    # Режим VLAN порта (None — не задан, как trunk) и число его VLAN с учётом «Все VLAN»; заполняются, только если запрошены (with_vlans).
    vlan_mode: str | None = None
    vlan_count: int = 0

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


def load_links(session: Session, *, with_vlans: bool = False) -> list[Link]:
    """Активные подключения с обоими концами. Число запросов постоянно: порты, их подинтерфейсы и устройства читаются пачками;
    VLAN портов (через services/port_vlans: с учётом «Все VLAN») читаются только по `with_vlans`."""
    rows = session.execute(
        select(Connection.id, Connection.source_interface_id, Connection.destination_interface_id)
        .where(Connection.is_active.is_(True))
        .order_by(Connection.id)
    ).all()
    port_ids = {port_id for row in rows for port_id in (row.source_interface_id, row.destination_interface_id)}
    ports: dict[str, tuple[str, str, bool, str | None]] = {}
    for batch in chunked(port_ids):
        for row in session.execute(
            select(
                DeviceInterface.id,
                DeviceInterface.name,
                DeviceInterface.physical_device_id,
                DeviceInterface.is_management,
                DeviceInterface.is_data_transfer,
                DeviceInterface.vlan_mode,
            ).where(DeviceInterface.id.in_(batch))
        ):
            ports[row.id] = (row.name, row.physical_device_id, bool(row.is_management or row.is_data_transfer), row.vlan_mode)
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
    labels = device_labels(session, {device_id for _, device_id, _, _ in ports.values()})
    vlans = effective_vlan_ids(session, port_ids) if with_vlans else {}

    def end(port_id: str) -> End:
        name, device_id, has_purpose, vlan_mode = ports[port_id]
        return End(
            port_id,
            name,
            device_id,
            labels.get(device_id, device_id),
            has_purpose or port_id in with_sub_purpose,
            vlan_mode,
            len(vlans.get(port_id, ())),
        )

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


def _access_ends(link: Link) -> list[End]:
    """Концы подключения с ЯВНО заданным режимом access. Режим не задан — порт считается trunk, и по нему судить нельзя: порты без VLAN
    бывают законными (L3, Fibre Channel, управление)."""
    return [end for end in link.ends if end.vlan_mode == VLAN_MODE_ACCESS]


@rule("connection_access_port_without_vlan", "Порт подключения в режиме access без VLAN", Severity.WARNING, Category.COMPLETENESS, sheet=3)
def check_access_without_vlan(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Порт access всегда несёт ровно один VLAN; без него столбцы «VLAN ID» и «VLAN Name» листа 3 пусты,
    если и у соседнего порта VLAN нет."""
    for link in load_links(session, with_vlans=True):
        lacking = [end for end in _access_ends(link) if end.vlan_count == 0]
        if lacking:
            where = ", ".join(end.title for end in lacking)
            yield spec.finding(
                ENTITY,
                link.id,
                link.name,
                f"{link.name}: порт {where} в режиме access без VLAN.",
                ports=[end.port_ref() for end in lacking],
            )


@rule(
    "connection_access_port_with_several_vlans",
    "Порт подключения в режиме access с несколькими VLAN",
    Severity.ERROR,
    Category.CONSISTENCY,
    sheet=3,
)
def check_access_with_several_vlans(session: Session, spec: RuleSpec) -> Iterable[Finding]:
    """Порт access не может нести больше одного VLAN: либо режим указан неверно (нужен trunk),
    либо лишние VLAN остались от старой настройки."""
    for link in load_links(session, with_vlans=True):
        overloaded = [end for end in _access_ends(link) if end.vlan_count > 1]
        if overloaded:
            where = ", ".join(f"{end.title} ({end.vlan_count} VLAN)" for end in overloaded)
            yield spec.finding(
                ENTITY,
                link.id,
                link.name,
                f"{link.name}: порт в режиме access несёт несколько VLAN — {where}.",
                ports=[end.port_ref() for end in overloaded],
                vlan_counts={end.port_id: end.vlan_count for end in overloaded},
            )
