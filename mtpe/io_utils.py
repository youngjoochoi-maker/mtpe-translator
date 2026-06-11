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


def _read_xlsx(path: Path, sheets: list[str] | None = None) -> str:
    """엑셀 TB를 텍스트로 변환한다. 시트별 '## <시트명>' 섹션 + 행을 ' | ' 로 연결.

    sheets 가 주어지면 해당 시트만 읽는다(없으면 전체).
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
        if sheets is not None and ws.title not in sheets:
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
            out.append(f"## [{ws.title}]\n" + "\n".join(lines))
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
