# 소설 분권 × n8n 자동화 가이드

Google Drive에 원고를 올리면 → n8n이 자동으로 분권 API를 호출해 → 분권 결과를 다시 Drive에 저장하는 자동화 구성 가이드입니다.

## 전체 그림

```
[Google Drive: 원고 업로드]
        │  ① n8n Google Drive 트리거 (새 파일 감지)
        ▼
[n8n 클라우드]
        │  ② 파일 다운로드 → ③ 분권 API 호출(HTTP)
        ▼
[Cloudflare 터널] ──▶ [담당자 PC: 분권API.exe]
        ▲                        └ 분권 + 글자수 집계
        │  ④ 결과(zip + 회차별 글자수) 반환
        ▼
[n8n: 결과를 Drive 업로드 / Sheet 기록]
```

- **담당자 PC**에서 `분권API.exe` 를 실행(상시)
- **Cloudflare 터널**로 그 API를 인터넷 주소로 안전하게 노출
- **n8n 클라우드**가 그 주소로 파일을 보내고 결과를 받음

---

## 1단계 · PC에서 분권 API 실행

1. `분권API.exe`(Windows) 또는 `분권API`(Mac)를 실행합니다.
2. 실행하면 콘솔 창에 **API 토큰**이 표시됩니다. 이 토큰을 복사해 두세요(n8n에서 사용).
   ```
   ========================================================
     소설 분권 API 서버
     주소   : http://0.0.0.0:8000
     API 토큰: AbCdEf...(여기 표시)
   ========================================================
   ```
3. 같은 PC 브라우저에서 `http://localhost:8000/health` 접속 → `{"status":"ok"}` 나오면 정상.

> 토큰을 직접 정하고 싶으면, 실행 전에 환경변수 `SPLITTER_API_TOKEN` 을 지정하세요.
> 창을 닫으면 서버가 꺼지므로, 자동화 중에는 켜 두어야 합니다.

---

## 2단계 · Cloudflare 터널로 인터넷에 노출

n8n 클라우드(인터넷)가 사내 PC를 부를 수 있도록 터널을 엽니다. 무료이고 공유기 설정이 필요 없습니다.

1. `cloudflared` 설치
   - Windows: <https://github.com/cloudflare/cloudflared/releases> 에서 `cloudflared-windows-amd64.exe` 다운로드
   - Mac: `brew install cloudflared`
2. 터널 실행(별도 창):
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
3. 출력에 나오는 공개 주소를 복사합니다(예: `https://random-words.trycloudflare.com`).
   이 주소가 n8n에서 쓸 **API 주소**입니다.

> 이 방식(빠른 터널)은 주소가 실행할 때마다 바뀝니다. 고정 주소가 필요하면
> Cloudflare 계정으로 명명된 터널(named tunnel)을 만들면 됩니다 — 필요 시 안내드립니다.

---

## 3단계 · n8n 연결 테스트 (먼저 이것부터)

1. n8n에서 **Import from File** → 저장소의 `n8n/n8n_연결테스트.json` 불러오기
2. `분권 API 호출` 노드를 열어 두 값을 바꿉니다:
   - `URL`: `https://<2단계 터널주소>/platform/episodes`
   - `X-API-Key` 헤더 값: `<1단계 토큰>`
3. **Execute Workflow** 클릭 → 네이버 회차 목록(JSON)이 나오면 연결 성공입니다.

---

## 4단계 · 전체 자동화 워크플로 구성

n8n에서 아래 4개 노드를 순서대로 연결합니다.

### ① Google Drive Trigger
- Event: **On File Created (또는 Updated)**
- 감시할 폴더: 원고를 올릴 Drive 폴더 지정
- (처음 사용 시 Google 계정 OAuth 연결)

### ② Google Drive — Download
- Operation: **Download**
- File: 트리거가 넘긴 파일 ID (`{{ $json.id }}`)
- 결과가 **바이너리**로 넘어옵니다(기본 속성명 `data`)

### ③ HTTP Request — 분권 API 호출
- Method: **POST**
- URL: `https://<터널주소>/split`
- **Send Headers** 켜기 → `X-API-Key` = `<토큰>`
- **Send Body** 켜기 → Body Content Type: **Form-Data (multipart)**
- Body 파라미터:
  | 이름 | 타입 | 값 |
  |------|------|-----|
  | `file` | **n8n Binary File** | 입력 바이너리 속성명(예: `data`) |
  | `mode` | Form Data | `separator` / `char_count` / `word_count` |
  | `separator` | Form Data | (구분자 기준일 때) 예: `###` |
  | `count_limit` | Form Data | (글자수/단어수 기준일 때) 예: `5000` |
- 응답(JSON): `output_count`, `chunks[]`(회차별 글자수·제목), `zip_base64`

### ④ 결과 저장 (택1 또는 병행)
- **분권 파일 Drive 업로드**:
  - Set/Code 노드로 `zip_base64` 를 바이너리로 변환
    (Code 노드: `return [{ binary: { zip: { data: $json.zip_base64, fileName: $json.zip_filename, mimeType: 'application/zip' } } } ]`)
  - Google Drive — Upload 로 업로드
- **회차별 글자수 Sheet 기록**:
  - `chunks` 배열을 Google Sheets — Append 로 기록
    (열: 파일명 `{{ $json.filename }}`, 공백포함 `{{ $json.counts.chars_with_spaces }}` 등)

---

## API 레퍼런스

| 메서드/경로 | 파라미터 | 반환 |
|-------------|----------|------|
| `GET /health` | (없음, 인증 불필요) | 상태 |
| `POST /count` | `file` | 전체 글자수/단어수/줄수 |
| `POST /split` | `file`, `mode`, `separator`, `include_separator`, `remove_separator`, `count_limit`, `char_count_with_spaces`, `number_position`, `overwrite`, `include_zip` | 분권 결과 JSON + zip(base64) |
| `POST /platform/episodes` | `url` | 네이버 시리즈 회차 목록 |

- 모든 요청에 헤더 `X-API-Key: <토큰>` 필요(`/health` 제외)
- 업로드 파일 최대 50MB, docx·txt 지원

---

## 주의사항

- **PC를 켜 두어야** 자동화가 동작합니다(API 서버가 그 PC에서 실행되므로).
- **토큰은 비밀**로 관리하세요. 노출되면 아무나 API를 부를 수 있습니다.
- 빠른 터널 주소는 재실행 시 바뀌므로, n8n의 URL도 함께 갱신해야 합니다(고정 주소는 named tunnel).
- 자동 수집(네이버 등)은 각 플랫폼 약관 범위 내에서 자사 작품 확인 용도로 사용하세요.
- 더 간단한 대안: 사내에 상시 서버(예: 기존 MTPE Docker 호스트)가 있으면 거기에 API를 올려 터널 없이 바로 연동할 수 있습니다.
