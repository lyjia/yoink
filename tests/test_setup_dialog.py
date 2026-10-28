import zipfile

import pytest

from yoink.ui.setup_dialog import compare_folder

FILES = {"yt-dlp_macos": b"exe", "_internal/libssl.dylib": b"ssl"}


@pytest.fixture
def folder(tmp_path):
    root = tmp_path / "yt-dlp_macos"
    for rel, data in FILES.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
    return root


def _zip(tmp_path, files):
    path = tmp_path / "yt-dlp_macos.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for rel, data in files.items():
            zf.writestr(f"yt-dlp_macos/{rel}", data)
    return path


def test_matching(tmp_path, folder):
    assert compare_folder(folder, _zip(tmp_path, FILES)) == ""


def test_differing_file(tmp_path, folder):
    error = compare_folder(folder, _zip(tmp_path, {**FILES, "_internal/libssl.dylib": b"evil"}))
    assert "libssl.dylib" in error


@pytest.mark.parametrize("extra_in", ["zip", "folder"])
def test_missing_file(tmp_path, folder, extra_in):
    files = dict(FILES)
    if extra_in == "zip":
        files["_internal/extra.so"] = b"so"
    else:
        (folder / "_internal" / "extra.so").write_bytes(b"so")
    assert "extra.so" in compare_folder(folder, _zip(tmp_path, files))


def test_not_a_zip(tmp_path, folder):
    (tmp_path / "bad.zip").write_bytes(b"not a zip")
    assert compare_folder(folder, tmp_path / "bad.zip")
