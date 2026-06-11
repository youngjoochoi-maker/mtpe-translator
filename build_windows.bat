@echo off
REM ── MTPE Windows 빌드 스크립트 ──────────────────────────────
REM 윈도우 PC 에서 실행: 더블클릭 또는  build_windows.bat
REM 결과:  dist\MTPE.exe  (단일 실행파일)
REM 필요: Python 3.11+ 설치 (python --version 으로 확인)

setlocal
echo [1/4] 가상환경 생성...
python -m venv build-venv || goto :err
call build-venv\Scripts\activate.bat || goto :err

echo [2/4] 의존성 설치...
python -m pip install --upgrade pip
pip install -r requirements.txt || goto :err
pip install pyinstaller || goto :err

echo [3/4] 빌드 (PyInstaller)...
pyinstaller mtpe.spec --noconfirm || goto :err

echo [4/4] 완료!
echo   실행파일: %CD%\dist\MTPE.exe
echo   더블클릭하면 앱이 실행됩니다.
goto :eof

:err
echo.
echo [오류] 빌드 실패. 위 메시지를 확인하세요.
exit /b 1
