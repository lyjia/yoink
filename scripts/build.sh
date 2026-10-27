#!/usr/bin/env bash
# Build a standalone Yoink folder for local testing (not a release build).
#
# Usage: scripts/build.sh [NUITKA_ARGS...]
#
# Extra arguments go to Nuitka; a later --mode wins, e.g.
# `scripts/build.sh --mode=onefile`. yt-dlp is not bundled.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# app-dist is a standalone folder, or a .app bundle on macOS. Windows attaches
# to the launching terminal so logging is visible.
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) extra="--windows-console-mode=attach"; out=dist/yoink.dist/yoink.exe ;;
    Darwin) extra="--macos-app-name=Yoink"; out=dist/yoink.app ;;
    *) extra=""; out=dist/yoink.dist/yoink ;;
esac

# --lto=no: MSVC 14.3 hits an internal compiler error linking with LTO, and a
# test build doesn't need it. $extra is unquoted on purpose: it may be empty.
# shellcheck disable=SC2086
uv run python -m nuitka --mode=app-dist --enable-plugin=pyside6 --lto=no \
    --output-dir=dist --assume-yes-for-downloads $extra "$@" yoink

echo "Built: $PWD/$out"
