"""Мелкие помощники, общие для модулей пакета auth: текущее время, адрес клиента запроса и разбор заголовка Authorization."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import Request

from ..timeutil import utcnow_naive

# ---------------------------------------------------------------------------
# Время: SQLite/SQLAlchemy отбрасывают tzinfo при round-trip через DateTime без
# timezone=True (проверено эмпирически), поэтому все datetime здесь — naive UTC.
# Сравнение naive с aware кидает TypeError, а не тихо считает их равными — лучше
# держать всё в одном представлении, чем ловить это в проде на первой проверке
# истечения сессии.
# ---------------------------------------------------------------------------
def naive_utc_now() -> datetime:
    return utcnow_naive()


def request_client_ip(request: Optional[Request]) -> Optional[str]:
    return request.client.host if request is not None and request.client else None


def extract_bearer(header: Optional[str]) -> Optional[str]:
    """Токен из заголовка `Authorization: Bearer <токен>` или None, если схема другая либо токена нет.

    Схема аутентификации в RFC 7235 нечувствительна к регистру (`bearer`, `BEARER` — та же схема), токен — после первого пробела; пробелы
    вокруг токена отбрасываются. Единственное место разбора: его используют и шлюз (gate.py), и роутер (api/auth.py) — раньше у каждого
    была своя регистрозависимая копия (R1-07 код-ревью).

    Пример:
        extract_bearer("bearer abc123")  # "abc123"
        extract_bearer("Basic abc123")   # None
        extract_bearer("Bearer ")        # None
    """
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    return (token.strip() or None) if scheme.lower() == "bearer" else None
