"""MTPE 자동화 API 서버 (n8n 등 HTTP 연동용).

데스크톱 앱과 같은 엔진이지만, 창 없이 HTTP API 만 상시 제공한다.
n8n 의 HTTP Request 노드로 아래 엔드포인트를 호출하면 번역이 자동 실행된다.

실행:
    python run_api.py
    MTPE_PORT=9000 python run_api.py

환경변수:
    MTPE_API_TOKEN   자동화 API 보호 토큰(설정 시 헤더 X-API-Key 필수). 외부 노출 시 반드시 설정.
    MTPE_DATA_DIR    데이터 폴더(prompts/works/.env). 미설정 시 OS 기본 위치.
    MTPE_HOST        바인드 호스트(기본 127.0.0.1; 다른 PC/n8n 클라우드에서 접속시 0.0.0.0)
    MTPE_PORT        포트(기본 8000)

주요 엔드포인트:
    GET  /api/automate/works       작품/언어/버전/회차 목록
    POST /api/automate/translate   회차(또는 원문 텍스트) 번역 → 최종 결과 JSON
"""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    from mtpe.server import API_TOKEN, app

    host = os.environ.get("MTPE_HOST", "127.0.0.1")
    port = int(os.environ.get("MTPE_PORT", "8000"))
    auth = ("X-API-Key 필수 (MTPE_API_TOKEN 설정됨)" if API_TOKEN
            else "⚠ 토큰 미설정 — 외부에 노출하지 마세요")
    print("=" * 56, flush=True)
    print(" MTPE 자동화 API 서버 실행 중", flush=True)
    print(f"   주소:       http://{host}:{port}", flush=True)
    print(f"   작품 조회:  GET  /api/automate/works", flush=True)
    print(f"   번역:       POST /api/automate/translate", flush=True)
    print(f"   인증:       {auth}", flush=True)
    print("   종료:       Ctrl+C", flush=True)
    print("=" * 56, flush=True)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
