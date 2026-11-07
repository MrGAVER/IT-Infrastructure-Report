"""Троттлинг входа по адресу, лимит параллельных проверок пароля и предел длины пароля (ревью 2.158.0, П-2).

Ключ троттлинга (IP, логин) обходился сменой логина: каждая выдуманная пара получала «первую» попытку, и ни одна не
задерживалась, при том что попытка с несуществующим логином стоит одного PBKDF2 (≈0,5 с CPU), а /login — синхронный
эндпоинт в ограниченном пуле потоков. Теперь есть второй счётчик на адрес (services/auth.ip_throttle), число одновременных
проверок пароля ограничено (_HASH_SLOTS → 503), а длина паролей — 256 символов.

Время в счётчике по адресу — управляемые часы: задержки проверяются точно и не зависят от скорости машины.
"""
from __future__ import annotations

import threading
import time

import pytest
from fastapi import HTTPException

from app.schemas import MAX_PASSWORD_LENGTH
from app.services.auth import login as login_module
from app.services.login_throttle import LoginThrottle

LOGIN_URL = "/api/v1/auth/login"
ADMIN_PASSWORD = "Admin1234"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def ip_clock(monkeypatch) -> FakeClock:
    """Счётчик по адресу с теми же параметрами, что у боевого, но на управляемых часах."""
    clock = FakeClock()
    prod = login_module.ip_throttle
    monkeypatch.setattr(
        login_module, "ip_throttle",
        LoginThrottle(free_attempts=prod.free_attempts, base_delay=prod.base_delay, max_delay=prod.max_delay, window=prod.window, clock=clock),
    )
    return clock


def _bootstrap_admin(client) -> None:
    r = client.post("/api/v1/auth/users", json={"username": "admin", "password": ADMIN_PASSWORD, "role": "admin"})
    assert r.status_code == 201, r.text
    r = client.put("/api/v1/auth/settings", json={"enabled": True})
    assert r.status_code == 200, r.text


def _fail_login(client, username: str):
    return client.post(LOGIN_URL, json={"username": username, "password": "wrong-pass1"})


def _admin_login(client):
    return client.post(LOGIN_URL, json={"username": "admin", "password": ADMIN_PASSWORD})


def _spend_free_attempts(client) -> None:
    """Исчерпывает бесплатные попытки адреса разными выдуманными логинами: 401 на каждой, ни одной задержки."""
    free = login_module.ip_throttle.free_attempts
    for i in range(free):
        assert _fail_login(client, f"ghost-{i}").status_code == 401


class TestProductionSettings:
    def test_ip_throttle_is_more_lenient_than_the_pair_throttle(self):
        """За одним адресом бывает много честных пользователей (NAT офиса): порог по адресу выше, чем по паре."""
        assert login_module.ip_throttle.free_attempts == 20
        assert login_module.ip_throttle.free_attempts > login_module.login_throttle.free_attempts
        assert login_module.ip_throttle.max_delay == 300.0

    def test_hash_slot_count_is_small(self):
        assert login_module._HASH_SLOT_COUNT == 4


class TestThrottleByAddress:
    def test_thirty_distinct_logins_from_one_ip_end_in_429(self, client, ip_clock):
        """Тот самый обход из ревью: смена логина на каждой попытке больше не держит атаку без задержек."""
        _bootstrap_admin(client)
        statuses = [_fail_login(client, f"ghost-{i}").status_code for i in range(30)]
        assert statuses[:21] == [401] * 21  # 20 бесплатных попыток, и 21-я неудача назначает первую задержку
        assert set(statuses[21:]) == {429}

    def test_429_carries_code_and_retry_after(self, client, ip_clock):
        _bootstrap_admin(client)
        _spend_free_attempts(client)
        assert _fail_login(client, "ghost-last").status_code == 401  # 21-я неудача назначает задержку в 1 с
        r = _fail_login(client, "ghost-next")
        assert r.status_code == 429
        assert r.json()["detail"]["code"] == "TOO_MANY_ATTEMPTS"
        assert r.headers["Retry-After"] == "1"

    def test_delay_grows_and_expires(self, client, ip_clock):
        _bootstrap_admin(client)
        _spend_free_attempts(client)
        assert _fail_login(client, "ghost-a").status_code == 401  # 21-я неудача: задержка 1 с
        assert _fail_login(client, "ghost-b").status_code == 429
        ip_clock.advance(1.5)
        assert _fail_login(client, "ghost-c").status_code == 401  # 22-я неудача: задержка 2 с
        ip_clock.advance(1.5)
        assert _fail_login(client, "ghost-d").status_code == 429  # 2 с ещё не прошло
        ip_clock.advance(1.0)
        assert _fail_login(client, "ghost-e").status_code == 401

    def test_valid_login_from_a_throttled_address_waits_too(self, client, ip_clock):
        """Цена общего счётчика: пока адрес в задержке, верный пароль тоже ждёт; после задержки вход проходит."""
        _bootstrap_admin(client)
        _spend_free_attempts(client)
        assert _fail_login(client, "ghost-a").status_code == 401
        assert _admin_login(client).status_code == 429
        ip_clock.advance(1.5)
        assert _admin_login(client).status_code == 200

    def test_other_address_is_not_affected(self, client, client_factory, ip_clock):
        _bootstrap_admin(client)
        _spend_free_attempts(client)
        assert _fail_login(client, "ghost-a").status_code == 401
        assert _fail_login(client, "ghost-b").status_code == 429
        elsewhere = client_factory("203.0.113.9")
        assert _admin_login(elsewhere).status_code == 200

    def test_blocked_request_does_no_password_hashing(self, client, ip_clock, monkeypatch):
        """429 отдаётся до PBKDF2: ради этого отказ и ставится первым — перебор не должен тратить CPU."""
        _bootstrap_admin(client)
        _spend_free_attempts(client)
        assert _fail_login(client, "ghost-a").status_code == 401

        def _forbidden(*_args, **_kwargs):
            raise AssertionError("PBKDF2 не должен вызываться для заблокированного адреса")

        monkeypatch.setattr(login_module, "hash_password", _forbidden)
        monkeypatch.setattr(login_module, "verify_password", _forbidden)
        assert _fail_login(client, "ghost-b").status_code == 429
        assert _admin_login(client).status_code == 429

    def test_successful_login_does_not_reset_the_address_counter(self, client, ip_clock):
        """Иначе нападающий с любой своей учётной записью вставлял бы между подборами удачный вход и обнулял бы счётчик."""
        _bootstrap_admin(client)
        _spend_free_attempts(client)
        assert _admin_login(client).status_code == 200
        assert _fail_login(client, "ghost-a").status_code == 401  # 21-я неудача адреса: задержка, несмотря на вход между
        assert _fail_login(client, "ghost-b").status_code == 429

    def test_counter_decays_after_the_idle_window(self, client, ip_clock):
        _bootstrap_admin(client)
        _spend_free_attempts(client)
        assert _fail_login(client, "ghost-a").status_code == 401
        ip_clock.advance(login_module.ip_throttle.window + 1)
        assert _fail_login(client, "ghost-b").status_code == 401  # окно истекло: счёт неудач начался заново
        assert _fail_login(client, "ghost-c").status_code == 401


class TestHashSlots:
    def test_busy_slots_give_503_for_known_and_unknown_logins(self, client, monkeypatch):
        _bootstrap_admin(client)
        slots = threading.BoundedSemaphore(1)
        assert slots.acquire(blocking=False)
        monkeypatch.setattr(login_module, "_HASH_SLOTS", slots)
        for username in ("admin", "ghost"):
            r = client.post(LOGIN_URL, json={"username": username, "password": ADMIN_PASSWORD})
            assert r.status_code == 503, r.text
            assert r.headers["Retry-After"] == "2"
        slots.release()
        assert _admin_login(client).status_code == 200

    def test_busy_slots_are_not_counted_as_failed_attempts(self, client, monkeypatch):
        """Тому, кому отказали по занятым слотам, пароль не проверяли — задержку ему назначать нельзя."""
        _bootstrap_admin(client)
        slots = threading.BoundedSemaphore(1)
        slots.acquire()
        monkeypatch.setattr(login_module, "_HASH_SLOTS", slots)
        for i in range(5):
            assert client.post(LOGIN_URL, json={"username": "admin" if i % 2 else f"ghost-{i}", "password": "x1"}).status_code == 503
        assert len(login_module.ip_throttle) == 0
        assert len(login_module.login_throttle) == 0

    def test_slots_are_released_after_every_outcome(self, client):
        """Утечка слота хоть на одном пути (успех, неверный пароль, неизвестный логин) через пару входов вернула бы 503 всем."""
        _bootstrap_admin(client)
        for i in range(login_module._HASH_SLOT_COUNT + 2):
            assert _admin_login(client).status_code == 200
            assert client.post(LOGIN_URL, json={"username": "admin", "password": "wrong-pass1"}).status_code == 401
            assert _fail_login(client, f"ghost-{i}").status_code == 401
            assert client.post(LOGIN_URL, json={"username": "admin", "password": ADMIN_PASSWORD}).status_code == 200

    def test_slot_is_released_when_the_block_raises(self, monkeypatch):
        slots = threading.BoundedSemaphore(1)
        monkeypatch.setattr(login_module, "_HASH_SLOTS", slots)
        with pytest.raises(RuntimeError):
            with login_module._password_hash_slot():
                raise RuntimeError("сбой внутри хеширования")
        assert slots.acquire(blocking=False), "слот должен освободиться даже при исключении"

    def test_parallel_holders_never_exceed_the_slot_count(self, monkeypatch):
        """12 потоков одновременно: четверо удерживают слот, остальные восемь сразу получают 503 и не ждут в очереди."""
        monkeypatch.setattr(login_module, "_HASH_SLOTS", threading.BoundedSemaphore(4))
        gate = threading.Event()
        lock = threading.Lock()
        state = {"inside": 0, "peak": 0, "rejected": []}

        def worker() -> None:
            try:
                with login_module._password_hash_slot():
                    with lock:
                        state["inside"] += 1
                        state["peak"] = max(state["peak"], state["inside"])
                    gate.wait(5)
                    with lock:
                        state["inside"] -= 1
            except HTTPException as exc:
                with lock:
                    state["rejected"].append(exc.status_code)

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for thread in threads:
            thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with lock:
                if state["inside"] == 4 and len(state["rejected"]) == 8:
                    break
            time.sleep(0.01)
        gate.set()
        for thread in threads:
            thread.join(5)
        assert state["peak"] == 4
        assert state["rejected"] == [503] * 8


class TestPasswordLengthLimit:
    LONGEST = "a1" * (MAX_PASSWORD_LENGTH // 2)
    TOO_LONG = LONGEST + "x"

    def test_limit_is_256_characters(self):
        assert MAX_PASSWORD_LENGTH == 256
        assert len(self.LONGEST) == 256 and len(self.TOO_LONG) == 257

    def test_login_rejects_an_oversized_password_before_any_hashing(self, client, monkeypatch):
        _bootstrap_admin(client)

        def _forbidden(*_args, **_kwargs):
            raise AssertionError("PBKDF2 не должен вызываться для слишком длинного пароля")

        monkeypatch.setattr(login_module, "hash_password", _forbidden)
        monkeypatch.setattr(login_module, "verify_password", _forbidden)
        r = client.post(LOGIN_URL, json={"username": "admin", "password": self.TOO_LONG})
        assert r.status_code == 422
        assert len(login_module.ip_throttle) == 0  # отказ валидации — не неудачная попытка входа

    def test_a_256_character_password_can_be_set_and_used_to_log_in(self, client):
        """Предел одинаков на создании и на входе: принятый при создании пароль должно быть возможно ввести."""
        r = client.post("/api/v1/auth/users", json={"username": "admin", "password": self.LONGEST, "role": "admin"})
        assert r.status_code == 201, r.text
        assert client.put("/api/v1/auth/settings", json={"enabled": True}).status_code == 200
        r = client.post(LOGIN_URL, json={"username": "admin", "password": self.LONGEST})
        assert r.status_code == 200, r.text

    def test_create_and_update_user_reject_an_oversized_password(self, client):
        r = client.post("/api/v1/auth/users", json={"username": "admin", "password": self.TOO_LONG, "role": "admin"})
        assert r.status_code == 422
        created = client.post("/api/v1/auth/users", json={"username": "admin", "password": ADMIN_PASSWORD, "role": "admin"})
        assert created.status_code == 201
        r = client.put(f"/api/v1/auth/users/{created.json()['id']}", json={"password": self.TOO_LONG})
        assert r.status_code == 422

    def test_change_own_password_rejects_an_oversized_password(self, client):
        _bootstrap_admin(client)
        token = _admin_login(client).json()["token"]
        headers = {"Authorization": f"Bearer {token}"}
        too_long_new = client.put("/api/v1/auth/me/password", json={"current_password": ADMIN_PASSWORD, "new_password": self.TOO_LONG}, headers=headers)
        assert too_long_new.status_code == 422
        too_long_current = client.put("/api/v1/auth/me/password", json={"current_password": self.TOO_LONG, "new_password": "Admin5678"}, headers=headers)
        assert too_long_current.status_code == 422
