#!/usr/bin/env bash
# Build a standalone Yoink folder (a .app on macOS) in dist/.
#
# Usage: scripts/build.sh [--release] [NUITKA_ARGS...]
#
# --release requires a clean tree on a v* tag, and zips the build to
# dist/yoink-<version>-<os>-<arch>.zip. Other arguments go to Nuitka; a later
# --mode wins, e.g. `scripts/build.sh --mode=onefile`. yt-dlp is not bundled.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

release=0
for arg; do
    shift
    if [[ $arg == --release ]]; then release=1; else set -- "$@" "$arg"; fi
done

# app-dist is a standalone folder, or a .app bundle on macOS. Windows attaches
# to the launching terminal so logging is visible.
case "$(uname -s)" in
    MINGW*|MSYS*|CYGWIN*) os=windows; extra="--windows-console-mode=attach"; out=dist/yoink.dist/yoink.exe ;;
    Darwin) os=macos; extra="--macos-app-name=Yoink"; out=dist/yoink.app ;;
    *) os=linux; extra=""; out=dist/yoink.dist/yoink ;;
esac

# Reinstall so the version metadata matches HEAD and the tree's dirty state.
uv sync --reinstall-package yoink
version=$(uv run python -c "import yoink; print(yoink.__version__, end='')")
if (( release )) && ! [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Refusing --release: version $version is not a clean tag (need a clean tree on a v* tag)." >&2
    exit 1
fi

# --lto=no: MSVC 14.3 hits an internal compiler error linking with LTO, and a
# test build doesn't need it. $extra is unquoted on purpose: it may be empty.
# shellcheck disable=SC2086
uv run python -m nuitka --mode=app-dist --enable-plugin=pyside6 --lto=no \
    --include-distribution-metadata=yoink \
    --output-dir=dist --assume-yes-for-downloads $extra "$@" yoink

echo "Built $version: $PWD/$out"

if (( release )); then
    zip="dist/yoink-$version-$os-$(uname -m).zip"
    rm -f "$zip"
    if [[ $os == macos ]]; then
        ditto -c -k --keepParent dist/yoink.app "$zip"
    elif command -v zip >/dev/null; then
        (cd dist && zip -qr "../$zip" yoink.dist)
    else
        uv run python -c "import shutil, sys; shutil.make_archive(sys.argv[1], 'zip', 'dist', 'yoink.dist')" "${zip%.zip}"
    fi
    echo "Release: $PWD/$zip"
fi
