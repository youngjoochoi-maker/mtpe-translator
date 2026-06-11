"""MTPE 데스크톱 앱 런처.

로컬 서버를 백그라운드 스레드로 띄우고, 네이티브 창(pywebview)으로 UI 를 연다.
pywebview 가 없거나 실패하면 기본 브라우저로 대신 연다.

환경변수:
  MTPE_PORT       시작 포트(기본 8000, 사용 중이면 다음 빈 포트)
  MTPE_NO_WINDOW  값이 있으면 창을 열지 않고 서버만 유지(테스트/헤드리스용)
"""

from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser


def _is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def _find_port(preferred: int = 8000) -> int:
    for p in [preferred, *range(8001, 8021)]:
        if _is_free(p):
            return p
    return preferred


def _wait_until_up(port: int, timeout: float = 20.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if not _is_free(port):
            return True
        time.sleep(0.2)
    return False


def _serve(port: int) -> None:
    import uvicorn

    from .server import app

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


class _DesktopApi:
    """JS ↔ Python 브리지. 네이티브 창에서 파일 저장/복사를 처리한다.

    (pywebview WebKit 에서는 blob 다운로드가 크래시하므로 저장은 Python 이 담당.)
    """

    def save_file(self, filename, content):
        import webview

        try:
            win = None
            getter = getattr(webview, "active_window", None)
            if getter:
                win = getter()
            if win is None and getattr(webview, "windows", None):
                win = webview.windows[0]
            if win is None:
                return {"ok": False, "error": "창을 찾을 수 없습니다."}
            result = win.create_file_dialog(
                webview.SAVE_DIALOG, save_filename=(filename or "result.txt")
            )
            if not result:
                return {"ok": False, "cancelled": True}
            path = result[0] if isinstance(result, (list, tuple)) else result
            with open(path, "w", encoding="utf-8") as f:
                f.write(content or "")
            return {"ok": True, "path": str(path)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def copy_text(self, content):
        # OS 별 클립보드 명령 (mac: pbcopy / windows: clip / linux: xclip|xsel)
        import subprocess
        import sys

        data = (content or "").encode("utf-8")
        if sys.platform == "darwin":
            cmds = [["pbcopy"]]
        elif sys.platform.startswith("win"):
            cmds = [["clip"]]
        else:
            cmds = [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
        for cmd in cmds:
            try:
                p = subprocess.run(cmd, input=data)
                if p.returncode == 0:
                    return {"ok": True}
            except Exception:  # noqa: BLE001
                continue
        # 실패해도 JS 쪽 navigator.clipboard 폴백이 있으므로 ok=False 만 반환
        return {"ok": False}


def main() -> None:
    port = _find_port(int(os.environ.get("MTPE_PORT", "8000")))
    url = f"http://127.0.0.1:{port}"

    threading.Thread(target=_serve, args=(port,), daemon=True).start()
    _wait_until_up(port)
    print(f"MTPE 실행 중: {url}", flush=True)

    if os.environ.get("MTPE_NO_WINDOW"):
        _idle()
        return

    try:
        import webview  # pywebview

        webview.create_window(
            "MTPE 번역 파이프라인", url, width=1280, height=880, min_size=(900, 600),
            js_api=_DesktopApi(),
        )
        webview.start()
    except Exception as exc:  # noqa: BLE001
        print(f"네이티브 창을 열 수 없어 브라우저로 엽니다: {exc}", flush=True)
        webbrowser.open(url)
        _idle()


def _idle() -> None:
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
