"""Locate the yt-dlp executable and tell how it was installed.

Phase 0 looks only at an explicit override and PATH. Downloading a managed
copy is Phase 4. The version and variant come from the config probe
(ytdlp_config.py). See docs/DESIGN.md sections 6.3 and 6.4.
"""

import shutil
import sys
from pathlib import Path

def find_binary(override: str | None = None) -> Path | None:
    """The configured path, even if nothing is there, else yt-dlp on PATH."""
    if override:
        return Path(override).expanduser()
    found = shutil.which("yt-dlp")
    return Path(found) if found else None


# yt-dlp reports "pip" for all of these; the resolved path tells them apart.
_PIP_METHODS = [("/Cellar/", "Homebrew"), ("/opt/local/", "MacPorts"),
                ("pipx/venvs", "pipx"), ("uv/tools", "uv tool")]
_UPDATE_COMMANDS = {
    "Homebrew": "brew upgrade yt-dlp",
    "MacPorts": "sudo port upgrade yt-dlp",
    "pipx": "pipx upgrade yt-dlp",
    "uv tool": "uv tool upgrade yt-dlp",
    "pip": f"{'python' if sys.platform == 'win32' else 'python3'} -m pip install -U yt-dlp",
}


def install_method(path: Path | None, variant: str) -> str:
    """The variant yt-dlp reports, narrowed down for "pip"; "unknown" if it reported none."""
    if variant != "pip" or path is None:
        return variant or "unknown"
    resolved = path.resolve().as_posix()
    return next((method for part, method in _PIP_METHODS if part in resolved), "pip")


def can_self_update(variant: str) -> bool:
    """Whether `yt-dlp -U` can update this build."""
    return variant == "zip" or variant.endswith("_exe")


def update_command(method: str) -> str | None:
    """The command that updates a package-manager install, for the user to run."""
    return _UPDATE_COMMANDS.get(method)
