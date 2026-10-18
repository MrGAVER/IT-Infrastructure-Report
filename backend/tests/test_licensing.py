"""Тесты лицензирования (app/licensing, api/license.py, tools/license_admin.py).

Ключи подписи здесь настоящие (Ed25519, генерируются на каждый прогон), а время и хост передаются явно — поэтому
каждое правило проверяется без подмены часов и сети. Запуск: pytest backend/tests/test_licensing.py -v
"""
from __future__ import annotations

import importlib.util
import ipaddress
import json
import os
import stat
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.license import router as license_router
from app.licensing import context as context_module
from app.licensing.clock_guard import ClockGuard, derive_secret
from app.licensing.codec import _signed_message, b64url_decode, b64url_encode, sign_token
from app.licensing.context import HostContext, collect_host_context, fingerprint
from app.licensing.keys import KeyRing, KeyRingError, export_public_key
from app.licensing.manager import LicenseActivationError, LicenseManager, LicenseStorageError, resolve_enforcement
from app.licensing.middleware import LicenseGateMiddleware
from app.licensing.models import SECONDS_PER_DAY, Binding, LicensePayload, LicenseState
from app.licensing.validator import evaluate_token

NOW = 1_800_000_000
DAY = SECONDS_PER_DAY


def _ips(*texts: str) -> frozenset:
    return frozenset(ipaddress.ip_address(text) for text in texts)


HOST = HostContext(
    hostname="SRV-205.corp.local",
    addresses=_ips("10.20.1.5", "192.168.1.205"),
    params={"os": "linux", "machine_id": "abc123", "org": "ООО Тест"},
)


@pytest.fixture(scope="module")
def vendor_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.generate()


@pytest.fixture(scope="module")
def ring(vendor_key) -> KeyRing:
    return KeyRing({"k1": export_public_key(vendor_key)})


def make_token(key: Ed25519PrivateKey, *, kid: str = "k1", bind: dict | None = None, **fields) -> str:
    base = {"id": "lic-00000001", "licensee": "ООО Тест", "iat": NOW - 365 * DAY, "nbf": NOW - 365 * DAY, "exp": None}
    return sign_token(key, kid, LicensePayload(**{**base, **fields}, bind=Binding(**(bind or {}))))


def evaluate(token: str, ring: KeyRing, *, host: HostContext = HOST, now: int = NOW):
    return evaluate_token(token, ring=ring, host=host, now=now)


def forge_token(key: Ed25519PrivateKey, payload: dict, *, kid: str = "k1") -> str:
    """Корректно подписанный токен с произвольным JSON — как если бы вендорский CLI выпустил его другой версией."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = key.sign(_signed_message(kid, body))
    return f"RIS1.{kid}.{b64url_encode(body)}.{b64url_encode(signature)}"


# --- срок: постоянные и временные ключи --------------------------------------------------------------------

def test_perpetual_key_without_binding_is_valid_forever(vendor_key, ring):
    token = make_token(vendor_key)
    for now in (NOW, NOW + 50 * 365 * DAY):
        report = evaluate(token, ring, now=now)
        assert report.state is LicenseState.VALID
        assert report.payload.kind == "perpetual"
    assert report.to_public_dict()["expires_at"] is None


@pytest.mark.parametrize("now_offset, grace_days, expected", [
    (-1, 0, LicenseState.NOT_YET_VALID),     # раньше начала действия
    (0, 0, LicenseState.VALID),              # ровно в момент exp ключ ещё действует (граница включена)
    (1, 0, LicenseState.EXPIRED),            # секунда после exp без льготного периода
    (DAY, 3, LicenseState.GRACE),            # внутри льготного периода
    (3 * DAY, 3, LicenseState.GRACE),        # граница льготного периода включена
    (3 * DAY + 1, 3, LicenseState.EXPIRED),
])
def test_temporary_key_period_boundaries(vendor_key, ring, now_offset, grace_days, expected):
    expires = NOW + 10 * DAY
    token = make_token(vendor_key, nbf=NOW, exp=expires, grace_days=grace_days)
    now = NOW - 1 if expected is LicenseState.NOT_YET_VALID else expires + now_offset
    report = evaluate(token, ring, now=now)
    assert report.state is expected
    assert report.allows_writes is (expected in (LicenseState.VALID, LicenseState.GRACE))


# --- подделка и повреждение --------------------------------------------------------------------------------

def test_editing_signed_payload_invalidates_signature(vendor_key, ring):
    """Главный сценарий взлома: продлить срок правкой содержимого ключа."""
    token = make_token(vendor_key, exp=NOW + DAY)
    prefix, kid, payload_part, signature_part = token.split(".")
    data = json.loads(b64url_decode(payload_part))
    data["exp"] = NOW + 100 * 365 * DAY
    forged = ".".join((prefix, kid, b64url_encode(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()), signature_part))
    report = evaluate(forged, ring)
    assert (report.state, report.reason) == (LicenseState.INVALID, "bad_signature")


def test_token_signed_by_foreign_key_is_rejected(ring):
    attacker = Ed25519PrivateKey.generate()
    report = evaluate(make_token(attacker), ring)
    assert (report.state, report.reason) == (LicenseState.INVALID, "bad_signature")


def test_signature_is_bound_to_key_id(vendor_key):
    """Подпись нельзя «перенести» на другой kid, даже если за обоими стоит один и тот же публичный ключ
    (так выглядит ротация): идентификатор ключа входит в подписываемое сообщение."""
    public = export_public_key(vendor_key)
    same_key_two_ids = KeyRing({"k1": public, "k2": public})
    token = make_token(vendor_key, kid="k1")
    renamed = token.replace("RIS1.k1.", "RIS1.k2.", 1)
    assert evaluate(renamed, same_key_two_ids).reason == "bad_signature"
    assert evaluate(token, same_key_two_ids).state is LicenseState.VALID


def test_unknown_key_id_is_rejected(vendor_key, ring):
    assert evaluate(make_token(vendor_key, kid="k9"), ring).reason == "unknown_key"


@pytest.mark.parametrize("garbage, reason", [
    ("", "empty"),
    ("   \n  ", "empty"),
    ("not a license", "malformed"),
    ("RIS2.k1.AAAA.BBBB", "malformed"),
    ("RIS1.k1.@@@@.BBBB", "malformed"),
    ("RIS1.k1.AAAA", "malformed"),
    ("A" * 20_000, "too_long"),
])
def test_garbage_input_never_raises(ring, garbage, reason):
    report = evaluate(garbage, ring)
    assert (report.state, report.reason) == (LicenseState.INVALID, reason)


def test_token_tolerates_armor_and_line_breaks(vendor_key, ring):
    token = make_token(vendor_key)
    wrapped = "-----BEGIN RIS LICENSE-----\n" + "\n".join(token[i:i + 40] for i in range(0, len(token), 40)) + "\n-----END RIS LICENSE-----\n"
    assert evaluate(wrapped, ring).state is LicenseState.VALID


@pytest.mark.parametrize("payload, reason", [
    ({"id": "lic-00000001", "licensee": "X", "iat": 1, "nbf": 1, "exp": None, "turbo": True}, "bad_payload"),        # неизвестное поле
    ({"id": "lic-00000001", "licensee": "X", "iat": 1, "nbf": 100, "exp": 50}, "bad_payload"),                       # exp раньше nbf
    ({"id": "lic-00000001", "licensee": "X", "iat": 1, "nbf": 1, "bind": {"networks": ["0.0.0.0/0"]}}, "bad_payload"),   # «привязка» ко всем
    ({"id": "lic-00000001", "licensee": "X", "iat": 1, "nbf": 1, "bind": {"ips": ["127.0.0.1"]}}, "bad_payload"),
    ({"id": "lic-00000001", "licensee": "X", "iat": 1, "nbf": 1, "bind": {"hostnames": ["*"]}}, "bad_payload"),
    ({"id": "lic-00000001", "licensee": "X", "iat": 1, "nbf": 1, "bind": {"dns": ["a"]}}, "bad_payload"),           # неизвестное измерение
    ({"id": "lic-00000001", "licensee": "X", "iat": 1, "nbf": 1, "product": "other-product"}, "wrong_product"),
])
def test_correctly_signed_but_unsafe_payload_fails_closed(vendor_key, ring, payload, reason):
    assert evaluate(forge_token(vendor_key, payload), ring).reason == reason


def test_key_ring_rejects_broken_public_key():
    with pytest.raises(KeyRingError):
        KeyRing({"k1": b64url_encode(b"too short")})
    with pytest.raises(KeyRingError):
        KeyRing({"bad kid!": "A" * 43})


# --- привязки ----------------------------------------------------------------------------------------------

def _host(hostname="srv-205", addresses=("10.20.1.5",), **params) -> HostContext:
    return HostContext(hostname=hostname, addresses=_ips(*addresses), params=params)


@pytest.mark.parametrize("bind, host, mismatched", [
    ({}, _host(), ()),                                                                # без привязок
    ({"ips": ["10.20.1.5"]}, _host(), ()),                                            # точный адрес
    ({"ips": ["10.20.1.6"]}, _host(), ("address",)),
    ({"networks": ["10.20.0.0/16"]}, _host(), ()),                                    # подсеть
    ({"networks": ["10.30.0.0/16"]}, _host(), ("address",)),
    ({"networks": ["10.20.1.99/16"]}, _host(), ()),                                   # биты хоста в маске допустимы
    ({"ips": ["10.99.0.1"], "networks": ["10.20.0.0/16"]}, _host(), ()),              # ips ИЛИ networks — одно измерение
    ({"networks": ["192.168.1.0/24"]}, _host(addresses=("10.20.1.5", "192.168.1.205")), ()),   # любой из адресов хоста
    ({"networks": ["fd00::/8"]}, _host(), ("address",)),                              # семейства адресов не смешиваются
    ({"ips": ["10.20.1.5"]}, _host(addresses=()), ("address",)),                      # адреса хоста неизвестны — fail closed
    ({"hostnames": ["srv-205"]}, _host(hostname="SRV-205"), ()),                      # регистр не важен
    ({"hostnames": ["srv-205"]}, _host(hostname="srv-205.corp.local"), ()),          # короткое имя
    ({"hostnames": ["srv-*"]}, _host(hostname="srv-300.corp.local"), ()),             # шаблон
    ({"hostnames": ["pc-*"]}, _host(hostname="srv-300"), ("hostname",)),
    ({"params": {"machine_id": "abc"}}, _host(machine_id="abc"), ()),
    ({"params": {"machine_id": "abc"}}, _host(machine_id="xyz"), ("param:machine_id",)),
    ({"params": {"machine_id": "abc"}}, _host(), ("param:machine_id",)),              # параметра нет у хоста — fail closed
    ({"params": {"org": "ООО Тест"}}, _host(org="ООО Тест"), ()),
    ({"ips": ["10.20.1.5"], "hostnames": ["pc-*"], "params": {"os": "windows"}}, _host(os="linux"), ("hostname", "param:os")),   # И между измерениями
])
def test_binding_matrix(vendor_key, ring, bind, host, mismatched):
    report = evaluate(make_token(vendor_key, bind=bind), ring, host=host)
    assert report.mismatched == mismatched
    assert report.state is (LicenseState.MISMATCH if mismatched else LicenseState.VALID)


def test_binding_is_checked_even_if_key_is_expired(vendor_key, ring):
    """Чужой ключ не должен сообщать «просрочен»: сначала привязка, потом срок."""
    token = make_token(vendor_key, exp=NOW - DAY, bind={"hostnames": ["pc-*"]})
    assert evaluate(token, ring, host=_host(hostname="srv-1")).state is LicenseState.MISMATCH


# --- сведения о хосте --------------------------------------------------------------------------------------

def test_host_context_env_overrides_and_filters(monkeypatch):
    env = {
        "INFRA_REGISTRY_LICENSE_HOSTNAME": " reestr-01 ",
        "INFRA_REGISTRY_LICENSE_HOST_IPS": "10.0.0.7, 127.0.0.1, ::ffff:10.0.0.8, 169.254.1.1, junk",
        "INFRA_REGISTRY_LICENSE_PARAM_ORG": "ООО Тест",
    }
    host = collect_host_context(env)
    assert host.hostname == "reestr-01"
    assert host.addresses == _ips("10.0.0.7", "10.0.0.8")           # петля, link-local и мусор отброшены, v4-mapped приведён
    assert host.params["org"] == "ООО Тест"


def test_builtin_params_cannot_be_overridden_from_environment(monkeypatch):
    """Иначе ключ, привязанный к machine_id, обходился бы одной переменной окружения."""
    monkeypatch.setattr(context_module, "read_machine_id", lambda: "raw-machine-id")
    host = collect_host_context({"INFRA_REGISTRY_LICENSE_PARAM_MACHINE_ID": "spoofed", "INFRA_REGISTRY_LICENSE_PARAM_OS": "spoofed"})
    assert host.params["machine_id"] == fingerprint("raw-machine-id") != "spoofed"
    assert host.params["os"] != "spoofed"
    assert "raw-machine-id" not in json.dumps(host.describe())      # исходный идентификатор наружу не уходит


def test_host_discovery_survives_broken_network(monkeypatch):
    def boom(*_a, **_k):
        raise OSError("network is down")

    monkeypatch.setattr(context_module.socket, "getaddrinfo", boom)
    monkeypatch.setattr(context_module.socket, "socket", boom)
    monkeypatch.setattr(context_module, "_addresses_from_psutil", lambda: set())     # необязательный psutil есть не везде
    host = collect_host_context({})
    assert host.addresses == frozenset()      # не исключение: ключ с привязкой к адресу просто не совпадёт


# --- защита от отката часов --------------------------------------------------------------------------------

def test_clock_guard_neutralizes_rollback(tmp_path):
    guard = ClockGuard(tmp_path / "state.json", b"secret", tolerance_seconds=3600)
    assert guard.observe(NOW).effective_now == NOW
    rolled = guard.observe(NOW - 10 * DAY)
    assert (rolled.effective_now, rolled.rolled_back) == (NOW, True)         # время не идёт назад
    small = guard.observe(NOW - 60)
    assert (small.effective_now, small.rolled_back) == (NOW, False)          # мелкая коррекция часов — без тревоги, но и без отката
    assert guard.observe(NOW + 5 * DAY).effective_now == NOW + 5 * DAY


def test_clock_guard_state_survives_restart_and_detects_hand_edits(tmp_path):
    path = tmp_path / "state.json"
    first = ClockGuard(path, b"secret")
    first.observe(NOW)
    first.flush()
    assert ClockGuard(path, b"secret").observe(NOW - DAY).effective_now == NOW     # после перезапуска отметка на месте

    data = json.loads(path.read_text())
    data["hwm"] = NOW + 1000 * DAY                                                 # правка файла без пересчёта подписи
    path.write_text(json.dumps(data))
    assert ClockGuard(path, b"secret").observe(NOW).effective_now == NOW           # изменённый файл игнорируется
    path.write_text("{broken json")
    assert ClockGuard(path, b"secret").observe(NOW).effective_now == NOW           # повреждённый — тоже, без исключения


def test_clock_guard_unwritable_state_is_not_fatal(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    guard = ClockGuard(blocker / "state.json", b"secret")                          # «каталог» — на самом деле файл
    assert guard.observe(NOW).effective_now == NOW
    guard.flush()


# --- менеджер ----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("setting, has_keys, frozen, expected", [
    ("auto", False, False, False),       # в сборке нет ключей — приложение работает как до появления лицензий
    ("auto", True, False, True),
    ("", True, False, True),
    ("on", False, False, True),          # «on» без ключей: любой ключ будет отвергнут
    ("off", True, False, False),         # отключение допустимо для разработки и Docker…
    ("off", True, True, True),           # …но не в собранном EXE
    ("off", False, True, False),
])
def test_resolve_enforcement(setting, has_keys, frozen, expected):
    assert resolve_enforcement(setting, has_keys=has_keys, frozen=frozen) is expected


def test_resolve_enforcement_rejects_typos():
    with pytest.raises(ValueError):
        resolve_enforcement("onn", has_keys=True, frozen=False)


class FakeClock:
    def __init__(self, now: int) -> None:
        self.now = now

    def __call__(self) -> float:
        return float(self.now)


def make_manager(ring, tmp_path, *, clock=None, host=HOST, guard=True, env_token="", recheck=0, **kwargs) -> LicenseManager:
    clock = clock or FakeClock(NOW)
    return LicenseManager(
        ring=ring, key_file=tmp_path / "license.key", env_token=env_token, context_provider=lambda: host,
        clock_guard=ClockGuard(tmp_path / "state.json", b"s") if guard else None,
        recheck_seconds=recheck, time_source=clock, **kwargs,
    )


def test_manager_key_sources_and_priority(vendor_key, ring, tmp_path):
    manager = make_manager(ring, tmp_path)
    assert manager.report().state is LicenseState.MISSING
    env_only = make_manager(ring, tmp_path, env_token=make_token(vendor_key, licensee="Из окружения"))
    assert env_only.report().payload.licensee == "Из окружения"
    (tmp_path / "license.key").write_text(make_token(vendor_key, licensee="Из файла") + "\n")
    assert env_only.report().payload.licensee == "Из файла"          # файл приоритетнее окружения


def test_activate_valid_key_persists_it_privately(vendor_key, ring, tmp_path):
    manager = make_manager(ring, tmp_path)
    report = manager.activate("\n  " + make_token(vendor_key, exp=NOW + DAY) + "  \n")
    assert report.state is LicenseState.VALID
    key_file = tmp_path / "license.key"
    assert key_file.read_text().strip().startswith("RIS1.k1.")
    if os.name == "posix":
        assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    assert make_manager(ring, tmp_path).report().state is LicenseState.VALID      # новый процесс видит ключ


@pytest.mark.parametrize("make_bad, state, reason", [
    (lambda key: make_token(Ed25519PrivateKey.generate()), LicenseState.INVALID, "bad_signature"),
    (lambda key: make_token(key, exp=NOW - 10 * DAY), LicenseState.EXPIRED, ""),
    (lambda key: make_token(key, bind={"hostnames": ["pc-*"]}), LicenseState.MISMATCH, ""),
    (lambda key: "garbage", LicenseState.INVALID, "malformed"),
])
def test_failed_activation_keeps_the_installed_key(vendor_key, ring, tmp_path, make_bad, state, reason):
    manager = make_manager(ring, tmp_path)
    good = make_token(vendor_key, licensee="Рабочий ключ")
    manager.activate(good)
    with pytest.raises(LicenseActivationError) as excinfo:
        manager.activate(make_bad(vendor_key))
    assert (excinfo.value.report.state, excinfo.value.report.reason) == (state, reason)
    assert manager.report().payload.licensee == "Рабочий ключ"
    assert (tmp_path / "license.key").read_text().strip() == good


def test_activation_without_public_keys_is_refused(vendor_key, tmp_path):
    manager = make_manager(KeyRing({}), tmp_path)
    with pytest.raises(LicenseActivationError) as excinfo:
        manager.activate(make_token(vendor_key))
    assert excinfo.value.report.reason == "no_public_keys"


def test_activation_reports_storage_failure(vendor_key, ring, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    manager = LicenseManager(ring=ring, key_file=blocker / "license.key", context_provider=lambda: HOST, time_source=FakeClock(NOW))
    with pytest.raises(LicenseStorageError):
        manager.activate(make_token(vendor_key))


def test_expiry_is_picked_up_without_restart_and_rollback_does_not_revive_the_key(vendor_key, ring, tmp_path):
    clock = FakeClock(NOW)
    manager = make_manager(ring, tmp_path, clock=clock)
    manager.activate(make_token(vendor_key, exp=NOW + 100))
    assert manager.report().state is LicenseState.VALID
    clock.now = NOW + 200
    assert manager.report().state is LicenseState.EXPIRED
    clock.now = NOW - 5 * DAY                                      # «откатили» часы, чтобы продлить ключ
    report = manager.report()
    assert (report.state, report.clock_rollback) == (LicenseState.EXPIRED, True)


def test_result_is_cached_between_rechecks(vendor_key, ring, tmp_path):
    calls = []

    def provider() -> HostContext:
        calls.append(1)
        return HOST

    manager = LicenseManager(ring=ring, key_file=tmp_path / "license.key", env_token=make_token(vendor_key),
                             context_provider=provider, recheck_seconds=60, time_source=FakeClock(NOW))
    for _ in range(5):
        assert manager.report().state is LicenseState.VALID
    assert len(calls) == 1
    manager.invalidate()
    manager.report()
    assert len(calls) == 2


def test_disabled_enforcement_never_touches_the_key(ring, tmp_path):
    manager = make_manager(ring, tmp_path, enforcement=False)
    report = manager.report()
    assert (report.state, report.allows_writes) == (LicenseState.DISABLED, True)


# --- HTTP: middleware и эндпоинты --------------------------------------------------------------------------

def make_app(manager: LicenseManager, mode: str = "readonly") -> FastAPI:
    app = FastAPI()
    app.state.license_manager = manager
    app.add_middleware(LicenseGateMiddleware, manager=manager, mode=mode)
    app.include_router(license_router)

    @app.get("/api/v1/items")
    def read_items():
        return {"ok": True}

    @app.post("/api/v1/items")
    def write_items():
        return {"ok": True}

    @app.post("/api/v1/auth/login")
    def login():
        return {"token": "t"}

    @app.get("/api/v1/health")
    def health():
        return {"status": "ok"}

    @app.get("/{path:path}")
    def spa(path: str):
        return {"spa": True}

    return app


@pytest.fixture()
def licensed_client(vendor_key, ring, tmp_path):
    def build(*, mode="readonly", activate=None, address="127.0.0.1"):
        manager = make_manager(ring, tmp_path)
        if activate is not None:
            manager.activate(activate)
        return TestClient(make_app(manager, mode), client=(address, 50000))
    return build


def test_without_license_readonly_mode_allows_reading_but_blocks_writes(licensed_client):
    http = licensed_client()
    assert http.get("/api/v1/items").status_code == 200
    blocked = http.post("/api/v1/items")
    assert blocked.status_code == 402
    assert blocked.json()["detail"]["code"] == "LICENSE_REQUIRED"
    assert blocked.json()["detail"]["license_state"] == "missing"
    # то, без чего лицензию не активировать, и оболочка интерфейса — доступны всегда
    assert http.get("/").status_code == 200
    assert http.get("/api/v1/health").status_code == 200
    assert http.post("/api/v1/auth/login").status_code == 200
    assert http.get("/api/v1/license").json()["state"] == "missing"


def test_block_mode_closes_the_whole_api_but_not_the_shell(licensed_client):
    http = licensed_client(mode="block")
    assert http.get("/api/v1/items").status_code == 402
    assert http.get("/").status_code == 200
    assert http.get("/api/v1/license").status_code == 200


def test_valid_license_opens_everything(vendor_key, licensed_client):
    http = licensed_client(activate=make_token(vendor_key, exp=NOW + DAY))
    assert http.post("/api/v1/items").status_code == 200


def test_activation_through_api_unlocks_writes_immediately(vendor_key, licensed_client):
    http = licensed_client()
    assert http.post("/api/v1/items").status_code == 402
    key = make_token(vendor_key, licensee="ООО Тест", exp=NOW + 30 * DAY, grace_days=5, bind={"networks": ["10.20.0.0/16"]}, claims={"edition": "pro"})
    response = http.post("/api/v1/license", json={"key": key})
    assert response.status_code == 200, response.text
    status = response.json()
    assert (status["state"], status["kind"], status["licensee"], status["claims"]) == ("valid", "temporary", "ООО Тест", {"edition": "pro"})
    assert status["days_left"] == 30
    assert status["host"]["hostname"] == HOST.hostname
    assert key not in response.text and key.split(".")[-1] not in response.text      # ключ и подпись не возвращаются
    assert http.post("/api/v1/items").status_code == 200                              # кэш сброшен активацией


def test_activation_of_foreign_key_returns_422_with_reasons(vendor_key, licensed_client):
    http = licensed_client()
    wrong_host = http.post("/api/v1/license", json={"key": make_token(vendor_key, bind={"hostnames": ["pc-*"]})})
    assert wrong_host.status_code == 422
    detail = wrong_host.json()["detail"]
    assert (detail["code"], detail["license_state"], detail["mismatched"]) == ("LICENSE_INVALID", "mismatch", ["hostname"])
    forged = http.post("/api/v1/license", json={"key": make_token(Ed25519PrivateKey.generate())})
    assert forged.json()["detail"]["reason"] == "bad_signature"
    assert http.post("/api/v1/items").status_code == 402                              # ничего не установилось


def test_activation_requires_setup_access(vendor_key, licensed_client):
    """С чужого адреса (аутентификация выключена) ключ установить нельзя — как и первичная настройка."""
    http = licensed_client(address="10.1.2.3")
    response = http.post("/api/v1/license", json={"key": make_token(vendor_key)})
    assert response.status_code == 403
    assert http.get("/api/v1/license").status_code == 200       # состояние читать можно


def test_gate_rejects_unknown_mode(ring, tmp_path):
    with pytest.raises(ValueError):
        LicenseGateMiddleware(FastAPI(), manager=make_manager(ring, tmp_path), mode="hard")


def test_real_application_exposes_license_status(client):
    """Подключение к настоящему приложению: в репозитории публичных ключей нет — принуждение выключено."""
    body = client.get("/api/v1/license").json()
    assert (body["state"], body["enforcement"], body["allows_writes"]) == ("disabled", False, True)
    assert body["host"]["hostname"]


# --- вендорский CLI ----------------------------------------------------------------------------------------

@pytest.fixture()
def cli():
    path = Path(__file__).resolve().parents[2] / "tools" / "license_admin.py"
    spec = importlib.util.spec_from_file_location("license_admin_under_test", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def test_cli_full_cycle_with_encrypted_key(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LICENSE_KEY_PASSPHRASE", "correct horse battery staple")
    keys_dir = tmp_path / "keys"
    assert cli.main(["gen-keypair", "--kid", "k7", "--out-dir", str(keys_dir)]) == 0
    public = next(line for line in capsys.readouterr().out.splitlines() if '"k7"' in line).split('"')[3]
    private_pem = keys_dir / "k7.private.pem"
    assert b"ENCRYPTED" in private_pem.read_bytes()
    assert cli.main(["gen-keypair", "--kid", "k7", "--out-dir", str(keys_dir)]) == 2        # существующий ключ не перезаписывается

    out = tmp_path / "customer.lic"
    ledger = tmp_path / "issued.jsonl"
    issue = ["issue", "--kid", "k7", "--private-key", str(private_pem), "--licensee", "ООО Клиент", "--ledger", str(ledger), "--out", str(out)]
    assert cli.main([*issue, "--days", "30", "--network", "10.20.0.0/16", "--hostname", "srv-*", "--claim", "max_devices=500"]) == 0
    assert json.loads(ledger.read_text().splitlines()[0])["claims"] == {"max_devices": 500}

    inspect = ["inspect", str(out), "--public-key", f"k7={public}"]
    capsys.readouterr()
    assert cli.main([*inspect, "--host-ip", "10.20.3.4", "--host-name", "srv-1"]) == 0
    assert cli.main([*inspect, "--host-ip", "172.16.0.1", "--host-name", "srv-1"]) == 1     # не та подсеть
    assert cli.main([*inspect, "--host-ip", "10.20.3.4", "--host-name", "srv-1", "--now", "2099-01-01"]) == 1   # срок вышел


def test_cli_refuses_unbound_key_without_explicit_flag_and_bad_input(cli, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("LICENSE_KEY_PASSPHRASE", raising=False)
    keys_dir = tmp_path / "keys"
    cli.main(["gen-keypair", "--out-dir", str(keys_dir)])
    base = ["issue", "--private-key", str(keys_dir / "k1.private.pem"), "--licensee", "X", "--no-ledger"]
    assert cli.main([*base, "--perpetual"]) == 2                                              # без привязок и без --unbound
    assert cli.main([*base, "--perpetual", "--unbound"]) == 0
    assert cli.main([*base, "--days", "5", "--ip", "127.0.0.1"]) == 2                         # недопустимая привязка
    assert cli.main([*base, "--until", "31.12.2030", "--unbound"]) == 2                       # неверный формат даты
    with pytest.raises(SystemExit):
        cli.main([*base, "--perpetual", "--days", "5"])                                       # срок задаётся одним способом
    capsys.readouterr()


def test_cli_until_date_includes_the_whole_last_day(cli):
    assert cli.parse_moment("2030-12-31", end_of_day=True) - cli.parse_moment("2030-12-31") == DAY - 1
    assert cli.parse_moment("2030-12-31T10:00", end_of_day=True) == cli.parse_moment("2030-12-31T10:00")


def test_derive_secret_depends_on_machine():
    assert derive_secret("a") != derive_secret("b") and derive_secret(None) == derive_secret(None)
