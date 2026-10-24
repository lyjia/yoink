"""Locate the yt-dlp executable and query its version.

Phase 0 looks only at an explicit override and PATH. Downloading a managed
copy is Phase 4.
"""

import logging
import shutil
import subprocess
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


def get_version(binary: Path) -> str | None:
    try:
        out = subprocess.run(
            [str(binary), "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log.warning("Could not run %s --version: %s", binary, e)
        return None
    return out.stdout.strip() or None
