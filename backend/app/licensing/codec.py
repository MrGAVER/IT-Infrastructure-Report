"""Формат токена лицензии и подпись.

    RIS1.<kid>.<payload: base64url(JSON)>.<signature: base64url(Ed25519)>

Подписывается не «JSON как объект», а те самые байты, что лежат в токене, с префиксом-доменом и идентификатором
ключа: ``b"RIS1\\0" + kid + b"\\0" + payload_bytes``. Поэтому нет неоднозначности канонизации JSON, а подпись
нельзя перенести на токен другого формата или с другим ``kid``. Проверка подписи ВСЕГДА идёт раньше разбора
содержимого: недоверенный JSON парсится только после того, как подлинность подтверждена.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from cryptography.exceptions import InvalidSignature
from pydantic import ValidationError

from .models import LicensePayload

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from .keys import KeyRing

TOKEN_PREFIX = "RIS1"
MAX_TOKEN_LENGTH = 16_384
_B64URL = re.compile(r"^[A-Za-z0-9_-]*$")
_ARMOR_LINE = re.compile(r"^-----(BEGIN|END) [A-Z ]+-----$")


class TokenError(ValueError):
    """Токен не прошёл разбор или проверку. ``code`` — машинная причина (попадает в LicenseReport.reason)."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class ParsedToken:
    kid: str
    payload_bytes: bytes
    signature: bytes


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    if not _B64URL.match(text):
        raise ValueError("недопустимые символы в base64url")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("повреждённые данные base64url") from exc


def normalize_token(text: str) -> str:
    """Токен из того, что вставил пользователь: строки обрамления (-----BEGIN ...-----), переносы строк и
    пробелы убираются — ключ часто приходит в письме или файле, разбитым на строки."""
    lines = [line.strip() for line in text.splitlines() if not _ARMOR_LINE.match(line.strip())]
    return "".join("".join(lines).split())


def _signed_message(kid: str, payload_bytes: bytes) -> bytes:
    return TOKEN_PREFIX.encode("ascii") + b"\x00" + kid.encode("ascii") + b"\x00" + payload_bytes


def sign_token(private_key: Ed25519PrivateKey, kid: str, payload: LicensePayload) -> str:
    payload_bytes = payload.canonical_json()
    signature = private_key.sign(_signed_message(kid, payload_bytes))
    return ".".join((TOKEN_PREFIX, kid, b64url_encode(payload_bytes), b64url_encode(signature)))


def parse_token(text: str) -> ParsedToken:
    """Разобрать токен БЕЗ проверки подписи (структура, длины, алфавит)."""
    token = normalize_token(text)
    if not token:
        raise TokenError("empty")
    if len(token) > MAX_TOKEN_LENGTH:
        raise TokenError("too_long")
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != TOKEN_PREFIX:
        raise TokenError("malformed", "ожидался формат RIS1.<kid>.<данные>.<подпись>")
    _, kid, payload_part, signature_part = parts
    try:
        return ParsedToken(kid=kid, payload_bytes=b64url_decode(payload_part), signature=b64url_decode(signature_part))
    except ValueError as exc:
        raise TokenError("malformed", str(exc)) from exc


def verify_signature(ring: KeyRing, parsed: ParsedToken) -> None:
    public_key = ring.get(parsed.kid)
    if public_key is None:
        raise TokenError("unknown_key", f"ключ подписи {parsed.kid!r} неизвестен этой версии приложения")
    try:
        public_key.verify(parsed.signature, _signed_message(parsed.kid, parsed.payload_bytes))
    except InvalidSignature as exc:
        raise TokenError("bad_signature") from exc


def decode_payload(payload_bytes: bytes) -> LicensePayload:
    """Разбор уже ПОДТВЕРЖДЁННОГО подписью содержимого. Неверный формат — TokenError('bad_payload')."""
    try:
        return LicensePayload.model_validate(json.loads(payload_bytes.decode("utf-8")))
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError, RecursionError) as exc:
        raise TokenError("bad_payload", str(exc)) from exc
