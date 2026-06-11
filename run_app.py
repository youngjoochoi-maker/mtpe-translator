"""데스크톱 앱 진입점 (PyInstaller 패키징용).

Windows: MTPE.exe / macOS: MTPE.app 가 이 스크립트를 실행한다.
서버를 백그라운드로 띄우고 네이티브 창(pywebview)으로 UI 를 연다.
"""

from mtpe.desktop import main

if __name__ == "__main__":
    main()
