"""Сборка LicenseManager из настроек приложения (вызывается из main.py; сам пакет config не импортирует)."""
from __future__ import annotations

import sys
from pathlib import Path

from .clock_guard import ClockGuard, derive_secret
from .context import read_machine_id
from .keys import default_key_ring
from .manager import LicenseManager, resolve_enforcement
from .middleware import LICENSE_MODES


def validate_mode(mode: str) -> str:
    """Режим работы без лицензии. Неверное значение — ошибка при старте, а не молчаливый откат к умолчанию:
    опечатка в «block» не должна тихо оставлять режим «только чтение»."""
    normalized = (mode or "readonly").strip().lower()
    if normalized not in LICENSE_MODES:
        raise ValueError(f"INFRA_REGISTRY_LICENSE_MODE должен быть одним из {LICENSE_MODES}, получено {mode!r}")
    return normalized


def build_license_manager(*, key_file: Path, state_file: Path, env_token: str, enforcement_setting: str) -> LicenseManager:
    ring = default_key_ring()
    enforcement = resolve_enforcement(enforcement_setting, has_keys=bool(ring), frozen=bool(getattr(sys, "frozen", False)))
    guard = ClockGuard(state_file, derive_secret(read_machine_id()))
    return LicenseManager(ring=ring, key_file=key_file, env_token=env_token, enforcement=enforcement, clock_guard=guard)
