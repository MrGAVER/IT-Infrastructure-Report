"""Принуждение лицензии на уровне HTTP.

Без действующей лицензии приложение переходит в режим ``readonly`` (по умолчанию: чтение и просмотр данных
работают, любая запись и формирование отчётов — 402) либо ``block`` (402 на весь API). Данные реестра
не берутся в заложники: просроченная лицензия не должна лишать организацию доступа к собственным записям.

Статика и оболочка интерфейса (всё вне ``/api/``) отдаются всегда — иначе пользователь не увидел бы экран
активации. Исключения внутри ``/api/``: состояние и активация лицензии, вход в систему (администратору нужно
авторизоваться, чтобы активировать ключ) и проверка живости.
"""
from __future__ import annotations

from typing import Literal

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ..constants import ErrorCode
from .manager import LicenseManager

LicenseMode = Literal["readonly", "block"]
LICENSE_MODES: tuple[str, ...] = ("readonly", "block")

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
EXEMPT_PATHS = frozenset({"/api/v1/health", "/api/v1/license"})
EXEMPT_PREFIXES = ("/api/v1/auth/",)


def is_exempt_path(path: str) -> bool:
    return path in EXEMPT_PATHS or path.startswith(EXEMPT_PREFIXES)


class LicenseGateMiddleware:
    """Чистый ASGI-middleware (как ClientAccessMiddleware): не буферизует тело и не оборачивает ответы."""

    def __init__(self, app: ASGIApp, manager: LicenseManager, mode: LicenseMode = "readonly") -> None:
        if mode not in LICENSE_MODES:
            raise ValueError(f"режим лицензии должен быть одним из {LICENSE_MODES}, получено {mode!r}")
        self.app = app
        self.manager = manager
        self.mode = mode

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._requires_license(scope):
            await self.app(scope, receive, send)
            return
        report = self.manager.report()
        if report.allows_writes or (self.mode == "readonly" and scope["method"] in SAFE_METHODS):
            await self.app(scope, receive, send)
            return
        response = JSONResponse(
            status_code=402,
            content={"detail": {
                "code": ErrorCode.LICENSE_REQUIRED,
                "message": report.message + (" Запись данных заблокирована." if self.mode == "readonly" else " Доступ заблокирован."),
                "license_state": report.state.value,
            }},
        )
        await response(scope, receive, send)

    @staticmethod
    def _requires_license(scope: Scope) -> bool:
        path: str = scope["path"]
        return path.startswith("/api/") and not is_exempt_path(path)
