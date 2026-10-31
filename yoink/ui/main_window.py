"""Main window: URL input, override controls, and the downloads table."""

import logging
import os
import re
import zlib
from collections.abc import Callable
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from PySide6.QtCore import QByteArray, QProcess, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
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
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from yoink import VERSION_LABEL, __version__, app, argv, binary, overrides, ytdlp_config
from yoink.job import DownloadJob, JobState, Progress
from yoink.ui.config_notice import ConfigNoticeDialog
from yoink.ui.options_form import side_by_side
from yoink.ui.prefs_dialog import PrefsDialog
from yoink.ui.setup_dialog import SetupDialog

log = logging.getLogger(__name__)

COLUMNS = ["", "Status", "Scheme", "Host", "Path", "Filename", "Downloaded", "Total", "Speed",
           "Progress", "Title", "Uploader", "Duration", "Resolution", "Upload date", ""]
(C_ICON, C_STATUS, C_SCHEME, C_HOST, C_PATH, C_FILE, C_DOWN, C_TOTAL, C_SPEED, C_PROG,
 C_TITLE, C_UPLOADER, C_DURATION, C_RES, C_DATE, C_ACTION) = range(len(COLUMNS))
META_COLUMNS = range(C_TITLE, C_ACTION)  # in the order of the META fields
HIDDEN = (C_SCHEME, *META_COLUMNS)  # until shown from the View menu
# Table widths, order and hidden columns. Qt restores them by column index, so a
# different column list gets a different key and starts from the defaults.
HEADER_KEY = f"{app.KEY_HEADER}/{zlib.crc32('|'.join(COLUMNS).encode()):08x}"
SP = QStyle.StandardPixmap
STATE_ICONS = {
    JobState.QUEUED: SP.SP_BrowserReload,
    JobState.STARTING: SP.SP_BrowserReload,
    JobState.DOWNLOADING: SP.SP_ArrowDown,
    JobState.POSTPROCESSING: SP.SP_FileDialogContentsView,
    JobState.FINISHED: SP.SP_DialogApplyButton,
    JobState.FAILED: SP.SP_MessageBoxCritical,
    JobState.CANCELLED: SP.SP_DialogCancelButton,
}

# Known cookie extraction pitfalls (docs/DESIGN.md section 4).
PITFALLS = {
    "firefox": "Firefox must be closed, or yt-dlp cannot read its cookies.",
    "chrome": "Chrome on Windows 127+ needs a current yt-dlp.",
    "safari": "Safari on macOS needs Full Disk Access.",
}
FOLLOWING = "Following the yt-dlp config."
STALE_TIP = (
    "This copy of yt-dlp is more than 90 days old. Sites change often, so an old copy is the "
    "usual reason downloads or cookies stop working. Update it from File > Preferences."
)
# The macOS single-file build takes ~6.5 s to start; a quarantined one may hang.
PROBE_TIMEOUT_MS = 20_000


def format_bytes(n: float | None) -> str:
    if n is None:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def open_path(path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = app.settings()
        self.jobs: list[DownloadJob] = []  # index == table row
        self.binary_path = binary.find_binary(self.settings.value(app.KEY_BINARY_PATH))
        # Last config probe result (docs/PHASE1.md 1.1); None until it succeeds.
        self.loaded_configs: list[ytdlp_config.LoadedConfig] | None = None
        self.config_defaults = ytdlp_config.config_defaults(None)
        self.variant = ""  # the build, from the probe's debug header
        self._probe: QProcess | None = None
        # The last result, as SetupDialog.show_result takes it; the dialog exists once opened.
        self.probe_result: tuple[Path | None, str, str, str] = (self.binary_path, "", "", "")
        self.setup_dialog: SetupDialog | None = None
        # Per-domain rules (docs/PHASE3.md section 5); `rule` matches the URL field.
        self._load_rules()
        self.url_host: str | None = None
        self.rule_domain: str | None = None
        self.rule: dict[str, str | bool] = {}

        self.setWindowTitle(f"{app.APP_TITLE} {__version__}")
        self._build_ui()
        self._restore_state()
        self.refresh_config()

    # ---- construction -----------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.url_edit = QLineEdit(placeholderText="URL")
        self.url_edit.returnPressed.connect(self.start_download)
        self.url_edit.textChanged.connect(self._url_changed)
        self.start_btn = QPushButton("Download")
        self.start_btn.setDefault(True)
        self.start_btn.clicked.connect(self.start_download)

        # Override controls (docs/PHASE1.md section 2). Each one is empty or
        # "Config default" while following the yt-dlp config.
        self.dir_edit = QLineEdit()  # placeholder set by _refresh_defaults
        self.dir_edit.setClearButtonEnabled(True)
        self.dir_edit.textChanged.connect(self._overrides_changed)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        self.pin_btn = self._tool_button(SP.SP_DialogSaveButton, "", self._pin)  # tip set below
        self.cookies_combo = QComboBox()
        # The first item's text grows once the probe reports; keep it unclipped.
        self.cookies_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.cookies_combo.addItem("", "")  # text set by _refresh_defaults
        self.cookies_combo.addItem("No cookies", "none")
        for b in ytdlp_config.BROWSERS:
            self.cookies_combo.addItem(b, b)
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
        grid.addWidget(self.pin_btn, 0, 3)
        grid.addWidget(QLabel("Cookies:"), 1, 0)
        grid.addWidget(self.cookies_combo, 1, 1, Qt.AlignmentFlag.AlignLeft)
        grid.addWidget(self.reset_btn, 1, 2)
        self.rule_label = QLabel()
        grid.addWidget(self.rule_label, 2, 1, 1, 2)

        root.addLayout(url_row)
        root.addLayout(grid)
        self._refresh_defaults()

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setSectionsMovable(True)
        self.table.setWordWrap(False)  # elide text that doesn't fit
        # Default widths: the header text, or room for the usual contents.
        self.table.resizeColumnsToContents()
        for col, width in {C_ICON: 28, C_STATUS: 80, C_HOST: 100, C_PATH: 180,
                           C_FILE: 180, C_TOTAL: 70, C_SPEED: 80, C_PROG: 100, C_TITLE: 180,
                           C_ACTION: 66}.items():
            self.table.setColumnWidth(col, width)
        for col in HIDDEN:
            hdr.setSectionHidden(col, True)
        self._default_header = hdr.saveState()
        root.addWidget(self.table, 1)

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction("Clear finished", self.clear_finished)
        file_menu.addAction("Refresh config", self.refresh_config)
        file_menu.addSeparator()
        self.prefs_action = file_menu.addAction("Preferences…", self.show_prefs)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close)
        view_menu = self.menuBar().addMenu("&View")
        self.column_actions = []  # checked shows the column; the action column always shows
        for col, name in enumerate(COLUMNS[:C_ACTION]):
            action = view_menu.addAction(name or "Status icon")
            action.setCheckable(True)
            action.toggled.connect(lambda on, c=col: hdr.setSectionHidden(c, not on))
            self.column_actions.append(action)
        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction("Set up yt-dlp…", self.show_setup)
        help_menu.addAction("About", self._about)

        # Override indicator (docs/PHASE1.md 1.3), left of the version.
        self.notice_icon = QLabel()
        icon = self.style().standardIcon(SP.SP_MessageBoxWarning)
        self.notice_icon.setPixmap(icon.pixmap(16, 16))
        self.notice_link = QLabel('<a href="#">Some configuration values overridden</a>')
        self.notice_link.setToolTip("Show which yt-dlp config files set the same option")
        self.notice_link.linkActivated.connect(self.show_config_notice)
        self.status_label = QLabel()
        for w in (self.notice_icon, self.notice_link, self.status_label):
            self.statusBar().addPermanentWidget(w)
        self._set_conflicts([])

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
        self._set_header(self.settings.value(HEADER_KEY))

    def _set_header(self, state: QByteArray | None) -> None:
        """Restore the table columns from `state`, or the defaults if there is none or Qt rejects it."""
        hdr = self.table.horizontalHeader()
        if not (state and hdr.restoreState(state)):
            hdr.restoreState(self._default_header)
        for col, action in enumerate(self.column_actions):
            action.setChecked(not hdr.isSectionHidden(col))

    # ---- config probe -----------------------------------------------------

    def refresh_config(self) -> None:
        """Ask yt-dlp which configs it loads; the answer arrives in _probe_done."""
        if not (self.binary_path and self.binary_path.is_file()):
            self.status_label.setText(
                f"yt-dlp not found: {self.binary_path}" if self.binary_path else "yt-dlp not found on PATH")
            self.status_label.setToolTip("Set the yt-dlp program in Preferences.")
            self.start_btn.setEnabled(False)
            self._set_probe_result(self.binary_path, "", "", "")
            return
        self.status_label.setText("Checking yt-dlp…")
        self.status_label.setToolTip(str(self.binary_path))
        # Until the probe says whether the config sets a home path, an empty
        # directory field can't tell "pass no -P" from "pass Downloads".
        # Preferences, too, needs the finished result.
        self.start_btn.setEnabled(False)
        self.prefs_action.setEnabled(False)
        self.start_btn.setToolTip("Waiting for yt-dlp to report its config")
        if self._probe:  # superseded; _probe_done ignores its result
            self._probe.kill()
        self._probe = proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        # As for downloads: yt-dlp looks for a "Home" config in the working directory.
        proc.setWorkingDirectory(argv.default_download_dir())
        proc.finished.connect(
            lambda _, status: self._probe_done(proc, status == QProcess.ExitStatus.NormalExit)
        )
        proc.errorOccurred.connect(
            lambda e: e == QProcess.ProcessError.FailedToStart and self._probe_done(proc, False)
        )
        proc.start(str(self.binary_path), ytdlp_config.PROBE_ARGS)
        proc.closeWriteChannel()  # so `--config-locations -` reads EOF instead of hanging
        QTimer.singleShot(PROBE_TIMEOUT_MS, proc, proc.kill)

    def _probe_done(self, proc: QProcess, exited: bool) -> None:
        proc.deleteLater()
        if proc is not self._probe:
            return
        self._probe = None
        self.start_btn.setEnabled(True)
        self.prefs_action.setEnabled(True)
        self.start_btn.setToolTip("")
        text = ytdlp_config.decode_output(bytes(proc.readAll()))
        # A killed probe may have listed some config files but not all of them.
        self.loaded_configs = ytdlp_config.parse_probe(text) if exited else None
        if self.loaded_configs is None:
            log.warning("Config probe failed:\n%s", text.strip())
        self.config_defaults = ytdlp_config.config_defaults(self.loaded_configs)
        self._refresh_defaults()
        self._set_conflicts(ytdlp_config.find_conflicts(self.loaded_configs or []))

        ver = ytdlp_config.parse_version(text)
        self.variant = ver[1] if ver else ""
        method = binary.install_method(self.binary_path, self.variant)
        self._set_probe_result(self.binary_path, ver[0] if ver else "", method, text.strip())
        if ver:
            status = f"yt-dlp {ver[0]} ({method})"
        else:
            status = "yt-dlp unknown version"
        tip = str(self.binary_path)
        if ytdlp_config.is_stale(text, date.today()):
            status, tip = f"{status}, over 90 days old", f"{STALE_TIP}\n\n{tip}"
        if self.loaded_configs is None:
            status = f"{status}, config: unknown" if ver else "yt-dlp config: unknown"
        self.status_label.setText(status)
        self.status_label.setToolTip(tip)

    def _set_probe_result(self, found: Path | None, version: str, method: str, output: str) -> None:
        self.probe_result = result = (found, version, method, output)
        if self.setup_dialog and self.setup_dialog.isVisible():
            self.setup_dialog.show_result(*result)

    def show_setup(self) -> None:
        if not self.setup_dialog:
            self.setup_dialog = SetupDialog(self)
            self.setup_dialog.check_requested.connect(self._check_again)
        self.setup_dialog.show_result(*self.probe_result)
        self.setup_dialog.open()

    def _check_again(self) -> None:
        """Discovery and the probe again: a new managed copy, say, replaces a broken one."""
        self.binary_path = binary.find_binary(self.settings.value(app.KEY_BINARY_PATH))
        self.refresh_config()

    def _set_conflicts(self, conflicts: list[ytdlp_config.Occurrence]) -> None:
        self.conflicts = conflicts
        self.notice_icon.setVisible(bool(conflicts))
        self.notice_link.setVisible(bool(conflicts))

    def show_config_notice(self) -> None:
        dialog = ConfigNoticeDialog(self.loaded_configs or [], self.conflicts, self)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.open()

    def show_prefs(self) -> None:
        dialog = PrefsDialog(self.settings, self.loaded_configs, self.binary_path, self.variant, self)
        dialog.setup_requested.connect(self.show_setup)
        dialog.exec()
        dialog.deleteLater()
        if dialog.binary_changed:
            self.binary_path = binary.find_binary(self.settings.value(app.KEY_BINARY_PATH))
        if dialog.binary_changed or dialog.config_written or dialog.updated:
            self.refresh_config()
        if dialog.table_reset:
            self._set_header(self._default_header)
        if dialog.rules_written:
            self._load_rules()
            self._url_changed()

    # ---- overrides --------------------------------------------------------

    def _load_rules(self) -> None:
        self.rules = overrides.load_rules(overrides.rules_path())

    def _url_changed(self) -> None:
        text = self.url_edit.text().strip()
        try:  # yt-dlp accepts a URL without a scheme; so does the match
            scheme = re.match(r"[a-z][a-z0-9+.-]*://|//", text, re.I)
            self.url_host = urlparse(text if scheme else "//" + text).hostname
        except ValueError:  # say, an unclosed "[" in the host
            self.url_host = None
        self.rule_domain = overrides.match(self.url_host, self.rules)
        self.rule = self.rules[self.rule_domain] if self.rule_domain else {}
        self._refresh_defaults()

    @property
    def rule_dir(self) -> str:
        """The rule's home download folder, or ""."""
        return ytdlp_config.home_path(str(self.rule.get("--paths") or "")) or ""

    def _refresh_defaults(self) -> None:
        """Show the defaults in effect: the URL's rule, else the config (docs/PHASE3.md section 5)."""
        d = self.config_defaults
        # The option takes a string; str() is for the typechecker.
        rule_cookies = str(self.rule.get("--cookies-from-browser") or "")
        directory = self.rule_dir or d.directory
        fallback = "Set by yt-dlp config" if d.sets_directory else argv.default_download_dir()
        self.dir_edit.setPlaceholderText(ytdlp_config.to_display_path(directory) or fallback)
        # The cookies tooltip and pitfall text follow this, too.
        self.config_cookies = rule_cookies or d.cookies
        self.cookies_combo.setItemText(
            0, f"Config default ({self.config_cookies})" if self.config_cookies else "Config default")
        self.rule_label.setVisible(self.rule_domain is not None)
        self.rule_label.setText(f"Rule for {self.rule_domain} applies")
        self.rule_label.setToolTip("\n".join(overrides.rule_lines(self.rule)))
        self._overrides_changed()

    def _overrides_changed(self) -> None:
        directory = self.dir_edit.text().strip()
        cookies = self.cookies_combo.currentData()
        self.reset_btn.setEnabled(bool(directory or cookies))
        # A green border marks a rule's default while it is in effect.
        rule_tip = f"Default from the {self.rule_domain} rule."
        dir_from_rule = not directory and bool(self.rule_dir)
        cookies_from_rule = not cookies and bool(self.rule.get("--cookies-from-browser"))
        for widget, on in ((self.dir_edit, dir_from_rule), (self.cookies_combo, cookies_from_rule)):
            # Scoped to the widget's class, so a combo's popup list keeps its own frame.
            widget.setStyleSheet(f"{type(widget).__name__} {{ border: 2px solid green }}" if on else "")
        overridden = f"the {self.rule_domain} rule" if self.rule_dir else "the yt-dlp config"
        self.dir_edit.setToolTip(
            f"Overriding {overridden}. Clear the field to follow it."
            if directory
            else f"{rule_tip if dir_from_rule else FOLLOWING} Type or browse to override it."
        )
        if not cookies:
            tip = rule_tip if cookies_from_rule else FOLLOWING
            # The spec is BROWSER[+KEYRING][:PROFILE][::CONTAINER].
            if (spec := self.config_cookies) and spec != "none":
                tip += f" It reads cookies from {spec}."
                if (browser := re.split("[+:]", spec)[0]) in PITFALLS:
                    tip += "\n" + PITFALLS[browser]
        elif cookies == "none":
            tip = "Overriding the yt-dlp config: no browser cookies."
        else:
            tip = f"Overriding the yt-dlp config: cookies from {cookies}."
            if cookies in PITFALLS:
                tip += "\n" + PITFALLS[cookies]
        self.cookies_combo.setToolTip(tip)
        self.pin_btn.setEnabled(bool(self._pin_domain() and directory))
        self.pin_btn.setToolTip(
            f"Save {directory} as the download folder for {self._pin_domain()}"
            if self.pin_btn.isEnabled()
            else "Type or pick a folder and a URL to save it as that site's download folder."
        )

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
            self.dir_edit.setText(os.path.normpath(chosen))

    def _pin_domain(self) -> str:
        """The matched rule's domain, else the URL's (docs/PHASE3.md section 5)."""
        return self.rule_domain or overrides.normalize_domain(self.url_host or "")

    def _pin(self) -> None:
        """Save the directory field as the URL's rule's --paths."""
        domain, directory = self._pin_domain(), self.dir_edit.text().strip()
        new = ytdlp_config.to_config_path(directory)
        old = self.rules.get(domain, {}).get("--paths")
        if old and old != new:
            answer = QMessageBox.question(
                self, app.APP_TITLE,
                f"Replace the download folder for {domain}?\n\n"
                f"{ytdlp_config.to_display_path(str(old))}\n→ {directory}")
            if answer != QMessageBox.StandardButton.Yes:
                return
        rules = dict(self.rules)
        rules[domain] = {**rules.get(domain, {}), "--paths": new}
        try:
            overrides.save_rules(overrides.rules_path(), rules)
        except OSError as e:
            QMessageBox.warning(self, app.APP_TITLE, overrides.SAVE_ERROR.format(e))
            return
        self._load_rules()
        self._url_changed()

    def start_download(self) -> None:
        url = self.url_edit.text().strip()
        if not url or self._probe:  # Enter while probing; the button is disabled
            return
        if not self.binary_path:
            QMessageBox.warning(self, app.APP_TITLE, "yt-dlp was not found on PATH.")
            return
        # Empty follows the rule or config: no -P if either sets a home path, else Downloads.
        directory = self.dir_edit.text().strip()
        if not (directory or self.config_defaults.sets_directory or self.rule_dir):
            directory = argv.default_download_dir()
        if directory and not os.path.isdir(directory):
            QMessageBox.warning(self, app.APP_TITLE, f"Directory does not exist:\n{directory}")
            return

        cookies = self.cookies_combo.currentData() or None
        # self.rule already matches the URL: _url_changed runs on every edit.
        extra = overrides.rule_argv(self.rule)
        job = DownloadJob(
            self.binary_path, argv.build_argv(url, directory, cookies, extra), url, parent=self)
        self._add_row(job)
        job.state_changed.connect(lambda s, j=job: self._on_state(j, s))
        job.file_named.connect(lambda f, j=job: self._set(j, C_FILE, os.path.basename(f)))
        job.metadata.connect(lambda fields, j=job: self._on_metadata(j, fields))
        job.progress.connect(lambda p, j=job: self._on_progress(j, p))
        job.postprocessing.connect(lambda name, j=job: self._set(j, C_SPEED, name))
        job.done.connect(lambda path, j=job: self._set(j, C_FILE, os.path.basename(path)))
        job.finished.connect(lambda j=job: self._on_finished(j))
        job.start()
        self.url_edit.clear()

    def clear_finished(self) -> None:
        for job in [j for j in self.jobs if j.state.terminal]:
            self._remove(job)

    def _about(self) -> None:
        QMessageBox.about(
            self,
            f"About {app.APP_TITLE}",
            f"{app.APP_TITLE} {VERSION_LABEL}\nA small front end for yt-dlp.\n\n"
            f"yt-dlp: {self.binary_path or 'not found'}",
        )

    # ---- table plumbing ---------------------------------------------------

    def _add_row(self, job: DownloadJob) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.jobs.append(job)
        for col in range(len(COLUMNS)):
            self.table.setItem(row, col, QTableWidgetItem(""))
        self._on_state(job, job.state)
        url = urlparse(job.url)
        self.table.item(row, C_SCHEME).setText(url.scheme)
        self.table.item(row, C_HOST).setText(url.netloc)
        self.table.item(row, C_PATH).setText(url._replace(scheme="", netloc="").geturl())
        self.table.item(row, C_PATH).setToolTip(job.url)

        bar = QProgressBar()
        bar.setRange(0, 0)  # indeterminate until the first progress line
        bar.setTextVisible(True)
        self.table.setCellWidget(row, C_PROG, bar)

        cancel = self._tool_button(SP.SP_BrowserStop, "Cancel", job.cancel)
        self.table.setCellWidget(row, C_ACTION, side_by_side(cancel, stretch=None))

    def _tool_button(self, icon: QStyle.StandardPixmap, tip: str, slot: Callable) -> QToolButton:
        button = QToolButton()
        button.setIcon(self.style().standardIcon(icon))
        button.setToolTip(tip)
        button.setAutoRaise(True)
        button.clicked.connect(slot)
        return button

    def _remove(self, job: DownloadJob) -> None:
        self.table.removeRow(self._row(job))
        self.jobs.remove(job)

    def _row(self, job: DownloadJob) -> int:
        return self.jobs.index(job)

    def _set(self, job: DownloadJob, col: int, text: str) -> None:
        self.table.item(self._row(job), col).setText(text)

    def _on_state(self, job: DownloadJob, state: JobState) -> None:
        self._set(job, C_STATUS, state.value)
        icon = self.style().standardIcon(STATE_ICONS[state])
        self.table.item(self._row(job), C_ICON).setIcon(icon)

    def _on_metadata(self, job: DownloadJob, fields: list[str]) -> None:
        row = self._row(job)
        for col, text in zip(META_COLUMNS, fields):
            self.table.item(row, col).setText(text)

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
        self.table.removeCellWidget(row, C_PROG)
        self.table.item(row, C_SPEED).setText("")
        if job.state is JobState.FAILED:
            self.table.item(row, C_FILE).setText(job.error_text)
            self.table.item(row, C_FILE).setToolTip("\n".join(job.log[-20:]))
        # Clear, and Open once there is a file to open.
        clear = self._tool_button(SP.SP_TrashIcon, "Remove from list", lambda: self._remove(job))
        buttons = [clear]
        if job.state is JobState.FINISHED and (path := job.final_path):
            open_ = self._tool_button(SP.SP_DialogOpenButton, "Open", lambda: open_path(path))
            open_.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            menu = QMenu(open_)
            menu.addAction("Open folder", lambda: open_path(os.path.dirname(path)))
            open_.setMenu(menu)
            buttons.append(open_)
        self.table.setCellWidget(row, C_ACTION, side_by_side(*buttons, stretch=None))

    # ---- lifecycle --------------------------------------------------------

    def closeEvent(self, event) -> None:
        self.settings.setValue(app.KEY_GEOMETRY, self.saveGeometry())
        self.settings.setValue(app.KEY_DIR, self.dir_edit.text().strip())
        self.settings.setValue(app.KEY_COOKIES, self.cookies_combo.currentData())
        self.settings.setValue(HEADER_KEY, self.table.horizontalHeader().saveState())
        if proc := self._probe:
            self._probe = None  # so _probe_done ignores it
            proc.kill()
            proc.waitForFinished(1000)
        for job in self.jobs:
            job.cancel()
        super().closeEvent(event)
