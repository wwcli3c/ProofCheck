@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Building ProofCheck.exe (requires Internet to install PyInstaller on this Windows PC).
py -3 -m pip install -U pyinstaller
if errorlevel 1 goto bad
py -3 -m PyInstaller --noconfirm --clean --onefile --name ProofCheck --add-data "index.html;." --add-data "assets;assets" server.py
if errorlevel 1 goto bad
echo Finished: dist\ProofCheck.exe
pause
exit /b 0
:bad
echo Failed. Check Python installation, permissions and PyInstaller logs.
pause
exit /b 1
