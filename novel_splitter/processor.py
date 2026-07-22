"""
processor.py
------------
reader / splitter / counter / writer 를 하나로 묶는 오케스트레이션 계층.

UI(mainwindow) 와 순수 로직을 분리하여 테스트와 재사용을 쉽게 한다.
GUI 없이도 이 모듈만으로 분권 처리를 수행할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional

from .counter import Counter, Counts
from .reader import Document, Reader
from .splitter import Splitter
from .writer import Writer, WriteResult


class SplitMode(Enum):
    """분권 방식."""

    SEPARATOR = "separator"   # 구분자 기준
    CHAR_COUNT = "char_count"  # 글자수 기준
    WORD_COUNT = "word_count"  # 단어수 기준


@dataclass
class SplitOptions:
    """분권 처리에 필요한 모든 옵션."""

    mode: SplitMode = SplitMode.SEPARATOR

    # 구분자 기준
    separator: str = ""
    include_separator: bool = True
    remove_separator: bool = False

    # 글자수 / 단어수 기준
    count_limit: int = 5000
    char_count_with_spaces: bool = True  # 글자수 기준: 공백포함 여부

    # 출력 옵션
    custom_output_dir: Optional[str] = None  # 출력 폴더 직접 선택
    overwrite: bool = False                   # 기존 파일 덮어쓰기
    number_position: str = "suffix"           # 'suffix'(뒤) 또는 'prefix'(앞)


@dataclass
class ChunkResult:
    """분권 1개에 대한 결과 정보(표 표시용)."""

    index: int
    filename: str
    path: str
    counts: Counts
    skipped: bool = False
    title: str = ""  # 회차 제목(각 분권의 첫 비어있지 않은 줄) - 플랫폼 대조용


@dataclass
class FileResult:
    """입력 파일 1개에 대한 처리 결과."""

    source_path: str
    output_dir: str
    chunks: List[ChunkResult] = field(default_factory=list)

    @property
    def total(self) -> Counts:
        """이 파일의 전체 분권 합계."""
        total = Counts()
        for c in self.chunks:
            total = total + c.counts
        return total


class Processor:
    """분권 처리 파이프라인."""

    def __init__(self) -> None:
        self.reader = Reader()
        self.splitter = Splitter()
        self.counter = Counter()
        self.writer = Writer()

    def analyze(self, path: str) -> Document:
        """파일을 읽어 Document 를 반환한다(전체 분량 미리보기용)."""
        return self.reader.read(path)

    def summarize(self, document: Document) -> Counts:
        """문서 전체 분량을 계산한다(표 포함)."""
        return self.counter.count_blocks(document.blocks)

    def split_document(
        self, document: Document, options: SplitOptions
    ) -> List[List["Block"]]:
        """옵션에 따라 문서를 분권한다(블록 단위)."""
        if options.mode == SplitMode.SEPARATOR:
            return self.splitter.split_by_separator(
                document.blocks,
                separator=options.separator,
                include_separator=options.include_separator,
                remove_separator=options.remove_separator,
            )
        elif options.mode == SplitMode.CHAR_COUNT:
            return self.splitter.split_by_char_count(
                document.blocks,
                limit=options.count_limit,
                with_spaces=options.char_count_with_spaces,
            )
        elif options.mode == SplitMode.WORD_COUNT:
            return self.splitter.split_by_word_count(
                document.blocks,
                limit=options.count_limit,
            )
        raise ValueError(f"알 수 없는 분권 방식: {options.mode}")

    def process_file(
        self,
        path: str,
        options: SplitOptions,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
    ) -> FileResult:
        """
        파일 1개를 읽고 분권하여 저장한 뒤 결과를 반환한다.

        progress_cb(current, total, message) 가 주어지면 분권 저장 진행률을 보고한다.
        """
        document = self.reader.read(path)
        chunks = self.split_document(document, options)

        output_dir = self.writer.resolve_output_dir(
            path, custom_dir=options.custom_output_dir
        )
        write_results: List[WriteResult] = self.writer.write_chunks(
            document,
            chunks,
            output_dir=output_dir,
            number_position=options.number_position,
            overwrite=options.overwrite,
        )

        # 결과 집계 (분량 계산)
        file_result = FileResult(source_path=path, output_dir=output_dir)
        total = len(chunks)
        for i, (chunk, wr) in enumerate(zip(chunks, write_results), start=1):
            counts = self.counter.count_blocks(chunk)
            file_result.chunks.append(
                ChunkResult(
                    index=wr.index,
                    filename=wr.filename,
                    path=wr.path,
                    counts=counts,
                    skipped=wr.skipped,
                    title=self._chunk_title(chunk),
                )
            )
            if progress_cb:
                progress_cb(i, total, wr.filename)

        return file_result

    @staticmethod
    def _chunk_title(chunk) -> str:
        """분권의 '회차 제목'으로 쓸 첫 비어있지 않은 텍스트 줄을 반환한다."""
        for block in chunk:
            for unit in block.text_units():
                text = unit.strip()
                if text:
                    return text
        return ""
