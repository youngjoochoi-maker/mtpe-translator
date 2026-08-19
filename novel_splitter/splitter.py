"""
splitter.py
-----------
문서를 여러 분권(chunk)으로 나누는 로직.

문서는 '블록(Block) 리스트'로 주어지며(문단/표), 각 분권도 블록 리스트다.
splitter 는 이 블록 리스트들의 리스트를 반환한다.

세 가지 분권 방식을 지원한다.
1) 구분자 기준 : 특정 문자열로 시작하는 '문단'에서 분권 (표는 경계로 쓰지 않음)
2) 글자수 기준 : 누적 글자수가 기준 이상이 되면 분권(블록 경계에서만)
3) 단어수 기준 : 누적 단어수가 기준 이상이 되면 분권(블록 경계에서만)
"""

from __future__ import annotations

import re
from typing import Callable, List

from .blocks import Block, ParagraphBlock, TableBlock
from .counter import Counter

# 문장 종료 부호(마침표/물음표/느낌표/말줄임표, 전각 포함) + 뒤따르는 닫는 따옴표·괄호.
# 이 패턴으로 문단을 문장 단위로 나눈다(문장 중간은 절대 자르지 않기 위함).
#
# 핵심: 종료 부호 '뒤에 공백 또는 문장 끝'이 와야만 문장 경계로 인정한다((?=\s|$)).
# 이렇게 하지 않으면 소수점(3.5), 천단위 숫자(1,200.50), 약어·URL(Mr.Kim,
# www.site.com) 의 마침표를 문장 끝으로 오인해 숫자/단어 중간을 잘라버린다.
_SENTENCE_END_RE = re.compile(r'[.!?…。！？]+["\'”’」』)\]]*(?=\s|$)\s*')


def split_sentences(text: str) -> List[str]:
    """
    문단 텍스트를 문장 리스트로 나눈다.
    각 조각은 종료 부호와 뒤 공백까지 포함하므로, 이어 붙이면 원문이 그대로 복원된다.
    종료 부호가 없으면 전체가 한 문장이 된다.
    """
    if not text:
        return []
    sentences: List[str] = []
    start = 0
    for m in _SENTENCE_END_RE.finditer(text):
        end = m.end()
        sentences.append(text[start:end])
        start = end
    if start < len(text):
        sentences.append(text[start:])
    return sentences


class Splitter:
    """분권 전략을 모아둔 클래스."""

    def __init__(self) -> None:
        self._counter = Counter()

    # ------------------------------------------------------------------ #
    # 1) 구분자 기준
    # ------------------------------------------------------------------ #
    def split_by_separator(
        self,
        blocks: List[Block],
        separator: str,
        include_separator: bool = True,
        remove_separator: bool = False,
        position: str = "start",
    ) -> List[List[Block]]:
        """
        구분자가 있는 문단을 기준으로 분권한다.

        Parameters
        ----------
        blocks : 원본 블록 리스트
        separator : 분권 기준 문자열 (예: 'Chapter', '###', '===')
        include_separator : 구분자 문단을 결과 파일에 포함할지 여부
        remove_separator : 구분자 '문자열'만 제거할지 여부
            - position='start' : '###제목' -> '제목'
            - position='end'   : '마지막 문장.###' -> '마지막 문장.'
        position : 구분자 위치
            - 'start'(앞) : 구분자로 '시작하는' 줄부터 '새 화'가 시작된다.
                            (예: 각 화 제목이 '제1화'처럼 맨 앞에 오는 경우)
            - 'end'(뒤)   : 구분자로 '끝나는' 줄이 '그 화의 마지막'이 된다.
                            (예: 각 화 끝에 '###' 또는 '(다음화에 계속)' 같은
                             구분자가 붙는 경우)

        Notes
        -----
        - 표(TableBlock)는 대표 텍스트가 없으므로 절대 분권 경계가 되지 않는다.
        - start: 첫 구분자 이전 내용이 있으면 그 부분도 하나의 분권(머리말)이 된다.
        - end  : 마지막 구분자 이후 내용이 있으면 그 부분도 하나의 분권이 된다.
        """
        if not separator:
            raise ValueError("구분자를 입력하세요.")

        if position == "end":
            chunks = self._split_sep_end(
                blocks, separator, include_separator, remove_separator
            )
        else:
            chunks = self._split_sep_start(
                blocks, separator, include_separator, remove_separator
            )

        # 내용이 없는 빈 분권(빈 파일이 되는 경우)은 제거한다.
        chunks = [c for c in chunks if any(b.count_text().strip() for b in c)]
        if not chunks:
            chunks = [list(blocks)]
        return chunks

    # -- 구분자가 화의 '앞(시작)'에 오는 경우 ----------------------------- #
    def _split_sep_start(
        self, blocks, separator, include_separator, remove_separator
    ) -> List[List[Block]]:
        chunks: List[List[Block]] = []
        current: List[Block] = []

        for block in blocks:
            # 문단이면서 구분자로 '시작'하면 새 화의 경계
            is_boundary = (
                isinstance(block, ParagraphBlock)
                and block.text.lstrip().startswith(separator)
            )
            if is_boundary:
                if current:
                    chunks.append(current)
                current = []
                if include_separator:
                    if remove_separator:
                        current.append(
                            ParagraphBlock(
                                text=self._strip_separator_start(block.text, separator)
                            )
                        )
                    else:
                        current.append(block)
                # include_separator=False 이면 구분자 줄은 버린다.
            else:
                current.append(block)

        if current:
            chunks.append(current)
        if not chunks:
            chunks = [list(blocks)]
        return chunks

    # -- 구분자가 화의 '뒤(끝)'에 있는 경우 ------------------------------- #
    def _split_sep_end(
        self, blocks, separator, include_separator, remove_separator
    ) -> List[List[Block]]:
        # 구분자가 '들어있는' 줄이면 그 줄을 통째로 화의 마지막(경계)으로 본다.
        # 구분자 뒤에 숫자든 글자든 무엇이 와도 인식한다.
        #   예) '문장.@1', '@2', '@1화', '문장.@1화 부제', '문장###' 모두 경계.
        # 참고: 이메일처럼 본문 중간에 구분자(@)가 들어간 줄도 경계가 되므로,
        #       구분자는 본문에 안 나오는 고유 문자열을 쓰는 것이 좋다.
        chunks: List[List[Block]] = []
        current: List[Block] = []

        for block in blocks:
            # 문단이 구분자를 '포함'하면 그 줄이 현재 화의 마지막
            is_boundary = (
                isinstance(block, ParagraphBlock)
                and separator in block.text
            )
            if is_boundary:
                if include_separator:
                    if remove_separator:
                        # 마지막 구분자부터 줄 끝(마커)까지 제거, 앞쪽 본문은 유지
                        idx = block.text.rfind(separator)
                        stripped = block.text[:idx].rstrip()
                        if stripped.strip():
                            current.append(ParagraphBlock(text=stripped))
                    else:
                        current.append(block)
                # include_separator=False 이면 구분자 줄은 통째로 버린다.
                # 이 줄로 현재 화가 끝났으므로 확정
                if current:
                    chunks.append(current)
                    current = []
            else:
                current.append(block)

        # 마지막 구분자 이후 남은 내용도 하나의 분권으로
        if current:
            chunks.append(current)
        if not chunks:
            chunks = [list(blocks)]
        return chunks

    @staticmethod
    def _strip_separator_start(line: str, separator: str) -> str:
        """줄 앞쪽의 공백과 구분자를 제거하고 나머지를 반환한다. '  ###제목' -> '제목'"""
        stripped = line.lstrip()
        if stripped.startswith(separator):
            return stripped[len(separator):].lstrip()
        return line

    @staticmethod
    def _strip_separator_end(line: str, separator: str) -> str:
        """줄 뒤쪽의 구분자와 공백을 제거하고 나머지를 반환한다. '문장.### ' -> '문장.'"""
        stripped = line.rstrip()
        if stripped.endswith(separator):
            return stripped[: len(stripped) - len(separator)].rstrip()
        return line

    # ------------------------------------------------------------------ #
    # 2) 글자수 기준
    # ------------------------------------------------------------------ #
    def split_by_char_count(
        self,
        blocks: List[Block],
        limit: int,
        with_spaces: bool = True,
    ) -> List[List[Block]]:
        """
        누적 글자수가 limit 이상이 되면 분권한다.
        블록(문단/표) 단위로만 자르므로 문장 중간에서 잘리지 않는다.

        Parameters
        ----------
        limit : 분권 기준 글자수 (예: 5000)
        with_spaces : True 면 공백포함 글자수, False 면 공백제외 글자수 기준
        """
        if limit <= 0:
            raise ValueError("글자수 기준은 1 이상이어야 합니다.")

        def measure_text(text: str) -> int:
            return (
                self._counter.count_chars_with_spaces(text)
                if with_spaces
                else self._counter.count_chars_without_spaces(text)
            )

        return self._accumulate(blocks, limit, measure_text)

    # ------------------------------------------------------------------ #
    # 3) 단어수 기준
    # ------------------------------------------------------------------ #
    def split_by_word_count(
        self,
        blocks: List[Block],
        limit: int,
    ) -> List[List[Block]]:
        """
        누적 단어수가 limit 이상이 되면 분권한다.
        블록(문단/표) 단위로만 자른다.
        """
        if limit <= 0:
            raise ValueError("단어수 기준은 1 이상이어야 합니다.")

        return self._accumulate(blocks, limit, self._counter.count_words)

    # ------------------------------------------------------------------ #
    # 공통: 누적 기반 분권 (문장 단위 보정)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _accumulate(
        blocks: List[Block],
        limit: int,
        measure_text: Callable[[str], int],
    ) -> List[List[Block]]:
        """
        measure_text(문자열) 값을 누적하며 limit 이상이 되면 분권을 확정한다.

        핵심: 기준보다 큰 블록도 통째로 넘기지 않고 더 작은 단위에서 나눈다.
        덕분에 각 분권이 기준에 훨씬 가깝게 맞춰진다.

        - 문단(ParagraphBlock): '문장 경계'에서 나누되, 한 분권 안에 들어간
          같은 문단의 문장들은 다시 하나의 문단으로 합쳐 원본 구조를 보존한다.
          문장 중간은 절대 자르지 않는다.
        - 표(TableBlock): '행(row) 경계'에서 나누되, 한 분권 안에 들어간
          같은 표의 행들은 다시 하나의 표로 합쳐 표 구조를 보존한다.
          셀·행 중간은 자르지 않는다.
        - 그 외 쪼갤 수 없는 블록은 통째로 배치한다(불가피한 초과 허용).
        - 종료 부호 없는 매우 긴 한 문장/한 행은 자르지 않으므로 초과할 수 있다.
        """
        chunks: List[List[Block]] = []
        current: List[Block] = []
        pending_sents: List[str] = []       # 현재 문단에서 현재 분권에 쌓이는 문장들
        pending_rows: List[List[str]] = []  # 현재 표에서 현재 분권에 쌓이는 행들
        running = 0

        def flush_para() -> None:
            """쌓인 문장들을 하나의 문단으로 합쳐 현재 분권에 넣는다."""
            nonlocal pending_sents
            if pending_sents:
                current.append(ParagraphBlock(text="".join(pending_sents)))
                pending_sents = []

        def flush_table() -> None:
            """쌓인 행들을 하나의 표로 합쳐 현재 분권에 넣는다."""
            nonlocal pending_rows
            if pending_rows:
                current.append(TableBlock(rows=list(pending_rows)))
                pending_rows = []

        def close_chunk() -> None:
            """현재 분권을 확정하고 초기화한다(대기 중인 문단·표를 먼저 확정)."""
            nonlocal current, running
            flush_para()
            flush_table()
            if current:
                chunks.append(current)
            current = []
            running = 0

        for block in blocks:
            if isinstance(block, ParagraphBlock):
                flush_table()  # 블록 종류가 바뀌면 대기 중인 표를 먼저 확정
                sentences = split_sentences(block.text)
                if not sentences:
                    # 빈 줄(빈 문단)도 구조 보존을 위해 그대로 유지
                    sentences = [block.text]
                for sent in sentences:
                    pending_sents.append(sent)
                    running += measure_text(sent)
                    if running >= limit:
                        close_chunk()
                # 문단이 끝나면 남은 문장들을 하나의 문단으로 확정(문단 경계 보존)
                flush_para()

            elif isinstance(block, TableBlock):
                flush_para()  # 블록 종류가 바뀌면 대기 중인 문단을 먼저 확정
                for row in block.rows:
                    pending_rows.append(row)
                    running += measure_text("\t".join(row))
                    if running >= limit:
                        close_chunk()
                # 표가 끝나면 남은 행들을 하나의 표로 확정(표 경계 보존)
                flush_table()

            else:
                # 알 수 없는 쪼갤 수 없는 블록: 통째로 배치
                flush_para()
                flush_table()
                current.append(block)
                running += measure_text(block.count_text())
                if running >= limit:
                    close_chunk()

        # 남은 내용(기준 미달)도 마지막 분권으로 추가
        close_chunk()

        return chunks
