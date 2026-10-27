"""What the yt-dlp config says, and editing the user config.

Yoink does not search for config files. It runs
`yt-dlp -v --no-update --no-cookies-from-browser` with no URL and parses the
`[debug] ... config "<path>": [tokens]` lines, which list every file yt-dlp
loaded, tokenized by yt-dlp itself. It never decides which file wins; it
only reports where a managed setting occurs. See docs/PHASE1.md section 1.

The Preferences dialog edits the user config line by line and keeps every
line it does not change byte for byte. See docs/PHASE2.md section 1.
"""

import ast
import codecs
import locale
import os
import re
import shlex
import shutil
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import NamedTuple, TypeGuard

COOKIES = "cookies"
DIRECTORY = "directory"
BROWSERS = ["brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale"]

# Run with no URL. --no-cookies-from-browser keeps a config's browser cookie
# database closed (no Keychain prompt); yt-dlp still lists that config's tokens.
PROBE_ARGS = ["-v", "--no-update", "--no-cookies-from-browser"]


@dataclass(frozen=True)
class LoadedConfig:
    label: str  # Portable, Home, User, System, Included, or Stdin
    path: str | None  # None only for a stdin include
    tokens: list[str]
    depth: int  # 0 for top level, +1 per --config-locations nesting


@dataclass(frozen=True)
class Occurrence:
    setting: str
    value: str
    path: str | None
    label: str


# Mirrors yt-dlp's Config.__str__ as flattened by options.parseOpts: one "| "
# per nesting level, then "<Label> config" or a bare "Config" for includes.
_HEAD = re.compile(r'\[debug\] ((?:\| )*)(?:(\S+) config|Config)(?= "|: )')
_PATH_END = re.compile(r'": (?=\[)')
# optparse's "<prog>: error: <msg>". The probe always ends on the missing URL;
# any other error (bad config, missing include) means the list is incomplete.
_ERROR = re.compile(r"[^:]+: error: (?!You must provide at least one URL)")


def _tokens(text: str) -> list[str] | None:
    try:
        value = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return None
    if isinstance(value, list) and all(isinstance(t, str) for t in value):
        return value
    return None


def _parse_line(head: re.Match, line: str) -> LoadedConfig | None:
    label, rest = head[2] or "Included", line[head.end():]
    depth = len(head[1]) // 2
    if rest.startswith(": "):
        tokens = _tokens(rest[2:])
        return None if tokens is None else LoadedConfig(label, None, tokens, depth)
    # The path is printed unescaped, so try each '": [' until the rest parses.
    for end in _PATH_END.finditer(rest, 2):  # rest starts with ' "'
        if (tokens := _tokens(rest[end.end():])) is not None:
            return LoadedConfig(label, rest[2:end.start()], tokens, depth)
    return None


def decode_output(data: bytes) -> str:
    """yt-dlp's output: it writes to a pipe in the locale encoding, unless in UTF-8 mode."""
    try:
        return data.decode()
    except UnicodeDecodeError:
        return data.decode(locale.getpreferredencoding(False), "replace")


def parse_probe(text: str) -> list[LoadedConfig] | None:
    """Loaded configs in probe order; None if `text` is not probe output.

    `text` is the probe's combined stdout and stderr.
    """
    loaded, saw_command_line = [], False
    for line in text.splitlines():
        if _ERROR.match(line):
            return None
        if not (head := _HEAD.match(line)):
            continue
        if not (config := _parse_line(head, line)):
            return None
        if config.label == "Command-line" and config.depth == 0:
            saw_command_line = True
        else:
            loaded.append(config)
    return loaded if saw_command_line else None


# yt-dlp's print_debug_header: the label from update._make_label, which is
# "<channel>@<tag> from <origin>", "<origin>@<tag>", or "<origin>@<tag> build
# <version>"; then "[<git head>]" and "(<variant>)", each optional. A variant
# set by a repackager ends in "*"; an unknown one is left out.
_VERSION = re.compile(
    r"^\[debug\] yt-dlp version (?P<label>\S+)(?: from (?P<origin>\S+)| build (?P<build>\S+))?"
    r"(?: \[[^\]]*\])?(?: \((?P<variant>[^)]*)\))?", re.M)


def _header(text: str) -> tuple[str, str, str] | None:
    """(origin, version, variant) from the probe's debug header."""
    if not (m := _VERSION.search(text)):
        return None
    origin, _, tag = m["label"].rpartition("@")
    return m["origin"] or origin, m["build"] or tag, m["variant"] or ""


def parse_version(text: str) -> tuple[str, str] | None:
    """(version, variant) from the probe's debug header; variant may be ""."""
    header = _header(text)
    return header and header[1:]


def is_stale(text: str, today: date) -> bool:
    """yt-dlp's own rule: an official build whose version date is over 90 days old.

    yt-dlp never prints this warning itself because the probe passes --no-update.
    """
    if not (header := _header(text)) or not header[0].startswith("yt-dlp/"):
        return False
    try:
        built = date(*map(int, header[1].split(".")[:3]))
    except (TypeError, ValueError):  # not a dated version
        return False
    return built < today - timedelta(days=90)


# `--paths [TYPES:]PATH`, as split by yt-dlp's _dict_from_options_callback.
# The types are "home", "temp", and the keys of yt-dlp's OUTTMPL_TYPES.
_PATH_TYPES = "|".join((
    "home", "temp", "chapter", "subtitle", "thumbnail", "description", "annotation",
    "infojson", "link", "pl_video", "pl_thumbnail", "pl_description", "pl_infojson",
))
_TYPED_PATH = re.compile(rf"(?is)(?P<keys>({_PATH_TYPES})(,({_PATH_TYPES}))*):(?P<val>.*)$")


def home_path(value: str) -> str | None:
    m = _TYPED_PATH.match(value)
    if not m:
        return value
    return m["val"] if "home" in m["keys"].lower().split(",") else None


class _Option(NamedTuple):
    setting: str
    takes_arg: bool
    value: Callable[[str], str | None]  # None: the occurrence doesn't count


_OPTIONS = {
    "--cookies-from-browser": _Option(COOKIES, True, str),
    "--no-cookies-from-browser": _Option(COOKIES, False, lambda _: "none"),
    "-P": _Option(DIRECTORY, True, home_path),
    "--paths": _Option(DIRECTORY, True, home_path),
}
SETTINGS = tuple(dict.fromkeys(o.setting for o in _OPTIONS.values()))


def _scan(tokens: list[str]) -> Iterator[tuple[_Option, str]]:
    """Yield (option, value) for each managed option in `tokens`."""
    i = 0
    while i < len(tokens):
        tok, i = tokens[i], i + 1
        if tok.startswith("--"):
            name, eq, arg = tok.partition("=")
        else:  # optparse also accepts a glued short form: -P/x
            name, arg = tok[:2], tok[2:]
            eq = "=" if arg else ""
        opt = _OPTIONS.get(name)
        if opt is None or (eq and not opt.takes_arg):
            continue
        if opt.takes_arg and not eq:
            if i == len(tokens):
                break
            arg, i = tokens[i], i + 1
        yield opt, arg


def config_values(loaded: list[LoadedConfig], setting: str) -> list[Occurrence]:
    """Every occurrence of `setting` in probe order. Never ranked."""
    return [
        Occurrence(setting, value, config.path, config.label)
        for config in loaded
        for opt, arg in _scan(config.tokens)
        if opt.setting == setting and (value := opt.value(arg)) is not None
    ]


def shared_value(occurrences: list[Occurrence]) -> str | None:
    values = {o.value for o in occurrences}
    return values.pop() if len(values) == 1 else None


def find_conflicts(loaded: list[LoadedConfig]) -> list[Occurrence]:
    """Occurrences of each managed setting that appears in more than one file."""
    conflicts = []
    for setting in SETTINGS:
        occurrences = config_values(loaded, setting)
        if len({o.path for o in occurrences}) > 1:
            conflicts += occurrences
    return conflicts


@dataclass(frozen=True)
class ConfigDefaults:
    """What the main window shows while following the config (PHASE1.md 2.1, 2.2)."""

    cookies: str | None  # for "Config default (...)"; None if unknown or disagreeing
    directory: str | None  # the home path, if every occurrence agrees
    sets_directory: bool  # some config sets a home path, so Yoink passes no -P


def config_defaults(loaded: list[LoadedConfig] | None) -> ConfigDefaults:
    """Interpret a probe result; None (probe failed) means nothing is known."""
    if loaded is None:
        return ConfigDefaults(None, None, False)
    cookies, dirs = config_values(loaded, COOKIES), config_values(loaded, DIRECTORY)
    return ConfigDefaults(shared_value(cookies) if cookies else "none",
                          shared_value(dirs), bool(dirs))


# ---- editing the user config (docs/PHASE2.md section 1) ----------------------


@dataclass(frozen=True)
class Line:
    raw: str  # as written, with its line ending


class Blank(Line): pass  # empty or whitespace only
class Comment(Line): pass  # only a "#" comment
class Opaque(Line): pass  # short flags, several options, a stray value, unsplittable


@dataclass(frozen=True)
class Option(Line):
    """Exactly one long option, with an optional value and trailing comment."""

    name: str
    value: str | None  # None for a bare flag


def _classify(raw: str) -> Line:
    body = raw.rstrip("\r\n")
    if not body.strip():
        return Blank(raw)
    if body.lstrip().startswith("#"):
        return Comment(raw)
    try:
        tokens = shlex.split(body, comments=True)
    except ValueError:
        return Opaque(raw)
    name, eq, value = tokens[0].partition("=") if tokens else ("", "", "")
    if name.startswith("--") and len(name) > 2:
        if len(tokens) == 1:
            return Option(raw, name, value if eq else None)
        if len(tokens) == 2 and not eq and not tokens[1].startswith("-"):
            return Option(raw, name, tokens[1])
    return Opaque(raw)


def parse_lines(text: str) -> list[Line]:
    # Split after each "\n" only: shlex ends a comment there and nowhere else.
    return [_classify(raw) for raw in re.split(r"(?<=\n)", text) if raw]


def format_lines(lines: list[Line]) -> str:
    return "".join(line.raw for line in lines)


def _owns(line: Line, name: str) -> TypeGuard[Option]:
    """Whether `line` belongs to the widget for option `name`."""
    if not isinstance(line, Option) or line.name != name:
        return False
    # A --paths line counts only if it sets the home path alone.
    m = name == "--paths" and _TYPED_PATH.match(line.value or "")
    return not m or m["keys"].lower() == "home"


def owned_lines(lines: list[Line], names: Iterable[str]) -> dict[str, list[Option]]:
    """The lines each managed option owns; more than one means it is repeated."""
    return {name: [line for line in lines if _owns(line, name)] for name in names}


def unmanaged(lines: list[Line], owned: dict[str, list[Option]]) -> list[Line]:
    """Lines for the warning box: all but blanks, comments, and lines a widget shows."""
    shown = [o[0] for o in owned.values() if len(o) == 1]
    return [line for line in lines if not isinstance(line, (Blank, Comment))
            and not any(line is s for s in shown)]


def _ending(raw: str) -> str:
    return raw[len(raw.rstrip("\r\n")):]


def _comment(body: str) -> str:
    """An option line's trailing comment, with the space before it, or ""."""
    tokens = shlex.split(body, comments=True)
    for i in (i for i, c in enumerate(body) if c == "#"):
        try:
            if shlex.split(body[:i]) == tokens:
                return body[len(body[:i].rstrip()):]
        except ValueError:  # this "#" is inside quotes
            pass
    return ""


def set_option(lines: list[Line], name: str, value: str | bool) -> list[Line]:
    """Apply one widget's state: True writes a bare flag, a falsy value removes the line."""
    new = (name if value is True else f"{name} {shlex.quote(value)}") if value else None
    for i, line in enumerate(lines):
        if not _owns(line, name):
            continue
        if new is None:
            return lines[:i] + lines[i + 1:]
        if line.value == (None if value is True else value):
            return lines
        rest = _comment(line.raw.rstrip("\r\n")) + _ending(line.raw)
        return [*lines[:i], _classify(new + rest), *lines[i + 1:]]
    if new is None:
        return lines
    end = (_ending(lines[0].raw) if lines else "") or "\n"
    if lines and not _ending(lines[-1].raw):
        lines = [*lines[:-1], _classify(lines[-1].raw + end)]
    return [*lines, _classify(new + end)]


# yt-dlp's Config.read_file and determine_file_encoding: a byte-order mark,
# else a "# coding:" first line, else the locale encoding.
_BOMS = [(codecs.BOM_UTF8, "utf-8"), (codecs.BOM_UTF32_BE, "utf-32-be"),
         (codecs.BOM_UTF32_LE, "utf-32-le"), (codecs.BOM_UTF16_LE, "utf-16-le"),
         (codecs.BOM_UTF16_BE, "utf-16-be")]
_CODING = re.compile(rb"(?m)^#\s*coding\s*:\s*(\S+)\s*$")


class ConfigChanged(Exception):
    """The file changed on disk after it was read."""


@dataclass(frozen=True)
class ConfigFile:
    path: Path
    lines: list[Line]
    encoding: str
    bom: bytes
    data: bytes | None  # as read; None if the file did not exist


def default_config_path() -> Path:
    """Where Yoink creates the user config if yt-dlp loaded none (DESIGN.md 3.1)."""
    if sys.platform == "win32":
        return Path(os.environ["APPDATA"], "yt-dlp", "config")
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config", "yt-dlp", "config")


def read_config(path: Path) -> ConfigFile:
    """Decode `path` as yt-dlp does; a missing file becomes a new UTF-8 file with a BOM."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return ConfigFile(path, [], "utf-8", codecs.BOM_UTF8, None)
    bom, encoding = next(((b, e) for b, e in _BOMS if data.startswith(b)), (b"", ""))
    if not bom:
        m = _CODING.match(data[:512].replace(b"\0", b""))
        encoding = m[1].decode() if m else locale.getpreferredencoding(False)
    return ConfigFile(path, parse_lines(data[len(bom):].decode(encoding)), encoding, bom, data)


def write_config(config: ConfigFile, lines: list[Line]) -> None:
    """Replace the file atomically, in its own encoding.

    Raises UnicodeEncodeError, or ConfigChanged if the file is no longer as
    read, before touching anything.
    """
    data = config.bom + format_lines(lines).encode(config.encoding)
    path = config.path.resolve()  # through a symlink, so the link survives
    if (path.read_bytes() if path.exists() else None) != config.data:
        raise ConfigChanged(str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.yoink-tmp")
    tmp.write_bytes(data)
    if config.data is not None:
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


# yt-dlp's Config.hide_login_info, which the probe applies before printing.
_PRIVATE = ("-p", "--password", "-u", "--username", "--video-password", "--ap-password",
            "--ap-username")
_PRIVATE_EQ = re.compile("^(" + "|".join(map(re.escape, _PRIVATE)) + ")=.+$")


def matches_probe(lines: list[Line], tokens: list[str]) -> bool:
    """Whether splitting line by line gives the tokens yt-dlp reported for the file."""
    try:
        ours = [t for line in lines for t in shlex.split(line.raw, comments=True)]
    except ValueError:  # e.g. a quoted value that spans lines
        return False
    ours = [f"{m[1]}=PRIVATE" if (m := _PRIVATE_EQ.match(t)) else t for t in ours]
    for i in range(len(ours) - 1):
        if ours[i] in _PRIVATE:
            ours[i + 1] = "PRIVATE"
    return ours == tokens


# yt-dlp's pattern for BROWSER[+KEYRING][:PROFILE][::CONTAINER] (yt_dlp/__init__.py).
_COOKIE_SPEC = re.compile(r"""(?x)
    (?P<browser>[^+:]+)
    (?:\s*\+\s*(?P<keyring>[^:]+))?
    (?:\s*:\s*(?!:)(?P<profile>.+?))?
    (?:\s*::\s*(?P<container>.+))?""")


def split_cookie_spec(spec: str) -> tuple[str, str, str, str]:
    """(browser, keyring, profile, container), "" for each missing part."""
    if not (m := _COOKIE_SPEC.fullmatch(spec)):
        return spec, "", "", ""  # yt-dlp rejects it, so the probe failed anyway
    browser, keyring, profile, container = (p or "" for p in m.groups())
    return browser.lower(), keyring.upper(), profile, container


def join_cookie_spec(browser: str, keyring: str, profile: str, container: str) -> str:
    return "".join((browser, keyring and f"+{keyring}", profile and f":{profile}",
                    container and f"::{container}"))


def to_config_path(path: str) -> str:
    """Forward slashes, which survive yt-dlp's POSIX shlex (DESIGN.md 3.2)."""
    return Path(path).as_posix() if path else ""


def to_display_path(value: str | None) -> str:
    return os.path.normpath(value) if value else ""
