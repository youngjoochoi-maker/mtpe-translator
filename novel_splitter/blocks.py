"""
blocks.py
---------
문서를 구성하는 '블록' 모델.

기존에는 문서를 단순히 '문단(문자열) 리스트'로만 다뤘기 때문에
docx 안의 표(table) 내용이 통째로 누락되는 문제가 있었다.
이를 해결하기 위해 문서를 순서가 보존된 블록들의 리스트로 표현한다.

블록 종류
- ParagraphBlock : 일반 문단(한 줄)
- TableBlock     : 표 (행 × 열의 셀 텍스트)

각 블록은 다음을 제공한다.
- text          : 구분자 매칭·표시에 쓰는 대표 텍스트
- count_text()  : 분량 계산에 쓰는 전체 텍스트
- line_count()  : 줄수 계산 시 기여하는 줄 수
- to_txt()      : txt 저장용 문자열
- write_docx()  : docx 문서에 자신을 추가
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


class Block:
    """모든 블록의 공통 인터페이스."""

    #: 구분자 매칭·미리보기에 사용하는 대표 텍스트
    text: str = ""

    def count_text(self) -> str:
        """분량 계산에 사용할 전체 텍스트."""
        raise NotImplementedError

    def line_count(self) -> int:
        """줄수 계산 시 이 블록이 차지하는 줄 수."""
        raise NotImplementedError

    def to_txt(self) -> str:
        """txt 파일로 저장할 때의 문자열 표현."""
        raise NotImplementedError

    def write_docx(self, doc) -> None:
        """python-docx Document 에 자신을 추가한다."""
        raise NotImplementedError


@dataclass
class ParagraphBlock(Block):
    """일반 문단(또는 txt 한 줄)."""

    text: str = ""

    def count_text(self) -> str:
        return self.text

    def line_count(self) -> int:
        return 1

    def to_txt(self) -> str:
        return self.text

    def write_docx(self, doc) -> None:
        doc.add_paragraph(self.text)


@dataclass
class TableBlock(Block):
    """
    표 블록. rows 는 행 리스트이고, 각 행은 셀 텍스트(str) 리스트다.
    셀 텍스트는 여러 문단을 포함할 경우 개행이 들어갈 수 있다.
    """

    rows: List[List[str]] = field(default_factory=list)

    # 표는 구분자 경계로 사용하지 않으므로 대표 텍스트는 비운다.
    text: str = ""

    def count_text(self) -> str:
        """모든 셀 텍스트를 이어 붙여 분량 계산에 사용한다(탭/개행 구분)."""
        return "\n".join("\t".join(cell for cell in row) for row in self.rows)

    def line_count(self) -> int:
        """표의 줄수는 행 수로 계산한다."""
        return len(self.rows)

    def to_txt(self) -> str:
        """txt 저장 시 탭 구분(TSV) 형태로 표현한다."""
        return "\n".join("\t".join(cell for cell in row) for row in self.rows)

    def write_docx(self, doc) -> None:
        """docx 에 실제 표로 다시 작성한다(테두리 있는 기본 스타일)."""
        if not self.rows:
            return
        cols = max(len(row) for row in self.rows)
        table = doc.add_table(rows=len(self.rows), cols=cols)
        # 'Table Grid' 는 기본 템플릿에 포함된 스타일로 테두리를 표시한다.
        try:
            table.style = "Table Grid"
        except Exception:
            pass  # 스타일이 없어도 표 자체는 생성됨
        for r, row in enumerate(self.rows):
            for c in range(cols):
                value = row[c] if c < len(row) else ""
                table.cell(r, c).text = value
