"""
main.py
-------
프로그램 진입점.

실행:
    python -m novel_splitter.main
또는 프로젝트 루트의 run_splitter.py 를 실행한다.
"""

from __future__ import annotations

import sys


def main() -> int:
    """GUI를 띄운다."""
    from .mainwindow import run_gui

    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
