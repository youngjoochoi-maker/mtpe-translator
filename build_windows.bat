@echo off
REM MTPE Windows build script.
REM Output: dist\MTPE.exe (desktop app) + dist\MTPEApi.exe (automation API server for n8n)
REM (ASCII only - Korean text breaks cmd parsing)
setlocal
cd /d "%~dp0"
echo ============================================
echo   MTPE Windows Build
echo ============================================
echo.

REM Find Python (python or py launcher)
set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY ( where py >nul 2>&1 && set "PY=py" )
if not defined PY (
    echo [ERROR] Python not found.
    echo   Install Python 3.11 - 3.12 from https://www.python.org/downloads/
    echo   Check "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)
echo Using Python:
%PY% --version
echo.

echo [1/5] Creating virtual environment...
%PY% -m venv build-venv || goto :err
call build-venv\Scripts\activate.bat || goto :err

echo [2/5] Installing dependencies (takes a few minutes)...
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :err
pip install pyinstaller || goto :err

echo [3/5] Building automation API server (MTPEApi.exe) - needed for n8n...
pyinstaller mtpe_api.spec --noconfirm || goto :err

echo [4/5] Building desktop app (MTPE.exe) - for a person to use...
pyinstaller mtpe.spec --noconfirm || goto :err

echo [5/5] Done.
echo.
echo ============================================
echo   [DONE] Files created in the "dist" folder:
echo     dist\MTPE.exe      - desktop app (for a person to use)
echo     dist\MTPEApi.exe   - automation API server (for n8n)
echo   Double-click an .exe to run it.
echo ============================================
echo.
pause
exit /b 0

:err
echo.
echo ============================================
echo   [ERROR] Build failed. Check the messages above.
echo   (Capture this screen if you need help.)
echo ============================================
echo.
pause
exit /b 1
