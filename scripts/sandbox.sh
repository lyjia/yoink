#!/usr/bin/env bash
# Run Yoink against a throwaway HOME so manual checks never touch the real
# yt-dlp config.
#
# Usage: scripts/sandbox.sh [--user-config FILE] [--include-config FILE]
#                           [--clean] [-h] [-- YOINK_ARGS...]
#
#   --user-config FILE     copy FILE to $XDG_CONFIG_HOME/yt-dlp/config
#   --include-config FILE  copy FILE to $HOME/included.conf and append
#                          "--config-locations <that path>" to the user config
#                          (creating the user config if needed)
#   --clean                delete the sandbox on exit (default: keep it)
#
# Creates a temp HOME with XDG_CONFIG_HOME=$HOME/.config and $HOME/Downloads,
# serves a 3 MB dummy clip at http://127.0.0.1:8765/clip.mp4, then runs
# `python -m yoink` with HOME and XDG_CONFIG_HOME pointing into the sandbox.
# yt-dlp's generic extractor downloads the clip as a direct file.
#
# Limitation (macOS): only yt-dlp config is isolated. Two things Qt gets from
# the OS ignore $HOME (verified on macOS 15):
#   - QSettings (Yoink's own settings) go through CFPreferences and are read
#     from and written to the real ~/Library/Preferences/com.lyjia.Yoink.plist,
#     even though QSettings.fileName() reports a path inside the sandbox.
#   - QStandardPaths' Downloads location is the real ~/Downloads, so Yoink's
#     Downloads fallback (and the child's working directory) is the real
#     folder. Paste the sandbox Downloads path into the directory field to keep
#     downloads in the sandbox (Yoink then remembers it in the real QSettings).
# On Linux both follow XDG_CONFIG_HOME / HOME, so the sandbox covers them.

set -euo pipefail

usage() { sed -n '2,/^$/s/^# \{0,1\}//p' "$0"; }

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port=8765
user_config=""
include_config=""
clean=0

while (($#)); do
    case "$1" in
        --user-config) user_config="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift 2 ;;
        --include-config) include_config="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"; shift 2 ;;
        --clean) clean=1; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; break ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

tmp="${TMPDIR:-/tmp}"
sandbox="$(mktemp -d "${tmp%/}/yoink-sandbox.XXXXXX")"
home="$sandbox/home"
srv="$sandbox/srv"
xdg="$home/.config"
mkdir -p "$home/Downloads" "$xdg" "$srv"

if [[ -n "$user_config" ]]; then
    mkdir -p "$xdg/yt-dlp"
    cp "$user_config" "$xdg/yt-dlp/config"
fi
if [[ -n "$include_config" ]]; then
    mkdir -p "$xdg/yt-dlp"
    cp "$include_config" "$home/included.conf"
    # Leading newline in case the user config lacks a trailing one.
    [[ -s "$xdg/yt-dlp/config" ]] && echo >> "$xdg/yt-dlp/config"
    echo "--config-locations \"$home/included.conf\"" >> "$xdg/yt-dlp/config"
fi

head -c 3000000 /dev/urandom > "$srv/clip.mp4"

server_pid=""
cleanup() {
    if [[ -n "$server_pid" ]]; then
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    if ((clean)); then
        rm -rf "$sandbox"
        echo "Removed sandbox $sandbox"
    else
        echo "Sandbox kept: $sandbox"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

uv run --project "$repo" python -m http.server "$port" --bind 127.0.0.1 \
    --directory "$srv" >"$sandbox/server.log" 2>&1 &
server_pid=$!

url="http://127.0.0.1:$port/clip.mp4"
for _ in $(seq 50); do
    curl -sfI "$url" >/dev/null 2>&1 && break
    kill -0 "$server_pid" 2>/dev/null || { cat "$sandbox/server.log" >&2; exit 1; }
    sleep 0.1
done

echo "Sandbox:   $sandbox"
echo "HOME:      $home"
echo "Downloads: $home/Downloads"
echo "URL:       $url"

# uv itself runs with the real environment (cache, interpreters); only Yoink
# sees the sandbox HOME.
uv run --project "$repo" env HOME="$home" XDG_CONFIG_HOME="$xdg" \
    python -m yoink "$@"
