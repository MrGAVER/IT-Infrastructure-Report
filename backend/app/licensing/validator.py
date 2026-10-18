"""Проверка ключа: подпись → содержимое → привязки → срок. Чистая функция без обращений к диску, сети и часам:
время и сведения о хосте передаются снаружи, поэтому каждое правило проверяется тестом без подмен окружения."""
from __future__ import annotations

import fnmatch
import ipaddress

from .codec import TokenError, decode_payload, parse_token, verify_signature
from .context import HostContext
from .keys import KeyRing
from .models import PRODUCT_ID, SECONDS_PER_DAY, Binding, LicensePayload, LicenseReport, LicenseState


def _address_matches(bind: Binding, host: HostContext) -> bool:
    exact = {ipaddress.ip_address(item) for item in bind.ips}
    networks = [ipaddress.ip_network(item) for item in bind.networks]
    return any(
        address in exact or any(address.version == network.version and address in network for network in networks)
        for address in host.addresses
    )


def _hostname_matches(bind: Binding, host: HostContext) -> bool:
    return any(
        fnmatch.fnmatchcase(candidate, pattern)
        for pattern in bind.hostnames
        for candidate in host.hostname_candidates
    )


def check_binding(bind: Binding, host: HostContext) -> tuple[str, ...]:
    """Имена измерений привязки, которые НЕ совпали ('address', 'hostname', 'param:<имя>'). Пусто — всё сходится.
    Измерение, которого нет у хоста (не удалось узнать адрес, нет machine_id), не совпадает: fail closed."""
    mismatched: list[str] = []
    if (bind.ips or bind.networks) and not _address_matches(bind, host):
        mismatched.append("address")
    if bind.hostnames and not _hostname_matches(bind, host):
        mismatched.append("hostname")
    for name, expected in sorted(bind.params.items()):
        if host.params.get(name) != expected:
            mismatched.append(f"param:{name}")
    return tuple(mismatched)


def _evaluate_period(payload: LicensePayload, now: int) -> LicenseReport:
    if now < payload.nbf:
        return LicenseReport(LicenseState.NOT_YET_VALID, payload=payload, now=now)
    if payload.exp is None or now <= payload.exp:
        return LicenseReport(LicenseState.VALID, payload=payload, now=now)
    if now <= payload.exp + payload.grace_days * SECONDS_PER_DAY:
        return LicenseReport(LicenseState.GRACE, payload=payload, now=now)
    return LicenseReport(LicenseState.EXPIRED, payload=payload, now=now)


def evaluate_token(token_text: str, *, ring: KeyRing, host: HostContext, now: int, product: str = PRODUCT_ID) -> LicenseReport:
    """Полная проверка токена на заданном хосте в момент ``now`` (секунды Unix, UTC)."""
    try:
        parsed = parse_token(token_text)
        verify_signature(ring, parsed)          # подлинность — до разбора содержимого
        payload = decode_payload(parsed.payload_bytes)
    except TokenError as exc:
        return LicenseReport(LicenseState.INVALID, reason=exc.code, now=now)
    if payload.product != product:
        return LicenseReport(LicenseState.INVALID, reason="wrong_product", payload=payload, now=now)
    mismatched = check_binding(payload.bind, host)
    if mismatched:
        return LicenseReport(LicenseState.MISMATCH, payload=payload, mismatched=mismatched, now=now)
    return _evaluate_period(payload, now)
