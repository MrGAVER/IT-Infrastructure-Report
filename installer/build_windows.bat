@echo off
setlocal
cd /d %~dp0..\
if not exist .venv py -3.12 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
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
