"""One yt-dlp child process per download, wrapped in a QObject.

Protocol lines (see argv.py) are tab separated and begin with the token.
Download progress arrives on stdout; postprocessor progress arrives on
stderr. Everything that is not a protocol line is kept in `log`.
"""

import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from yoink.argv import TOKEN, default_download_dir

log = logging.getLogger(__name__)

_PREFIX = TOKEN + "\t"


class JobState(Enum):
    QUEUED = "Queued"
    STARTING = "Starting"
    DOWNLOADING = "Downloading"
    POSTPROCESSING = "Processing"
    FINISHED = "Finished"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

    @property
    def terminal(self) -> bool:
        return self in (JobState.FINISHED, JobState.FAILED, JobState.CANCELLED)


@dataclass(frozen=True)
class Progress:
    status: str
    downloaded: int | None
    total: int | None
    speed: float | None
    eta: int | None

    @property
    def percent(self) -> int | None:
        if self.downloaded is None or not self.total:
            return None
        return max(0, min(100, int(100 * self.downloaded / self.total)))


def _opt_int(s: str) -> int | None:
    try:
        return int(float(s))
    except ValueError:
        return None


def _opt_float(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


class DownloadJob(QObject):
    state_changed = Signal(object)  # JobState
    file_named = Signal(str)  # filename as yt-dlp will write it
    progress = Signal(object)  # Progress
    postprocessing = Signal(str)  # postprocessor name
    done = Signal(str)  # final file path
    finished = Signal()  # terminal state reached, any outcome

    def __init__(self, binary: Path, argv: list[str], url: str, parent: QObject | None = None):
        super().__init__(parent)
        self.binary = binary
        self.argv = argv
        self.url = url
        self.state = JobState.QUEUED
        self.log: list[str] = []
        self.error_text = ""
        self.final_path: str | None = None
        self._buf = {"out": "", "err": ""}
        self._cancel_requested = False

        self._proc = QProcess(self)
        # A config with only `-P temp:...` would otherwise download into
        # whatever directory Yoink was launched from.
        self._proc.setWorkingDirectory(default_download_dir())
        self._proc.readyReadStandardOutput.connect(self._read_stdout)
        self._proc.readyReadStandardError.connect(self._read_stderr)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_proc_error)

    # ---- public -----------------------------------------------------------

    def start(self) -> None:
        self._set_state(JobState.STARTING)
        log.info("Starting: %s %s", self.binary, " ".join(self.argv))
        self._proc.start(str(self.binary), self.argv)

    def cancel(self) -> None:
        if self.state.terminal:
            return
        self._cancel_requested = True
        if self._proc.state() == QProcess.ProcessState.NotRunning:
            self._set_state(JobState.CANCELLED)
            self.finished.emit()
            return
        # Ask nicely first so yt-dlp can clean up part files; escalate if it
        # does not exit promptly.
        self._proc.terminate()
        if not self._proc.waitForFinished(3000):
            self._proc.kill()

    # ---- internals --------------------------------------------------------

    def _set_state(self, state: JobState) -> None:
        if state is self.state:
            return
        self.state = state
        self.state_changed.emit(state)

    def _read_stdout(self) -> None:
        data = bytes(self._proc.readAllStandardOutput()).decode("utf-8", "replace")
        self._feed("out", data)

    def _read_stderr(self) -> None:
        data = bytes(self._proc.readAllStandardError()).decode("utf-8", "replace")
        self._feed("err", data)

    def _feed(self, channel: str, data: str) -> None:
        self._buf[channel] += data
        *lines, rest = self._buf[channel].split("\n")
        self._buf[channel] = rest
        for line in lines:
            self._handle_line(line.rstrip("\r"))

    def _handle_line(self, line: str) -> None:
        if not line.startswith(_PREFIX):
            if line:
                self.log.append(line)
            return
        fields = line.split("\t")
        kind = fields[1] if len(fields) > 1 else ""
        try:
            if kind == "FILE":
                self.file_named.emit(fields[2])
            elif kind == "DL":
                self._handle_dl(fields)
            elif kind == "PP":
                self._set_state(JobState.POSTPROCESSING)
                self.postprocessing.emit(fields[3])
            elif kind == "DONE":
                self.final_path = fields[2]
                self.done.emit(fields[2])
            else:
                self.log.append(line)
        except IndexError:
            self.log.append(line)

    def _handle_dl(self, f: list[str]) -> None:
        status = f[2]
        total = _opt_int(f[4])
        if total is None:
            total = _opt_int(f[5])
        p = Progress(
            status=status,
            downloaded=_opt_int(f[3]),
            total=total,
            speed=_opt_float(f[6]),
            eta=_opt_int(f[7]),
        )
        if status == "downloading":
            self._set_state(JobState.DOWNLOADING)
        self.progress.emit(p)

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        # Flush any partial trailing line.
        for ch in ("out", "err"):
            if self._buf[ch]:
                self._handle_line(self._buf[ch])
                self._buf[ch] = ""

        if self._cancel_requested:
            self._set_state(JobState.CANCELLED)
        elif exit_status == QProcess.ExitStatus.NormalExit and exit_code == 0:
            self._set_state(JobState.FINISHED)
        else:
            self.error_text = self._last_error_line() or f"yt-dlp exited with code {exit_code}"
            self._set_state(JobState.FAILED)
        self.finished.emit()

    def _on_proc_error(self, err: QProcess.ProcessError) -> None:
        if err == QProcess.ProcessError.FailedToStart:
            self.error_text = f"Could not start {self.binary}"
            self._set_state(JobState.FAILED)
            self.finished.emit()

    def _last_error_line(self) -> str:
        for line in reversed(self.log):
            if line.startswith("ERROR:"):
                return line[len("ERROR:"):].strip()
        return self.log[-1] if self.log else ""
