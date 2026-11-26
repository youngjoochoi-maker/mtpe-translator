"""원문/설정집 입력 읽기와 결과 쓰기. txt/md/docx 지원."""

from __future__ import annotations

import re
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


# ── 회차별 필수 용어(TB 다이제스트) ─────────────────────────────────
# 설정집 전체(수천 행)를 넣으면 모델이 이번 회차에 필요한 용어를 놓치기 쉽다.
# 원문에 실제로 나온 TB 항목만 글자 대조로 골라 '이번 회차 필수 용어' 블록으로 앞에 붙인다.
# (AI 호출 없음 · 같은 원문이면 항상 같은 결과 · 전체 설정집은 그대로 뒤에 남김)
_TERM_COLS: dict[str, list[str]] = {
    "중국어": ["중문명", "중문", "중국어", "中文", "chinese", "원문"],
    "한국어": ["국문명", "국문", "한국어", "한글", "korean"],
    "일본어": ["일문명", "일문", "일본어", "日本語", "japanese"],
    "영어": ["영문명", "영문", "영어", "english"],
}
_FIRST_COLS = ["첫 등장시기", "첫 등장", "첫등장", "등장회차", "first appearance"]
_NAME_SHEETS = ("인물", "characters")


def _find_col(header: list[str], keys: list[str]) -> int:
    low = [h.strip().lower() for h in header]
    for k in keys:
        if k.lower() in low:
            return low.index(k.lower())
    return -1


def tb_episode_digest(glossary: str, source: str, source_lang: str = "중국어",
                      target_lang: str = "한국어", min_len: int = 2) -> tuple[str, int]:
    """원문에 나온 TB 항목만 뽑아 '이번 회차 필수 용어' 블록을 만든다. (블록, 항목 수) 반환.

    glossary 는 _read_xlsx 가 만든 텍스트('## [탭]' + 'A | B | …' 행). 탭의 첫 줄(머리글)에서
    원문 언어 칸(예: 중문명)과 번역 언어 칸(예: 국문명)을 찾을 수 있는 탭만 대상으로 한다.
    대조 규칙: 원문에서 각 용어의 위치를 모두 찾고, 더 긴 용어 안에 '완전히 들어간' 짧은 용어는
    오탐으로 보고 뺀다(예: 赵夫人和 의 人和). 단 인물 탭 이름은 긴 용어 안에 있어도 남긴다.
    서로 걸쳐 겹치는 경우는 둘 다 남긴다. 찾은 것이 없으면 빈 문자열."""
    import unicodedata as _ud
    norm = lambda s: _ud.normalize("NFC", str(s or "")).strip()
    src = norm(source)
    s_keys = _TERM_COLS.get(source_lang, _TERM_COLS["중국어"])
    t_keys = _TERM_COLS.get(target_lang, _TERM_COLS["한국어"])
    if not src or not glossary:
        return "", 0
    entries = []  # (term, target, sheet, first, is_name)
    sheet, header, si, ti, fi = "", [], -1, -1, -1
    for line in glossary.splitlines():
        if line.startswith("## "):
            sheet, header, si, ti, fi = line[3:].strip(), [], -1, -1, -1
            continue
        cells = [c.strip() for c in line.split(" | ")]
        if not header:
            header = cells
            si, ti = _find_col(header, s_keys), _find_col(header, t_keys)
            fi = _find_col(header, _FIRST_COLS)
            continue
        if si < 0 or ti < 0 or len(cells) <= max(si, ti):
            continue
        term, tgt = norm(cells[si]), norm(cells[ti])
        if not term or not tgt:
            continue
        first = norm(cells[fi]) if 0 <= fi < len(cells) else ""
        is_name = sheet.strip("[]").lower().startswith(_NAME_SHEETS) or "characters" in sheet.lower()
        # '王氏/王燕如' 처럼 한 칸에 여러 표기가 묶여 있으면 각각 대조(국문도 같은 개수면 짝지어 씀)
        parts = [p for p in re.split(r"\s*[/、,，;；]\s*", term) if p]
        tparts = [p for p in re.split(r"\s*/\s*", tgt) if p]
        for k, p in enumerate(parts):
            if len(p) < min_len:
                continue
            t_k = tparts[k] if len(parts) > 1 and len(tparts) == len(parts) else tgt
            entries.append((p, t_k, sheet.split("]")[0].strip("["), first, is_name))
    if not entries:
        return "", 0
    # 원문 속 모든 위치
    occ: dict[str, list[tuple[int, int]]] = {}
    for term in {e[0] for e in entries}:
        pos, i = [], src.find(term)
        while i >= 0:
            pos.append((i, i + len(term)))
            i = src.find(term, i + 1)
        if pos:
            occ[term] = pos
    if not occ:
        return "", 0
    spans = sorted(((a, b, t) for t, ps in occ.items() for a, b in ps), key=lambda x: (x[0], -x[1]))
    names = {e[0] for e in entries if e[4]}

    def nested(a: int, b: int, t: str) -> bool:
        return any(x <= a and b <= y and (y - x) > (b - a) for x, y, u in spans if u != t)

    def crossing(a: int, b: int, t: str) -> bool:
        return any(x < b and a < y and not (x <= a and b <= y) and not (a <= x and y <= b)
                   for x, y, u in spans if u != t)

    keep = {t for t, ps in occ.items() if t in names or any(not nested(a, b, t) for a, b in ps)}
    # 다른 용어와 '걸쳐' 겹친 자리에서만 나온 용어(예: 夫人和 의 人和)는 글자만으로 맞는지 알 수 없어 표시
    unsure = {t for t in keep if t not in names
              and all(nested(a, b, t) or crossing(a, b, t) for a, b in occ[t])}
    first_pos = {t: occ[t][0][0] for t in keep}
    seen, lines = set(), []
    for term, tgt, sh, first, _ in sorted((e for e in entries if e[0] in keep),
                                           key=lambda e: first_pos[e[0]]):
        if (term, tgt) in seen:
            continue
        seen.add((term, tgt))
        extra = ", ".join(x for x in (sh, f"첫 등장 {first}" if first else "",
                                      "다른 용어와 겹침·문맥 확인" if term in unsure else "") if x)
        lines.append(f"- {term} → {tgt}" + (f" ({extra})" if extra else ""))
    head = ("## [이번 회차 필수 용어] — 이번 회차 원문에 실제로 나온 설정집(TB) 항목만 자동으로 모은 목록"
            "(원문 등장 순). 전체 설정집은 아래에 그대로 있음.")
    return head + "\n" + "\n".join(lines), len(lines)
