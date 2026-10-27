# Yoink!

A small GUI front-end for yt-dlp. 

Design and roadmap: [docs/DESIGN.md](docs/DESIGN.md).

## Running from source

Requires Python 3.11+ and a `yt-dlp` executable on PATH.

```
pip install -e .
python -m yoink
```

### Building

Requires uv. From bash (Git Bash on Windows):

```
scripts/build.sh
```

The result lands in `dist/yoink.dist/` (`dist/yoink.app` on macOS).

## Status

Phase 2: Preferences dialog. On top of Phase 1 (main-window overrides and
cookies):

- File > Preferences… sets common yt-dlp options, each with a
  plain-language tooltip.
- Preferences edits your yt-dlp config file in place. Only the lines you
  change are rewritten; everything else is kept as written.
- **Update** in Preferences updates yt-dlp, or shows the command that does.
- The View menu shows or hides download table columns. Columns can be
  resized and reordered, and the layout is remembered.
- Preferences has a theme setting.
