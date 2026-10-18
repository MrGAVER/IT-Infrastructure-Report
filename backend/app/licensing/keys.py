"""Набор публичных ключей проверки подписи, встроенных в приложение.

Приложение содержит ТОЛЬКО публичные ключи: подделать ключ лицензии без приватного ключа нельзя, а извлечь
приватный из приложения нечего. Приватный ключ создаёт и хранит вендор (``tools/license_admin.py gen-keypair``) —
не в репозитории и не в сборке.

Несколько записей нужны для ротации: ключ подписи (``kid``) указан в самом токене, поэтому новая версия
приложения может принимать ключи и старого, и нового ключа подписи одновременно.

Пока набор пуст, принуждение выключено (см. manager.resolve_enforcement) — приложение работает, как до
появления лицензирования. Релизная сборка ОБЯЗАНА содержать хотя бы один ключ: см. docs/licensing.md.
"""
from __future__ import annotations

import re
from collections.abc import Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from .codec import b64url_decode, b64url_encode

# kid -> публичный ключ Ed25519 (32 байта, base64url без «=»). Значение печатает `license_admin.py gen-keypair`.
EMBEDDED_PUBLIC_KEYS: dict[str, str] = {
    # "k1": "<base64url публичного ключа>",
}

_KID = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
_RAW_KEY_LENGTH = 32


class KeyRingError(ValueError):
    """Неверная запись в наборе ключей — ошибка сборки, а не пользовательского ввода: падаем при старте."""


class KeyRing:
    def __init__(self, keys: Mapping[str, str]) -> None:
        self._keys: dict[str, Ed25519PublicKey] = {}
        for kid, encoded in keys.items():
            if not _KID.match(kid):
                raise KeyRingError(f"недопустимый идентификатор ключа {kid!r}")
            try:
                raw = b64url_decode(encoded)
                if len(raw) != _RAW_KEY_LENGTH:
                    raise ValueError(f"ожидалось {_RAW_KEY_LENGTH} байт, получено {len(raw)}")
                self._keys[kid] = Ed25519PublicKey.from_public_bytes(raw)
            except ValueError as exc:
                raise KeyRingError(f"публичный ключ {kid!r} повреждён: {exc}") from exc

    def get(self, kid: str) -> Ed25519PublicKey | None:
        return self._keys.get(kid)

    def __len__(self) -> int:
        return len(self._keys)

    def __bool__(self) -> bool:
        return bool(self._keys)


def default_key_ring() -> KeyRing:
    return KeyRing(EMBEDDED_PUBLIC_KEYS)


def export_public_key(private_key: Ed25519PrivateKey) -> str:
    """Публичная часть ключа в виде, пригодном для EMBEDDED_PUBLIC_KEYS."""
    raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return b64url_encode(raw)
