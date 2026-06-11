# MTPE 번역 파이프라인

원문 + 설정집(TB)을 **작품·언어·버전별 5단계 프롬프트 번들**에 통과시켜 MT(기계번역)를 추출하는 CLI 도구.
LiteLLM 기반이라 모델 문자열만 바꾸면 **모든 LLM(Anthropic / OpenAI / Google …)** 을 쓸 수 있다.

```
[설정집/TB] ─┐
[원문] ───────┼─▶ STEP1 → STEP2 → STEP3 → STEP4 → STEP5 ─▶ 최종 MT
             ┘   (각 단계는 자기가 필요한 이전 산출물만 골라 받음)
```

## 프롬프트 번들 (작품별·언어별·버전별)

프롬프트는 코드와 분리되어 **번들 폴더**로 관리된다. 새 버전은 폴더만 떨어뜨리면 적용된다.

```
prompts/<작품>/<언어쌍>/<버전>/
    step1.txt … step5.txt     # 단계별 프롬프트 (따로 작업 → 버전업 시 교체)
    meta.yaml                 # 단계별 입력 의존성·모델·출력추출·최종단계
```

예: `prompts/장저견/zh-ko/v1/`. 버전을 지정하지 않으면 **최신 버전**(숫자가 큰 폴더)을 자동 선택.
버전업은 `v2/` 폴더를 추가하고 `-V v2` 로 지정(또는 미지정 시 자동으로 최신).

### meta.yaml — 단계별 데이터 흐름 정의
단계 간 흐름이 단순 선형이 아니므로, 각 단계가 받을 산출물을 `inputs`로 명시한다.

```yaml
steps:
  - id: 1   # 번역핵심정보 추출
    inputs: [source, glossary]
    extract: tag:o          # 출력의 <o>...</o> 안만 추출 (JSON)
  - id: 3   # 초벌 번역
    inputs: [source, step2]
  - id: 5   # 최종 교열
    inputs: [source, step2, step4, step3]
    output: final           # 이 단계 결과 = 최종 산출물
```
`inputs` 키: `source`(원문) · `glossary`(설정집/TB) · `step1`~`stepN`(각 단계 출력).
지정한 산출물이 프롬프트 뒤에 `[입력 자료]` 블록으로 자동 첨부된다.
(프롬프트에 `{{SOURCE}}` 같은 토큰을 직접 쓰면 자동첨부 대신 토큰 치환 모드로 동작.)

## 설치

```bash
python -m venv .venv && ./.venv/bin/python -m pip install -r requirements.txt
```

## A. 앱으로 실행 (더블클릭) — 가장 쉬움

Finder 에서 **`MTPE.app`** 더블클릭 → 내부 서버가 자동으로 뜨고 **네이티브 창**으로 UI 가 열린다.
(창이 안 되면 기본 브라우저로 자동 전환). 창을 닫으면 서버도 함께 종료된다.
자주 쓰면 **Dock 이나 응용 프로그램 폴더로 드래그**해 두면 편하다.

- 동작 원리: `MTPE.app/Contents/MacOS/MTPE` → 프로젝트 `.venv` 로 `python -m mtpe.desktop` 실행
- 앱이 프로젝트 폴더 안에 있으면 경로를 자동 인식. 다른 곳으로 옮기면 런처 스크립트의 `FALLBACK` 경로를 사용
- 로그: `/tmp/mtpe-app.log`
- 네이티브 창은 `pywebview`(설치됨). 없으면 자동으로 브라우저로 열림

## B. 웹 UI (서버 직접 실행)

브라우저에서 키·모델을 넣고 파일을 올려 클릭으로 번역. 키는 **로컬 `.env`에만** 저장.

```bash
./.venv/bin/python -m mtpe.server      # http://127.0.0.1:8000
# 또는 데스크톱 런처(빈 포트 자동 선택 + 창):
./.venv/bin/python -m mtpe.desktop
```
**번역 탭** — 화별 운영:
- 모델 선택 → API 키 저장
- 작품/언어/버전(프롬프트) 선택
- **설정집(TB)**: 최신 1개 유지(주차 업데이트 시 교체). 업로드/삭제(✕).
  엑셀(.xlsx) 권장 — **양식 템플릿 다운로드**(`/api/tb-template`)로 인물·용어·호칭·인물관계·제목·서식 시트가
  채워진 .xlsx 를 받아 작성. **시트 선택**: 작품마다 TB 시트 구성이 달라서, 업로드된 TB의 실제 시트 목록을
  보여주고 **체크한 시트만 AI에 전달**(선택은 작품별 `library.json`에 저장). 새 TB 업로드 시 선택은 전체로 초기화
- **회차 원문**: 폴더 경로 지정(외부 폴더 읽기) + 개별 업로드 둘 다. 업로드분은 삭제(✕) 가능,
  폴더 원문은 보호(앱에서 삭제 안 함)
- **회차 선택**(체크박스, 전체/해제) → 선택한 회차만 **순차 번역** (대량 일괄 없음)
- 회차마다 단계별 진행(STEP1✓ … STEP5)이 실시간 표시되고, 결과는 회차별 복사/다운로드
- 결과는 서버에도 저장: `works/<작품>/output/<회차>/final.txt`

자료 라이브러리 구조: `works/<작품>/episodes/`(업로드 회차) · `tb/`(설정집 1개) · `library.json`(폴더 경로)

**프롬프트 관리 탭**: 작품/언어/버전을 불러와 STEP1~5 프롬프트와 메타(이름·inputs·모델·extract·최종)를 편집.
저장은 **현재 버전 덮어쓰기** 또는 **새 버전으로 저장(자동 v+1)**, **이 버전 삭제**도 가능.
`+ 새 작품/언어`로 새 번들을 빈 5단계 템플릿부터 만들 수 있다 → 프롬프트를 따로 작업해 버전업으로 교체하는 흐름을 UI에서 직접 수행.

**프롬프트 튜닝(시험 실행)**: 같은 탭에서 샘플 회차 + 모델을 골라 **저장하지 않은 편집본**으로 실행(`/api/tune`).
각 STEP 카드 아래에 그 단계 결과 + **실제 보낸 프롬프트**가 표시되고, 프롬프트를 고친 뒤 **[이 단계부터 다시]**로
그 단계만 재실행(앞 단계 출력은 재사용해 비용 절감). 만족하면 그대로 버전 저장 → MT 추출 프롬프트 개선 루프.

## B. CLI

```bash
export ANTHROPIC_API_KEY=sk-...        # 또는 .env 파일 (cp .env.example .env)

# 기본 작품/언어(config) + 최신 버전
./.venv/bin/python -m mtpe.cli -s 원문.txt -g tb.xlsx --out out/

# 작품/언어/버전 지정 + 단계별 모델 강제 + 중간결과 저장
./.venv/bin/python -m mtpe.cli -s 원문.txt -g tb.xlsx -w 장저견 -l zh-ko -V v1 -m gpt-4o --save-stages

# 점검(토큰 0): 번들 로드 + API키 상태
./.venv/bin/python -m mtpe.cli --check
# 조립 프롬프트만 저장(LLM 호출 없음): 원문·TB 주입 확인
./.venv/bin/python -m mtpe.cli -s 원문.txt -g tb.xlsx --dry-run
```
- 최종: `out/final.txt` (표준출력으로도 출력 → 파이프 연결 가능)
- `--save-stages`: 각 단계 **원응답**을 `out/step1_*.txt` … 로 저장
- 입력은 txt/md/docx + **xlsx**(설정집/TB) 지원

## 구성 요소

| 파일 | 역할 |
|---|---|
| `config.yaml` | 전역 기본값(모델·언어·기본 작품) + 프롬프트 루트/기본 선택 |
| `prompts/<작품>/<언어>/<버전>/` | 번들: `step*.txt` + `meta.yaml` (**프롬프트는 여기서 따로 작업**) |
| `mtpe/bundle.py` | 번들 해석·버전 선택(최신 자동) |
| `mtpe/pipeline.py` | 단계 체인 + 입력 자동첨부 + `<o>` 추출 + 최종단계 선택 |
| `mtpe/llm.py` | LiteLLM 호출 래퍼 (provider 무관) |
| `mtpe/io_utils.py` | txt/md/docx/**xlsx** 읽기·쓰기 |
| `mtpe/cli.py` | CLI 진입점 (`--check`, `--dry-run` 포함) |
| `mtpe/server.py` + `mtpe/web/` | 로컬 웹 UI (FastAPI + 단일 HTML) |

### 단계별 다른 LLM
`meta.yaml` 각 step `model:` 에 모델 문자열을 넣으면 그 단계만 다른 LLM을 쓴다
(예: STEP3 초벌은 빠른 모델, STEP5 교열만 고성능 모델). 전체 강제는 CLI `-m`.

## 테스트

```bash
python -m pytest tests/ -q   # 실제 API 호출 없이 번들·체인 로직 검증
```
