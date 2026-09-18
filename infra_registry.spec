# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

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
        # Единственный UI (см. backend/app/config.py:FRONTEND_DIR) — должен быть собран ДО
        # запуска PyInstaller: `cd frontend-vue && npm ci && npm run build` (см.
        # installer/build_windows.bat, который делает это автоматически). Без этого шага dist/
        # не существует и Analysis просто не найдёт директорию — сборка EXE упадёт на строке
        # ниже с понятной ошибкой, а не тихо соберёт EXE без UI.
        (str(ROOT / 'frontend-vue' / 'dist'), 'frontend-vue/dist'),
        (str(ROOT / 'backend' / 'alembic'), 'alembic'),
        (str(ROOT / 'backend' / 'alembic.ini'), '.'),
    ]
    # Экспорт диаграммы топологии сети в .drawio/.vsdx (backend/app/services/diagram_export.py)
    # падал в EXE-сборке с FileNotFoundError на media/media.vsdx (пакет vsdx) и
    # formatting_database/edge_styles.toml (пакет drawpyo, читается уже при самом импорте —
    # drawpyo/diagram/base_diagram.py:import_shape_database) — в .py-модуль сборка. Analysis
    # находит оба пакета обходом графа импортов (как и любой другой hiddenimport), но эти два
    # файла — не Python-код, а ресурсы данных, к которым каждый пакет обращается в рантайме
    # через путь относительно собственного __file__ (см. os.path.dirname(vsdx.__file__)/media/
    # media.vsdx в diagram_export.py). Статический анализ импортов такие обращения принципиально
    # не видит — то же самое несоответствие "видно по коду" vs "видно PyInstaller", что уже
    # объяснено про alembic/versions/*.py в комментарии к hiddenimports ниже. collect_data_files
    # копирует ВСЕ файлы пакета, что не .py/.pyc, сохраняя относительную структуру каталогов —
    # то есть распакуется ровно туда, где рантайм-код их и ищет.
    + collect_data_files('vsdx')
    + collect_data_files('drawpyo'),
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
