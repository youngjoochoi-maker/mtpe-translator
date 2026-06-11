# -*- mode: python ; coding: utf-8 -*-
# MTPE 데스크톱 앱 PyInstaller 스펙 (Windows .exe / 단일 파일)
#
# 빌드: pyinstaller mtpe.spec --noconfirm
# 결과: dist/MTPE.exe
#
# 앱은 서버를 백그라운드로 띄우고 네이티브 창(pywebview)으로 UI 를 연다.
# pywebview 백엔드 로딩이 실패하면 자동으로 기본 브라우저로 대체된다(desktop.py).

from PyInstaller.utils.hooks import collect_all

# 번들에 포함할 읽기전용 리소스
datas = [
    ('config.yaml', '.'),
    ('mtpe/web', 'mtpe/web'),
    ('prompts', 'prompts'),
]
binaries = []
hiddenimports = [
    # uvicorn 은 동적 import 가 많아 명시
    'uvicorn', 'uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto',
    'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto',
    'uvicorn.protocols.http.h11_impl',
    'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan', 'uvicorn.lifespan.on',
    'multipart', 'python_multipart', 'itsdangerous',
]

# 데이터·서브모듈이 많은 패키지는 통째로 수집 (best-effort)
for pkg in ('litellm', 'tiktoken', 'tiktoken_ext', 'webview', 'openpyxl', 'docx', 'yaml'):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MTPE',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,             # 첫 빌드 디버깅용(오류 확인). 정상 확인 후 False 로 바꾸세요.
    disable_windowed_traceback=False,
    icon='MTPE.ico',
)
