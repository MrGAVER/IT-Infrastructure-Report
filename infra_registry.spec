# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH)

# collect_submodules('app') находит модули обходом файловой системы пакета и должен ловить всё
# автоматически — но alembic/versions/*.py грузятся как ДАННЫЕ (см. datas ниже) и импортируются
# динамически самим alembic в рантайме (alembic/util/pyfiles.py: load_python_file), уже ПОСЛЕ
# старта приложения — это в принципе невидимо для статического анализа PyInstaller (Analysis
# видит только то, что импортируется по обычной цепочке из launcher.py). Модули, на которые
# ссылаются ТОЛЬКО такие миграции (а не обычный код приложения), явно перечисляем здесь —
# отдельная строчка на каждую такую миграцию, если/когда появится следующая.
hiddenimports = collect_submodules('app') + [
    'app.services.report_seed_templates',  # используется только из alembic/versions/b1f0a2265711_*.py
    'app.services.report_seed_word_template',  # используется только из alembic/versions/b44cd42f9fa0_*.py
]

a = Analysis(
    ['launcher.py'],
    pathex=[str(ROOT / 'backend'), str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'frontend'), 'frontend'),
        # Основной UI (см. backend/app/config.py:FRONTEND_DIR) — должен быть собран ДО запуска
        # PyInstaller: `cd frontend-vue && npm ci && npm run build` (см. installer/build_windows.bat,
        # который делает это автоматически). Без этого шага dist/ не существует и Analysis
        # просто не найдёт директорию — сборка EXE упадёт на строке ниже с понятной ошибкой,
        # а не тихо соберёт EXE без UI.
        (str(ROOT / 'frontend-vue' / 'dist'), 'frontend-vue/dist'),
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
