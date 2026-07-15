"""
counter.py
----------
텍스트 분량 계산 담당.

- 공백포함 글자수
- 공백제외 글자수
- 단어수 (공백 기준 토큰 수 - 한국어/영어 혼용 번역 분량 산정에 사용)
- 줄수
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

# 연속된 공백류(스페이스/탭/개행 등)를 하나의 구분자로 취급하기 위한 정규식
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class Counts:
    """분량 계산 결과."""

    chars_with_spaces: int = 0     # 공백포함 글자수
    chars_without_spaces: int = 0  # 공백제외 글자수
    words: int = 0                 # 단어수
    lines: int = 0                 # 줄수

    def __add__(self, other: "Counts") -> "Counts":
        """총합 계산을 위한 덧셈 지원."""
        return Counts(
            chars_with_spaces=self.chars_with_spaces + other.chars_with_spaces,
            chars_without_spaces=self.chars_without_spaces + other.chars_without_spaces,
            words=self.words + other.words,
            lines=self.lines + other.lines,
        )


class Counter:
    """텍스트/문단 리스트의 분량을 계산하는 클래스."""

    def count_text(self, text: str) -> Counts:
        """단일 문자열의 분량을 계산한다."""
        chars_with = len(text)
        # 공백제외: 모든 공백류 문자를 제거한 길이
        chars_without = len(_WHITESPACE_RE.sub("", text))
        return Counts(
            chars_with_spaces=chars_with,
            chars_without_spaces=chars_without,
            words=self.count_words(text),
            lines=self.count_lines(text),
        )

    def count_paragraphs(self, paragraphs: List[str]) -> Counts:
        """
        문단(줄) 리스트의 분량을 계산한다.
        줄수는 리스트의 항목 수로 계산하여 원본 줄 구조와 일치시킨다.
        """
        joined = "\n".join(paragraphs)
        chars_with = len(joined)
        chars_without = len(_WHITESPACE_RE.sub("", joined))
        return Counts(
            chars_with_spaces=chars_with,
            chars_without_spaces=chars_without,
            words=self.count_words(joined),
            lines=len(paragraphs),
        )

    def count_blocks(self, blocks) -> Counts:
        """
        블록(문단/표) 리스트의 분량을 계산한다.
        표 안의 텍스트까지 포함하여 집계하며, 줄수는 각 블록의
        line_count() 합으로 계산한다(표는 행 수만큼 기여).
        """
        joined = "\n".join(b.count_text() for b in blocks)
        chars_with = len(joined)
        chars_without = len(_WHITESPACE_RE.sub("", joined))
        return Counts(
            chars_with_spaces=chars_with,
            chars_without_spaces=chars_without,
            words=self.count_words(joined),
            lines=sum(b.line_count() for b in blocks),
        )

    # ------------------------------------------------------------------ #
    # 개별 지표 계산 (분권 로직에서도 재사용)
    # ------------------------------------------------------------------ #
    @staticmethod
    def count_chars_with_spaces(text: str) -> int:
        """공백포함 글자수."""
        return len(text)

    @staticmethod
    def count_chars_without_spaces(text: str) -> int:
        """공백제외 글자수."""
        return len(_WHITESPACE_RE.sub("", text))

    @staticmethod
    def count_words(text: str) -> int:
        """
        단어수. 공백류로 분리한 토큰의 개수를 센다.
        한국어/영어 등 공백으로 어절을 구분하는 언어의 분량 산정에 적합하다.
        """
        tokens = _WHITESPACE_RE.split(text.strip())
        # strip 결과가 빈 문자열이면 split 은 [''] 를 반환하므로 걸러낸다.
        return len([t for t in tokens if t])

    @staticmethod
    def count_lines(text: str) -> int:
        """줄수. 텍스트에 포함된 줄의 개수."""
        if text == "":
            return 0
        return len(text.split("\n"))
