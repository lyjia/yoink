"""Application-wide constants, settings keys, and logging setup."""

import logging
import os
from pathlib import Path

from PySide6.QtCore import QSettings

ORG_NAME = "Lyjia"
APP_NAME = "Yoink"
APP_TITLE = "Yoink!"

# QSettings keys. Only front-end state lives here; anything yt-dlp has a flag
# for belongs in yt-dlp's own config file (see docs/DESIGN.md, principle 1).
KEY_DIR = "main/dir"  # override path; empty follows the config
KEY_COOKIES = "main/cookies"  # empty follows the config, "none", or a browser
KEY_GEOMETRY = "main/geometry"
KEY_HEADER = "main/header"  # prefix; see main_window.HEADER_KEY
KEY_BINARY_PATH = "ytdlp/binary_path"
_KEY_LAST_DIR = "main/last_dir"  # Phase 0's name for KEY_DIR


def settings() -> QSettings:
    # On macOS QSettings ignores $HOME, so the sandbox redirects it here.
    if d := os.environ.get("YOINK_SETTINGS_DIR"):
        return QSettings(str(Path(d) / "yoink.ini"), QSettings.Format.IniFormat)
    return QSettings(ORG_NAME, APP_NAME)


def migrate_settings(s: QSettings) -> None:
    """Carry Phase 0's directory over to KEY_DIR, once."""
    if s.contains(_KEY_LAST_DIR):
        if not s.contains(KEY_DIR):
            s.setValue(KEY_DIR, s.value(_KEY_LAST_DIR))
        s.remove(_KEY_LAST_DIR)


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
