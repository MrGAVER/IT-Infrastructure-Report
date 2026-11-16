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
call npm run build
if errorlevel 1 exit /b 1
popd
if not exist .venv py -3.12 -m venv .venv
call .venv\Scripts\activate.bat
rem Зависимости ставятся строго по lock-файлу с хешами (те же версии, что в Docker и CI, прошедшие pip-audit): сборка
rem завтра даёт то же, что сегодня, а подмена пакета в индексе не пройдёт проверку хеша. pip не обновляем: версия pip из
rem venv Python 3.12 понимает --require-hashes. Для чистой воспроизводимой сборки удалите каталог .venv перед запуском.
python -m pip install --require-hashes -r backend\requirements-build.lock
if errorlevel 1 exit /b 1
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
