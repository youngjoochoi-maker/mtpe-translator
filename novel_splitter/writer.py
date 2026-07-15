"""
writer.py
---------
분권 결과(chunk 리스트)를 실제 파일로 저장한다.

- 원본 형식(docx/txt)에 맞춰 저장
- 출력 폴더 생성 (기본: 원본과 같은 폴더 안의 '원본이름/' 폴더)
- 4자리 번호 파일명, 앞/뒤 번호 옵션
- 덮어쓰기 옵션
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from .reader import Document
from .utils import build_output_filename, ensure_dir, get_stem


@dataclass
class WriteResult:
    """개별 분권 저장 결과."""

    index: int
    filename: str
    path: str
    skipped: bool = False  # 덮어쓰기 비활성 상태에서 기존 파일이 있어 건너뛴 경우


class Writer:
    """분권 결과를 파일로 저장하는 클래스."""

    def resolve_output_dir(
        self,
        source_path: str,
        custom_dir: Optional[str] = None,
    ) -> str:
        """
        출력 폴더 경로를 결정한다.

        - custom_dir 가 지정되면 그 폴더 안에 '원본이름/' 하위 폴더를 만든다.
        - 지정되지 않으면 원본 파일과 같은 폴더 안에 '원본이름/' 폴더를 만든다.
        """
        stem = get_stem(source_path)
        if custom_dir:
            base = custom_dir
        else:
            base = os.path.dirname(os.path.abspath(source_path))
        return os.path.join(base, stem)

    def write_chunks(
        self,
        document: Document,
        chunks: List[List[str]],
        output_dir: str,
        number_position: str = "suffix",
        overwrite: bool = False,
    ) -> List[WriteResult]:
        """
        분권들을 output_dir 에 저장한다.

        Parameters
        ----------
        document : 원본 Document (형식/인코딩 정보 사용)
        chunks : 분권 리스트 (각 항목은 문단 문자열 리스트)
        output_dir : 저장 폴더
        number_position : 'suffix'(뒤) 또는 'prefix'(앞)
        overwrite : 기존 파일 덮어쓰기 여부
        """
        ensure_dir(output_dir)
        stem = get_stem(document.source_path)
        extension = ".docx" if document.file_format == "docx" else ".txt"

        results: List[WriteResult] = []
        for i, chunk in enumerate(chunks, start=1):
            filename = build_output_filename(
                stem, i, extension, number_position=number_position
            )
            path = os.path.join(output_dir, filename)

            # 덮어쓰기 비활성 + 기존 파일 존재 -> 건너뜀
            if os.path.exists(path) and not overwrite:
                results.append(
                    WriteResult(index=i, filename=filename, path=path, skipped=True)
                )
                continue

            if document.file_format == "docx":
                self._write_docx(chunk, path)
            else:
                self._write_txt(chunk, path, document.encoding)

            results.append(WriteResult(index=i, filename=filename, path=path))

        return results

    # ------------------------------------------------------------------ #
    # 형식별 저장 구현
    # ------------------------------------------------------------------ #
    @staticmethod
    def _write_docx(paragraphs: List[str], path: str) -> None:
        """문단 리스트를 새 docx 파일로 저장한다."""
        from docx import Document as DocxDocument

        doc = DocxDocument()
        for para in paragraphs:
            doc.add_paragraph(para)
        doc.save(path)

    @staticmethod
    def _write_txt(paragraphs: List[str], path: str, encoding: str) -> None:
        """
        문단 리스트를 txt 파일로 저장한다.
        원본 인코딩을 유지하되, 실패 시 UTF-8 로 대체한다.
        """
        text = "\n".join(paragraphs)
        try:
            with open(path, "w", encoding=encoding, newline="") as f:
                f.write(text)
        except (LookupError, UnicodeEncodeError):
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(text)
