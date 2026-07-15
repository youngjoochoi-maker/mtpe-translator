"""
splitter.py
-----------
문서를 여러 분권(chunk)으로 나누는 로직.

세 가지 분권 방식을 지원한다.
1) 구분자 기준 : 특정 문자열로 시작하는 줄에서 분권
2) 글자수 기준 : 누적 글자수가 기준 이상이 되면 분권(문단 경계에서만)
3) 단어수 기준 : 누적 단어수가 기준 이상이 되면 분권(문단 경계에서만)

각 분권은 '문단(문자열) 리스트' 이며, splitter 는 이 리스트들의 리스트를 반환한다.
"""

from __future__ import annotations

from typing import List

from .counter import Counter


class Splitter:
    """분권 전략을 모아둔 클래스."""

    def __init__(self) -> None:
        self._counter = Counter()

    # ------------------------------------------------------------------ #
    # 1) 구분자 기준
    # ------------------------------------------------------------------ #
    def split_by_separator(
        self,
        paragraphs: List[str],
        separator: str,
        include_separator: bool = True,
        remove_separator: bool = False,
    ) -> List[List[str]]:
        """
        구분자로 '시작하는' 줄에서 새로운 분권을 시작한다.

        Parameters
        ----------
        paragraphs : 원본 문단(줄) 리스트
        separator : 분권 기준 문자열 (예: 'Chapter', '###', '===')
        include_separator : 구분자 줄을 결과 파일에 포함할지 여부
            - True  : 구분자 줄을 유지
            - False : 구분자 줄을 결과에서 제거
        remove_separator : 구분자 '문자열'만 줄 앞에서 제거할지 여부
            - True  : '###제목' -> '제목' (include_separator 가 True 일 때만 의미 있음)

        Notes
        -----
        - 첫 구분자 이전에 내용이 있으면 그 부분도 하나의 분권(머리말)이 된다.
        - 앞뒤 공백을 무시하고 startswith 로 판정한다.
        """
        if not separator:
            raise ValueError("구분자를 입력하세요.")

        chunks: List[List[str]] = []
        current: List[str] = []

        for line in paragraphs:
            # 앞쪽 공백을 제거한 뒤 구분자로 시작하는지 확인
            is_boundary = line.lstrip().startswith(separator)

            if is_boundary:
                # 지금까지 모은 내용이 있으면 하나의 분권으로 확정
                if current:
                    chunks.append(current)
                current = []

                # 구분자 줄 자체의 처리
                if include_separator:
                    if remove_separator:
                        current.append(self._strip_separator(line, separator))
                    else:
                        current.append(line)
                # include_separator=False 이면 구분자 줄은 버린다.
            else:
                current.append(line)

        # 마지막 분권 추가
        if current:
            chunks.append(current)

        # 아무 구분자도 찾지 못한 경우 전체를 한 개의 분권으로 반환
        if not chunks:
            chunks = [list(paragraphs)]

        return chunks

    @staticmethod
    def _strip_separator(line: str, separator: str) -> str:
        """
        줄 앞쪽의 공백과 구분자 문자열을 제거하고 나머지를 반환한다.
        예) '  ###제목' , sep='###' -> '제목'
        """
        stripped = line.lstrip()
        leading_ws = line[: len(line) - len(stripped)]  # 앞 공백 보존 후보(사용 안 함)
        if stripped.startswith(separator):
            remainder = stripped[len(separator):]
            # 구분자 뒤에 붙은 공백도 정리
            return remainder.lstrip()
        return line

    # ------------------------------------------------------------------ #
    # 2) 글자수 기준
    # ------------------------------------------------------------------ #
    def split_by_char_count(
        self,
        paragraphs: List[str],
        limit: int,
        with_spaces: bool = True,
    ) -> List[List[str]]:
        """
        누적 글자수가 limit 이상이 되면 분권한다.
        문단(줄) 단위로만 자르므로 문장 중간에서 잘리지 않는다.

        Parameters
        ----------
        limit : 분권 기준 글자수 (예: 5000)
        with_spaces : True 면 공백포함 글자수, False 면 공백제외 글자수 기준
        """
        if limit <= 0:
            raise ValueError("글자수 기준은 1 이상이어야 합니다.")

        def measure(text: str) -> int:
            return (
                self._counter.count_chars_with_spaces(text)
                if with_spaces
                else self._counter.count_chars_without_spaces(text)
            )

        return self._accumulate(paragraphs, limit, measure)

    # ------------------------------------------------------------------ #
    # 3) 단어수 기준
    # ------------------------------------------------------------------ #
    def split_by_word_count(
        self,
        paragraphs: List[str],
        limit: int,
    ) -> List[List[str]]:
        """
        누적 단어수가 limit 이상이 되면 분권한다.
        문단(줄) 단위로만 자른다.
        """
        if limit <= 0:
            raise ValueError("단어수 기준은 1 이상이어야 합니다.")

        return self._accumulate(paragraphs, limit, self._counter.count_words)

    # ------------------------------------------------------------------ #
    # 공통: 누적 기반 분권
    # ------------------------------------------------------------------ #
    @staticmethod
    def _accumulate(paragraphs, limit, measure):
        """
        measure(문단) 값을 누적하며 limit 이상이 되면 분권을 확정한다.

        하나의 문단만으로 limit 을 초과하는 경우에도 문장 중간을 자르지 않고
        그 문단을 하나의 분권으로 처리한다.
        """
        chunks: List[List[str]] = []
        current: List[str] = []
        running = 0

        for para in paragraphs:
            current.append(para)
            running += measure(para)

            # 기준 이상이 되면 현재까지를 하나의 분권으로 확정하고 초기화
            if running >= limit:
                chunks.append(current)
                current = []
                running = 0

        # 남은 내용(기준 미달)도 마지막 분권으로 추가
        if current:
            chunks.append(current)

        return chunks
