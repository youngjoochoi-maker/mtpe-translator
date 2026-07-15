"""
reader.py
---------
원본 소설 파일(docx, txt)을 읽어 내부 표현(Document)으로 변환한다.

내부 표현은 '문단(문자열)들의 리스트'로 단순화한다.
- docx : 각 docx 문단(paragraph)이 하나의 항목
- txt  : 각 줄(line)이 하나의 항목

이 통일된 표현 덕분에 splitter/counter/writer 가 파일 형식에 관계없이
동일한 방식으로 동작할 수 있다.

txt 인코딩은 UTF-8, UTF-8 BOM, CP949 를 자동 감지한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .utils import get_file_extension


@dataclass
class Document:
    """읽어들인 문서의 내부 표현."""

    paragraphs: List[str] = field(default_factory=list)  # 문단(또는 줄) 목록
    file_format: str = "txt"  # 'docx' 또는 'txt'
    encoding: str = "utf-8"   # txt 원본 인코딩 (docx는 무시)
    source_path: str = ""     # 원본 파일 경로

    @property
    def full_text(self) -> str:
        """전체 텍스트를 줄바꿈으로 이어붙여 반환한다."""
        return "\n".join(self.paragraphs)


# txt 인코딩 자동 감지 시도 순서
# 1) utf-8-sig : BOM이 있으면 처리하고 BOM 없는 UTF-8도 읽음
# 2) cp949     : 한국어 Windows 기본 인코딩(EUC-KR 상위호환)
_TXT_ENCODINGS = ("utf-8-sig", "cp949")


class Reader:
    """파일 형식에 맞춰 문서를 읽어 Document 로 반환하는 클래스."""

    def read(self, path: str) -> Document:
        """확장자에 따라 적절한 리더를 호출한다."""
        ext = get_file_extension(path)
        if ext == ".docx":
            return self._read_docx(path)
        elif ext == ".txt":
            return self._read_txt(path)
        raise ValueError(f"지원하지 않는 파일 형식입니다: {ext}")

    # ------------------------------------------------------------------ #
    # 내부 구현
    # ------------------------------------------------------------------ #
    def _read_docx(self, path: str) -> Document:
        """python-docx 로 docx 문단 텍스트를 읽는다."""
        try:
            from docx import Document as DocxDocument
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "docx 파일을 읽으려면 python-docx 가 필요합니다. "
                "'pip install python-docx' 로 설치하세요."
            ) from exc

        docx_doc = DocxDocument(path)
        # 각 문단의 텍스트를 그대로 가져온다(빈 문단도 유지하여 줄 구조 보존).
        paragraphs = [p.text for p in docx_doc.paragraphs]
        return Document(
            paragraphs=paragraphs,
            file_format="docx",
            encoding="utf-8",
            source_path=path,
        )

    def _read_txt(self, path: str) -> Document:
        """
        txt 파일을 인코딩 자동 감지하여 읽는다.
        UTF-8(BOM 포함) -> CP949 순으로 시도한다.
        """
        raw = self._read_bytes(path)

        text = None
        used_encoding = "utf-8"
        for enc in _TXT_ENCODINGS:
            try:
                text = raw.decode(enc)
                # utf-8-sig 로 성공하면 실제 인코딩 이름을 정리
                used_encoding = "utf-8" if enc == "utf-8-sig" else enc
                break
            except (UnicodeDecodeError, LookupError):
                continue

        if text is None:
            # 마지막 수단: 손실 허용(replace) UTF-8 디코딩
            text = raw.decode("utf-8", errors="replace")
            used_encoding = "utf-8"

        # 개행 문자를 통일한 뒤 줄 단위로 분리한다.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        paragraphs = text.split("\n")

        return Document(
            paragraphs=paragraphs,
            file_format="txt",
            encoding=used_encoding,
            source_path=path,
        )

    @staticmethod
    def _read_bytes(path: str) -> bytes:
        """파일을 바이트로 읽는다."""
        with open(path, "rb") as f:
            return f.read()
