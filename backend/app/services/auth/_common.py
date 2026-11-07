"""Мелкие помощники, общие для модулей пакета auth: текущее время и адрес клиента запроса."""
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


def client_ip(request: Optional[Request]) -> Optional[str]:
    return request.client.host if request is not None and request.client else None
