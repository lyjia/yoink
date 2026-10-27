import codecs
import locale
import os

import pytest

from yoink.ytdlp_config import (
    COOKIES,
    DIRECTORY,
    Blank,
    Comment,
    ConfigChanged,
    ConfigDefaults,
    LoadedConfig,
    Occurrence,
    Opaque,
    Option,
    config_defaults,
    config_values,
    find_conflicts,
    format_lines,
    join_cookie_spec,
    matches_probe,
    owned_lines,
    parse_lines,
    parse_probe,
    parse_version,
    read_config,
    set_option,
    shared_value,
    split_cookie_spec,
    to_config_path,
    to_display_path,
    unmanaged,
    write_config,
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


@pytest.mark.parametrize(("line", "expected"), [
    ("stable@2026.10.21 from yt-dlp/yt-dlp [8cdf4fea4] (pip)", ("2026.10.21", "pip")),
    ("stable@2026.10.21 from yt-dlp/yt-dlp [8cdf4fea4] (darwin_dir)", ("2026.10.21", "darwin_dir")),
    ("nightly@2026.10.22.233505 from yt-dlp/yt-dlp-nightly-builds [0123abcde] (zip)",
     ("2026.10.22.233505", "zip")),
    ("stable@2026.03.17 from yt-dlp/yt-dlp (debian*)", ("2026.03.17", "debian*")),
    ("someone/yt-dlp-fork@2026.10.21 [0123abcde] (source)", ("2026.10.21", "source")),
    ("yt-dlp/yt-dlp@stable build 2026.10.21 [0123abcde] (pip)", ("2026.10.21", "pip")),
    ("stable@2026.10.21 from yt-dlp/yt-dlp [8cdf4fea4]", ("2026.10.21", "")),  # unknown variant
    ("stable@2026.10.21 from yt-dlp/yt-dlp", ("2026.10.21", "")),
])
def test_parse_version(line, expected):
    probe = f"{CMDLINE}[debug] Encodings: locale UTF-8\n[debug] yt-dlp version {line}\n" \
        "[debug] Python 3.12.11 (CPython arm64 64bit)\n"
    assert parse_version(probe) == expected


@pytest.mark.parametrize("text", ["", CMDLINE, "yt-dlp 2026.10.21\n", SAMPLE])
def test_parse_version_missing(text):
    assert parse_version(text) is None


@pytest.mark.parametrize(("loaded", "expected"), [
    (None, ConfigDefaults(None, None, False)),  # probe failed
    ([], ConfigDefaults("none", None, False)),
    ([cfg("--cookies-from-browser", "firefox", "-P", "/dl")], ConfigDefaults("firefox", "/dl", True)),
    ([cfg("--no-cookies-from-browser", "-P", "temp:/t")], ConfigDefaults("none", None, False)),
    ([cfg("-P", "/a", path="/a"), cfg("-P", "/b", path="/b", label="Included")],
     ConfigDefaults("none", None, True)),
    ([cfg("--cookies-from-browser", "safari", path="/a"),
      cfg("--cookies-from-browser", "safari", "-P", "home:/x", path="/b")],
     ConfigDefaults("safari", "/x", True)),
    ([cfg("--cookies-from-browser", "safari", path="/a"),
      cfg("--no-cookies-from-browser", path="/b")], ConfigDefaults(None, None, False)),
])
def test_config_defaults(loaded, expected):
    assert config_defaults(loaded) == expected


# ---- editing the user config (docs/PHASE2.md section 1) ----------------------

CONFIG = "# my config\n\n--no-mtime\n-f best\n--format best  # mine\n--paths temp:/t\n"


@pytest.mark.parametrize(("raw", "expected"), [
    ("\n", Blank("\n")),
    ("   \r\n", Blank("   \r\n")),
    ("  # note\n", Comment("  # note\n")),
    ("--no-mtime\n", Option("--no-mtime\n", "--no-mtime", None)),
    ("--format best\n", Option("--format best\n", "--format", "best")),
    ("--format=best", Option("--format=best", "--format", "best")),
    ("--output '%(title)s x' # c\r\n", Option("--output '%(title)s x' # c\r\n", "--output",
                                               "%(title)s x")),
    ("-f best\n", Opaque("-f best\n")),
    ("--no-mtime --embed-subs\n", Opaque("--no-mtime --embed-subs\n")),
    ("--format 'best\n", Opaque("--format 'best\n")),
    ("stray\n", Opaque("stray\n")),
])
def test_parse_lines(raw, expected):
    assert parse_lines(raw) == [expected]
    assert format_lines(parse_lines(raw)) == raw


@pytest.mark.parametrize("text", [CONFIG, CONFIG.replace("\n", "\r\n"), "--a\n--b", ""])
def test_format_round_trips(text):
    assert format_lines(parse_lines(text)) == text


@pytest.mark.parametrize(("text", "name", "value", "expected"), [
    ("--format best  # mine\n", "--format", "a b", "--format 'a b'  # mine\n"),
    ("--format=best\n", "--format", "it's", "--format 'it'\"'\"'s'\n"),
    ("--format best\n", "--format", "best", "--format best\n"),  # unchanged: not rewritten
    ("--format best\n--no-mtime\n", "--format", "", "--no-mtime\n"),
    ("--embed-subs\n", "--embed-subs", False, ""),
    ("-f best\r\n", "--embed-subs", True, "-f best\r\n--embed-subs\r\n"),
    ("-f best", "--limit-rate", "5M", "-f best\n--limit-rate 5M\n"),
    ("", "--limit-rate", "5M", "--limit-rate 5M\n"),
    ("", "--limit-rate", "", ""),
    ("--paths temp:/t\n", "--paths", "/x", "--paths temp:/t\n--paths /x\n"),
    ("--paths home:/h\n", "--paths", "/x", "--paths /x\n"),
])
def test_set_option(text, name, value, expected):
    assert format_lines(set_option(parse_lines(text), name, value)) == expected


def test_managed_lines():
    lines = parse_lines(CONFIG + "--sub-langs en\n--sub-langs=es\n--paths home:/h\n")
    owned = owned_lines(lines, ["--format", "--sub-langs", "--paths", "--proxy"])
    assert {n: [o.value for o in v] for n, v in owned.items()} == {
        "--format": ["best"], "--sub-langs": ["en", "es"], "--paths": ["home:/h"], "--proxy": [],
    }
    # Repeated options, unmanaged options, and Opaque lines go to the warning box.
    assert [line.raw for line in unmanaged(lines, owned)] == [
        "--no-mtime\n", "-f best\n", "--paths temp:/t\n", "--sub-langs en\n", "--sub-langs=es\n",
    ]


@pytest.mark.parametrize(("data", "encoding"), [
    (codecs.BOM_UTF8 + "--format é\n".encode(), "utf-8"),
    (codecs.BOM_UTF16_LE + "--format é\r\n".encode("utf-16-le"), "utf-16-le"),
    ("# coding: latin-1\n--format é\n".encode("latin-1"), "latin-1"),
    (b"--format best\n", locale.getpreferredencoding(False)),
])
def test_read_write_round_trip(tmp_path, data, encoding):
    path = tmp_path / "config"
    path.write_bytes(data)
    config = read_config(path)
    assert config.encoding == encoding
    write_config(config, set_option(config.lines, "--proxy", "p"))
    assert path.read_bytes().startswith(data)
    write_config(read_config(path), config.lines)
    assert path.read_bytes() == data


def test_new_file_gets_utf8_bom(tmp_path):
    path = tmp_path / "yt-dlp" / "config"
    config = read_config(path)
    write_config(config, set_option(config.lines, "--limit-rate", "5M"))
    assert path.read_bytes() == codecs.BOM_UTF8 + b"--limit-rate 5M\n"


def test_write_failures_leave_file_untouched(tmp_path):
    path = tmp_path / "config"
    path.write_bytes(b"# coding: cp1252\n--no-mtime\n")
    config = read_config(path)
    with pytest.raises(UnicodeEncodeError):
        write_config(config, set_option(config.lines, "--output", "\U0001f600"))
    path.write_bytes(b"# coding: cp1252\n--no-mtime\n--edited\n")
    with pytest.raises(ConfigChanged):
        write_config(config, set_option(config.lines, "--proxy", "p"))
    assert path.read_bytes() == b"# coding: cp1252\n--no-mtime\n--edited\n"
    assert [p.name for p in tmp_path.iterdir()] == ["config"]


@pytest.mark.parametrize(("text", "tokens", "matches"), [
    ("# c\n--format 'a b'  # x\n-f\tbest\n", ["--format", "a b", "-f", "best"], True),
    ("--format 'a\nb'\n", ["--format", "a\nb"], False),  # a value spanning two lines
    ("--format a\\\nb\n", ["--format", "a\nb"], False),  # a backslash ending a line
    ("--password x\n-p\ny\n", ["--password", "PRIVATE", "-p", "PRIVATE"], True),
    ("--username=x\n", ["--username=PRIVATE"], True),
    ("--username=x\n", ["--username=x"], False),
])
def test_matches_probe(text, tokens, matches):
    assert matches_probe(parse_lines(text), tokens) is matches


@pytest.mark.parametrize(("spec", "parts"), [
    ("firefox", ("firefox", "", "", "")),
    ("chrome+KWALLET6", ("chrome", "KWALLET6", "", "")),
    ("chrome:Profile 2", ("chrome", "", "Profile 2", "")),
    ("firefox::Work", ("firefox", "", "", "Work")),
    ("chrome+basictext:Default::none", ("chrome", "BASICTEXT", "Default", "none")),
])
def test_cookie_spec(spec, parts):
    assert split_cookie_spec(spec) == parts
    assert split_cookie_spec(join_cookie_spec(*parts)) == parts


def test_paths():
    assert to_config_path("/home/u/My Videos/") == "/home/u/My Videos"
    assert to_config_path("") == to_display_path("") == ""


@pytest.mark.skipif(os.name == "nt", reason="POSIX paths")
def test_paths_posix():
    assert to_display_path("/home/u//Videos/") == "/home/u/Videos"


@pytest.mark.skipif(os.name != "nt", reason="Windows paths")
def test_paths_windows():
    assert to_config_path("C:\\Users\\u\\Videos") == "C:/Users/u/Videos"
    assert to_display_path("C:/Users/u/Videos") == "C:\\Users\\u\\Videos"
    assert format_lines(set_option([], "--paths", to_config_path("C:\\My Videos"))) \
        == "--paths 'C:/My Videos'\n"
