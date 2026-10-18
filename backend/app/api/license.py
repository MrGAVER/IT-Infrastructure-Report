"""Роутер лицензии: /api/v1/license (см. app/licensing).

GET   — состояние лицензии (действует ли, срок, для кого выдана, какие измерения привязки не совпали) и сведения о
        хосте (имя, адреса, отпечаток машины), которые вендору нужны, чтобы выпустить ключ с привязкой. Сам ключ и его
        подпись не возвращаются.
POST  — активация ключа: проверка подписи, привязок к ЭТОМУ компьютеру и срока, затем сохранение в файл. Недействительный
        ключ — 422 (LICENSE_INVALID) и установленный ранее ключ остаётся на месте. При включённой аутентификации — только
        администратор, при выключенной — как первичная настройка (localhost или токен установки).
Эндпоинты доступны и без действующей лицензии (см. licensing/middleware.py): иначе её нельзя было бы активировать.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from ..constants import ErrorCode
from ..licensing.manager import LicenseActivationError, LicenseManager, LicenseStorageError
from ..schemas import LicenseActivateRequest
from ..services.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/license", tags=["License"])


def _manager(request: Request) -> LicenseManager:
    return request.app.state.license_manager


@router.get("")
def get_license_status(request: Request) -> dict:
    return _manager(request).public_status()


@router.post("")
def activate_license(payload: LicenseActivateRequest, request: Request) -> dict:
    require_admin(request)
    manager = _manager(request)
    try:
        manager.activate(payload.key)
    except LicenseActivationError as exc:
        report = exc.report
        raise HTTPException(422, {
            "code": ErrorCode.LICENSE_INVALID,
            "message": report.message,
            "license_state": report.state.value,
            "reason": report.reason,
            "mismatched": list(report.mismatched),
        }) from exc
    except LicenseStorageError as exc:
        logger.error("Не удалось сохранить лицензионный ключ: %s", exc)
        raise HTTPException(500, {
            "code": ErrorCode.LICENSE_INVALID,
            "message": "Ключ верный, но сохранить его не удалось: проверьте права на запись в каталог данных приложения.",
        }) from exc
    return manager.public_status()
