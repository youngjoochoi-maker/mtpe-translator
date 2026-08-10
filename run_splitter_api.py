"""
run_splitter_api.py
-------------------
소설 분권 API 서버 실행 런처(n8n 연동용).

실행:
    python run_splitter_api.py
환경변수(선택):
    SPLITTER_API_TOKEN : API 인증 토큰(미지정 시 자동 생성/저장)
    SPLITTER_API_PORT  : 포트(기본 8000)
    SPLITTER_API_HOST  : 바인드 주소(기본 0.0.0.0 - 외부 접속 허용)
"""

import os

import uvicorn

from novel_splitter.api import API_TOKEN


def main() -> None:
    host = os.environ.get("SPLITTER_API_HOST", "0.0.0.0")
    port = int(os.environ.get("SPLITTER_API_PORT", "8000"))

    print("=" * 56)
    print("  소설 분권 API 서버")
    print("=" * 56)
    print(f"  웹 UI  : http://localhost:{port}/   (브라우저로 접속해 직접 사용)")
    print(f"  상태확인: http://localhost:{port}/health")
    print(f"  API 토큰: {API_TOKEN}")
    print("  (웹 UI 첫 접속 시 위 토큰을 한 번 입력 / n8n 은 X-API-Key 헤더에 사용)")
    print("=" * 56)

    uvicorn.run("novel_splitter.api:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
