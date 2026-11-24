"""Тела запросов роутера проверки данных. Правила проверки отпечатка и комментария — в services/consistency/approvals.py."""

from __future__ import annotations

from pydantic import Field

from ..services.consistency.approvals import MAX_COMMENT_LENGTH
from .schema_base import RequestBody

FINGERPRINT_LENGTH = 64  # sha256 в hex (services/consistency/model.py: Finding.fingerprint)


class ApproveFindingBody(RequestBody):
    """Одобрение проблемы: отпечаток из ответа проверки и необязательный комментарий («почему допустимо»)."""

    fingerprint: str = Field(max_length=FINGERPRINT_LENGTH)
    comment: str | None = Field(default=None, max_length=MAX_COMMENT_LENGTH)
