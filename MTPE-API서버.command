#!/bin/bash
# MTPE 자동화 API 서버 — 로컬 실행 (더블클릭)
# n8n(같은 PC) 에서 http://127.0.0.1:8000/api/automate/... 로 호출.
# 창을 닫으면 서버가 꺼집니다. 켜 두면 n8n 이 호출할 수 있습니다.

cd "/Users/p-063/Library/Mobile Documents/com~apple~CloudDocs/young/MTPE" || exit 1

# 데이터(프롬프트·회차·결과·키)는 iCloud 밖 로컬 폴더 사용(동기화 삭제 방지)
export MTPE_DATA_DIR="$HOME/MTPE-data"
export MTPE_HOST="127.0.0.1"      # 같은 PC의 n8n 만 접속(로컬 전용). 사내망 공유하려면 0.0.0.0
export MTPE_PORT="8000"

# 로컬 테스트는 토큰 없이도 됩니다. 사내 공유/배포 시 아래 주석을 풀고 값을 바꾸세요.
# export MTPE_API_TOKEN="사내-비밀-토큰"

echo "MTPE API 서버를 시작합니다. (종료: 이 창에서 Ctrl+C 또는 창 닫기)"
exec "./.venv/bin/python" run_api.py
