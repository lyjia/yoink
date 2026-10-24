# Yoink!

A small Qt front end for yt-dlp. yt-dlp's own config file holds every
yt-dlp setting; Yoink shows downloads in a table and stays out of the way.

Design and roadmap: [docs/DESIGN.md](docs/DESIGN.md).

## Running from source

Requires Python 3.11+ and a `yt-dlp` executable on PATH.

```
pip install -e .
python -m yoink
```

## Status

Phase 0: walking skeleton. Paste a URL, pick a directory, download, cancel.
