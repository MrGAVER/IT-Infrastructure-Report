"""Кэш флага «аутентификация включена» в middleware (services/auth/settings.auth_enabled_cached, ревью 2.158.0, П-5).

_authorize на каждый запрос к /api/* читал настройки из БД — даже при выключенной аутентификации (режим по умолчанию), где
больше ничего из БД не нужно. Теперь флаг кэшируется на _FLAG_TTL секунд; set_auth_enabled сбрасывает кэш сразу. Кэшируется
только флаг: токен и пользователь по-прежнему проверяются по БД на каждый запрос.

Время — управляемые часы (_flag_clock): сроки проверяются точно, а «значение обновилось из-за сброса, а не из-за истечения TTL»
отделяется от «из-за истечения» заморозкой часов.
"""
from __future__ import annotations

import pytest

from app.models import AuthSettings
from app.services.auth import settings as settings_module

HEALTH_URL = "/api/v1/health"
ADMIN_PASSWORD = "Admin1234"


class FakeClock:
    def __init__(self) -> None:
        self.now = 5_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def clock(monkeypatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(settings_module, "_flag_clock", fake)
    return fake


def _settings_selects(sql_log) -> int:
    return sum(1 for statement in sql_log if "FROM auth_settings" in statement)


def _enable_auth(client) -> str:
    r = client.post("/api/v1/auth/users", json={"username": "admin", "password": ADMIN_PASSWORD, "role": "admin"})
    assert r.status_code == 201, r.text
    assert client.put("/api/v1/auth/settings", json={"enabled": True}).status_code == 200
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert r.status_code == 200, r.text
    return r.json()["token"]


class TestFlagIsReadOncePerTtl:
    def test_repeated_requests_read_settings_once(self, client, sql_log, clock):
        """Измеренный эффект: до правки каждый из пяти запросов делал свой SELECT настроек, теперь — один на все."""
        sql_log.clear()
        for _ in range(5):
            assert client.get(HEALTH_URL).status_code == 200
        assert _settings_selects(sql_log) == 1

    def test_flag_is_read_again_after_the_ttl(self, client, sql_log, clock):
        sql_log.clear()
        assert client.get(HEALTH_URL).status_code == 200
        clock.advance(settings_module._FLAG_TTL - 0.1)
        assert client.get(HEALTH_URL).status_code == 200
        assert _settings_selects(sql_log) == 1  # ещё в пределах TTL
        clock.advance(0.2)
        assert client.get(HEALTH_URL).status_code == 200
        assert _settings_selects(sql_log) == 2  # TTL истёк: перечитали

    def test_ttl_is_short(self):
        """Задержка видимости переключателя в других процессах равна TTL — он должен оставаться порядка секунд."""
        assert 0 < settings_module._FLAG_TTL <= 5


class TestSwitchTakesEffectImmediately:
    def test_enabling_applies_to_the_next_request_in_the_same_process(self, client, clock):
        """Часы заморожены: значение обновилось из-за сброса кэша в set_auth_enabled, а не из-за истечения TTL."""
        assert client.get("/api/v1/resources/manufacturers").status_code == 200  # кэш: «выключена»
        token = _enable_auth(client)
        assert client.get("/api/v1/resources/manufacturers").status_code == 401
        assert client.get("/api/v1/resources/manufacturers", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    def test_disabling_applies_to_the_next_request_in_the_same_process(self, client, clock):
        token = _enable_auth(client)
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/resources/manufacturers").status_code == 401  # кэш: «включена»
        assert client.put("/api/v1/auth/settings", json={"enabled": False}, headers=headers).status_code == 200
        assert client.get("/api/v1/resources/manufacturers").status_code == 200

    def test_enabling_never_leaves_the_old_flag_in_the_cache(self, client, clock):
        client.get(HEALTH_URL)
        assert settings_module._flag_cache is not None and settings_module._flag_cache[1] is False
        _enable_auth(client)
        assert settings_module._flag_cache is None or settings_module._flag_cache[1] is True


class TestOnlyTheFlagIsCached:
    def test_revoked_token_stops_working_at_once_while_the_flag_is_cached(self, client, clock):
        """Часы заморожены, кэш флага «включена» действует: выход из системы всё равно отзывает токен мгновенно."""
        token = _enable_auth(client)
        headers = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/v1/resources/manufacturers", headers=headers).status_code == 200
        assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
        assert client.get("/api/v1/resources/manufacturers", headers=headers).status_code == 401

    def test_password_change_revokes_other_tokens_at_once(self, client, clock):
        token = _enable_auth(client)
        second = client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD}).json()["token"]
        r = client.put("/api/v1/auth/me/password", json={"current_password": ADMIN_PASSWORD, "new_password": "Newpass5678"}, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, r.text
        assert client.get("/api/v1/resources/manufacturers", headers={"Authorization": f"Bearer {second}"}).status_code == 401


class TestOtherProcessesSeeTheSwitchAfterTheTtl:
    def test_direct_database_change_is_seen_only_after_the_ttl(self, client, db_session, clock):
        """Другой процесс переключил флаг в общей БД: этот увидит его не позже, чем через TTL (осознанный компромисс П-5)."""
        assert client.get("/api/v1/resources/manufacturers").status_code == 200  # кэш: «выключена»
        row = db_session.get(AuthSettings, "singleton")
        row.enabled = True
        db_session.commit()
        assert client.get("/api/v1/resources/manufacturers").status_code == 200  # TTL не истёк — ещё по кэшу
        clock.advance(settings_module._FLAG_TTL + 0.1)
        assert client.get("/api/v1/resources/manufacturers").status_code == 401


class TestResetRace:
    def test_value_read_before_a_concurrent_switch_is_not_cached(self, db_session, monkeypatch, clock):
        """Читатель взял «выключена» из БД, а переключатель успел нажать и сбросить кэш до того, как читатель его заполнил:
        устаревшее значение не должно остаться в кэше на весь TTL."""
        reads: list[int] = []

        def racing_read(session):
            reads.append(1)
            value = AuthSettings(id="singleton", enabled=False)
            settings_module.reset_auth_enabled_cache()  # «параллельный» set_auth_enabled закоммитил и сбросил кэш
            return value

        monkeypatch.setattr(settings_module, "get_or_create_auth_settings", racing_read)
        assert settings_module.auth_enabled_cached(db_session) is False  # этот запрос начался до переключения
        assert settings_module._flag_cache is None
        assert settings_module.auth_enabled_cached(db_session) is False
        assert len(reads) == 2  # второй запрос перечитал БД, а не взял устаревшее из кэша

    def test_value_is_cached_when_nobody_switched_during_the_read(self, db_session, monkeypatch, clock):
        reads: list[int] = []

        def plain_read(session):
            reads.append(1)
            return AuthSettings(id="singleton", enabled=True)

        monkeypatch.setattr(settings_module, "get_or_create_auth_settings", plain_read)
        assert settings_module.auth_enabled_cached(db_session) is True
        assert settings_module.auth_enabled_cached(db_session) is True
        assert len(reads) == 1

    def test_reset_makes_the_next_call_read_the_database(self, db_session, monkeypatch, clock):
        reads: list[int] = []

        def plain_read(session):
            reads.append(1)
            return AuthSettings(id="singleton", enabled=False)

        monkeypatch.setattr(settings_module, "get_or_create_auth_settings", plain_read)
        settings_module.auth_enabled_cached(db_session)
        settings_module.reset_auth_enabled_cache()
        settings_module.auth_enabled_cached(db_session)
        assert len(reads) == 2
