@echo off
REM MTPE Windows build script. Output: dist\MTPE.exe
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

echo [1/4] Creating virtual environment...
%PY% -m venv build-venv || goto :err
call build-venv\Scripts\activate.bat || goto :err

echo [2/4] Installing dependencies (takes a few minutes)...
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :err
pip install pyinstaller || goto :err

echo [3/4] Building with PyInstaller...
pyinstaller mtpe.spec --noconfirm || goto :err

echo.
echo ============================================
echo   [DONE] dist\MTPE.exe has been created.
echo   Double-click it to run the app.
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
