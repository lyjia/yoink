# Yoink!

A small GUI front-end for yt-dlp. 

Design and roadmap: [docs/DESIGN.md](docs/DESIGN.md).

Status: Phases 0 to 3 are done (per-domain rules landed last); Phase 4,
onboarding, is next.

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
