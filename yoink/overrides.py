"""Per-domain rules: storage, matching, and command-line options.

A rule maps a domain to a set of yt-dlp options. See docs/PHASE3.md
section 1 and docs/DESIGN.md section 5.
"""

import json
import logging
import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths

log = logging.getLogger(__name__)

Rules = dict[str, dict[str, str | bool]]
SAVE_ERROR = "Yoink couldn't save the domain rules:\n{}"


def rules_path() -> Path:
    # Same sandbox redirect as app.settings().
    if d := os.environ.get("YOINK_SETTINGS_DIR"):
        return Path(d) / "overrides.json"
    loc = QStandardPaths.StandardLocation.AppDataLocation
    return Path(QStandardPaths.writableLocation(loc)) / "overrides.json"


def load_rules(path: Path) -> Rules:
    """Return the valid rules in `path`, keyed by normalized domain; `{}` if it is missing or
    malformed."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("Ignoring unreadable %s: %s", path, e)
        return {}
    if not isinstance(data, dict):
        log.warning("Ignoring %s: not a JSON object", path)
        return {}
    rules = {normalize_domain(d): {k: v for k, v in o.items() if isinstance(v, (str, bool))}
             for d, o in data.items() if isinstance(o, dict) and normalize_domain(d)}
    # Fewer entries: a bad or duplicate domain, or a non-object rule. Else a bad setting.
    if len(rules) < len(data) or rules != {normalize_domain(d): o for d, o in data.items()}:
        log.warning("Ignoring invalid rules or settings in %s", path)
    return rules


def save_rules(path: Path, rules: Rules) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rules, indent=2), encoding="utf-8")


def normalize_domain(text: str) -> str:
    domain = text.strip().strip(".").lower()
    return domain.removeprefix("www.")


def match(host: str | None, rules: Rules) -> str | None:
    """Return the longest domain in `rules` that is `host` or a parent of it."""
    if not host:
        return None
    host = host.lower()
    hits = [d for d in rules if host == d or host.endswith("." + d)]
    return max(hits, key=len, default=None)


def _set_options(options: dict[str, str | bool]) -> list[list[str]]:
    """Each set option as `[name]` or `[name, value]`, in the dict's order."""
    return [[name] if value is True else [name, value] for name, value in options.items() if value]


def rule_lines(options: dict[str, str | bool]) -> list[str]:
    """Return the set options as `name` or `name value`, for display."""
    return [" ".join(option) for option in _set_options(options)]


def rule_argv(options: dict[str, str | bool]) -> list[str]:
    """Return the set options as yt-dlp arguments.

    Arguments follow the dict's order, which does not matter to yt-dlp.
    """
    return [arg for option in _set_options(options) for arg in option]
