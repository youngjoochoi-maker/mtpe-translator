# -*- mode: python ; coding: utf-8 -*-
# 소설 분권 프로그램 PyInstaller 스펙 (Windows .exe / macOS .app)
#
# 빌드:
#   pyinstaller novel_splitter.spec --noconfirm
# 결과:
#   Windows -> dist/소설분권.exe
#   macOS   -> dist/소설분권.app  (및 dist/소설분권 실행 파일)

from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
hiddenimports = []

# PySide6 / python-docx 는 데이터·서브모듈이 많아 통째로 수집
for pkg in ("PySide6", "shiboken6", "docx"):
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception:
        pass

a = Analysis(
    ["run_splitter.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 용량을 줄이기 위해 사용하지 않는 무거운 패키지는 제외
    excludes=[
        "tkinter", "matplotlib", "numpy", "pandas", "scipy",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtQml",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

# onedir 모드: macOS .app 번들 권장 방식(실행 안정·속도 개선)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,   # 바이너리는 COLLECT 로 분리 (onedir)
    name="소설분권",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,           # GUI 앱 (콘솔 창 없음)
    disable_windowed_traceback=False,
    argv_emulation=False,    # LaunchServices(더블클릭) 실행 시 조기 종료 방지
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="소설분권",
)

# macOS 앱 번들
app = BUNDLE(
    coll,
    name="소설분권.app",
    icon=None,
    bundle_identifier="com.voithru.novelsplitter",
    info_plist={
        "CFBundleName": "소설분권",
        "CFBundleDisplayName": "소설 분권 프로그램",
        "NSHighResolutionCapable": True,
    },
)
