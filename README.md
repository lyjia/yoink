# Yoink!

A small Qt front end for yt-dlp. yt-dlp's own config file holds every
yt-dlp setting; Yoink shows downloads in a table and stays out of the way.

Design and roadmap: [docs/DESIGN.md](docs/DESIGN.md).

## Running from source

Requires [uv](https://docs.astral.sh/uv/), Python 3.11+, and a `yt-dlp`
executable on PATH.

```
uv sync
uv run python -m yoink
uv run pytest
```

On macOS, a Homebrew yt-dlp (`brew install yt-dlp`) works best. A release
downloaded in a browser is blocked by Gatekeeper; see
[DESIGN.md section 6.6](docs/DESIGN.md#66-macos-gatekeeper-and-quarantine).

`scripts/sandbox.sh` runs Yoink against a throwaway HOME, yt-dlp config,
and Yoink settings, and serves a dummy clip to download. Add
`--pypi-yt-dlp` to install yt-dlp from PyPI into the sandbox instead of
using the one on PATH; `--help` lists the other options.

IDE run configurations are checked in. IntelliJ/PyCharm: **Yoink**,
**Yoink (sandbox)**, **Yoink (sandbox, clean)**, and **Tests**. VS Code:
launch configurations for Yoink, Yoink with sandboxed settings, and the
tests under the debugger, plus tasks for the sandbox and `uv run pytest`.

## Status

Phase 1: main-window overrides and cookies. On top of Phase 0 (paste a URL,
download, cancel):

- The cookies combo offers **Config default**, **No cookies**, or a browser
  to read cookies from. Config default shows the yt-dlp config's value and
  passes nothing.
- An empty directory field follows the yt-dlp config's `-P`, or falls back
  to the Downloads folder. A typed or browsed directory overrides it.
- **Reset** clears both overrides. Overrides are restored on the next launch.
- The status bar shows the yt-dlp version, and a warning when the same
  setting appears in more than one config file. Click it for the details.
- **File > Refresh config** rereads the yt-dlp config without a restart.
