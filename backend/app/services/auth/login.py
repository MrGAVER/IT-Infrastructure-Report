"""Вход: троттлинг по адресу и логину, ограничение параллельных проверок пароля и сам authenticate.

Порядок защит в authenticate: троттлинг (429) → поиск пользователя → блокировка учётной записи (423, см. auth/lockout.py) →
проверка пароля под ограничением параллелизма (503). Состояние троттлинга живёт в памяти процесса."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from ...config import AUTH_LOCKOUT_KNOWN_CLIENT_BYPASS
from ...constants import AuditAction
from ...models import User
from ..actor_context import Actor
from ..crud import audit
from ..login_throttle import LoginThrottle
from ._common import naive_utc_now, request_client_ip, too_many_attempts
from .lockout import account_locked, is_known_client, register_failed_password
from .passwords import hash_password, needs_rehash, verify_password
from .sessions import create_session
from .users import find_user_by_username

# Один на процесс: состояние троттлинга (см. services/login_throttle.py) живёт в памяти.
# Ключ — пара (адрес клиента, логин): гасит перебор пароля одного логина, не задевая его владельца с другого адреса.
login_throttle = LoginThrottle()

# Второй рубеж — на адрес клиента целиком, независимо от логина (ключ (адрес, None)). Пара (адрес, логин) обходится сменой
# логина: каждая попытка с выдуманным логином оказывается «первой» для своей пары и никогда не задерживается, а стоит одного
# PBKDF2 (≈0,5 с CPU). Здесь порог выше (20 бесплатных попыток): за одним адресом (NAT офиса, прокси без FORWARDED_ALLOW_IPS)
# бывают много честных пользователей. Успешный вход этот счётчик НЕ сбрасывает — иначе нападающий с любой своей учётной
# записью вставлял бы между подборами удачный вход и обнулял задержку; счётчик сам затухает по окну неактивности.
ip_throttle = LoginThrottle(free_attempts=20, base_delay=1.0, max_delay=300.0)

# Не больше стольких одновременных проверок пароля (PBKDF2) на входе. /login — синхронный эндпоинт в пуле потоков
# (по умолчанию ~40), и без этого предела два десятка параллельных запросов заняли бы весь пул на ~0,5 с каждый: API
# перестало бы отвечать ещё до аутентификации. Лишний запрос отклоняется сразу (503), а не ждёт в очереди и не держит поток.
_HASH_SLOT_COUNT = 4
_HASH_SLOTS = threading.BoundedSemaphore(_HASH_SLOT_COUNT)


@contextmanager
def _password_hash_slot():
    """Занимает один из _HASH_SLOTS на время хеширования или проверки пароля; свободных нет — 503 с Retry-After.
    Слот освобождается всегда, в том числе при исключении внутри блока. Отказ по занятым слотам не считается неудачной
    попыткой входа: тот, кому отказали, пароль ещё не проверял."""
    slots = _HASH_SLOTS  # тот же объект и на release, даже если модульное имя подменили посреди запроса
    if not slots.acquire(blocking=False):
        raise HTTPException(503, "Сервер занят проверкой паролей, повторите позже.", headers={"Retry-After": "2"})
    try:
        yield
    finally:
        slots.release()


def _invalid_credentials() -> HTTPException:
    """Новый экземпляр на каждый отказ: повторный raise одного и того же объекта накапливал бы в нём
    traceback всех прошлых отказов (утечка памяти и чужие стеки в логах)."""
    return HTTPException(401, "Неверное имя пользователя или пароль.")


def _reject_if_throttled(pair_key: tuple, ip_key: tuple) -> None:
    """429, если задержка назначена паре (адрес, логин) или всему адресу — по большей из двух. Вызывается до любой работы
    с БД и хешированием: перебор отбивается дёшево, без траты CPU на PBKDF2."""
    wait = max(login_throttle.retry_after(pair_key), ip_throttle.retry_after(ip_key))
    if wait <= 0:
        return
    raise too_many_attempts("Слишком много неудачных попыток входа. Повторите через {seconds} с.", wait)


def _record_login_failure(pair_key: tuple, ip_key: tuple) -> None:
    login_throttle.record_failure(pair_key)
    ip_throttle.record_failure(ip_key)


def authenticate(session: Session, username: str, password: str, *, request: Optional[Request] = None) -> tuple[User, str]:
    """Возвращает (пользователь, токен сессии) либо кидает HTTPException. Намеренно не различает
    в тексте ошибки «нет такого пользователя» и «неверный пароль» (защита от перебора логинов) —
    но блокировка (423) неизбежно подтверждает существование аккаунта, это осознанный компромисс
    между защитой от перебора паролей и полной анонимностью логинов.

    Порядок защит: троттлинг по паре (адрес, логин) и по адресу (429) → поиск пользователя → блокировка учётной записи
    (423) → проверка пароля под ограничением параллелизма (503, см. _password_hash_slot)."""
    client_ip = request_client_ip(request)
    throttle_key = (client_ip, username.strip().casefold())
    ip_key = (client_ip, None)
    _reject_if_throttled(throttle_key, ip_key)

    user = find_user_by_username(session, username)
    if user is None or not user.is_active:
        # Тратим примерно то же время, что и на реальную проверку пароля — чтобы «нет такого
        # пользователя» не отвечал заметно быстрее «пароль неверный» (ещё один timing-сигнал).
        with _password_hash_slot():
            hash_password(password)
        _record_login_failure(throttle_key, ip_key)
        raise _invalid_credentials()

    now = naive_utc_now()
    if user.locked_until and user.locked_until > now and not (AUTH_LOCKOUT_KNOWN_CLIENT_BYPASS and is_known_client(session, user.id, client_ip, now)):
        # С «знакомого» адреса пароль проверяется и во время блокировки (см. config.AUTH_LOCKOUT_KNOWN_CLIENT_BYPASS): иначе
        # посторонний, посылая неверные пароли, держал бы владельца заблокированным. Троттлинг выше и счётчик ниже действуют.
        raise account_locked(user.locked_until, now)

    with _password_hash_slot():
        verified = verify_password(password, user.password_hash)
        # Пересчёт устаревшего хеша — тоже PBKDF2, поэтому под тем же слотом.
        upgraded_hash = hash_password(password) if verified and needs_rehash(user.password_hash) else None
    if not verified:
        _record_login_failure(throttle_key, ip_key)
        register_failed_password(
            session,
            user,
            details=f"Неудачная попытка входа «{user.username}»",
            now=now,
            actor=Actor(user.id, user.username, client_ip),
        )
        raise _invalid_credentials()

    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    if upgraded_hash is not None:
        user.password_hash = upgraded_hash
    session.commit()

    login_throttle.reset(throttle_key)
    token = create_session(session, user, request=request)
    audit(session, "auth", user.id, AuditAction.LOGIN, f"Вход «{user.username}»", actor=Actor(user.id, user.username, client_ip))
    session.commit()
    return user, token
