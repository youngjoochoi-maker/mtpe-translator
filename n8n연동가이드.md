# MTPE 자동화 API — n8n 연동 가이드

MTPE 번역을 **n8n(또는 다른 자동화 도구)**에서 HTTP로 호출하는 방법입니다.
데스크톱 앱과 같은 엔진이지만, 창 없이 **HTTP API 서버**로 상시 실행합니다.

---

## 1. 왜 API 서버인가
- n8n은 **HTTP 요청**으로 동작합니다 → 항상 떠 있는 서버가 필요.
- 데스크톱 앱(MTPE.app/.exe)은 창 닫으면 종료돼서 자동화 대상이 못 됩니다.
- → **API 서버**(이 문서)를 상시 실행하고, n8n이 그 주소를 호출합니다.

## 1-A. 추천 구성 (사내 사용)
**self-hosted n8n + MTPE API 서버를 같은 사내 PC/서버에서 함께 실행** → n8n이 `localhost` 로 호출.
- 가장 간단(배포·공인도메인 불필요), 전부 사내망 안이라 보안 유리, 비용 0.
- n8n 클라우드는 MTPE API 를 인터넷에 공개 배포해야 해서(HTTPS·보안·비용) 사내 용도엔 과함.
- 빠른 시작용 **import 파일**: `n8n_MTPE_워크플로_스타터.json` (아래 4번) — n8n 에 불러와서 URL·토큰만 바꾸면 됨.

---

## 2. 서버 실행

### 맥/리눅스
```bash
cd <프로젝트>
MTPE_API_TOKEN="원하는-비밀토큰" MTPE_DATA_DIR="$HOME/MTPE-data" ./.venv/bin/python run_api.py
```

### 윈도우
```bat
set MTPE_API_TOKEN=원하는-비밀토큰
python run_api.py
```
(또는 배포한 `MTPEApi.exe` 실행)

### 환경변수
| 변수 | 설명 |
|---|---|
| `MTPE_API_TOKEN` | 자동화 API 보호 토큰. **외부 노출 시 반드시 설정**(헤더 `X-API-Key` 로 검사) |
| `MTPE_DATA_DIR` | 데이터 폴더(prompts/works/.env). 실제 모델 쓰려면 이 `.env` 에 키가 있어야 함 |
| `MTPE_HOST` | 기본 `127.0.0.1`. **다른 PC나 n8n 클라우드에서 접속**하려면 `0.0.0.0` |
| `MTPE_PORT` | 기본 `8000` |

> 실제 번역(Gemini 등)을 하려면 서버의 `.env`(=`$MTPE_DATA_DIR/.env`)에 API 키가 있어야 합니다.
> n8n이 **다른 서버/클라우드**에 있으면, 이 API 서버를 공인 주소로 배포해야 합니다 → `배포가이드.md`.

---

## 3. 엔드포인트

모든 자동화 엔드포인트는 `MTPE_API_TOKEN` 설정 시 헤더 **`X-API-Key: <토큰>`** 이 필요합니다.

### GET `/api/automate/works` — 작품/회차 목록
무엇을 번역할 수 있는지 조회.
```json
{ "ok": true, "works": [
  { "work": "장저견", "langs": [{"lang":"zh-ko","versions":["v1"]}],
    "episodes": ["데모_1화.txt", "데모_2화.txt"] }
]}
```

### POST `/api/automate/translate` — 번역 실행 (핵심)
**요청 본문(JSON):**
| 필드 | 필수 | 설명 |
|---|---|---|
| `work` | ✅ | 작품명 (예: `"장저견"`) |
| `lang` | ✅ | 언어쌍 (예: `"zh-ko"`) — 소문자 |
| `model` | | 기본 `"mock"`. 실제: `"gemini/gemini-2.5-pro"`, `"claude-opus-4-8"` 등 |
| `version` | | 미지정 시 최신 |
| `episode` | △ | 라이브러리 회차 파일명. 주면 그 원문을 읽음 |
| `source` | △ | 원문 텍스트 직접 전달(episode 없을 때) |
| `glossary` | | 설정집 텍스트 직접 전달(없으면 작품 TB 사용) |
| `save` | | 기본 true. episode 일 때 `works/<작품>/output/<회차>/final.txt` 저장 |
| `include_steps` | | 기본 true. 단계별 결과 포함 여부 |

> `episode` 또는 `source` 중 **하나는 필수**.

**응답:**
```json
{ "ok": true, "work": "장저견", "lang": "zh-ko", "version": "v1",
  "episode": "데모_1화.txt", "model": "gemini/gemini-2.5-pro",
  "final": "…최종 번역문…",
  "saved": "…/works/장저견/output/데모_1화/final.txt",
  "steps": [ {"id":1,"name":"1단계","chars":320,"skipped":false,"error":"","output":"…"}, … ] }
```
실패 시: `{ "ok": false, "error": "설명" }` (HTTP 400/401).

---

## 4. n8n 설정 (HTTP Request 노드)

1. **HTTP Request** 노드 추가
2. **Method**: `POST`
3. **URL**: `http://<서버주소>:8000/api/automate/translate`
4. **Authentication**: None (헤더로 직접) → **Headers** 에 `X-API-Key = <토큰>` 추가
5. **Body Content Type**: `JSON` → 아래처럼:
```json
{
  "work": "장저견",
  "lang": "zh-ko",
  "model": "gemini/gemini-2.5-pro",
  "episode": "데모_1화.txt"
}
```
6. 실행 → 응답의 `{{$json.final}}` 이 최종 번역문.

**예시 흐름:** (Schedule) → HTTP GET `/api/automate/works` 로 회차 목록 → Split → 각 회차마다 HTTP POST `/api/automate/translate` → 결과를 Google Drive/Sheets/메일 등으로.

### 빠른 시작 — 스타터 워크플로 import
1. n8n → 우상단 **⋯ → Import from File** → `n8n_MTPE_워크플로_스타터.json` 선택
2. 두 HTTP 노드의 **URL**(서버 주소)과 헤더 **`X-API-Key`**(토큰)만 실제 값으로 변경
3. **MTPE 번역** 노드의 Body(work/lang/model/episode)를 원하는 값으로 수정 → 실행
   (노드: 수동 실행 → 작품·회차 조회 / MTPE 번역)

---

## 5. 보안 주의
- **토큰 없이 외부 노출 금지.** 반드시 `MTPE_API_TOKEN` 설정.
- 서버 `.env` 에 회사 공용 키를 두면 n8n은 키를 몰라도 됩니다(서버가 대신 호출).
- 공인 배포 시 HTTPS(리버스 프록시) 권장.
