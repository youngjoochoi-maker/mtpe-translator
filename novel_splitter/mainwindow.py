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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .counter import Counter, Counts
from .processor import FileResult, Processor, SplitMode, SplitOptions
from .utils import is_supported_file


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
# 메인 윈도우
# ---------------------------------------------------------------------------- #
class MainWindow(QWidget):
    """소설 분권 프로그램 메인 창."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("소설 분권 프로그램")
        self.resize(920, 780)
        self.setAcceptDrops(True)  # 드래그앤드롭 허용

        self._files: List[str] = []            # 선택된 파일 목록
        self._processor = Processor()          # 미리보기(전체 분량)용
        self._counter = Counter()
        self._thread: QThread | None = None
        self._worker: Worker | None = None
        self._results: List[FileResult] = []   # 처리 결과 누적

        self._build_ui()

    # ------------------------------------------------------------------ #
    # UI 구성
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        root.addWidget(self._build_file_section())
        root.addWidget(self._build_mode_section())
        root.addWidget(self._build_output_section())
        root.addWidget(self._build_run_section())
        root.addWidget(self._build_result_section(), stretch=1)

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

        self.result_table = QTableWidget(0, 6)
        self.result_table.setHorizontalHeaderLabels(
            ["번호", "파일명", "공백포함 글자수", "공백제외 글자수", "단어수", "줄수"]
        )
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch
        )
        layout.addWidget(self.result_table)

        self.total_label = QLabel("총합: -")
        self.total_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.total_label)

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
            counts: Counts = self._counter.count_paragraphs(document.paragraphs)
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
