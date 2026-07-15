"""
run_splitter.py
---------------
소설 분권 프로그램 실행 런처.

프로젝트 루트에서 다음과 같이 실행한다.
    python run_splitter.py
"""

import sys

from novel_splitter.main import main

if __name__ == "__main__":
    sys.exit(main())
