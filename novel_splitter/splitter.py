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

from .blocks import Block, ParagraphBlock
from .counter import Counter

# 문장 종료 부호(마침표/물음표/느낌표/말줄임표, 전각 포함) + 뒤따르는 닫는 따옴표·괄호와 공백.
# 이 패턴으로 문단을 문장 단위로 나눈다(문장 중간은 절대 자르지 않기 위함).
_SENTENCE_END_RE = re.compile(r'[.!?…。！？]+["\'”’」』)\]]*\s*')


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
    ) -> List[List[Block]]:
        """
        구분자로 '시작하는' 문단에서 새로운 분권을 시작한다.

        Parameters
        ----------
        blocks : 원본 블록 리스트
        separator : 분권 기준 문자열 (예: 'Chapter', '###', '===')
        include_separator : 구분자 문단을 결과 파일에 포함할지 여부
        remove_separator : 구분자 '문자열'만 문단 앞에서 제거할지 여부
            - True : '###제목' -> '제목'

        Notes
        -----
        - 표(TableBlock)는 대표 텍스트가 없으므로 절대 분권 경계가 되지 않고,
          직전 문단이 속한 분권에 그대로 포함된다.
        - 첫 구분자 이전 내용이 있으면 그 부분도 하나의 분권(머리말)이 된다.
        """
        if not separator:
            raise ValueError("구분자를 입력하세요.")

        chunks: List[List[Block]] = []
        current: List[Block] = []

        for block in blocks:
            # 문단이면서 구분자로 시작하는 경우에만 경계로 판정한다.
            is_boundary = (
                isinstance(block, ParagraphBlock)
                and block.text.lstrip().startswith(separator)
            )

            if is_boundary:
                # 지금까지 모은 내용이 있으면 하나의 분권으로 확정
                if current:
                    chunks.append(current)
                current = []

                # 구분자 문단 자체의 처리
                if include_separator:
                    if remove_separator:
                        current.append(
                            ParagraphBlock(
                                text=self._strip_separator(block.text, separator)
                            )
                        )
                    else:
                        current.append(block)
                # include_separator=False 이면 구분자 문단은 버린다.
            else:
                current.append(block)

        # 마지막 분권 추가
        if current:
            chunks.append(current)

        # 아무 구분자도 찾지 못한 경우 전체를 한 개의 분권으로 반환
        if not chunks:
            chunks = [list(blocks)]

        return chunks

    @staticmethod
    def _strip_separator(line: str, separator: str) -> str:
        """
        문단 앞쪽의 공백과 구분자 문자열을 제거하고 나머지를 반환한다.
        예) '  ###제목' , sep='###' -> '제목'
        """
        stripped = line.lstrip()
        if stripped.startswith(separator):
            remainder = stripped[len(separator):]
            return remainder.lstrip()
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

        핵심: 문단이 기준보다 길면 문단 경계에서만 자르지 않고 '문장 경계'에서
        나눈다. 덕분에 각 분권이 기준에 훨씬 가깝게 맞춰지며,
        문장 중간은 절대 잘리지 않는다.

        - 문단(ParagraphBlock): 문장 단위로 채우되, 한 분권 안에 들어간
          같은 문단의 문장들은 다시 하나의 문단으로 합쳐 원본 구조를 보존한다.
        - 표(TableBlock) 등: 쪼갤 수 없으므로 통째로 배치한다(불가피한 초과 허용).
        - 종료 부호 없는 매우 긴 한 문장은 자르지 않으므로 초과할 수 있다.
        """
        chunks: List[List[Block]] = []
        current: List[Block] = []
        pending: List[str] = []  # 현재 문단에서 현재 분권에 쌓이는 문장들
        running = 0

        def flush_pending() -> None:
            """쌓인 문장들을 하나의 문단으로 합쳐 현재 분권에 넣는다."""
            nonlocal pending
            if pending:
                current.append(ParagraphBlock(text="".join(pending)))
                pending = []

        def close_chunk() -> None:
            """현재 분권을 확정하고 초기화한다."""
            nonlocal current, running
            flush_pending()
            if current:
                chunks.append(current)
            current = []
            running = 0

        for block in blocks:
            if isinstance(block, ParagraphBlock):
                sentences = split_sentences(block.text)
                if not sentences:
                    # 빈 줄(빈 문단)도 구조 보존을 위해 그대로 유지
                    sentences = [block.text]
                for sent in sentences:
                    pending.append(sent)
                    running += measure_text(sent)
                    # 기준 이상이 되면 현재까지를 한 분권으로 확정
                    if running >= limit:
                        close_chunk()
                # 문단이 끝나면 남은 문장들을 하나의 문단으로 확정(문단 경계 보존)
                flush_pending()
            else:
                # 표 등 쪼갤 수 없는 블록: 통째로 배치
                flush_pending()
                current.append(block)
                running += measure_text(block.count_text())
                if running >= limit:
                    close_chunk()

        # 남은 내용(기준 미달)도 마지막 분권으로 추가
        close_chunk()

        return chunks
