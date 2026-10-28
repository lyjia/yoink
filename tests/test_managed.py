import hashlib
import sys

import pytest

from yoink import managed
from yoink.managed import MISMATCH, install_hint, switch, verify


@pytest.fixture
def asset(tmp_path):
    path = tmp_path / "yt-dlp_linux"
    path.write_bytes(b"fake yt-dlp")
    return path


def _sums(name, data=b"fake yt-dlp"):
    return f"{'0' * 64}  other.zip\n{hashlib.sha256(data).hexdigest().upper()}  {name}\n"


def test_verify_pass(asset):
    assert verify(asset, _sums(asset.name)) == ""


def test_verify_mismatch(asset):
    assert verify(asset, _sums(asset.name, b"something else")) == MISMATCH


def test_verify_asset_absent(asset):
    assert asset.name in verify(asset, _sums("yt-dlp.exe"))


def _tree(root, name, marker):
    (root / name).mkdir(parents=True)
    (root / name / "yt-dlp").write_text(marker)


@pytest.mark.parametrize("has_current", [True, False])
def test_switch(tmp_path, has_current):
    _tree(tmp_path, "new", "new")
    if has_current:
        _tree(tmp_path, "current", "old")
    switch(tmp_path)
    assert (tmp_path / "current" / "yt-dlp").read_text() == "new"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["current"]


def test_failure_leaves_current(tmp_path, monkeypatch):
    _tree(tmp_path, "new", "new")
    _tree(tmp_path, "current", "old")
    monkeypatch.setattr(managed.binary, "managed_path", lambda: tmp_path / "current" / "yt-dlp")
    installer, errors = managed.Installer(), []
    installer.finished.connect(errors.append)
    installer._fail("warm-up failed")
    assert errors == ["warm-up failed"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["current"]
    assert (tmp_path / "current" / "yt-dlp").read_text() == "old"


@pytest.mark.parametrize(
    ("platform", "found", "expected"),
    [
        ("darwin", {"brew"}, ("Homebrew", "brew install yt-dlp")),
        ("win32", {"scoop", "choco"}, ("Scoop", "scoop install yt-dlp")),
        ("win32", {"winget", "choco"}, ("winget", "winget install yt-dlp.yt-dlp")),
        ("linux", {"pipx"}, ("pipx", "pipx install yt-dlp")),
        ("linux", set(), None),
    ],
)
def test_install_hint(monkeypatch, platform, found, expected):
    calls = []

    def which(cmd, path=None):
        calls.append(path)
        return f"/bin/{cmd}" if cmd in found else None

    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(managed.shutil, "which", which)
    assert install_hint() == expected
    # Homebrew is looked for where it installs, not on a Finder-launched app's PATH.
    assert all(("/opt/homebrew/bin" in p) if platform == "darwin" else p is None for p in calls)
