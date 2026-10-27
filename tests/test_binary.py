import sys
from pathlib import Path

import pytest

from yoink.binary import can_self_update, install_method, update_command


@pytest.mark.parametrize(("path", "variant", "method"), [
    ("/opt/homebrew/Cellar/yt-dlp/2026.10.21/libexec/bin/yt-dlp", "pip", "Homebrew"),
    ("/opt/local/bin/yt-dlp", "pip", "MacPorts"),
    ("/home/u/.local/share/pipx/venvs/yt-dlp/bin/yt-dlp", "pip", "pipx"),
    ("/home/u/.local/share/uv/tools/yt-dlp/bin/yt-dlp", "pip", "uv tool"),
    ("/home/u/venv/bin/yt-dlp", "pip", "pip"),
    ("/home/u/bin/yt-dlp", "win_exe", "win_exe"),
    ("/home/u/bin/yt-dlp", "darwin_dir", "darwin_dir"),
    ("/usr/bin/yt-dlp", "debian*", "debian*"),
    ("/usr/bin/yt-dlp", "", "unknown"),
])
def test_install_method(path, variant, method):
    assert install_method(Path(path), variant) == method


@pytest.mark.parametrize(("variant", "expected"), [
    ("zip", True), ("win_exe", True), ("linux_exe", True), ("darwin_exe", True),
    ("pip", False), ("darwin_dir", False), ("win_dir", False), ("debian*", False),
    ("unknown", False),
])
def test_can_self_update(variant, expected):
    assert can_self_update(variant) is expected


PIP = "python" if sys.platform == "win32" else "python3"


@pytest.mark.parametrize(("method", "command"), [
    ("Homebrew", "brew upgrade yt-dlp"),
    ("MacPorts", "sudo port upgrade yt-dlp"),
    ("pipx", "pipx upgrade yt-dlp"),
    ("uv tool", "uv tool upgrade yt-dlp"),
    ("pip", f"{PIP} -m pip install -U yt-dlp"),
    ("win_exe", None),
    ("unknown", None),
])
def test_update_command(method, command):
    assert update_command(method) == command
