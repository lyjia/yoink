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


def rules_path() -> Path:
    # Same sandbox redirect as app.settings().
    if d := os.environ.get("YOINK_SETTINGS_DIR"):
        return Path(d) / "overrides.json"
    loc = QStandardPaths.StandardLocation.AppDataLocation
    return Path(QStandardPaths.writableLocation(loc)) / "overrides.json"


def load_rules(path: Path) -> Rules:
    """Return the rules in `path`; `{}` if it is missing or malformed."""
    try:
        rules = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning("Ignoring unreadable %s: %s", path, e)
        return {}
    if not isinstance(rules, dict):
        log.warning("Ignoring %s: not a JSON object", path)
        return {}
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


def rule_argv(options: dict[str, str | bool]) -> list[str]:
    """Return the options as yt-dlp arguments, skipping unset ones.

    Arguments follow the dict's order; rules are saved in the option table's order.
    """
    args: list[str] = []
    for name, value in options.items():
        if value is True:
            args.append(name)
        elif value:
            args += [name, value]
    return args
