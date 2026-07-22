"""
mainwindow.py
-------------
PySide6 기반 메인 GUI.

- 파일 선택 / 드래그앤드롭
- 전체 분량 표시
- 분권 방식 선택(구분자/글자수/단어수) 및 옵션
- 출력 옵션
- 진행률 표시(Progress Bar) 및 로그
- 결과 표 및 총합

실제 분권 처리는 백그라운드 스레드(Worker)에서 수행하여 UI가 멈추지 않게 한다.
"""

from __future__ import annotations

import os
import re
from typing import List

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .counter import Counter, Counts
from .exporter import ExcelExporter
from .platform_fetcher import (
    Comparison,
    PlatformError,
    PlatformFetcher,
    PlatformResult,
    compare_titles,
)
from .processor import FileResult, Processor, SplitMode, SplitOptions
from .utils import get_stem, is_supported_file


# ---------------------------------------------------------------------------- #
# 백그라운드 처리 스레드
# ---------------------------------------------------------------------------- #
class Worker(QObject):
    """여러 파일을 순차 처리하는 백그라운드 워커."""

    progress = Signal(int)              # 전체 진행률 (0~100)
    current_file = Signal(str)          # 현재 처리 중인 파일 메시지
    log = Signal(str)                   # 로그 메시지
    file_done = Signal(object)          # FileResult
    finished = Signal()                 # 전체 완료
    error = Signal(str)                 # 오류 메시지

    def __init__(self, files: List[str], options: SplitOptions) -> None:
        super().__init__()
        self._files = files
        self._options = options
        self._processor = Processor()

    def run(self) -> None:
        """모든 파일을 순차적으로 처리한다."""
        total_files = len(self._files)
        try:
            for idx, path in enumerate(self._files):
                name = os.path.basename(path)
                self.current_file.emit(f"처리 중: {name}")
                self.log.emit(f"[{idx + 1}/{total_files}] {name} 읽는 중...")

                def progress_cb(cur, tot, fname, _idx=idx):
                    # 파일 내부 진행 + 전체 파일 진행을 합산하여 백분율 계산
                    file_fraction = cur / tot if tot else 1
                    overall = (_idx + file_fraction) / total_files * 100
                    self.progress.emit(int(overall))
                    self.current_file.emit(f"저장 중: {fname}")

                result: FileResult = self._processor.process_file(
                    path, self._options, progress_cb=progress_cb
                )
                self.file_done.emit(result)

                saved = sum(1 for c in result.chunks if not c.skipped)
                skipped = sum(1 for c in result.chunks if c.skipped)
                msg = f"[{idx + 1}/{total_files}] {name} 완료 — {saved}개 저장"
                if skipped:
                    msg += f", {skipped}개 건너뜀(기존 파일 존재)"
                self.log.emit(msg)
                self.log.emit(f"    출력 폴더: {result.output_dir}")

                self.progress.emit(int((idx + 1) / total_files * 100))

            self.finished.emit()
        except Exception as exc:  # noqa: BLE001 - 사용자에게 오류 표시 목적
            self.error.emit(str(exc))


# ---------------------------------------------------------------------------- #
# 플랫폼 회차 수집 백그라운드 워커
# ---------------------------------------------------------------------------- #
class FetchWorker(QObject):
    """네트워크로 플랫폼 회차 목록을 가져오는 워커(UI 멈춤 방지)."""

    done = Signal(object)   # PlatformResult
    error = Signal(str)

    def __init__(self, url: str) -> None:
        super().__init__()
        self._url = url

    def run(self) -> None:
        try:
            result = PlatformFetcher().fetch(self._url)
            self.done.emit(result)
        except PlatformError as exc:
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"수집 중 오류가 발생했습니다: {exc}")


# ---------------------------------------------------------------------------- #
# 메인 윈도우
# ---------------------------------------------------------------------------- #
class MainWindow(QWidget):
    """소설 분권 프로그램 메인 창."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("소설 분권 프로그램")
        self.resize(1000, 1000)
        self.setMinimumSize(760, 600)
        self.setAcceptDrops(True)  # 드래그앤드롭 허용

        self._files: List[str] = []            # 선택된 파일 목록
        self._processor = Processor()          # 미리보기(전체 분량)용
        self._counter = Counter()
        self._thread: QThread | None = None
        self._worker: Worker | None = None
        self._results: List[FileResult] = []   # 처리 결과 누적

        # 플랫폼 회차 대조용
        self._fetch_thread: QThread | None = None
        self._fetch_worker: FetchWorker | None = None
        self._platform_result: PlatformResult | None = None

        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI 구성
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # 위(설정)와 아래(결과)를 세로 스플리터로 나눠, 경계를 드래그해
        # 결과 표 영역을 원하는 만큼 넓힐 수 있게 한다.
        splitter = QSplitter(Qt.Vertical)

        # 위쪽: 설정 영역(파일/방식/출력/실행). 창이 작아지면 스크롤된다.
        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addWidget(self._build_file_section())
        top_layout.addWidget(self._build_mode_section())
        top_layout.addWidget(self._build_output_section())
        top_layout.addWidget(self._build_run_section())
        top_layout.addStretch(0)

        top_scroll = QScrollArea()
        top_scroll.setWidgetResizable(True)
        top_scroll.setWidget(top)
        top_scroll.setFrameShape(QScrollArea.NoFrame)

        splitter.addWidget(top_scroll)
        splitter.addWidget(self._build_result_section())
        splitter.addWidget(self._build_platform_section())
        # 결과 영역이 넓어지는 방향으로 크기 배분
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 1)
        splitter.setSizes([500, 340, 300])

        root.addWidget(splitter)

    # --- 1) 파일 선택 영역 ------------------------------------------------ #
    def _build_file_section(self) -> QGroupBox:
        box = QGroupBox("① 파일 선택")
        layout = QVBoxLayout(box)

        top = QHBoxLayout()
        self.btn_select = QPushButton("파일 선택")
        self.btn_select.clicked.connect(self._on_select_files)
        self.btn_clear = QPushButton("목록 비우기")
        self.btn_clear.clicked.connect(self._on_clear_files)
        hint = QLabel("또는 이곳으로 파일을 드래그앤드롭 하세요 (docx, txt)")
        hint.setStyleSheet("color: gray;")
        top.addWidget(self.btn_select)
        top.addWidget(self.btn_clear)
        top.addWidget(hint, stretch=1)
        layout.addLayout(top)

        # 선택된 파일별 전체 분량 표
        self.file_table = QTableWidget(0, 4)
        self.file_table.setHorizontalHeaderLabels(
            ["파일명", "전체 글자수", "전체 단어수", "전체 줄수"]
        )
        self.file_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.file_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        self.file_table.setMaximumHeight(150)
        layout.addWidget(self.file_table)

        return box

    # --- 2) 분권 방식 영역 ------------------------------------------------ #
    def _build_mode_section(self) -> QGroupBox:
        box = QGroupBox("② 분권 방식")
        layout = QVBoxLayout(box)

        self.mode_group = QButtonGroup(self)
        self.rb_separator = QRadioButton("구분자 기준")
        self.rb_char = QRadioButton("글자수 기준")
        self.rb_word = QRadioButton("단어수 기준")
        self.rb_separator.setChecked(True)
        for rb in (self.rb_separator, self.rb_char, self.rb_word):
            self.mode_group.addButton(rb)
            rb.toggled.connect(self._on_mode_changed)

        radios = QHBoxLayout()
        radios.addWidget(self.rb_separator)
        radios.addWidget(self.rb_char)
        radios.addWidget(self.rb_word)
        radios.addStretch(1)
        layout.addLayout(radios)

        # 구분자 기준 옵션
        sep_row = QHBoxLayout()
        sep_row.addWidget(QLabel("구분자:"))
        self.sep_input = QLineEdit()
        self.sep_input.setPlaceholderText("예) Chapter, ###, ===  (해당 문자열로 시작하는 줄에서 분권)")
        sep_row.addWidget(self.sep_input, stretch=1)
        layout.addLayout(sep_row)

        sep_opts = QHBoxLayout()
        self.chk_include_sep = QCheckBox("구분자를 결과 파일에 포함")
        self.chk_include_sep.setChecked(True)
        self.chk_remove_sep = QCheckBox("구분자 문자열 제거 (예: '###제목' → '제목')")
        sep_opts.addWidget(self.chk_include_sep)
        sep_opts.addWidget(self.chk_remove_sep)
        sep_opts.addStretch(1)
        layout.addLayout(sep_opts)

        # 글자수/단어수 기준 옵션 (공용 입력)
        count_row = QHBoxLayout()
        self.count_label = QLabel("기준 글자수:")
        self.count_input = QSpinBox()
        self.count_input.setRange(1, 100_000_000)
        self.count_input.setValue(5000)
        self.count_input.setSingleStep(1000)
        self.count_input.setGroupSeparatorShown(True)
        count_row.addWidget(self.count_label)
        count_row.addWidget(self.count_input)
        self.chk_char_no_space = QCheckBox("공백 제외 글자수 기준")
        count_row.addWidget(self.chk_char_no_space)
        count_row.addStretch(1)
        layout.addLayout(count_row)

        self._on_mode_changed()  # 초기 활성/비활성 상태 반영
        return box

    # --- 3) 출력 옵션 영역 ------------------------------------------------ #
    def _build_output_section(self) -> QGroupBox:
        box = QGroupBox("③ 출력 옵션")
        layout = QVBoxLayout(box)

        # 출력 폴더 직접 선택
        dir_row = QHBoxLayout()
        self.chk_custom_dir = QCheckBox("출력 폴더 직접 선택")
        self.chk_custom_dir.toggled.connect(self._on_custom_dir_toggled)
        self.dir_display = QLineEdit()
        self.dir_display.setReadOnly(True)
        self.dir_display.setPlaceholderText("기본: 원본 파일과 같은 폴더 안에 '원본이름/' 폴더 생성")
        self.btn_pick_dir = QPushButton("폴더 선택...")
        self.btn_pick_dir.clicked.connect(self._on_pick_dir)
        self.btn_pick_dir.setEnabled(False)
        dir_row.addWidget(self.chk_custom_dir)
        dir_row.addWidget(self.dir_display, stretch=1)
        dir_row.addWidget(self.btn_pick_dir)
        layout.addLayout(dir_row)

        # 덮어쓰기 / 번호 위치
        opt_row = QHBoxLayout()
        self.chk_overwrite = QCheckBox("기존 파일 덮어쓰기")
        opt_row.addWidget(self.chk_overwrite)

        opt_row.addSpacing(20)
        opt_row.addWidget(QLabel("번호 위치:"))
        self.number_group = QButtonGroup(self)
        self.rb_suffix = QRadioButton("파일명 뒤 (소설_0001)")
        self.rb_prefix = QRadioButton("파일명 앞 (0001_소설)")
        self.rb_suffix.setChecked(True)
        self.number_group.addButton(self.rb_suffix)
        self.number_group.addButton(self.rb_prefix)
        opt_row.addWidget(self.rb_suffix)
        opt_row.addWidget(self.rb_prefix)
        opt_row.addStretch(1)
        layout.addLayout(opt_row)

        return box

    # --- 4) 실행 / 진행률 영역 ------------------------------------------- #
    def _build_run_section(self) -> QGroupBox:
        box = QGroupBox("④ 실행")
        layout = QVBoxLayout(box)

        self.btn_run = QPushButton("분권 실행")
        self.btn_run.clicked.connect(self._on_run)
        layout.addWidget(self.btn_run)

        self.progress = QProgressBar()
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.status_label = QLabel("대기 중")
        self.status_label.setStyleSheet("color: gray;")
        layout.addWidget(self.status_label)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(120)
        layout.addWidget(self.log_view)

        return box

    # --- 5) 결과 표 영역 ------------------------------------------------- #
    def _build_result_section(self) -> QGroupBox:
        box = QGroupBox("⑤ 결과")
        layout = QVBoxLayout(box)

        # 상단 버튼 줄: Excel 내보내기
        top = QHBoxLayout()
        top.addStretch(1)
        self.btn_export = QPushButton("Excel로 내보내기")
        self.btn_export.clicked.connect(self._on_export_excel)
        self.btn_export.setEnabled(False)  # 결과가 있을 때만 활성화
        top.addWidget(self.btn_export)
        layout.addLayout(top)

        self.result_table = QTableWidget(0, 6)
        self.result_table.setHorizontalHeaderLabels(
            ["번호", "파일명", "공백포함 글자수", "공백제외 글자수", "단어수", "줄수"]
        )
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        # 결과 표가 기본적으로 넉넉히 보이도록 최소 높이 지정(스플리터로 더 키울 수 있음)
        self.result_table.setMinimumHeight(320)
        layout.addWidget(self.result_table, stretch=1)

        self.total_label = QLabel("총합: -")
        self.total_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.total_label)

        return box

    # --- 6) 플랫폼 회차 대조 영역 --------------------------------------- #
    def _build_platform_section(self) -> QGroupBox:
        box = QGroupBox("⑥ 플랫폼 회차 대조 (네이버 시리즈)")
        layout = QVBoxLayout(box)

        # URL 입력 줄
        url_row = QHBoxLayout()
        url_row.addWidget(QLabel("작품 URL:"))
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "네이버 시리즈 작품 URL 붙여넣기 (예: https://series.naver.com/novel/detail.series?productNo=...)"
        )
        url_row.addWidget(self.url_input, stretch=1)
        self.btn_fetch = QPushButton("가져와서 대조")
        self.btn_fetch.clicked.connect(self._on_fetch_platform)
        url_row.addWidget(self.btn_fetch)
        # 가져온 회차 목록을 Excel 로 저장(분권 전 확인용). 수집 성공 후 활성화.
        self.btn_export_platform = QPushButton("회차 목록 Excel 저장")
        self.btn_export_platform.clicked.connect(self._on_export_platform_excel)
        self.btn_export_platform.setEnabled(False)
        url_row.addWidget(self.btn_export_platform)
        layout.addLayout(url_row)

        # 요약 라벨
        self.platform_summary = QLabel(
            "분권을 실행한 뒤, 위에 작품 URL을 넣고 [가져와서 대조]를 누르세요. "
            "회차 수와 제목을 플랫폼 연재분과 비교합니다."
        )
        self.platform_summary.setWordWrap(True)
        self.platform_summary.setStyleSheet("color: gray;")
        layout.addWidget(self.platform_summary)

        # 대조 표
        self.compare_table = QTableWidget(0, 4)
        self.compare_table.setHorizontalHeaderLabels(
            ["번호", "우리 분권 제목", "플랫폼 회차", "일치"]
        )
        self.compare_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.compare_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        self.compare_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch
        )
        self.compare_table.setMinimumHeight(180)
        layout.addWidget(self.compare_table, stretch=1)

        return box

    # ------------------------------------------------------------------ #
    # 드래그앤드롭
    # ------------------------------------------------------------------ #
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [url.toLocalFile() for url in event.mimeData().urls()]
        self._add_files(paths)

    # ------------------------------------------------------------------ #
    # 파일 선택 처리
    # ------------------------------------------------------------------ #
    def _on_select_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "소설 파일 선택",
            "",
            "지원 파일 (*.docx *.txt);;모든 파일 (*.*)",
        )
        if paths:
            self._add_files(paths)

    def _on_clear_files(self) -> None:
        self._files.clear()
        self.file_table.setRowCount(0)

    def _add_files(self, paths: List[str]) -> None:
        """파일 목록에 추가하고 전체 분량을 계산해 표에 표시한다."""
        added = 0
        for path in paths:
            if not os.path.isfile(path):
                continue
            if not is_supported_file(path):
                self._log(f"지원하지 않는 파일 건너뜀: {os.path.basename(path)}")
                continue
            if path in self._files:
                continue
            self._files.append(path)
            self._append_file_row(path)
            added += 1
        if added:
            self._log(f"{added}개 파일 추가됨 (총 {len(self._files)}개)")

    def _append_file_row(self, path: str) -> None:
        """파일의 전체 분량을 계산하여 파일 표에 한 줄 추가한다."""
        try:
            document = self._processor.analyze(path)
            counts: Counts = self._counter.count_blocks(document.blocks)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "읽기 오류", f"{os.path.basename(path)}\n{exc}")
            self._files.remove(path)
            return

        row = self.file_table.rowCount()
        self.file_table.insertRow(row)
        self.file_table.setItem(row, 0, QTableWidgetItem(os.path.basename(path)))
        self.file_table.setItem(row, 1, self._num_item(counts.chars_with_spaces))
        self.file_table.setItem(row, 2, self._num_item(counts.words))
        self.file_table.setItem(row, 3, self._num_item(counts.lines))

    def _on_custom_dir_toggled(self, checked: bool) -> None:
        self.btn_pick_dir.setEnabled(checked)
        if not checked:
            self.dir_display.clear()

    def _on_pick_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "출력 폴더 선택")
        if directory:
            self.dir_display.setText(directory)

    def _on_mode_changed(self) -> None:
        """선택된 분권 방식에 따라 입력 위젯의 활성 상태를 조정한다."""
        sep_mode = self.rb_separator.isChecked()
        char_mode = self.rb_char.isChecked()
        word_mode = self.rb_word.isChecked()

        # 구분자 입력
        self.sep_input.setEnabled(sep_mode)
        self.chk_include_sep.setEnabled(sep_mode)
        self.chk_remove_sep.setEnabled(sep_mode)

        # 글자수/단어수 입력
        self.count_input.setEnabled(char_mode or word_mode)
        self.chk_char_no_space.setEnabled(char_mode)
        if char_mode:
            self.count_label.setText("기준 글자수:")
        elif word_mode:
            self.count_label.setText("기준 단어수:")

    # ------------------------------------------------------------------ #
    # 실행
    # ------------------------------------------------------------------ #
    def _collect_options(self) -> SplitOptions:
        """UI 입력값을 SplitOptions 로 수집한다."""
        if self.rb_separator.isChecked():
            mode = SplitMode.SEPARATOR
        elif self.rb_char.isChecked():
            mode = SplitMode.CHAR_COUNT
        else:
            mode = SplitMode.WORD_COUNT

        return SplitOptions(
            mode=mode,
            separator=self.sep_input.text(),
            include_separator=self.chk_include_sep.isChecked(),
            remove_separator=self.chk_remove_sep.isChecked(),
            count_limit=self.count_input.value(),
            char_count_with_spaces=not self.chk_char_no_space.isChecked(),
            custom_output_dir=(
                self.dir_display.text()
                if self.chk_custom_dir.isChecked() and self.dir_display.text()
                else None
            ),
            overwrite=self.chk_overwrite.isChecked(),
            number_position="prefix" if self.rb_prefix.isChecked() else "suffix",
        )

    def _validate(self, options: SplitOptions) -> bool:
        """실행 전 입력값 검증."""
        if not self._files:
            QMessageBox.warning(self, "확인", "먼저 파일을 선택하세요.")
            return False
        if options.mode == SplitMode.SEPARATOR and not options.separator.strip():
            QMessageBox.warning(self, "확인", "구분자를 입력하세요.")
            return False
        if (
            options.mode in (SplitMode.CHAR_COUNT, SplitMode.WORD_COUNT)
            and options.count_limit <= 0
        ):
            QMessageBox.warning(self, "확인", "기준 수치는 1 이상이어야 합니다.")
            return False
        return True

    def _on_run(self) -> None:
        options = self._collect_options()
        if not self._validate(options):
            return

        # 결과 표 초기화
        self.result_table.setRowCount(0)
        self._results = []
        self.total_label.setText("총합: -")
        self.progress.setValue(0)
        self.log_view.clear()
        self.btn_export.setEnabled(False)
        self._set_running(True)

        # 백그라운드 스레드 구성
        self._thread = QThread()
        self._worker = Worker(list(self._files), options)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.current_file.connect(self.status_label.setText)
        self._worker.log.connect(self._log)
        self._worker.file_done.connect(self._on_file_done)
        self._worker.finished.connect(self._on_all_finished)
        self._worker.error.connect(self._on_error)

        self._thread.start()

    def _set_running(self, running: bool) -> None:
        """실행 중에는 조작 버튼을 비활성화한다."""
        self.btn_run.setEnabled(not running)
        self.btn_select.setEnabled(not running)
        self.btn_clear.setEnabled(not running)
        if running:
            self.status_label.setText("처리 시작...")

    def _on_file_done(self, result: FileResult) -> None:
        """파일 하나가 끝날 때마다 결과 표에 누적 반영한다."""
        self._results.append(result)
        self._refresh_result_table()
        # 결과가 하나라도 생기면 Excel 내보내기 활성화
        self.btn_export.setEnabled(bool(self._results))

    def _refresh_result_table(self) -> None:
        """누적된 모든 결과로 표와 총합을 다시 그린다."""
        self.result_table.setRowCount(0)
        grand_total = Counts()
        seq = 0

        for file_result in self._results:
            for chunk in file_result.chunks:
                seq += 1
                row = self.result_table.rowCount()
                self.result_table.insertRow(row)
                self.result_table.setItem(row, 0, QTableWidgetItem(str(seq)))
                name = chunk.filename + ("  (건너뜀)" if chunk.skipped else "")
                self.result_table.setItem(row, 1, QTableWidgetItem(name))
                self.result_table.setItem(
                    row, 2, self._num_item(chunk.counts.chars_with_spaces)
                )
                self.result_table.setItem(
                    row, 3, self._num_item(chunk.counts.chars_without_spaces)
                )
                self.result_table.setItem(row, 4, self._num_item(chunk.counts.words))
                self.result_table.setItem(row, 5, self._num_item(chunk.counts.lines))
                grand_total = grand_total + chunk.counts

        self.total_label.setText(
            f"총합 — 분권 {seq}개 | "
            f"공백포함 {grand_total.chars_with_spaces:,}자 | "
            f"공백제외 {grand_total.chars_without_spaces:,}자 | "
            f"단어 {grand_total.words:,} | "
            f"줄 {grand_total.lines:,}"
        )

    def _on_all_finished(self) -> None:
        self._set_running(False)
        self.progress.setValue(100)
        self.status_label.setText("완료")
        self._log("모든 처리가 완료되었습니다.")
        self._cleanup_thread()
        QMessageBox.information(self, "완료", "분권 처리가 완료되었습니다.")

    def _on_error(self, message: str) -> None:
        self._set_running(False)
        self.status_label.setText("오류 발생")
        self._log(f"오류: {message}")
        self._cleanup_thread()
        QMessageBox.critical(self, "오류", f"처리 중 오류가 발생했습니다.\n{message}")

    def _cleanup_thread(self) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None

    # ------------------------------------------------------------------ #
    # Excel 내보내기
    # ------------------------------------------------------------------ #
    def _on_export_excel(self) -> None:
        """현재 결과를 Excel(.xlsx) 파일로 저장한다."""
        if not self._results:
            QMessageBox.warning(self, "확인", "내보낼 결과가 없습니다.")
            return

        # 기본 저장 이름: 첫 원본 파일명 기반, 원본 폴더에 저장 제안
        first_source = self._results[0].source_path
        default_name = f"{get_stem(first_source)}_분권결과.xlsx"
        default_dir = os.path.dirname(os.path.abspath(first_source))
        default_path = os.path.join(default_dir, default_name)

        path, _ = QFileDialog.getSaveFileName(
            self, "Excel로 내보내기", default_path, "Excel 파일 (*.xlsx)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        try:
            ExcelExporter().export(self._results, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, "내보내기 오류", f"Excel 저장 중 오류가 발생했습니다.\n{exc}"
            )
            return

        self._log(f"Excel 저장 완료: {path}")
        QMessageBox.information(self, "완료", f"Excel 파일로 저장했습니다.\n{path}")

    # ------------------------------------------------------------------ #
    # 플랫폼 회차 대조
    # ------------------------------------------------------------------ #
    def _on_fetch_platform(self) -> None:
        """작품 URL 로 플랫폼 회차 목록을 가져와 대조한다."""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "확인", "작품 URL 을 입력하세요.")
            return

        self.btn_fetch.setEnabled(False)
        self.platform_summary.setText("회차 목록을 가져오는 중입니다...")

        self._fetch_thread = QThread()
        self._fetch_worker = FetchWorker(url)
        self._fetch_worker.moveToThread(self._fetch_thread)
        self._fetch_thread.started.connect(self._fetch_worker.run)
        self._fetch_worker.done.connect(self._on_platform_done)
        self._fetch_worker.error.connect(self._on_platform_error)
        self._fetch_thread.start()

    def _on_platform_done(self, result: PlatformResult) -> None:
        """수집 성공 시 우리 분권 결과와 대조하여 표시한다."""
        self._platform_result = result
        self._cleanup_fetch_thread()
        self.btn_fetch.setEnabled(True)
        # 회차 목록을 가져왔으므로 Excel 저장 활성화
        self.btn_export_platform.setEnabled(bool(result.episodes))

        # 우리 분권 제목(각 분권 첫 줄) 목록 - 건너뛴 분권 제외
        our_titles = [
            c.title for fr in self._results for c in fr.chunks if not c.skipped
        ]
        comparison: Comparison = compare_titles(our_titles, result)

        # 요약
        mark = "✅ 일치" if comparison.count_match else "❌ 불일치"
        self.platform_summary.setText(
            f"작품: {result.work_title or '(제목 미확인)'}  |  "
            f"플랫폼 회차 {comparison.platform_count}개  vs  "
            f"우리 분권 {comparison.our_count}개  →  회차 수 {mark}"
        )
        if not self._results:
            self.platform_summary.setText(
                self.platform_summary.text()
                + "   (분권을 먼저 실행하면 제목까지 나란히 대조됩니다)"
            )

        # 대조 표 채우기
        self.compare_table.setRowCount(0)
        for row in comparison.rows:
            r = self.compare_table.rowCount()
            self.compare_table.insertRow(r)
            self.compare_table.setItem(r, 0, QTableWidgetItem(str(row.no)))
            self.compare_table.setItem(r, 1, QTableWidgetItem(row.our_title))
            self.compare_table.setItem(r, 2, QTableWidgetItem(row.platform_title))
            # 일치 표시: 제목이 있을 때만 O/X, 한쪽이 비면 누락 표시
            if not row.our_title and row.platform_title:
                mark_item = QTableWidgetItem("우리 측 없음")
            elif row.our_title and not row.platform_title:
                mark_item = QTableWidgetItem("플랫폼 측 없음")
            else:
                mark_item = QTableWidgetItem("O" if row.title_match else "△")
            mark_item.setTextAlignment(Qt.AlignCenter)
            self.compare_table.setItem(r, 3, mark_item)

        self._log(
            f"플랫폼 대조: {result.work_title} - 플랫폼 {comparison.platform_count}회차, "
            f"우리 {comparison.our_count}분권"
        )

    def _on_platform_error(self, message: str) -> None:
        self._cleanup_fetch_thread()
        self.btn_fetch.setEnabled(True)
        self.platform_summary.setText("가져오기 실패")
        QMessageBox.warning(self, "가져오기 실패", message)

    def _on_export_platform_excel(self) -> None:
        """가져온 플랫폼 회차 목록을 Excel(.xlsx)로 저장한다(분권 전 확인용)."""
        if not self._platform_result or not self._platform_result.episodes:
            QMessageBox.warning(self, "확인", "먼저 작품 URL로 회차 목록을 가져오세요.")
            return

        title = self._platform_result.work_title or "회차목록"
        # 파일명에 쓸 수 없는 문자를 정리
        safe = re.sub(r'[\\/:*?"<>|]', "_", title).strip() or "회차목록"
        default_path = os.path.join(
            os.path.expanduser("~"), f"{safe}_플랫폼회차목록.xlsx"
        )
        path, _ = QFileDialog.getSaveFileName(
            self, "회차 목록 Excel로 저장", default_path, "Excel 파일 (*.xlsx)"
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"

        try:
            ExcelExporter().export_platform(self._platform_result, path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(
                self, "내보내기 오류", f"Excel 저장 중 오류가 발생했습니다.\n{exc}"
            )
            return

        self._log(f"플랫폼 회차 목록 저장 완료: {path}")
        QMessageBox.information(self, "완료", f"회차 목록을 저장했습니다.\n{path}")

    def _cleanup_fetch_thread(self) -> None:
        if self._fetch_thread:
            self._fetch_thread.quit()
            self._fetch_thread.wait()
            self._fetch_thread = None
            self._fetch_worker = None

    # ------------------------------------------------------------------ #
    # 보조
    # ------------------------------------------------------------------ #
    @staticmethod
    def _num_item(value: int) -> QTableWidgetItem:
        """숫자를 천단위 콤마와 우측 정렬로 표시하는 표 항목을 만든다."""
        item = QTableWidgetItem(f"{value:,}")
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return item

    def _log(self, message: str) -> None:
        """로그 창에 메시지를 추가한다."""
        self.log_view.append(message)


def run_gui() -> int:
    """GUI 애플리케이션을 실행한다."""
    import sys

    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
