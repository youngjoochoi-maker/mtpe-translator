"""
run_api.py
----------
소설 분권 API 서버 실행 런처(n8n 연동용).

실행:
    python run_api.py
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
    print(f"  주소   : http://{host}:{port}")
    print(f"  상태확인: http://localhost:{port}/health")
    print(f"  API 토큰: {API_TOKEN}")
    print("  (n8n HTTP Request 헤더에 X-API-Key 로 이 토큰을 넣으세요)")
    print("=" * 56)

    uvicorn.run("novel_splitter.api:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
