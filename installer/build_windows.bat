@echo off
setlocal
cd /d %~dp0..\
where node >nul 2>nul
if errorlevel 1 (
    echo ОШИБКА: Node.js не найден в PATH. Он нужен для сборки Vue-фронтенда ^(frontend-vue^),
    echo который теперь является основным UI ^(см. backend/app/config.py:FRONTEND_DIR^).
    echo Установите Node.js 20+ и повторите сборку.
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
python -m pip install --upgrade pip
pip install -r backend\requirements-build.txt
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
python -m PyInstaller --clean --noconfirm infra_registry.spec
copy /Y README_EXE.md dist\README_EXE.md
copy /Y installer\run_infra_registry.bat dist\run_infra_registry.bat
if errorlevel 1 exit /b 1
echo.
echo EXE создан: dist\InfraRegistry.exe
echo Запуск: dist\InfraRegistry.exe
echo Данные: %%LOCALAPPDATA%%\InfraRegistry
