"""원문/설정집 입력 읽기와 결과 쓰기. txt/md/docx 지원."""

from __future__ import annotations

from pathlib import Path


def read_text(path: str | Path) -> str:
    """텍스트/문서 파일을 평문 문자열로 읽는다."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {path}")

    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _read_docx(path)
    if suffix in {".xlsx", ".xlsm"}:
        return _read_xlsx(path)
    if suffix in {".txt", ".md", ".srt", ".vtt", ""}:
        return path.read_text(encoding="utf-8")
    # 알 수 없는 확장자는 일단 평문으로 시도
    return path.read_text(encoding="utf-8")


def _read_docx(path: Path) -> str:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "docx 파일을 읽으려면 python-docx 가 필요합니다: pip install python-docx"
        ) from exc
    document = Document(str(path))
    return "\n".join(p.text for p in document.paragraphs)


# ── TB 탭 이름 별칭 ──────────────────────────────────────────────
# 작품마다 TB 양식이 달라 같은 탭이 한국어(인물/용어/호칭) 또는 영어(Characters/Term Localizations/
# Honorifics)로 되어 있다. 프롬프트·배치지시서(TB시트)는 어느 쪽 이름을 써도 되도록 같은 탭으로 본다.
#   - 시트 선택(TB시트) 매칭: '인물' 로 골라도 'Characters' 탭이 선택되고, 그 반대도 마찬가지.
#   - AI 에 넘기는 제목: '## [Characters] (= 인물)' 처럼 원래 이름 + 같은 뜻의 다른 이름을 함께 표기.
# 대소문자·앞뒤 공백은 무시. 목록에 없는 탭은 원래 이름 그대로.
TB_SHEET_ALIASES: dict[str, list[str]] = {
    "인물": ["Characters"],
    "용어": ["Term Localizations"],
    "호칭": ["Honorifics", "Forms of Address"],
}


def _norm_sheet(name: str) -> str:
    return " ".join(str(name or "").split()).lower()


def tb_sheet_group(name: str) -> str | None:
    """탭 이름이 속한 별칭 그룹(한국어 표준명). 해당 없으면 None."""
    n = _norm_sheet(name)
    for ko, ens in TB_SHEET_ALIASES.items():
        if n == _norm_sheet(ko) or n in (_norm_sheet(e) for e in ens):
            return ko
    return None


def tb_sheet_matches(title: str, wanted: str) -> bool:
    """TB 탭(title)이 선택 이름(wanted)과 같은 탭인지 — 정확히 같거나 같은 별칭 그룹이면 True."""
    if str(title).strip() == str(wanted).strip():
        return True
    g = tb_sheet_group(title)
    return g is not None and g == tb_sheet_group(wanted)


def tb_sheet_label(title: str) -> str:
    """AI 에 넘길 탭 제목. 별칭 그룹이면 같은 뜻의 다른 이름을 함께 표기."""
    g = tb_sheet_group(title)
    if not g:
        return f"[{title}]"
    others = [n for n in [g] + TB_SHEET_ALIASES[g] if _norm_sheet(n) != _norm_sheet(title)]
    return f"[{title}] (= {' / '.join(others)})"


def _read_xlsx(path: Path, sheets: list[str] | None = None) -> str:
    """엑셀 TB를 텍스트로 변환한다. 시트별 '## <시트명>' 섹션 + 행을 ' | ' 로 연결.

    sheets 가 주어지면 해당 시트만 읽는다(없으면 전체). 탭 이름은 TB_SHEET_ALIASES 별칭도 같은 탭으로 본다.
    완전히 빈 행은 건너뛰고, 후행 빈 셀은 잘라낸다.
    """
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "xlsx 파일을 읽으려면 openpyxl 이 필요합니다: pip install openpyxl"
        ) from exc

    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    out: list[str] = []
    for ws in wb.worksheets:
        # sheets is None → 전체 / 리스트(빈 리스트 포함) → 그 시트만
        if sheets is not None and not any(tb_sheet_matches(ws.title, w) for w in sheets):
            continue
        lines: list[str] = []
        for row in ws.iter_rows(values_only=True):
            cells = [_fmt_cell(c) for c in row]
            while cells and cells[-1] == "":
                cells.pop()
            # 내용 있는 셀이 2개 미만이면(인덱스만 있는 빈 템플릿 행 등) 건너뜀
            if sum(1 for c in cells if c) < 2:
                continue
            lines.append(" | ".join(cells))
        if lines:
            out.append(f"## {tb_sheet_label(ws.title)}\n" + "\n".join(lines))
    wb.close()
    return "\n\n".join(out)


def _fmt_cell(c) -> str:
    """셀 값을 문자열로. 정수형 float(1.0)는 '1' 로 정리."""
    if c is None:
        return ""
    if isinstance(c, float) and c.is_integer():
        return str(int(c))
    return str(c).strip()


def write_text(path: str | Path, content: str) -> None:
    """결과를 파일로 저장한다. 상위 디렉터리는 자동 생성."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
