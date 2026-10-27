import pytest

from yoink.argv import build_argv

URL = "https://example.com/watch?v=1"

COOKIE_FLAGS = ["--cookies-from-browser", "--no-cookies-from-browser"]


@pytest.mark.parametrize("directory", [None, "", "/tmp/out"])
@pytest.mark.parametrize(
    ("cookies", "expected"),
    [
        (None, []),
        ("none", ["--no-cookies-from-browser"]),
        ("chrome", ["--cookies-from-browser", "chrome"]),
    ],
)
def test_overrides_precede_fixed_flags(directory, cookies, expected):
    args = build_argv(URL, directory, cookies)
    want_dir = ["-P", directory] if directory else []
    # Overrides come first, in order, and the fixed flags start right after.
    head = want_dir + expected
    assert args[: len(head)] == head
    assert args[len(head)] == "--no-simulate"
    # Nothing is passed twice or anywhere else.
    assert args.count("-P") == len(want_dir) // 2
    for flag in COOKIE_FLAGS:
        assert args.count(flag) == expected.count(flag)


def test_quiet_kept():
    assert "--quiet" in build_argv(URL)


@pytest.mark.parametrize("url", [URL, "-P/etc", "--exec=rm -rf ~"])
def test_url_last_after_separator(url):
    args = build_argv(url, "/tmp/out", "chrome")
    assert args[-2:] == ["--", url]
    assert args.count("--") == 1
