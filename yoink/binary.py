"""Locate the yt-dlp executable and tell how it was installed.

Discovery checks the override, Yoink's managed copy, PATH, then well-known
directories, and spots a copy that macOS quarantine blocks. The version and
variant come from the config probe (ytdlp_config.py). See docs/PHASE4.md
section 1 and docs/DESIGN.md sections 6.2 to 6.6.
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths

log = logging.getLogger(__name__)

_EXECUTABLE = {"darwin": "yt-dlp_macos/yt-dlp_macos", "win32": "yt-dlp.exe"}
# Finder-launched apps get launchd's PATH, which lacks these (DESIGN.md 6.2).
_WELL_KNOWN = {
    "darwin": ["/opt/homebrew/bin", "/usr/local/bin", "/opt/local/bin", "~/.local/bin"],
    "win32": [r"%LOCALAPPDATA%\Microsoft\WinGet\Links", r"%USERPROFILE%\scoop\shims",
              r"%ChocolateyInstall%\bin"],
    "linux": ["/usr/local/bin", "~/.local/bin"],
}


def managed_path() -> Path:
    """Where Yoink's own copy of yt-dlp lives, whether or not it is there."""
    # Same branch as overrides.rules_path().
    if d := os.environ.get("YOINK_SETTINGS_DIR"):
        app_data = Path(d)
    else:
        loc = QStandardPaths.StandardLocation.AppDataLocation
        app_data = Path(QStandardPaths.writableLocation(loc))
    return app_data / "yt-dlp" / "current" / _EXECUTABLE.get(sys.platform, "yt-dlp_linux")


def find_binary(override: str | None = None) -> Path | None:
    """The configured path, even if nothing is there, else the first copy found."""
    if override:
        return Path(override).expanduser()
    if managed_path().is_file():
        return managed_path()
    dirs = (os.path.expandvars(os.path.expanduser(d))
            for d in _WELL_KNOWN.get(sys.platform, _WELL_KNOWN["linux"]))
    found = shutil.which("yt-dlp") or shutil.which(
        "yt-dlp", path=os.pathsep.join(d for d in dirs if os.path.isdir(d)))
    return Path(found) if found else None


def is_managed(path: Path | None) -> bool:
    return path == managed_path()


def install_root(path: Path) -> Path:
    """The folder build's folder (the one with `_internal/`), else the single-file binary itself."""
    return path.parent if (path.parent / "_internal").is_dir() else path


def is_quarantined(path: Path) -> bool:
    """Whether anything in the binary's install root (see install_root) has macOS quarantine."""
    if sys.platform != "darwin":
        return False
    root = install_root(path)
    try:
        out = subprocess.run(["xattr", "-lr", str(root)], capture_output=True, text=True,
                             errors="replace", timeout=10, check=True).stdout
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Couldn't check %s for quarantine: %s", root, e)
        return False
    return "com.apple.quarantine" in out


def is_blocked(exited: bool, output: str, path: Path | None) -> bool:
    """Whether a probe that crashed or timed out (`exited` False) with no output was Gatekeeper
    killing a quarantined binary (DESIGN.md 6.6)."""
    return not exited and not output.strip() and path is not None and is_quarantined(path)


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
