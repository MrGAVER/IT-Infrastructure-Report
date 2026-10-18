"""Модели лицензии: содержимое подписанного ключа и результат его проверки.

Модели «закрывают» формат: ``extra="forbid"`` — ключ с неизвестными полями (например, выпущенный более новой
версией вендорского CLI) не принимается молча с потерей части ограничений, а отвергается целиком. Любые
дополнительные данные ключа кладутся в ``claims``.
"""
from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

IPNetwork = Union[ipaddress.IPv4Network, ipaddress.IPv6Network]
IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]

PRODUCT_ID = "infra-registry"
SECONDS_PER_DAY = 86_400
MAX_LIST_ITEMS = 64          # ключ не должен раздуваться: короткий ключ проще передавать и вводить
MAX_CLAIMS_JSON_BYTES = 4_096
_PARAM_NAME = re.compile(r"^[a-z0-9_.-]{1,64}$")
_MAX_PARAM_VALUE = 256
_MAX_HOSTNAME = 253


def is_usable_host_address(address: IPAddress) -> bool:
    """Адрес, к которому имеет смысл привязывать ключ и который может быть у хоста.

    Петля, ``0.0.0.0``, link-local и multicast исключены: привязка к ним либо никогда не сработает, либо (127.0.0.0/8,
    0.0.0.0/0) подошла бы любому компьютеру и превратила бы «привязанный» ключ в непривязанный."""
    return not (address.is_loopback or address.is_unspecified or address.is_link_local or address.is_multicast)


class Binding(BaseModel):
    """Ограничения, при которых ключ действует. Каждое непустое измерение обязательно (И между измерениями).

    * ``ips`` + ``networks`` — ОДНО измерение «адрес»: хост подходит, если хотя бы один его адрес равен одному из
      ``ips`` или входит в одну из ``networks``;
    * ``hostnames`` — имя компьютера без учёта регистра, допускается шаблон (``srv-*``);
    * ``params`` — произвольные параметры: каждый должен совпасть со значением, которое сообщает хост
      (отпечаток машины ``machine_id``, ``os``, а также ``INFRA_REGISTRY_LICENSE_PARAM_<ИМЯ>``).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    ips: tuple[str, ...] = Field(default=(), max_length=MAX_LIST_ITEMS)
    networks: tuple[str, ...] = Field(default=(), max_length=MAX_LIST_ITEMS)
    hostnames: tuple[str, ...] = Field(default=(), max_length=MAX_LIST_ITEMS)
    params: dict[str, str] = Field(default_factory=dict)

    @field_validator("ips")
    @classmethod
    def _normalize_ips(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        result = []
        for raw in values:
            address = ipaddress.ip_address(raw.strip())
            if not is_usable_host_address(address):
                raise ValueError(f"адрес {address} не может быть привязкой (петля, неопределённый, link-local или multicast)")
            result.append(str(address))
        return tuple(result)

    @field_validator("networks")
    @classmethod
    def _normalize_networks(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        result = []
        for raw in values:
            network = ipaddress.ip_network(raw.strip(), strict=False)
            if network.prefixlen == 0 or not is_usable_host_address(network.network_address):
                raise ValueError(f"подсеть {network} не может быть привязкой (подходит любому хосту или не routable)")
            result.append(str(network))
        return tuple(result)

    @field_validator("hostnames")
    @classmethod
    def _normalize_hostnames(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        result = []
        for raw in values:
            name = raw.strip().lower()
            if not name or len(name) > _MAX_HOSTNAME:
                raise ValueError("имя хоста пустое или слишком длинное")
            if name.strip("*") == "":
                raise ValueError("шаблон имени, состоящий только из '*', подходит любому хосту")
            result.append(name)
        return tuple(result)

    @field_validator("params")
    @classmethod
    def _check_params(cls, values: dict[str, str]) -> dict[str, str]:
        if len(values) > MAX_LIST_ITEMS:
            raise ValueError("слишком много параметров привязки")
        for name, value in values.items():
            if not _PARAM_NAME.match(name):
                raise ValueError(f"недопустимое имя параметра {name!r}: латиница нижнего регистра, цифры, '_', '.', '-'")
            if len(value) > _MAX_PARAM_VALUE:
                raise ValueError(f"значение параметра {name!r} длиннее {_MAX_PARAM_VALUE} символов")
        return values

    @property
    def is_empty(self) -> bool:
        return not (self.ips or self.networks or self.hostnames or self.params)


class LicensePayload(BaseModel):
    """Подписываемое содержимое ключа. Время — целые секунды Unix (UTC), без часовых поясов.

    ``exp is None`` — постоянный ключ; иначе временный. ``grace_days`` — сколько дней после ``exp`` приложение
    остаётся полнофункциональным с предупреждением (окно на продление)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=8, max_length=64)
    product: str = PRODUCT_ID
    licensee: str = Field(min_length=1, max_length=200)
    iat: int = Field(ge=0)
    nbf: int = Field(ge=0)
    exp: int | None = Field(default=None, ge=0)
    grace_days: int = Field(default=0, ge=0, le=365)
    bind: Binding = Field(default_factory=Binding)
    claims: dict[str, Any] = Field(default_factory=dict)

    @field_validator("claims")
    @classmethod
    def _check_claims(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > MAX_CLAIMS_JSON_BYTES:
            raise ValueError(f"claims больше {MAX_CLAIMS_JSON_BYTES} байт")
        return value

    @model_validator(mode="after")
    def _check_period(self) -> "LicensePayload":
        if self.exp is not None and self.exp <= self.nbf:
            raise ValueError("срок окончания (exp) должен быть позже начала действия (nbf)")
        return self

    @property
    def kind(self) -> str:
        return "perpetual" if self.exp is None else "temporary"

    def canonical_json(self) -> bytes:
        """Детерминированная сериализация (сортировка ключей, без пробелов) — именно эти байты подписываются."""
        data = self.model_dump(mode="json")
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class LicenseState(str, Enum):
    VALID = "valid"
    GRACE = "grace"                    # срок истёк, но идёт льготный период — работает полностью, с предупреждением
    EXPIRED = "expired"
    NOT_YET_VALID = "not_yet_valid"
    MISSING = "missing"                # ключа нет
    INVALID = "invalid"                # повреждён, подпись не сошлась, неизвестный ключ подписи и т.п.
    MISMATCH = "mismatch"              # ключ подлинный, но выдан для другого хоста/параметров
    DISABLED = "disabled"              # принуждение выключено (сборка без публичных ключей, разработка)


_WRITE_ALLOWED = frozenset({LicenseState.VALID, LicenseState.GRACE, LicenseState.DISABLED})

_MESSAGES: dict[LicenseState, str] = {
    LicenseState.VALID: "Лицензия действует.",
    LicenseState.GRACE: "Срок лицензии истёк, действует льготный период. Продлите лицензию.",
    LicenseState.EXPIRED: "Срок действия лицензии истёк.",
    LicenseState.NOT_YET_VALID: "Срок действия лицензии ещё не начался.",
    LicenseState.MISSING: "Лицензионный ключ не установлен.",
    LicenseState.INVALID: "Лицензионный ключ недействителен.",
    LicenseState.MISMATCH: "Лицензионный ключ выдан для другого компьютера или другой конфигурации.",
    LicenseState.DISABLED: "Проверка лицензии отключена.",
}


def _iso(timestamp: int | None) -> str | None:
    return None if timestamp is None else datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


@dataclass(frozen=True)
class LicenseReport:
    """Итог проверки. ``reason`` — машинный код причины для INVALID (bad_signature, unknown_key, ...);
    ``mismatched`` — какие измерения привязки не совпали (имена, без ожидаемых значений)."""

    state: LicenseState
    reason: str = ""
    payload: LicensePayload | None = None
    mismatched: tuple[str, ...] = ()
    now: int = 0
    clock_rollback: bool = False

    @property
    def allows_writes(self) -> bool:
        return self.state in _WRITE_ALLOWED

    @property
    def message(self) -> str:
        return _MESSAGES[self.state]

    def to_public_dict(self) -> dict[str, Any]:
        payload = self.payload
        expires = payload.exp if payload else None
        data: dict[str, Any] = {
            "state": self.state.value,
            "reason": self.reason,
            "message": self.message,
            "allows_writes": self.allows_writes,
            "mismatched": list(self.mismatched),
            "clock_rollback": self.clock_rollback,
            "licensee": payload.licensee if payload else None,
            "license_id": payload.id if payload else None,
            "kind": payload.kind if payload else None,
            "issued_at": _iso(payload.iat) if payload else None,
            "not_before": _iso(payload.nbf) if payload else None,
            "expires_at": _iso(expires),
            "grace_until": _iso(expires + payload.grace_days * SECONDS_PER_DAY) if payload and expires is not None and payload.grace_days else None,
            "days_left": None if expires is None else (expires - self.now) // SECONDS_PER_DAY,
            "claims": dict(payload.claims) if payload else {},
            "bound_to": None,
        }
        if payload and not payload.bind.is_empty:
            bind = payload.bind
            data["bound_to"] = {
                "ips": list(bind.ips), "networks": list(bind.networks),
                "hostnames": list(bind.hostnames), "params": sorted(bind.params),
            }
        return data
