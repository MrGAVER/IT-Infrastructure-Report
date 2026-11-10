"""
Код-ревью r3, A-04: перебор токена установки (заголовок X-Setup-Token) ограничивается по адресу клиента.

Вход (/auth/login) троттлился давно, а неверные значения X-Setup-Token — нет: их можно было подставлять без задержки. Токен ≥ 16 случайных
символов перебором не взять, но защита не должна зависеть от того, какой токен задал владелец. Теперь после серии неверных значений
с одного адреса следующая попытка получает 429 с Retry-After (задержка растёт вдвое), успех сбрасывает счётчик. Считаются только
подставленные неверные значения: запрос без заголовка — это не попытка подбора (так интерфейс узнаёт, что нужен токен), его блокировка
заперла бы самого владельца.

Запуск: pytest backend/tests/test_setup_token_throttle.py -v
"""
from __future__ import annotations

import pytest

from app.services.auth import guards as guards_module
from app.services.login_throttle import LoginThrottle

TOKEN = "k3Xr-9vT2mQa7wLp-4Zd8"  # сильный: не заглушка и не короче 16 символов
ATTACKER = "203.0.113.7"
OWNER = "198.51.100.20"
USER = {"username": "admin", "password": "Admin1234", "role": "admin"}
FREE = guards_module.SETUP_TOKEN_FREE_ATTEMPTS


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    """Токен задан, троттлинг идёт на управляемых часах (чтобы «прошла задержка» без sleep)."""
    fake = FakeClock()
    monkeypatch.setattr(guards_module, "SETUP_TOKEN", TOKEN)
    monkeypatch.setattr(
        guards_module, "setup_token_throttle",
        LoginThrottle(free_attempts=FREE, base_delay=guards_module.SETUP_TOKEN_BASE_DELAY, max_delay=guards_module.SETUP_TOKEN_MAX_DELAY, clock=fake),
    )
    return fake


def _guess(client, value: str = "wrong-token-0123456789"):
    return client.post("/api/v1/auth/users", json=USER, headers={"X-Setup-Token": value})


def _burn_free_attempts(client) -> None:
    for attempt in range(FREE):
        assert _guess(client).status_code == 403, f"попытка {attempt + 1} из {FREE} бесплатных должна быть обычным 403"


def test_wrong_tokens_are_denied_normally_until_the_free_attempts_run_out(client_factory, clock):
    _burn_free_attempts(client_factory(ATTACKER))


def test_the_attempt_after_the_free_ones_is_throttled_with_retry_after(client_factory, clock):
    attacker = client_factory(ATTACKER)
    _burn_free_attempts(attacker)
    assert _guess(attacker).status_code == 403  # N+1-я неверная попытка ещё отвечает 403, но уже назначает задержку
    blocked = _guess(attacker)  # следующая — 429
    assert blocked.status_code == 429, blocked.text
    assert blocked.json()["detail"]["code"] == "TOO_MANY_ATTEMPTS"
    assert int(blocked.headers["Retry-After"]) >= 1
    assert "токен" in blocked.json()["detail"]["message"].lower()


def test_while_throttled_even_the_correct_token_is_not_accepted(client_factory, clock):
    attacker = client_factory(ATTACKER)
    _burn_free_attempts(attacker)
    _guess(attacker)
    # Иначе по ответу можно было бы отличать верное значение от неверного, не дожидаясь конца задержки.
    assert _guess(attacker, TOKEN).status_code == 429


def test_the_delay_grows_with_every_further_failure(client_factory, clock):
    attacker = client_factory(ATTACKER)
    _burn_free_attempts(attacker)
    delays = []
    for _ in range(3):
        assert _guess(attacker).status_code == 403  # попытка, которая назначает следующую задержку
        blocked = _guess(attacker)
        assert blocked.status_code == 429
        delays.append(int(blocked.headers["Retry-After"]))
        clock.now += delays[-1] + 1  # дождались конца задержки
    assert delays[0] < delays[1] < delays[2]


def test_after_the_delay_the_correct_token_works_and_resets_the_counter(client_factory, clock):
    attacker = client_factory(ATTACKER)
    _burn_free_attempts(attacker)
    _guess(attacker)
    blocked = _guess(attacker)
    clock.now += int(blocked.headers["Retry-After"]) + 1

    assert _guess(attacker, TOKEN).status_code == 201  # токен принят, пользователь создан
    # Счётчик сброшен: снова FREE бесплатных неверных попыток без 429 (создание повторно не мешает — до проверки тела идёт гард).
    for _ in range(FREE):
        assert _guess(attacker).status_code == 403


def test_a_success_in_the_middle_resets_the_count(client_factory, clock):
    owner = client_factory(OWNER)
    for _ in range(FREE - 1):
        assert _guess(owner).status_code == 403
    assert _guess(owner, TOKEN).status_code == 201
    for _ in range(FREE):
        assert _guess(owner).status_code == 403  # не 429: прежние неудачи не накопились


def test_requests_without_the_header_are_not_guesses_and_never_throttled(client_factory, clock):
    owner = client_factory(OWNER)
    # Интерфейс сначала обращается без токена, получает 403 SETUP_ACCESS_DENIED и только потом просит токен. Считай мы такие запросы
    # попытками, владелец блокировал бы сам себя обычными перезагрузками страницы настроек.
    for _ in range(FREE * 4):
        r = owner.post("/api/v1/auth/users", json=USER)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "SETUP_ACCESS_DENIED"
    assert _guess(owner, TOKEN).status_code == 201


def test_an_empty_header_value_is_not_a_guess_either(client_factory, clock):
    owner = client_factory(OWNER)
    for _ in range(FREE * 2):
        assert owner.post("/api/v1/auth/users", json=USER, headers={"X-Setup-Token": ""}).status_code == 403
    assert _guess(owner, TOKEN).status_code == 201


def test_the_throttle_is_per_client_address(client_factory, clock):
    attacker = client_factory(ATTACKER)
    _burn_free_attempts(attacker)
    _guess(attacker)
    assert _guess(attacker).status_code == 429
    owner = client_factory(OWNER)
    assert _guess(owner, TOKEN).status_code == 201  # другой адрес не затронут


def test_the_settings_endpoint_is_throttled_by_the_same_counter(client_factory, clock):
    attacker = client_factory(ATTACKER)
    _burn_free_attempts(attacker)  # через /auth/users
    _guess(attacker)
    blocked = attacker.put("/api/v1/auth/settings", json={"enabled": True}, headers={"X-Setup-Token": "another-wrong-token-1"})
    assert blocked.status_code == 429  # счётчик общий для всех мест, где проверяется токен установки


def test_without_a_configured_token_nothing_is_counted(client_factory, monkeypatch):
    monkeypatch.setattr(guards_module, "SETUP_TOKEN", "")
    remote = client_factory(ATTACKER)
    for _ in range(FREE * 3):
        assert _guess(remote).status_code == 403  # токена нет — сравнивать и считать нечего; остаётся обычный отказ по адресу
    assert len(guards_module.setup_token_throttle) == 0

