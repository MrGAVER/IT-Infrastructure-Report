@echo off
setlocal
cd /d %~dp0..\
where node >nul 2>nul
if errorlevel 1 (
    echo ОШИБКА: Node.js не найден в PATH. Он нужен для сборки Vue-фронтенда ^(frontend-vue^),
    echo который теперь является основным UI ^(см. backend/app/config.py:FRONTEND_DIR^).
    echo Установите Node.js 22+ и повторите сборку.
    exit /b 1
)
pushd frontend-vue
call npm ci
if errorlevel 1 exit /b 1
rem Известные уязвимости в зависимостях frontend: тот же gate, что в CI (npm audit по runtime-зависимостям, уровень high и выше,
rem исключения заданы в frontend-vue\scripts\audit-gate.mjs). Нужен доступ к registry.npmjs.org, как и для npm ci.
call npm run audit:gate
if errorlevel 1 exit /b 1
call npm run build
if errorlevel 1 exit /b 1
popd
if not exist .venv py -3.12 -m venv .venv
call .venv\Scripts\activate.bat
rem Зависимости ставятся строго по lock-файлу с хешами (те же версии, что в Docker и CI, прошедшие pip-audit): сборка
rem завтра даёт то же, что сегодня, а подмена пакета в индексе не пройдёт проверку хеша. Отдельно pip не обновляем: версия pip из
rem venv Python 3.12 понимает --require-hashes, а нужная версия закреплена в самом lock. Для чистой воспроизводимой сборки удалите
rem каталог .venv перед запуском.
python -m pip install --require-hashes -r backend\requirements-build.lock
if errorlevel 1 exit /b 1
rem Известные уязвимости в Python-зависимостях: pip-audit стоит в этом же venv (он есть в lock), пакеты сверяются по PyPI
rem (--disable-pip: lock полный и с хешами, второй venv с повторной установкой не нужен). Правила те же, что в CI: runtime-набор
rem блокирует сборку (эти пакеты попадут в EXE), набор для сборки только сообщает: сборочные инструменты изредка дают замечания,
rem не относящиеся к рантайму.
python -m pip_audit -r backend\requirements.lock --require-hashes --disable-pip
if errorlevel 1 (
    echo ОШИБКА: в runtime-зависимостях ^(backend\requirements.lock^) найдены известные уязвимости, EXE не собирается.
    echo Обновите пакеты и пересоберите lock-файлы ^(см. README, раздел про requirements*.lock^), затем повторите сборку.
    exit /b 1
)
python -m pip_audit -r backend\requirements-build.lock --require-hashes --disable-pip
if errorlevel 1 echo ПРЕДУПРЕЖДЕНИЕ: pip-audit нашёл замечания в наборе для сборки ^(requirements-build.lock^); сборка продолжается, см. вывод выше.
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
python -m PyInstaller --clean --noconfirm infra_registry.spec
if errorlevel 1 exit /b 1
rem Каждое копирование проверяется отдельно: прежний единственный "if errorlevel" после двух copy видел только результат
rem второго, и сборка без README_EXE.md считалась успешной.
copy /Y installer\README_EXE.md dist\README_EXE.md || exit /b 1
copy /Y installer\run_infra_registry.bat dist\run_infra_registry.bat || exit /b 1
echo.
echo EXE создан: dist\InfraRegistry.exe
echo Запуск: dist\InfraRegistry.exe
echo Данные: рядом с InfraRegistry.exe ^(infra_registry.db, reports\^), либо в каталоге из переменной INFRA_REGISTRY_DATA_DIR
echo Инструкция: dist\README_EXE.md
