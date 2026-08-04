# -*- mode: python ; coding: utf-8 -*-
# MTPE 자동화 API 서버 PyInstaller 스펙 (Windows .exe / 단일 파일)
#
# 빌드: pyinstaller mtpe_api.spec --noconfirm
# 결과: dist/MTPEApi.exe
#
# 창 없이 HTTP API 만 상시 제공(n8n 등 연동). 실행하면 콘솔에 주소·엔드포인트가 뜬다.

from PyInstaller.utils.hooks import collect_all

datas = [
    ('config.yaml', '.'),
    ('mtpe/web', 'mtpe/web'),
    ('prompts', 'prompts'),
]
binaries = []
hiddenimports = [
    'uvicorn', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
    'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan', 'uvicorn.lifespan.on',
    'multipart', 'python_multipart', 'itsdangerous',
]

# API 서버는 pywebview 불필요 → webview 제외(용량↓). 나머지는 통째로 수집.
for pkg in ('litellm', 'tiktoken', 'tiktoken_ext', 'openpyxl', 'docx', 'yaml'):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ['run_api.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'webview'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MTPEApi',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,             # API 서버라 콘솔 표시(주소·로그 확인)
    disable_windowed_traceback=False,
    icon='MTPE.ico',
)
