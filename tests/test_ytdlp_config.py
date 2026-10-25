import pytest

from yoink.ytdlp_config import (
    COOKIES,
    DIRECTORY,
    LoadedConfig,
    Occurrence,
    config_values,
    find_conflicts,
    parse_probe,
    shared_value,
)

SAMPLE = """\
[debug] Command-line config: ['-v', '--no-update', '--no-cookies-from-browser']
[debug] User config "/Users/u/.config/yt-dlp/config": ['--cookies-from-browser', 'firefox', \
'--config-locations', '/Users/u/extra.conf', '-P', '/tmp/a']
[debug] | Config "/Users/u/extra.conf": ['-P', '/tmp/b']
[debug] Encodings: locale UTF-8, fs utf-8, pref UTF-8, out utf-8, error utf-8, screen utf-8
WARNING: Your yt-dlp version (2026.03.17) is older than 90 days!
Usage: yt-dlp [OPTIONS] URL [URL...]

yt-dlp: error: You must provide at least one URL.
Type yt-dlp --help to see a list of all options.
"""
CMDLINE = "[debug] Command-line config: ['-v']\n"


def cfg(*tokens: str, path: str = "/c", label: str = "User") -> LoadedConfig:
    return LoadedConfig(label, path, list(tokens), 0)


def test_parse_sample():
    assert parse_probe(SAMPLE) == [
        LoadedConfig(
            "User",
            "/Users/u/.config/yt-dlp/config",
            ["--cookies-from-browser", "firefox", "--config-locations", "/Users/u/extra.conf",
             "-P", "/tmp/a"],
            0,
        ),
        LoadedConfig("Included", "/Users/u/extra.conf", ["-P", "/tmp/b"], 1),
    ]


@pytest.mark.parametrize("path", [
    "/Users/u/My Configs/yt-dlp.conf",
    "/home/jürgen/設定/yt-dlp.conf",
    'C:\\Users\\u\\odd": [name].conf',
])
def test_parse_paths(path):
    probe = CMDLINE + f"[debug] System config \"{path}\": ['-P', '/x y']\n"
    assert parse_probe(probe) == [LoadedConfig("System", path, ["-P", "/x y"], 0)]


def test_parse_deep_nesting_and_stdin():
    probe = CMDLINE + (
        "[debug] Portable config \"/p/yt-dlp.conf\": []\n"
        "[debug] | Config \"/a\": []\n"
        "[debug] | | Config \"/b\": ['-P', '/b']\n"
        "[debug] | Stdin config: ['-P', '/s']\n"
    )
    assert [(c.label, c.path, c.depth) for c in parse_probe(probe)] == [
        ("Portable", "/p/yt-dlp.conf", 0), ("Included", "/a", 1),
        ("Included", "/b", 2), ("Stdin", None, 1),
    ]


def test_parse_no_config_files():
    assert parse_probe(CMDLINE + "yt-dlp: error: You must provide at least one URL.\n") == []


@pytest.mark.parametrize("text", [
    "",
    "zsh: command not found: yt-dlp\n",
    CMDLINE + "[debug] User config \"/c\": ['-P', \n",  # truncated token list
    CMDLINE + "[debug] User config \"/c\": [1, 2]\n",
    # A config yt-dlp could not load: it prints only what it got so far.
    CMDLINE + "yt-dlp: error: config location /x/extra.conf does not exist\n",
    CMDLINE + "yt-dlp_macos: error: no such option: --bogus\n",
])
def test_parse_garbage(text):
    assert parse_probe(text) is None


@pytest.mark.parametrize(("tokens", "setting", "values"), [
    (["--cookies-from-browser", "firefox"], COOKIES, ["firefox"]),
    (["--cookies-from-browser=chrome:Profile 2"], COOKIES, ["chrome:Profile 2"]),
    (["--no-cookies-from-browser"], COOKIES, ["none"]),
    (["--cookies-from-browser", "safari", "--no-cookies-from-browser"], COOKIES,
     ["safari", "none"]),
    (["-P", "/x"], DIRECTORY, ["/x"]),
    (["-P", "home:/x"], DIRECTORY, ["/x"]),
    (["-P", "HOME:/x"], DIRECTORY, ["/x"]),
    (["-P", "temp,home:/x"], DIRECTORY, ["/x"]),
    (["-P", "temp:/x"], DIRECTORY, []),
    (["-P", "thumbnail:/x"], DIRECTORY, []),
    (["-P", "pl_infojson,temp:/x"], DIRECTORY, []),
    (["-P", "C:\\x"], DIRECTORY, ["C:\\x"]),
    (["-P", "bogus:/x"], DIRECTORY, ["bogus:/x"]),
    (["--paths", "/x"], DIRECTORY, ["/x"]),
    (["--paths=home:/x"], DIRECTORY, ["/x"]),
    (["-P/x"], DIRECTORY, ["/x"]),
    (["-o", "%(title)s.%(ext)s", "-P"], DIRECTORY, []),  # dangling option
    (["--cookies-from-browser", "firefox"], DIRECTORY, []),
])
def test_config_values(tokens, setting, values):
    assert [o.value for o in config_values([cfg(*tokens)], setting)] == values


def test_config_values_probe_order():
    loaded = parse_probe(SAMPLE)
    assert config_values(loaded, DIRECTORY) == [
        Occurrence(DIRECTORY, "/tmp/a", "/Users/u/.config/yt-dlp/config", "User"),
        Occurrence(DIRECTORY, "/tmp/b", "/Users/u/extra.conf", "Included"),
    ]


@pytest.mark.parametrize(("values", "shared"), [
    ([], None),
    (["firefox"], "firefox"),
    (["firefox", "firefox"], "firefox"),
    (["firefox", "none"], None),
])
def test_shared_value(values, shared):
    assert shared_value([Occurrence(COOKIES, v, f"/{i}", "User") for i, v in enumerate(values)]) \
        == shared


def test_find_conflicts_across_files():
    loaded = parse_probe(SAMPLE)
    assert [(o.value, o.label) for o in find_conflicts(loaded)] == [
        ("/tmp/a", "User"), ("/tmp/b", "Included"),
    ]


def test_find_conflicts_counts_files_not_values():
    # Two files that agree still count; repeats inside one file do not.
    two_files = [cfg("-P", "/x", path="/a"), cfg("-P", "/x", path="/b", label="Included")]
    assert len(find_conflicts(two_files)) == 2
    one_file = [cfg("-P", "/x", "-P", "/y", "--no-cookies-from-browser")]
    assert find_conflicts(one_file) == []
    # temp-only -P is not a home path, so it does not conflict.
    assert find_conflicts([cfg("-P", "/x", path="/a"), cfg("-P", "temp:/t", path="/b")]) == []
