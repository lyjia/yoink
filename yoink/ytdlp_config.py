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
