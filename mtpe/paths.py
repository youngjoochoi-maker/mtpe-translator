"""실행 환경(개발 / PyInstaller 패키징)과 OS 에 맞는 경로 해석.

- resource_root(): 읽기전용 번들 리소스(config.yaml, mtpe/web, 기본 prompts)
- data_root():     쓰기 가능한 데이터(prompts 편집본, works, .env)
  · MTPE_DATA_DIR 환경변수가 있으면 그것을 사용(서버 배포)
  · 패키징(.exe/.app) 이면 OS 별 사용자 데이터 폴더
  · 개발(소스 실행)이면 프로젝트 루트
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """번들된 읽기전용 리소스의 루트."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", _PROJECT_ROOT))
    return _PROJECT_ROOT


def app_data_dir() -> Path:
    """OS 별 사용자 데이터 폴더 (.../MTPE)."""
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "MTPE"


def data_root() -> Path:
    """쓰기 가능한 데이터 루트."""
    env = os.environ.get("MTPE_DATA_DIR")
    if env:
        return Path(env)
    if is_frozen():
        return app_data_dir()
    return _PROJECT_ROOT
