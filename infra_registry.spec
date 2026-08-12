# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)

hiddenimports = collect_submodules('app')

a = Analysis(
    ['launcher.py'],
    pathex=[str(ROOT / 'backend'), str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'frontend'), 'frontend'),
        (str(ROOT / 'backend' / 'alembic'), 'alembic'),
        (str(ROOT / 'backend' / 'alembic.ini'), '.'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='InfraRegistry',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
