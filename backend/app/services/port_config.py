"""Сверка конфигурации портов-соседей подключения: роль, режим порта и назначенные VLAN.

Конфигурация порта хранится на самом интерфейсе — роль (DeviceInterface.is_management /
is_data_transfer), режим (vlan_mode: access / trunk) и VLAN (связи interface_vlans) — это
единственный источник данных, из которого отчёты и схема сети берут «назначение линии связи» и
VLAN порта. Подключение соединяет два порта, и их конфигурации могут не совпадать: порт сервера —
порт управления, а порт коммутатора, куда он включён, — порт передачи данных; один конец линии —
trunk, другой — access; на концах транка разрешены разные наборы VLAN. Иногда это ошибка ввода,
иногда — осознанная конфигурация, поэтому расхождение не «чинится» молча, а получает статус:

    ok        — роль, режим и набор VLAN совпадают (или подключение неактивно и не участвует в проверке);
    mismatch  — что-то из этого различается, решение пользователя ещё не принято;
    approved  — различается, но пользователь одобрил именно это расхождение.

VLAN сравниваются по номеру (802.1Q-тегу), а не по записи справочника: один и тот же номер в
разных доменах VLAN — это один и тот же тег на линии.

Одобрение хранится как «подпись расхождения» — описание того, чем именно различаются порты, в
порядке «источник > назначение». Подпись содержит только различающиеся грани, поэтому подписи,
записанные до появления проверки режима и VLAN (`management>data`), остаются валидными для пар,
у которых различается одна лишь роль, а пара с ещё и не одобренным расхождением режима/VLAN
автоматически возвращается в «mismatch». Изменилась любая грань — подпись перестаёт совпадать, и
расхождение снова требует проверки. VLAN в подписи представлены отпечатком фиксированного размера
(транк может нести сотни VLAN — перечислять их в строке нельзя); отпечаток считается в Python и
в SQL (services/connection_query.py) по одной и той же формуле, соответствие проверяет
tests/test_connection_query.py.

Модуль намеренно чистый (без обращения к БД и без импорта serialization/crud): его используют
и enrich_connections(), и операции одобрения (services/connection_review.py).

Пример:
    server = PortConfig(PortRole.MANAGEMENT, "trunk", frozenset())
    switch = PortConfig(PortRole.DATA, "access", frozenset({10}))
    config_differences(server, switch)            # -> [ConfigFacet.ROLE, ConfigFacet.MODE, ConfigFacet.VLANS]
    evaluate_port_config(server, switch, None)    # -> PortConfigStatus.MISMATCH, пока не одобрено
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Protocol


class PortRole(str, Enum):
    NONE = "none"
    MANAGEMENT = "management"
    DATA = "data"
    MANAGEMENT_DATA = "management_data"


class PortConfigStatus(str, Enum):
    OK = "ok"
    MISMATCH = "mismatch"
    APPROVED = "approved"


class HasPortRoleFlags(Protocol):
    is_management: bool
    is_data_transfer: bool


class HasPortConfig(HasPortRoleFlags, Protocol):
    vlan_mode: str | None


class ConfigFacet(str, Enum):
    """Грань конфигурации порта, по которой пара портов может различаться."""

    ROLE = "role"
    MODE = "mode"
    VLANS = "vlans"


VLAN_MODE_ACCESS = "access"
VLAN_MODE_TRUNK = "trunk"
# Как у колонки DeviceInterface.vlan_mode (server_default): порт без явного режима — trunk.
DEFAULT_VLAN_MODE = VLAN_MODE_TRUNK

# Отпечаток набора VLAN — одно целое число: сумма «перемешанных» номеров + число VLAN в старших
# разрядах. Не зависит от порядка и размера набора и считается в SQL обычными SUM/COUNT и целочисленной
# арифметикой (без string_agg/group_concat: у них разный синтаксис по СУБД и нет гарантии порядка).
# Перемешивание нелинейное (аффинный шаг и два возведения в квадрат по простому модулю 2^31-1): у
# линейного `n*K mod M` наборы с одинаковой суммой номеров, например {1,5,6} и {2,3,7}, почти всегда
# давали бы один отпечаток. Все промежуточные значения < 2^62 — без переполнения знакового int64
# и у SQLite, и у PostgreSQL. Это не криптографический хеш: два РАЗНЫХ набора дают одинаковый
# отпечаток с вероятностью порядка 2^-32..2^-43 (зависит от размера наборов) — тогда различие
# VLAN у такой пары не будет замечено; для сверки инвентаря это пренебрежимо мало.
FINGERPRINT_MODULUS = 2_147_483_647  # простое число Мерсенна 2^31-1
FINGERPRINT_AFFINE = (1_103_515_245, 12_345)  # шаг 1: x = (n * a + b) mod M
FINGERPRINT_SQUARE_ADDENDS = (1_013_904_223, 1_664_525)  # шаги 2..: x = (x * x + c) mod M
FINGERPRINT_COUNT_WEIGHT = 1 << 44  # сумма ≤ 4094·2^31 < 2^43 — разряды числа VLAN не пересекаются


def vlan_hash(number: int) -> int:
    """«Перемешанный» номер VLAN. Формула продублирована в SQL — см.
    connection_query._vlan_fingerprint_sql; менять только вместе."""
    multiplier, offset = FINGERPRINT_AFFINE
    value = (number * multiplier + offset) % FINGERPRINT_MODULUS
    for addend in FINGERPRINT_SQUARE_ADDENDS:
        value = (value * value + addend) % FINGERPRINT_MODULUS
    return value


def vlan_fingerprint(vlans: Iterable[int]) -> int:
    """Отпечаток набора номеров VLAN (дубликаты не учитываются)."""
    unique = set(vlans)
    return sum(vlan_hash(n) for n in unique) + len(unique) * FINGERPRINT_COUNT_WEIGHT


@dataclass(frozen=True)
class PortConfig:
    """Снимок конфигурации порта для сверки: роль, режим (access / trunk), номера VLAN."""

    role: PortRole = PortRole.NONE
    mode: str = DEFAULT_VLAN_MODE
    vlans: frozenset[int] = frozenset()


PORT_ROLE_LABELS: dict[PortRole, str] = {
    PortRole.NONE: "не задано",
    PortRole.MANAGEMENT: "Управление активами",
    PortRole.DATA: "Передача данных",
    PortRole.MANAGEMENT_DATA: "Передача данных и управление активами",
}


def role_from_flags(is_management: bool, is_data_transfer: bool) -> PortRole:
    if is_management and is_data_transfer:
        return PortRole.MANAGEMENT_DATA
    if is_management:
        return PortRole.MANAGEMENT
    if is_data_transfer:
        return PortRole.DATA
    return PortRole.NONE


def port_role(iface: HasPortRoleFlags) -> PortRole:
    return role_from_flags(bool(iface.is_management), bool(iface.is_data_transfer))


def port_config_of(iface: HasPortConfig, vlans: Iterable[int] = ()) -> PortConfig:
    """Снимок порта. VLAN передаются отдельно: связи interface_vlans — не атрибут DeviceInterface,
    а загружаются пакетом на все порты сразу (services/port_config_db.py)."""
    return PortConfig(port_role(iface), iface.vlan_mode or DEFAULT_VLAN_MODE, frozenset(vlans))


def config_differences(source: PortConfig, destination: PortConfig) -> list[ConfigFacet]:
    """Грани, по которым порты различаются, в порядке «роль, режим, VLAN»; пусто — конфигурации
    совпадают."""
    facets: list[ConfigFacet] = []
    if source.role != destination.role:
        facets.append(ConfigFacet.ROLE)
    if source.mode != destination.mode:
        facets.append(ConfigFacet.MODE)
    if source.vlans != destination.vlans:
        facets.append(ConfigFacet.VLANS)
    return facets


def approval_signature(source: PortConfig, destination: PortConfig) -> str:
    """Подпись расхождения «источник>назначение» — только по различающимся граням:

        роль:   `management>data`            (без префикса — формат прежних подписей)
        режим:  `|mode:trunk>access`
        VLAN:   `|vlan:<отпечаток источника>><отпечаток назначения>`

    Порядок важен: пара «управление>данные» и «данные>управление» — разные расхождения,
    одобрение одного не распространяется на другое. Для совпадающих конфигураций — пустая строка.
    Тот же формат строит SQL (connection_query._Joined.signature)."""
    signature = ""
    if source.role != destination.role:
        signature += f"{source.role.value}>{destination.role.value}"
    if source.mode != destination.mode:
        signature += f"|mode:{source.mode}>{destination.mode}"
    if source.vlans != destination.vlans:
        signature += f"|vlan:{vlan_fingerprint(source.vlans)}>{vlan_fingerprint(destination.vlans)}"
    return signature


def evaluate_port_config(
    source: PortConfig,
    destination: PortConfig,
    approved_signature: str | None,
    *,
    is_active: bool = True,
) -> PortConfigStatus:
    """Статус подключения. Неактивное подключение не несёт трафика — его порты могут быть в
    процессе перенастройки, поэтому оно не считается расхождением."""
    if not is_active or not config_differences(source, destination):
        return PortConfigStatus.OK
    if approved_signature and approved_signature == approval_signature(source, destination):
        return PortConfigStatus.APPROVED
    return PortConfigStatus.MISMATCH
