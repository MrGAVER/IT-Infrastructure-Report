"""Пароли: хеширование PBKDF2, проверка и правила стойкости.

Самоописывающийся формат хеша и выбор hashlib.pbkdf2_hmac вместо bcrypt/argon2 объяснены в докстринге пакета
(services/auth/__init__.py) и в hash_password."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Optional

from fastapi import HTTPException

from ...config import AUTH_MIN_PASSWORD_LENGTH
from ...constants import ErrorCode

PBKDF2_ALGORITHM = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000  # рекомендация OWASP для PBKDF2-HMAC-SHA256; хеши с меньшим числом итераций пересчитываются при входе
_SALT_BYTES = 16


def hash_password(password: str) -> str:
    """'<алгоритм>$<итерации>$<соль-b64>$<хеш-b64>' — самоописывающийся формат: при повышении
    PBKDF2_ITERATIONS в будущей версии старые хеши не ломаются, а прозрачно пересчитываются на
    следующий успешный вход (см. needs_rehash + login.authenticate)."""
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"{PBKDF2_ALGORITHM}${PBKDF2_ITERATIONS}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    """hmac.compare_digest — таймингобезопасное сравнение: посимвольный '==' на разной длине
    совпадения давал бы микроскопическую, но реальную для локальной сети утечку через тайминг."""
    try:
        algorithm, iterations_s, salt_b64, hash_b64 = stored.split("$")
        if algorithm != PBKDF2_ALGORITHM:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        iterations = int(iterations_s)
        # Вычисление — под тем же try: число итераций из повреждённого хеша (0, отрицательное, не помещающееся в C long) pbkdf2_hmac
        # отвергает
        # ValueError/OverflowError, а это «пароль не подошёл», а не 500 на экране входа.
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    except (ValueError, TypeError, OverflowError):
        return False
    return hmac.compare_digest(candidate, expected)


def needs_rehash(stored: str) -> bool:
    try:
        algorithm, iterations_s, _salt, _hash = stored.split("$")
        return algorithm != PBKDF2_ALGORITHM or int(iterations_s) < PBKDF2_ITERATIONS
    except ValueError:
        return True


def validate_password_strength(password: str, *, username: Optional[str] = None) -> None:
    if len(password) < AUTH_MIN_PASSWORD_LENGTH:
        raise HTTPException(422, {
            "message": f"Пароль должен быть не короче {AUTH_MIN_PASSWORD_LENGTH} символов.",
            "code": ErrorCode.WEAK_PASSWORD,
        })
    if username and password.casefold() == username.strip().casefold():
        raise HTTPException(422, {
            "message": "Пароль не должен совпадать с именем пользователя.",
            "code": ErrorCode.WEAK_PASSWORD,
        })
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        raise HTTPException(422, {
            "message": "Пароль должен содержать и буквы, и цифры.",
            "code": ErrorCode.WEAK_PASSWORD,
        })
