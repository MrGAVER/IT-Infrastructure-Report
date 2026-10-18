"""Что приложение знает о своём хосте — то, с чем сверяются привязки ключа.

Привязка к имени и IP — барьер против «скопировал каталог на другой компьютер», а не криптографическая гарантия:
имя и адрес администратор может сменить. Надёжнее ``machine_id`` (отпечаток идентификатора машины), но и он
поддаётся подмене на уровне ОС. Сильнее всего ограничивает срок ключа и то, что подделать сам ключ нельзя.

Для Docker (внутренние адреса контейнера и случайное имя) можно задать значения явно:
``INFRA_REGISTRY_LICENSE_HOSTNAME``, ``INFRA_REGISTRY_LICENSE_HOST_IPS`` (через запятую).
Произвольные параметры привязки: ``INFRA_REGISTRY_LICENSE_PARAM_<ИМЯ>=значение``.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import platform
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import IPAddress, is_usable_host_address

logger = logging.getLogger(__name__)

ENV_HOSTNAME = "INFRA_REGISTRY_LICENSE_HOSTNAME"
ENV_HOST_IPS = "INFRA_REGISTRY_LICENSE_HOST_IPS"
ENV_PARAM_PREFIX = "INFRA_REGISTRY_LICENSE_PARAM_"
# Адреса из TEST-NET (RFC 5737 / RFC 3849): к ним не отправляется ни одного пакета — connect() у UDP-сокета лишь
# выбирает маршрут по умолчанию и позволяет узнать адрес исходящего интерфейса.
_PROBE_V4 = "192.0.2.1"
_PROBE_V6 = "2001:db8::1"


@dataclass(frozen=True)
class HostContext:
    hostname: str
    addresses: frozenset[IPAddress] = frozenset()
    params: Mapping[str, str] = field(default_factory=dict)

    @property
    def hostname_candidates(self) -> frozenset[str]:
        """Полное имя и короткое (до первой точки): ``srv-205.corp.local`` подходит под ``srv-205``."""
        name = self.hostname.lower()
        return frozenset({name, name.split(".", 1)[0]})

    def describe(self) -> dict[str, Any]:
        """Сведения для запроса ключа у вендора (GET /api/v1/license и `InfraRegistry.exe --license-info`)."""
        return {
            "hostname": self.hostname,
            "ips": sorted(str(address) for address in self.addresses),
            "params": dict(sorted(self.params.items())),
        }


def _normalize(address: IPAddress) -> IPAddress:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return address.ipv4_mapped
    return address


def _parse_address(text: str) -> IPAddress | None:
    try:
        return _normalize(ipaddress.ip_address(text.split("%", 1)[0]))  # «fe80::1%eth0» — зона не часть адреса
    except ValueError:
        return None


def _addresses_from_hostname(hostname: str) -> set[str]:
    try:
        return {info[4][0] for info in socket.getaddrinfo(hostname, None)}
    except OSError:
        return set()


def _address_of_default_route(family: int, probe: str) -> set[str]:
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as sock:
            sock.connect((probe, 9))
            return {sock.getsockname()[0]}
    except OSError:
        return set()


def _addresses_from_psutil() -> set[str]:
    """Все интерфейсы — если установлен необязательный psutil (stdlib не умеет перечислять интерфейсы)."""
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return set()
    try:
        return {a.address for addrs in psutil.net_if_addrs().values() for a in addrs if a.family in (socket.AF_INET, socket.AF_INET6)}
    except OSError:
        return set()


def discover_host_addresses(hostname: str) -> frozenset[IPAddress]:
    raw = _addresses_from_hostname(hostname)
    raw |= _address_of_default_route(socket.AF_INET, _PROBE_V4)
    if socket.has_ipv6:
        raw |= _address_of_default_route(socket.AF_INET6, _PROBE_V6)
    raw |= _addresses_from_psutil()
    parsed = (_parse_address(text) for text in raw)
    return frozenset(address for address in parsed if address is not None and is_usable_host_address(address))


def read_machine_id() -> str | None:
    """Идентификатор машины из ОС (MachineGuid в Windows, /etc/machine-id в Linux) или None."""
    try:
        if platform.system() == "Windows":
            import winreg  # type: ignore[import-not-found]

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                return str(winreg.QueryValueEx(key, "MachineGuid")[0])
        for candidate in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            path = Path(candidate)
            if path.is_file():
                value = path.read_text(encoding="ascii", errors="ignore").strip()
                if value:
                    return value
    except OSError:
        logger.debug("Идентификатор машины недоступен", exc_info=True)
    return None


def fingerprint(raw_machine_id: str) -> str:
    """Отпечаток: исходный идентификатор машины ни в API, ни в ключ не попадает."""
    return hashlib.sha256(b"ris-machine-v1:" + raw_machine_id.encode("utf-8")).hexdigest()[:32]


def collect_host_context(env: Mapping[str, str] | None = None) -> HostContext:
    """Собрать сведения о хосте. Никогда не бросает исключений: недоступное измерение просто отсутствует,
    а ключ, привязанный к нему, не совпадёт (fail closed)."""
    env = os.environ if env is None else env
    hostname = (env.get(ENV_HOSTNAME) or socket.gethostname()).strip()

    override = [item.strip() for item in env.get(ENV_HOST_IPS, "").split(",") if item.strip()]
    if override:
        parsed = (_parse_address(item) for item in override)
        addresses = frozenset(address for address in parsed if address is not None and is_usable_host_address(address))
    else:
        addresses = discover_host_addresses(hostname)

    # Параметры из окружения — «токены конфигурации», их задаёт сам администратор. Встроенные (os, machine_id)
    # записываются ПОСЛЕ них и перекрывают одноимённые: иначе ключ с привязкой к machine_id обходился бы
    # одной переменной окружения.
    params: dict[str, str] = {
        name[len(ENV_PARAM_PREFIX):].lower(): value
        for name, value in env.items()
        if name.startswith(ENV_PARAM_PREFIX) and value
    }
    params["os"] = platform.system().lower()
    machine_id = read_machine_id()
    if machine_id:
        params["machine_id"] = fingerprint(machine_id)
    else:
        params.pop("machine_id", None)
    return HostContext(hostname=hostname, addresses=addresses, params=params)


ContextProvider = Callable[[], HostContext]
