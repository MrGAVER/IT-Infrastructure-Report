"""Выполнение `infra_registry.spec` без PyInstaller — чтобы проверять то, что спецификация РЕАЛЬНО передаёт в `Analysis`.

Прежний страж читал `hiddenimports` из текста .spec (AST) и сверял только перечисленные строкой модули: он не видел, что сам вызов
`collect_submodules('app')` при настоящей сборке возвращает пустой список. PyInstaller выполняет .spec из корня репозитория, где
пакета `app` нет в `sys.path` (он лежит в `backend/`), а `pathex` применяется только к самому `Analysis`, то есть позже. В тестах же
`app` импортируется всегда, поэтому вызов настоящего `collect_submodules` дал бы здесь «всё найдено» и скрыл бы эту ошибку.

Поэтому `collect_submodules` в заглушке возвращает `[]` — ровно то, что он возвращает при сборке (проверено на PyInstaller 6.22.3: из корня
репозитория без `backend/` в `sys.path` — 0 модулей, с ним — 85). Спецификация, которая опирается на него, тут «видит» пустой список и
проваливает проверки; спецификация, которая находит модули `app` сама (обходом каталога), проходит независимо от `sys.path`.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

SPEC_PATH = Path(__file__).resolve().parents[2] / "infra_registry.spec"


def evaluate_spec(monkeypatch: Any) -> dict[str, Any]:
    """Выполняет .spec и возвращает именованные аргументы, с которыми он вызвал `Analysis(...)` (`hiddenimports`, `datas` и т. д.).

    `monkeypatch` — фикстура pytest: подмена `PyInstaller.utils.hooks` в `sys.modules` снимается по окончании теста. PyInstaller для теста
    не нужен вовсе (в `requirements-dev.lock` его нет), поэтому проверка не даёт «неожиданного пропуска» в CI.
    """
    hooks = types.ModuleType("PyInstaller.utils.hooks")
    hooks.collect_data_files = lambda package, *args, **kwargs: []  # type: ignore[attr-defined]
    hooks.collect_submodules = lambda package, *args, **kwargs: []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "PyInstaller.utils.hooks", hooks)

    captured: dict[str, Any] = {}

    def analysis(*scripts: Any, **kwargs: Any) -> types.SimpleNamespace:
        captured.update(kwargs, scripts=scripts)
        return types.SimpleNamespace(pure=[], scripts=[], binaries=[], datas=[])

    namespace: dict[str, Any] = {
        "__file__": str(SPEC_PATH),
        "SPECPATH": str(SPEC_PATH.parent),
        "Analysis": analysis,
        "PYZ": lambda *args, **kwargs: None,
        "EXE": lambda *args, **kwargs: None,
    }
    exec(compile(SPEC_PATH.read_text(encoding="utf-8"), str(SPEC_PATH), "exec"), namespace)  # noqa: S102 - собственный .spec репозитория
    if "hiddenimports" not in captured:
        raise AssertionError("infra_registry.spec не вызвал Analysis(..., hiddenimports=...)")
    return captured
