"""What the yt-dlp config says about the settings Yoink shows.

Yoink does not search for config files. It runs
`yt-dlp -v --no-update --no-cookies-from-browser` with no URL and parses the
`[debug] ... config "<path>": [tokens]` lines, which list every file yt-dlp
loaded, tokenized by yt-dlp itself. It never decides which file wins; it
only reports where a managed setting occurs. See docs/PHASE1.md section 1.
"""

import ast
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import NamedTuple

COOKIES = "cookies"
DIRECTORY = "directory"

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
    r"^\[debug\] yt-dlp version (?P<label>\S+)(?: from \S+| build (?P<build>\S+))?"
    r"(?: \[[^\]]*\])?(?: \((?P<variant>[^)]*)\))?", re.M)


def parse_version(text: str) -> tuple[str, str] | None:
    """(version, variant) from the probe's debug header; variant may be ""."""
    if not (m := _VERSION.search(text)):
        return None
    return m["build"] or m["label"].rpartition("@")[2], m["variant"] or ""


# `--paths [TYPES:]PATH`, as split by yt-dlp's _dict_from_options_callback.
# The types are "home", "temp", and the keys of yt-dlp's OUTTMPL_TYPES.
_PATH_TYPES = "|".join((
    "home", "temp", "chapter", "subtitle", "thumbnail", "description", "annotation",
    "infojson", "link", "pl_video", "pl_thumbnail", "pl_description", "pl_infojson",
))
_TYPED_PATH = re.compile(rf"(?is)(?P<keys>({_PATH_TYPES})(,({_PATH_TYPES}))*):(?P<val>.*)$")


def _home_path(value: str) -> str | None:
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
    "-P": _Option(DIRECTORY, True, _home_path),
    "--paths": _Option(DIRECTORY, True, _home_path),
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
