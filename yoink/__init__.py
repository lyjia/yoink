"""Yoink: a small Qt front end for yt-dlp."""

from importlib.metadata import version

__version__ = version("yoink")

# Nuitka sets __compiled__ in compiled modules.
FROZEN = "__compiled__" in globals()

# The version as shown to the user: About and the startup log line.
VERSION_LABEL = __version__ if FROZEN else f"{__version__} (running from source)"
