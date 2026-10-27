"""Locate the yt-dlp executable.

Phase 0 looks only at an explicit override and PATH. Downloading a managed
copy is Phase 4. The version comes from the config probe (ytdlp_config.py).
"""

import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)


def find_binary(override: str | None = None) -> Path | None:
    if override:
        p = Path(override).expanduser()
        if p.is_file():
            return p
        log.warning("Configured yt-dlp path does not exist: %s", p)
    found = shutil.which("yt-dlp")
    return Path(found) if found else None
