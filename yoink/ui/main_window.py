"""Main window: URL and directory inputs plus the downloads table."""

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from yoink import __version__, app, argv, binary
from yoink.job import DownloadJob, JobState, Progress

log = logging.getLogger(__name__)

COLUMNS = ["Status", "URL", "Host", "Filename", "Downloaded", "Total", "Speed", "Progress", ""]
(C_STATUS, C_URL, C_HOST, C_FILE, C_DOWN, C_TOTAL, C_SPEED, C_PROG, C_CANCEL) = range(len(COLUMNS))


def format_bytes(n: float | None) -> str:
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings(app.ORG_NAME, app.APP_NAME)
        self.jobs: list[DownloadJob] = []  # index == table row
        self.binary_path = binary.find_binary(self.settings.value(app.KEY_BINARY_PATH))

        self.setWindowTitle(f"{app.APP_TITLE} {__version__}")
        self._build_ui()
        self._restore_state()
        self._report_binary()

    # ---- construction -----------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.url_edit = QLineEdit(placeholderText="URL")
        self.url_edit.returnPressed.connect(self.start_download)
        self.dir_edit = QLineEdit(placeholderText=argv.default_download_dir())
        self.dir_edit.setToolTip("Download directory. Empty means the OS Downloads folder.")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        self.start_btn = QPushButton("Download")
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self.start_download)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Save to:"))
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(browse)

        url_row = QHBoxLayout()
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(self.start_btn)

        root.addLayout(url_row)
        root.addLayout(dir_row)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(C_URL, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(C_FILE, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(C_PROG, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(C_PROG, 140)
        root.addWidget(self.table, 1)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction("Clear finished", self.clear_finished)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close)
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("About", self._about)

        self.status_label = QLabel()
        self.statusBar().addPermanentWidget(self.status_label)

    def _restore_state(self) -> None:
        if geo := self.settings.value(app.KEY_GEOMETRY):
            self.restoreGeometry(geo)
        else:
            self.resize(1000, 560)
        self.dir_edit.setText(self.settings.value(app.KEY_LAST_DIR, ""))

    def _report_binary(self) -> None:
        if not self.binary_path:
            self.status_label.setText("yt-dlp not found on PATH")
            self.start_btn.setEnabled(False)
            return
        ver = binary.get_version(self.binary_path) or "unknown version"
        self.status_label.setText(f"yt-dlp {ver}")
        self.status_label.setToolTip(str(self.binary_path))

    # ---- actions ----------------------------------------------------------

    def _browse(self) -> None:
        start = self.dir_edit.text() or argv.default_download_dir()
        chosen = QFileDialog.getExistingDirectory(self, "Download directory", start)
        if chosen:
            self.dir_edit.setText(chosen)

    def start_download(self) -> None:
        url = self.url_edit.text().strip()
        if not url:
            return
        if not self.binary_path:
            QMessageBox.warning(self, app.APP_TITLE, "yt-dlp was not found on PATH.")
            return
        directory = self.dir_edit.text().strip() or argv.default_download_dir()
        if not os.path.isdir(directory):
            QMessageBox.warning(self, app.APP_TITLE, f"Directory does not exist:\n{directory}")
            return

        job = DownloadJob(self.binary_path, argv.build_argv(url, directory), url, parent=self)
        self._add_row(job)
        job.state_changed.connect(lambda s, j=job: self._on_state(j, s))
        job.file_named.connect(lambda f, j=job: self._set(j, C_FILE, os.path.basename(f)))
        job.progress.connect(lambda p, j=job: self._on_progress(j, p))
        job.postprocessing.connect(lambda name, j=job: self._set(j, C_SPEED, name))
        job.done.connect(lambda path, j=job: self._set(j, C_FILE, os.path.basename(path)))
        job.finished.connect(lambda j=job: self._on_finished(j))
        job.start()
        self.url_edit.clear()

    def clear_finished(self) -> None:
        for row in range(len(self.jobs) - 1, -1, -1):
            if self.jobs[row].state.terminal:
                self.table.removeRow(row)
                del self.jobs[row]

    def _about(self) -> None:
        QMessageBox.about(
            self,
            f"About {app.APP_TITLE}",
            f"{app.APP_TITLE} {__version__}\nA small front end for yt-dlp.\n\n"
            f"yt-dlp: {self.binary_path or 'not found'}",
        )

    # ---- table plumbing ---------------------------------------------------

    def _add_row(self, job: DownloadJob) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.jobs.append(job)
        for col in range(len(COLUMNS)):
            self.table.setItem(row, col, QTableWidgetItem(""))
        self.table.item(row, C_STATUS).setText(job.state.value)
        self.table.item(row, C_URL).setText(job.url)
        self.table.item(row, C_URL).setToolTip(job.url)
        self.table.item(row, C_HOST).setText(urlparse(job.url).netloc)

        bar = QProgressBar()
        bar.setRange(0, 0)  # indeterminate until the first progress line
        bar.setTextVisible(True)
        self.table.setCellWidget(row, C_PROG, bar)

        cancel = QPushButton("Cancel")
        cancel.clicked.connect(job.cancel)
        self.table.setCellWidget(row, C_CANCEL, cancel)

    def _row(self, job: DownloadJob) -> int:
        return self.jobs.index(job)

    def _set(self, job: DownloadJob, col: int, text: str) -> None:
        self.table.item(self._row(job), col).setText(text)

    def _on_state(self, job: DownloadJob, state: JobState) -> None:
        self._set(job, C_STATUS, state.value)

    def _on_progress(self, job: DownloadJob, p: Progress) -> None:
        row = self._row(job)
        self.table.item(row, C_DOWN).setText(format_bytes(p.downloaded))
        self.table.item(row, C_TOTAL).setText(format_bytes(p.total))
        self.table.item(row, C_SPEED).setText(f"{format_bytes(p.speed)}/s" if p.speed else "")
        bar: QProgressBar = self.table.cellWidget(row, C_PROG)
        if p.percent is None:
            bar.setRange(0, 0)
        else:
            bar.setRange(0, 100)
            bar.setValue(p.percent)

    def _on_finished(self, job: DownloadJob) -> None:
        row = self._row(job)
        bar: QProgressBar = self.table.cellWidget(row, C_PROG)
        bar.setRange(0, 100)
        self.table.item(row, C_SPEED).setText("")
        if job.state is JobState.FINISHED:
            bar.setValue(100)
        elif job.state is JobState.FAILED:
            self.table.item(row, C_FILE).setText(job.error_text)
            self.table.item(row, C_FILE).setToolTip("\n".join(job.log[-20:]))
        self.table.cellWidget(row, C_CANCEL).setEnabled(False)

    # ---- lifecycle --------------------------------------------------------

    def closeEvent(self, event) -> None:
        self.settings.setValue(app.KEY_GEOMETRY, self.saveGeometry())
        self.settings.setValue(app.KEY_LAST_DIR, self.dir_edit.text().strip())
        for job in self.jobs:
            job.cancel()
        super().closeEvent(event)
