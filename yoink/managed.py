"""Yoink's own copy of yt-dlp: download, verify, warm up, and switch to it.

The copy lives in `<appdata>/yt-dlp/current/`; an install builds `new/` beside
it and renames. See docs/PHASE4.md section 2 and docs/DESIGN.md 6.5 and 6.6.
"""

import hashlib
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from yoink import binary, ytdlp_config

RELEASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"  # tests may point it elsewhere
ASSET = {"darwin": "yt-dlp_macos.zip", "win32": "yt-dlp.exe", "linux": "yt-dlp_linux"}
SUMS = "SHA2-256SUMS"
WARMUP_TIMEOUT_MS = 20_000  # as the config probe
MISMATCH = "The download didn't match the published checksum."

_HINTS = {
    "darwin": [("Homebrew", "brew install yt-dlp")],
    "win32": [("winget", "winget install yt-dlp.yt-dlp"), ("Scoop", "scoop install yt-dlp"),
              ("Chocolatey", "choco install yt-dlp")],
    "linux": [("pipx", "pipx install yt-dlp")],
}
# A Finder-launched app's PATH has no Homebrew (DESIGN.md 6.2), so look where brew installs.
_BREW_PATH = os.pathsep.join(["/opt/homebrew/bin", "/usr/local/bin"])


def verify(asset: Path, sums_text: str, name: str = "") -> str:
    """"" if `asset` matches the `SHA2-256SUMS` line for `name` (default: its own file name),
    else the reason it doesn't."""
    name = name or asset.name
    for line in sums_text.splitlines():
        digest, _, entry = line.strip().partition(" ")
        if entry.strip().lstrip("*") == name:
            with asset.open("rb") as f:
                actual = hashlib.file_digest(f, "sha256").hexdigest()
            return "" if actual == digest.lower() else MISMATCH
    return f"{SUMS} has no entry for {name}."


def switch(root: Path) -> None:
    """Replace `root/current/` with `root/new/`; `current/` may be missing."""
    current, old = root / "current", root / "old"
    shutil.rmtree(old, ignore_errors=True)  # left by an interrupted switch
    if current.exists():
        current.rename(old)
    (root / "new").rename(current)
    shutil.rmtree(old, ignore_errors=True)


def install_hint() -> tuple[str, str] | None:
    """(label, command) for the first package manager found on this platform, else None."""
    path = _BREW_PATH if sys.platform == "darwin" else None
    for label, command in _HINTS.get(sys.platform, _HINTS["linux"]):
        if shutil.which(command.split()[0], path=path):
            return label, command
    return None


class Installer(QObject):
    """Install the latest release as the managed copy; `finished` carries "" or the error.

    Every step but the last works in `new/`, so a failure leaves `current/` alone."""

    progress = Signal(int, int)
    status = Signal(str)
    finished = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._net = QNetworkAccessManager(self)
        exe = binary.managed_path()
        current = next(p for p in exe.parents if p.name == "current")
        self._root, self._new = current.parent, current.parent / "new"
        self._exe = self._new / exe.relative_to(current)
        self._asset = self._new / ASSET.get(sys.platform, ASSET["linux"])

    def start(self) -> None:
        def prepare() -> None:
            shutil.rmtree(self._new, ignore_errors=True)
            self._new.mkdir(parents=True)
            self._download(SUMS, lambda: self._download(self._asset.name, self._unpack))
        self._step(prepare)

    def _step(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except (OSError, subprocess.CalledProcessError) as e:
            self._fail(getattr(e, "stderr", None) or str(e))

    def _fail(self, error: str) -> None:
        shutil.rmtree(self._new, ignore_errors=True)
        self.finished.emit(error)

    def _download(self, name: str, then: Callable[[], None]) -> None:
        self.status.emit(f"Downloading {name}…")
        request = QNetworkRequest(QUrl(RELEASE + name))
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        f = (self._new / name).open("wb")
        reply = self._net.get(request)
        reply.readyRead.connect(lambda: f.write(reply.readAll().data()))
        reply.downloadProgress.connect(lambda received, total: self.progress.emit(received, total))
        reply.finished.connect(lambda: self._downloaded(reply, f, then))

    def _downloaded(self, reply: QNetworkReply, f, then: Callable[[], None]) -> None:
        f.write(reply.readAll().data())
        f.close()
        reply.deleteLater()
        code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if reply.error() != QNetworkReply.NetworkError.NoError or code != 200:
            self._fail(reply.errorString())
        else:
            self._step(then)

    def _unpack(self) -> None:
        sums = self._new / SUMS
        if error := verify(self._asset, sums.read_text(encoding="utf-8")):
            return self._fail(error)
        sums.unlink()
        if sys.platform == "darwin":
            # ditto keeps the folder build's permission bits and symlinks; zipfile does not.
            subprocess.run(["ditto", "-x", "-k", self._asset, self._new],
                           check=True, capture_output=True, text=True)
            self._asset.unlink()
        elif sys.platform != "win32":
            self._exe.chmod(0o755)
        self._warm_up()

    def _warm_up(self) -> None:
        """Run the new copy once, as the probe does, so a broken download never replaces a working one."""
        self.status.emit("Preparing yt-dlp…")
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        proc.finished.connect(lambda _, st: self._warmed(proc, st == QProcess.ExitStatus.NormalExit))
        proc.errorOccurred.connect(
            lambda e: e == QProcess.ProcessError.FailedToStart and self._warmed(proc, False))
        proc.start(str(self._exe), ytdlp_config.PROBE_ARGS)
        proc.closeWriteChannel()
        QTimer.singleShot(WARMUP_TIMEOUT_MS, proc, proc.kill)

    def _warmed(self, proc: QProcess, exited: bool) -> None:
        proc.deleteLater()
        text = ytdlp_config.decode_output(bytes(proc.readAll().data())).strip()
        # With no URL yt-dlp exits 2 after the header, so the header is the test, not the exit code.
        if not (exited and ytdlp_config.parse_version(text)):
            return self._fail(text or proc.errorString())
        self._step(self._switch)

    def _switch(self) -> None:
        switch(self._root)
        self.finished.emit("")
