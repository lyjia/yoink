import os
import subprocess
import sys
from pathlib import Path

import pytest

from yoink import binary
from yoink.binary import (can_self_update, candidates, find_binary, install_method, is_blocked,
                          is_managed, is_quarantined, managed_path, update_command)

EXE = "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp"


def _make_exe(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    path.chmod(0o755)
    return path


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    """An empty settings dir, PATH, and well-known directory; returns the last two."""
    monkeypatch.chdir(tmp_path)  # Windows `which` also looks in the current directory
    monkeypatch.setenv("YOINK_SETTINGS_DIR", str(tmp_path / "settings"))
    on_path, well_known = tmp_path / "path", tmp_path / "well-known"
    on_path.mkdir()
    well_known.mkdir()
    monkeypatch.setenv("PATH", str(on_path))
    monkeypatch.setitem(binary._WELL_KNOWN, sys.platform, [str(tmp_path / "missing"), str(well_known)])
    return on_path, well_known


def test_find_binary_override_first(dirs):
    _make_exe(managed_path())
    assert find_binary("~/yt-dlp") == Path("~/yt-dlp").expanduser()


def test_find_binary_managed_before_path(dirs):
    _make_exe(dirs[0] / EXE)
    managed = _make_exe(managed_path())
    assert find_binary() == managed
    assert is_managed(find_binary())


def test_find_binary_path_before_well_known(dirs):
    on_path, _ = (_make_exe(d / EXE) for d in dirs)
    assert find_binary() == on_path
    assert not is_managed(find_binary())


def test_find_binary_well_known(dirs):
    well_known = _make_exe(dirs[1] / EXE)
    assert find_binary() == well_known


def test_find_binary_none(dirs):
    assert find_binary() is None


def test_candidates_order(dirs):
    on_path, well_known = (_make_exe(d / EXE) for d in dirs)
    managed = _make_exe(managed_path())
    assert candidates() == [managed, on_path, well_known]


def test_candidates_without_duplicates(dirs, monkeypatch):
    on_path = _make_exe(dirs[0] / EXE)
    monkeypatch.setenv("PATH", os.pathsep.join([str(dirs[0]), str(dirs[0]) + os.sep]))
    assert candidates() == [on_path]


def test_candidates_none(dirs):
    assert candidates() == []


@pytest.mark.parametrize(("exited", "output", "quarantined", "blocked"), [
    (False, "", True, True),  # crashed or timed out
    (False, " \n", True, True),
    (True, "", True, False),
    (False, "[debug] yt-dlp version 2026.10.21", True, False),
    (False, "", False, False),
])
def test_is_blocked(monkeypatch, exited, output, quarantined, blocked):
    monkeypatch.setattr(binary, "is_quarantined", lambda path: quarantined)
    assert is_blocked(exited, output, Path("/bin/yt-dlp")) is blocked


def test_is_blocked_without_path():
    assert is_blocked(False, "", None) is False


def _xattr(stdout="", error=None):
    def run(args, **kwargs):
        if error:
            raise error
        return subprocess.CompletedProcess(args, 0, stdout=stdout)
    return run


@pytest.mark.parametrize(("platform", "run", "quarantined"), [
    ("darwin", _xattr("_internal/libssl.dylib: com.apple.quarantine: 0081;6720;Safari;"), True),
    ("darwin", _xattr("yt-dlp_macos: com.apple.provenance:"), False),
    ("darwin", _xattr(error=FileNotFoundError("xattr")), False),
    ("darwin", _xattr(error=subprocess.TimeoutExpired("xattr", 10)), False),
    ("darwin", _xattr(error=subprocess.CalledProcessError(1, "xattr")), False),
    ("win32", _xattr("com.apple.quarantine"), False),
])
def test_is_quarantined(monkeypatch, platform, run, quarantined):
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(sys, "platform", platform)
    assert is_quarantined(Path("/Applications/yt-dlp_macos/yt-dlp_macos")) is quarantined


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
