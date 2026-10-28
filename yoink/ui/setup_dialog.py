"""Set up yt-dlp: get a working copy when there is none, or it doesn't run, or macOS blocks it.

The dialog never runs the probe: it emits `check_requested`, and the main window answers
with `show_result`. See docs/PHASE4.md sections 3 and 4 and docs/DESIGN.md 6.6 and 6.7.
"""

import hashlib
import subprocess
import zipfile
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from yoink import binary, managed
from yoink.ui.options_form import side_by_side

TITLE = "Set up yt-dlp"
NOT_FOUND = "Yoink needs yt-dlp to download videos, and couldn't find it."
QUARANTINED = "Yoink found yt-dlp at {}, but macOS blocks programs downloaded in a browser."
FAILED = "Yoink found yt-dlp at {}, but it didn't run."
WORKING = "yt-dlp {} ({}) is working."
DOWNLOAD = "Download yt-dlp for me"
DOWNLOAD_TIP = "Yoink downloads yt-dlp from its GitHub releases, checks it, and keeps its own copy."
DOWNLOAD_FAILED = "The download didn't work: {}"
THEN_CHECK = "then click Check again."
# Repair verification (PHASE4.md section 4).
BLOCKED = "macOS blocks this copy. Yoink only unblocks a copy it can verify."
CHECKING = "Checking this copy against yt-dlp's published checksums…"
CANT_VERIFY = "Yoink can't verify this copy, so it recommends {}. {}"
NO_ZIP = "To verify it, choose the zip you downloaded."
SUMS_FAILED = "Yoink couldn't download yt-dlp's checksums: {}"
MATCHES = "This copy matches yt-dlp."
CHOOSE_ZIP = "Choose the zip you downloaded…"
ALLOW = "Allow this copy"
ALLOW_QUESTION = "Remove the macOS quarantine flag from {}?\n\nmacOS will then run it without asking."
ALLOW_FAILED = "Yoink couldn't unblock this copy: {}"
SINGLE_FILE = "yt-dlp_macos"  # the single-file asset's name in SHA2-256SUMS


def _is_link(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def _sha256(f) -> bytes:
    return hashlib.file_digest(f, "sha256").digest()


def compare_folder(folder: Path, zip_path: Path) -> str:
    """"" if the regular files under `folder` and in the zip are the same, else the first
    difference. The zip's one top-level folder, if it has one, stands for `folder`."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            entries = {i.filename: i for i in zf.infolist() if not (i.is_dir() or _is_link(i))}
            tops = {name.partition("/")[0] for name in entries}
            if len(tops) == 1 and all("/" in name for name in entries):
                entries = {name.partition("/")[2]: i for name, i in entries.items()}
            files = {p.relative_to(folder).as_posix(): p for p in folder.rglob("*")
                     if p.is_file() and not p.is_symlink() and p.name != ".DS_Store"}
            for rel in sorted(entries.keys() | files.keys()):
                if rel not in files:
                    return f"{rel} is missing from {folder}."
                if rel not in entries:
                    return f"{rel} isn't in {zip_path.name}."
                with zf.open(entries[rel]) as a, files[rel].open("rb") as b:
                    if _sha256(a) != _sha256(b):
                        return f"{rel} differs from the copy in {zip_path.name}."
    except (OSError, zipfile.BadZipFile) as e:
        return str(e)
    return ""


class SetupDialog(QDialog):
    check_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.setModal(True)
        self._found: Path | None = None
        self._zip: Path | None = None
        self._sums: str | None = None  # SHA2-256SUMS, once fetched
        self._sums_error = ""
        self._sums_reply: QNetworkReply | None = None
        self._verified = False
        self._net = QNetworkAccessManager(self)
        layout = QVBoxLayout(self)

        self.message = QLabel(wordWrap=True)
        self.output = QPlainTextEdit(readOnly=True)

        self.repair_icon = QLabel()
        self.repair_text = QLabel(wordWrap=True)
        self.choose_zip = QPushButton(CHOOSE_ZIP)
        self.choose_zip.clicked.connect(self._choose_zip)
        self.allow = QPushButton(ALLOW)
        self.allow.clicked.connect(self._allow)
        self.repair = QWidget()
        repair = QVBoxLayout(self.repair)
        repair.setContentsMargins(0, 0, 0, 0)
        repair.addWidget(side_by_side(self.repair_icon, self.repair_text, stretch=1))
        repair.addWidget(side_by_side(self.choose_zip, self.allow, stretch=None))

        self.download = QPushButton(DOWNLOAD)
        self.download.setToolTip(DOWNLOAD_TIP)
        self.download.setDefault(True)
        self.download.clicked.connect(self._download)
        self.check = QPushButton("Check again")
        self.check.clicked.connect(self.check_requested)
        self.hint = QPushButton()
        self.hint_row = QWidget()
        if hint := managed.install_hint():
            self.hint.setText(f"I use {hint[0]}")
            copy = QPushButton("Copy")
            copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(hint[1]))
            self.hint_row = side_by_side(QLineEdit(hint[1], readOnly=True), copy, QLabel(THEN_CHECK))
            self.hint.clicked.connect(lambda: self.hint_row.setVisible(True))
        self.options = side_by_side(self.download, self.hint, self.check, stretch=None)
        self.hint.setVisible(hint is not None)
        self.hint_row.setVisible(False)

        self.progress = QProgressBar()
        self.status = QLabel()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        for w in (self.message, self.output, self.repair, self.options, self.hint_row,
                  self.progress, self.status, buttons):
            layout.addWidget(w)
        self._show_progress(False)
        self.setMinimumWidth(560)

    def show_result(self, found: Path | None, version: str, method: str, output: str) -> None:
        """Show the probe's result for `found`: working if it reported a version."""
        file = found if found is not None and found.is_file() else None
        quarantined = not version and file is not None and binary.is_quarantined(file)
        failed = not version and file is not None and not quarantined
        if version:
            self.message.setText(WORKING.format(version, method))
        elif file is None:
            self.message.setText(NOT_FOUND)
        else:
            self.message.setText((QUARANTINED if quarantined else FAILED).format(found))
        self.output.setPlainText(output)
        self.output.setVisible(failed and bool(output.strip()))
        self.options.setVisible(not version)
        if version:
            self.hint_row.hide()
        if found != self._found:
            self._zip = None
        self._found = found
        self.repair.setVisible(quarantined)
        if quarantined:
            self.choose_zip.setVisible(self._folder_build)
            self._fetch_sums()
            self._check_copy()
        self._fit()

    def _fit(self) -> None:
        """Grow or shrink to the current state; wrapped labels need the layout settled first."""
        self.layout().activate()
        self.resize(self.width(), self.sizeHint().height())

    # ---- download ---------------------------------------------------------

    def _download(self) -> None:
        self._set_busy(True)
        self._show_progress(True)
        installer = managed.Installer(self)
        installer.progress.connect(self._progress)
        installer.status.connect(self.status.setText)
        installer.finished.connect(lambda error: self._installed(installer, error))
        installer.start()

    def _progress(self, received: int, total: int) -> None:
        self.progress.setRange(0, max(total, 0))  # (0, 0) is indeterminate
        self.progress.setValue(received)

    def _installed(self, installer: managed.Installer, error: str) -> None:
        installer.deleteLater()
        self._set_busy(False)
        self._show_progress(False)
        if error:
            self.message.setText(DOWNLOAD_FAILED.format(error))
        else:
            self.check_requested.emit()

    def _set_busy(self, busy: bool) -> None:
        for w in (self.download, self.hint, self.check, self.choose_zip):
            w.setEnabled(not busy)
        self.allow.setEnabled(self._verified and not busy)

    def _show_progress(self, on: bool) -> None:
        self.progress.setVisible(on)
        self.status.setVisible(on)
        self.progress.setRange(0, 0)

    # ---- repair (macOS) ---------------------------------------------------

    @property
    def _folder_build(self) -> bool:
        return self._found is not None and binary.install_root(self._found) != self._found

    def _fetch_sums(self) -> None:
        """Fetch the checksums unless they are here or on the way; a failed fetch is retried."""
        if self._sums_reply or (self._sums is not None and not self._sums_error):
            return
        self._sums, self._sums_error = None, ""
        self._sums_reply = reply = self._net.get(QNetworkRequest(QUrl(managed.RELEASE + managed.SUMS)))
        reply.finished.connect(lambda: self._sums_fetched(reply))

    def _sums_fetched(self, reply: QNetworkReply) -> None:
        reply.deleteLater()
        self._sums_reply = None
        self._sums = bytes(reply.readAll().data()).decode("utf-8", "replace")
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._sums_error = SUMS_FAILED.format(reply.errorString())
        if not self.repair.isHidden():  # still showing a quarantined copy
            self._check_copy()

    def _verification_error(self) -> str:
        assert self._found is not None and self._sums is not None
        if self._sums_error:
            return self._sums_error
        if not self._folder_build:
            return managed.verify(self._found, self._sums, SINGLE_FILE)
        if not self._zip:
            return NO_ZIP
        return (managed.verify(self._zip, self._sums, managed.ASSET["darwin"])
                or compare_folder(self._found.parent, self._zip))

    def _check_copy(self) -> None:
        """Verify the quarantined copy once the checksums are here, and say how it went."""
        error = self._verification_error() if self._sums is not None else ""
        self._verified = self._sums is not None and not error
        if self._sums is None:
            text = f"{BLOCKED} {CHECKING}"
        else:
            text = MATCHES if self._verified else f"{BLOCKED} {CANT_VERIFY.format(DOWNLOAD, error)}"
        sp = QStyle.StandardPixmap
        icon = sp.SP_DialogApplyButton if self._verified else sp.SP_MessageBoxCritical
        self.repair_icon.setPixmap(self.style().standardIcon(icon).pixmap(32, 32))
        self.repair_text.setText(text)
        self.allow.setEnabled(self._verified)
        self._fit()

    def _choose_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, CHOOSE_ZIP.rstrip("…"), str(Path.home() / "Downloads"), "Zip files (*.zip)")
        if path:
            self._zip = Path(path)
            self._check_copy()

    def _allow(self) -> None:
        assert self._found is not None
        target = binary.install_root(self._found)
        answer = QMessageBox.question(self, TITLE, ALLOW_QUESTION.format(target))
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(target)],
                           check=True, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            self.message.setText(ALLOW_FAILED.format(getattr(e, "stderr", None) or e))
            return
        self.check_requested.emit()
