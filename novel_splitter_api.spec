# -*- mode: python ; coding: utf-8 -*-
# 소설 분권 API 서버 PyInstaller 스펙 (n8n 연동용 콘솔 실행 파일)
#
# 빌드: pyinstaller novel_splitter_api.spec --noconfirm
# 결과:
#   Windows -> dist/분권API.exe    (더블클릭/실행하면 서버 시작)
#   macOS   -> dist/분권API        (터미널에서 ./분권API 실행)
#
# GUI 가 아니라 콘솔 서버이므로 onefile + console=True 로 만든다.

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
# uvicorn/fastapi/starlette 는 동적 import 가 많아 명시 + 통째 수집
hiddenimports = [
    "uvicorn", "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "multipart", "python_multipart",
    "novel_splitter.api",
]

for pkg in ("fastapi", "starlette", "uvicorn", "anyio", "docx", "openpyxl", "multipart"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ["run_api.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "scipy", "PySide6"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="분권API",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,   # 콘솔 서버(로그·토큰 출력)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
