# 소설 분권 프로그램 (Novel Splitter)

번역용 소설(docx/txt)을 다양한 기준으로 자동 분권하고, 각 분권의 분량을 계산하는 데스크톱 프로그램입니다. Windows / macOS 양쪽에서 동작합니다.

## 주요 기능

- **지원 파일**: `.docx`, `.txt` (UTF-8, UTF-8 BOM, CP949 자동 감지)
- **파일 선택 / 드래그앤드롭**, 여러 파일 일괄 처리
- 선택 파일의 **전체 글자수·단어수·줄수** 미리보기
- **3가지 분권 방식**
  1. **구분자 기준** — 입력한 문자열로 시작하는 줄에서 분권 (구분자 포함/제거 옵션)
  2. **글자수 기준** — 누적 글자수가 기준 이상이면 분권 (문단 경계에서만, 문장 중간 자르지 않음)
  3. **단어수 기준** — 누적 단어수가 기준 이상이면 분권
- **출력**: 원본과 같은 폴더에 `원본이름/` 폴더 자동 생성, `원본_0001.docx` 형식 4자리 번호
- **출력 옵션**: 출력 폴더 직접 선택 / 덮어쓰기 / 번호 앞·뒤 위치
- **진행률 표시**(Progress Bar), 로그, 결과 표(번호·파일명·공백포함/제외 글자수·단어수·줄수)와 총합

## 설치

```bash
pip install PySide6 python-docx
```

## 실행

```bash
# 방법 1: 런처
python run_splitter.py

# 방법 2: 모듈
python -m novel_splitter.main
```

## 모듈 구조

| 파일 | 역할 |
|------|------|
| `reader.py` | 파일 읽기 (docx/txt, 인코딩 자동 감지) |
| `splitter.py` | 분권 로직 (구분자/글자수/단어수) |
| `counter.py` | 분량 계산 (글자수/단어수/줄수) |
| `writer.py` | 분권 결과 저장 |
| `processor.py` | reader/splitter/counter/writer 오케스트레이션 |
| `mainwindow.py` | PySide6 GUI |
| `utils.py` | 공통 유틸리티 |
| `main.py` | 진입점 |

`processor.py` 는 GUI 없이도 사용할 수 있어 자동화·테스트에 활용할 수 있습니다.
