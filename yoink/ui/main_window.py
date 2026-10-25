"""Main window: URL input, override controls, and the downloads table."""

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGridLayout,
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

BROWSERS = ["brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale"]
# Known cookie extraction pitfalls (docs/DESIGN.md section 4).
PITFALLS = {
    "firefox": "Firefox must be closed, or yt-dlp cannot read its cookies.",
    "chrome": "Chrome on Windows 127+ needs a current yt-dlp.",
    "safari": "Safari on macOS needs Full Disk Access.",
}
FOLLOWING = "Following the yt-dlp config."


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
        self.settings = app.settings()
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
        self.start_btn = QPushButton("Download")
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self.start_download)

        # Override controls (docs/PHASE1.md section 2). Each one is empty or
        # "Config default" while following the yt-dlp config.
        self.dir_edit = QLineEdit(placeholderText=argv.default_download_dir())
        self.dir_edit.setClearButtonEnabled(True)
        self.dir_edit.textChanged.connect(self._overrides_changed)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        self.cookies_combo = QComboBox()
        self.cookies_combo.addItem("", "")  # text set by _set_config_cookies
        self.cookies_combo.addItem("No cookies", "none")
        for b in BROWSERS:
            self.cookies_combo.addItem(b, b)
        self._set_config_cookies(None)
        self.cookies_combo.currentIndexChanged.connect(self._overrides_changed)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setToolTip("Clear main-window overrides and use the yt-dlp config")
        self.reset_btn.clicked.connect(self.reset_overrides)

        url_row = QHBoxLayout()
        url_row.addWidget(self.url_edit, 1)
        url_row.addWidget(self.start_btn)

        grid = QGridLayout()
        grid.addWidget(QLabel("Save to:"), 0, 0)
        grid.addWidget(self.dir_edit, 0, 1)
        grid.addWidget(browse, 0, 2)
        grid.addWidget(QLabel("Cookies:"), 1, 0)
        grid.addWidget(self.cookies_combo, 1, 1, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self.reset_btn, 1, 2)

        root.addLayout(url_row)
        root.addLayout(grid)
        self._overrides_changed()

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
        app.migrate_settings(self.settings)
        self.dir_edit.setText(self.settings.value(app.KEY_DIR, ""))
        # An unknown value (say, a browser dropped from the list) follows the config.
        i = self.cookies_combo.findData(self.settings.value(app.KEY_COOKIES, ""))
        self.cookies_combo.setCurrentIndex(max(i, 0))

    def _report_binary(self) -> None:
        if not self.binary_path:
            self.status_label.setText("yt-dlp not found on PATH")
            self.start_btn.setEnabled(False)
            return
        ver = binary.get_version(self.binary_path) or "unknown version"
        self.status_label.setText(f"yt-dlp {ver}")
        self.status_label.setToolTip(str(self.binary_path))

    # ---- overrides --------------------------------------------------------

    def _set_config_cookies(self, value: str | None) -> None:
        """Label the first combo item with the config's cookies value, if known."""
        self.cookies_combo.setItemText(0, f"Config default ({value})" if value else "Config default")

    def _overrides_changed(self) -> None:
        directory = self.dir_edit.text().strip()
        cookies = self.cookies_combo.currentData()
        self.reset_btn.setEnabled(bool(directory or cookies))
        self.dir_edit.setToolTip(
            "Overriding the yt-dlp config. Clear the field to follow it."
            if directory
            else f"{FOLLOWING} Type or browse to override it."
        )
        if not cookies:
            tip = FOLLOWING
        elif cookies == "none":
            tip = "Overriding the yt-dlp config: no browser cookies."
        else:
            tip = f"Overriding the yt-dlp config: cookies from {cookies}."
            if cookies in PITFALLS:
                tip += "\n" + PITFALLS[cookies]
        self.cookies_combo.setToolTip(tip)

    def reset_overrides(self) -> None:
        self.dir_edit.clear()
        self.cookies_combo.setCurrentIndex(0)

    # ---- actions ----------------------------------------------------------

    def _browse(self) -> None:
        # The placeholder may be text rather than a path once the config is probed.
        candidates = (self.dir_edit.text().strip(), self.dir_edit.placeholderText())
        start = next((d for d in candidates if os.path.isdir(d)), argv.default_download_dir())
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

        cookies = self.cookies_combo.currentData() or None
        job = DownloadJob(self.binary_path, argv.build_argv(url, directory, cookies), url, parent=self)
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
        self.settings.setValue(app.KEY_DIR, self.dir_edit.text().strip())
        self.settings.setValue(app.KEY_COOKIES, self.cookies_combo.currentData())
        for job in self.jobs:
            job.cancel()
        super().closeEvent(event)
