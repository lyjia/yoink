"""Application-wide constants, settings keys, and logging setup."""

import logging

ORG_NAME = "Lyjia"
APP_NAME = "Yoink"
APP_TITLE = "Yoink!"

# QSettings keys. Only front-end state lives here; anything yt-dlp has a flag
# for belongs in yt-dlp's own config file (see docs/DESIGN.md, principle 1).
KEY_LAST_DIR = "main/last_dir"
KEY_GEOMETRY = "main/geometry"
KEY_BINARY_PATH = "ytdlp/binary_path"


def setup_logging(level: int = logging.INFO) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
