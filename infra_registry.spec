# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH)


def collect_app_modules(backend_dir):
    """Все модули пакета `app` (backend/app/**/*.py) в виде имён `app.services.x`, обходом каталога, без импорта.

    Раньше здесь стоял `collect_submodules('app')`, и он при сборке НИЧЕГО не находил: PyInstaller выполняет .spec из корня
    репозитория, где `app` не лежит в sys.path (пакет живёт в backend/; `pathex` ниже применяется только к самому Analysis, то есть
    позже), поэтому функция возвращала пустой список (проверено на PyInstaller 6.22.3: из корня без backend/ в sys.path — 0 модулей,
    с ним — 85) и молча. В EXE попадало лишь то, что достижимо обычным анализом импортов от launcher.py; всё, что импортируют только
    alembic/env.py и alembic/versions/*.py, приходилось перечислять вручную, а новый `app.alembic_filters` (его импортирует только
    env.py, R1-02) в перечень не попал — EXE падал при запуске: `ModuleNotFoundError: No module named 'app.alembic_filters'`.
    alembic/env.py и alembic/versions/*.py грузятся как ДАННЫЕ (см. datas ниже) и импортируются самим alembic в рантайме
    (alembic/util/pyfiles.py: load_python_file), уже после старта приложения, — для статического анализа PyInstaller они невидимы.
    Обход файловой системы от этого не зависит: ни от sys.path, ни от текущего каталога, ни от побочных эффектов импорта пакета.
    """
    package_root = backend_dir / 'app'
    modules = []
    for path in sorted(package_root.rglob('*.py')):
        parts = path.relative_to(backend_dir).with_suffix('').parts
        modules.append('.'.join(parts[:-1] if parts[-1] == '__init__' else parts))
    return modules


hiddenimports = collect_app_modules(ROOT / 'backend')
if 'app.main' not in hiddenimports:
    # Громкий отказ вместо тихой сборки без модулей: пустой результат здесь означает неверный путь, а не «модулей нет».
    raise SystemExit(f'infra_registry.spec: каталог {ROOT / "backend" / "app"} не содержит пакет app (найдено модулей: {len(hiddenimports)})')

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
    # Экспорт диаграммы топологии сети в .drawio/.vsdx (backend/app/services/diagram_export/)
    # падал в EXE-сборке с FileNotFoundError на media/media.vsdx (пакет vsdx) и
    # formatting_database/edge_styles.toml (пакет drawpyo, читается уже при самом импорте —
    # drawpyo/diagram/base_diagram.py:import_shape_database) — в .py-модуль сборка. Analysis
    # находит оба пакета обходом графа импортов (как и любой другой hiddenimport), но эти два
    # файла — не Python-код, а ресурсы данных, к которым каждый пакет обращается в рантайме
    # через путь относительно собственного __file__ (см. os.path.dirname(vsdx.__file__)/media/
    # media.vsdx в diagram_export/vsdx.py). Статический анализ импортов такие обращения принципиально
    # не видит — то же самое несоответствие "видно по коду" vs "видно PyInstaller", что уже
    # объяснено про alembic/env.py и alembic/versions/*.py в docstring collect_app_modules выше. collect_data_files
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
