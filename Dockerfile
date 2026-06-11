# MTPE 번역 파이프라인 — 서버 배포용 이미지
FROM python:3.11-slim

WORKDIR /app

# 의존성 먼저 설치(캐시 활용). pywebview 는 darwin 전용 마커라 리눅스에선 설치 안 됨.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드 복사 (.dockerignore 로 .venv/works/.env 등은 제외)
COPY . .

# 데이터(prompts/works)는 영구 디스크에 보관. 비어있으면 startup 에서 기본 프롬프트 시드.
ENV MTPE_DATA_DIR=/data
RUN mkdir -p /data

EXPOSE 8000
# PORT 는 호스팅(예: Render)이 주입. 없으면 8000.
CMD ["sh", "-c", "uvicorn mtpe.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
