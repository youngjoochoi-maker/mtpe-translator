"""앱 내 통신 로그 버퍼 — LLM 요청/응답/재시도/오류를 한 줄씩 기록.
터미널(stdout)에도 같이 출력하고, UI 콘솔 박스가 /api/log 로 가져간다."""
from __future__ import annotations

import sys
import threading
import time
from collections import deque

_LINES: deque[tuple[int, str]] = deque(maxlen=800)
_SEQ = 0
_LOCK = threading.Lock()
_CTX = threading.local()  # 스레드별 문맥(회차명) — 동시 실행 시 로그 구분용


def set_context(name: str | None) -> None:
    """현재 스레드의 로그 접두어(예: 회차명)를 설정. None 이면 해제."""
    _CTX.name = name


def log(msg: str) -> None:
    global _SEQ
    ctx = getattr(_CTX, "name", None)
    line = f"[{time.strftime('%H:%M:%S')}] " + (f"[{ctx}] " if ctx else "") + msg
    with _LOCK:
        _SEQ += 1
        _LINES.append((_SEQ, line))
    try:
        print(line, flush=True, file=sys.stdout)
    except Exception:  # noqa: BLE001
        pass


def since(seq: int) -> tuple[int, list[str]]:
    with _LOCK:
        lines = [l for s, l in _LINES if s > seq]
        return _SEQ, lines


def clear() -> None:
    global _SEQ
    with _LOCK:
        _LINES.clear()
