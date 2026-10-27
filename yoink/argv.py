"""Build the yt-dlp command line for one download.

The order is deliberate: yt-dlp applies its config file first, then the
command line left to right, so anything Yoink must control goes last.
See docs/DESIGN.md sections 2.2 and 2.3.
"""

import os

from PySide6.QtCore import QStandardPaths

# Every protocol line Yoink emits through yt-dlp starts with this token
# followed by a tab. Fields are tab separated; absent values print as "NA".
TOKEN = "YOINK"

_DL_TEMPLATE = "\t".join(
    [
        f"download:{TOKEN}",
        "DL",
        "%(progress.status)s",
        "%(progress.downloaded_bytes)s",
        "%(progress.total_bytes)s",
        "%(progress.total_bytes_estimate)s",
        "%(progress.speed)s",
        "%(progress.eta)s",
    ]
)
_PP_TEMPLATE = "\t".join(
    [
        f"postprocess:{TOKEN}",
        "PP",
        "%(progress.status)s",
        "%(progress.postprocessor)s",
    ]
)
_PRINT_FILE = f"before_dl:{TOKEN}\tFILE\t%(filename)s"
_PRINT_DONE = f"after_move:{TOKEN}\tDONE\t%(filepath)s"


def default_download_dir() -> str:
    # Native separators: Qt returns forward slashes on Windows.
    return os.path.normpath(
        QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation))


def build_argv(url: str, directory: str | None = None, cookies: str | None = None) -> list[str]:
    """Return the argument list (without the binary) for downloading `url`.

    `None` (or an empty directory) passes nothing for that setting, so the
    yt-dlp config decides. A directory is passed as `-P`. `cookies="none"`
    passes `--no-cookies-from-browser`; any other value is a browser name for
    `--cookies-from-browser`. Falling back to the Downloads folder when the
    config sets no home path is the caller's job.
    """
    args: list[str] = []
    if directory:
        args += ["-P", directory]
    if cookies == "none":
        args += ["--no-cookies-from-browser"]
    elif cookies:
        args += ["--cookies-from-browser", cookies]
    args += [
        # --print implies --simulate; undo that.
        "--no-simulate",
        # Keep progress lines even if the user's config says --quiet.
        "--progress",
        "--newline",
        "--quiet",
        "--progress-template", _DL_TEMPLATE,
        "--progress-template", _PP_TEMPLATE,
        "--print", _PRINT_FILE,
        "--print", _PRINT_DONE,
        "--",
        url,
    ]
    return args
