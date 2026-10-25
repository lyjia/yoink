#!/usr/bin/env bash
# Run Yoink against a throwaway HOME so manual checks never touch the real
# yt-dlp config or Yoink's own settings.
#
# Usage: scripts/sandbox.sh [--user-config FILE] [--include-config FILE]
#                           [--pypi-yt-dlp[=VERSION] | --yt-dlp PATH]
#                           [--clean] [--dry-run] [-h] [-- YOINK_ARGS...]
#
#   --user-config FILE     copy FILE to $XDG_CONFIG_HOME/yt-dlp/config
#   --include-config FILE  copy FILE to $HOME/included.conf and append
#                          "--config-locations <that path>" to the user config
#                          (creating the user config if needed)
#   --pypi-yt-dlp[=VERSION]
#                          install yt-dlp from PyPI (latest, or ==VERSION) into
#                          a venv inside the sandbox and put it first on
#                          Yoink's PATH
#   --yt-dlp PATH          put the yt-dlp executable at PATH first on Yoink's
#                          PATH (symlinked as $sandbox/bin/yt-dlp)
#   --clean                delete the sandbox on exit (default: keep it)
#   --dry-run              set up the sandbox, print the environment Yoink
#                          would get and the yt-dlp it would run, then exit
#                          without starting the server or Yoink
#
# Creates a temp HOME with XDG_CONFIG_HOME=$HOME/.config and $HOME/Downloads,
# serves a 3 MB dummy clip at http://127.0.0.1:8765/clip.mp4, then runs
# `python -m yoink` with HOME and XDG_CONFIG_HOME pointing into the sandbox
# and YOINK_SETTINGS_DIR=$sandbox/settings, so Yoink keeps its QSettings in an
# INI file there instead of the OS-native store. yt-dlp's generic extractor
# downloads the clip as a direct file.
#
# Without --pypi-yt-dlp or --yt-dlp, Yoink inherits PATH and runs whatever
# yt-dlp is on it (a warning is printed if there is none). Nothing is
# installed outside the sandbox either way.
#
# Limitation (macOS): QStandardPaths' Downloads location ignores $HOME and is
# the real ~/Downloads (verified on macOS 15), so Yoink's Downloads fallback
# (and the child's working directory) is the real folder. Paste the sandbox
# Downloads path into the directory field to keep downloads in the sandbox
# (Yoink remembers it in the sandbox settings). On Linux it follows HOME /
# XDG, so the sandbox covers it.

set -euo pipefail

usage() { sed -n '2,/^$/s/^# \{0,1\}//p' "$0"; }

abspath() {
    local dir
    dir="$(cd "$(dirname "$1")" && pwd)" || return 1
    echo "${dir%/}/$(basename "$1")"
}

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port=8765
user_config=""
include_config=""
pypi=0
pypi_version=""
ytdlp_path=""
clean=0
dry_run=0

while (($#)); do
    case "$1" in
        --user-config) user_config="$(abspath "$2")"; shift 2 ;;
        --include-config) include_config="$(abspath "$2")"; shift 2 ;;
        --pypi-yt-dlp) pypi=1; shift ;;
        --pypi-yt-dlp=*) pypi=1; pypi_version="${1#*=}"; shift ;;
        --yt-dlp) ytdlp_path="$(abspath "$2")"; shift 2 ;;
        --clean) clean=1; shift ;;
        --dry-run) dry_run=1; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; break ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

if ((pypi)) && [[ -n "$ytdlp_path" ]]; then
    echo "--pypi-yt-dlp and --yt-dlp are mutually exclusive" >&2; exit 2
fi
if [[ -n "$ytdlp_path" && ! ( -f "$ytdlp_path" && -x "$ytdlp_path" ) ]]; then
    echo "--yt-dlp: not an executable file: $ytdlp_path" >&2; exit 2
fi

tmp="${TMPDIR:-/tmp}"
sandbox="$(mktemp -d "${tmp%/}/yoink-sandbox.XXXXXX")"
home="$sandbox/home"
srv="$sandbox/srv"
xdg="$home/.config"
settings="$sandbox/settings"
bin="$sandbox/bin"  # prepended to Yoink's PATH; holds only a yt-dlp link
mkdir -p "$home/Downloads" "$xdg" "$srv" "$settings" "$bin"

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

if ((pypi)); then
    venv="$sandbox/ytdlp-venv"
    echo "Installing yt-dlp${pypi_version:+==$pypi_version} from PyPI into $venv"
    uv venv --quiet "$venv"
    uv pip install --quiet --python "$venv/bin/python" \
        "yt-dlp${pypi_version:+==$pypi_version}"
    # Link only yt-dlp, not the venv's bin, so `python` still resolves to the
    # project interpreter.
    ln -s "$venv/bin/yt-dlp" "$bin/yt-dlp"
elif [[ -n "$ytdlp_path" ]]; then
    ln -s "$ytdlp_path" "$bin/yt-dlp"
fi

head -c 3000000 /dev/urandom > "$srv/clip.mp4"

url="http://127.0.0.1:$port/clip.mp4"
if ! ((dry_run)); then
    uv run --project "$repo" python -m http.server "$port" --bind 127.0.0.1 \
        --directory "$srv" >"$sandbox/server.log" 2>&1 &
    server_pid=$!

    for _ in $(seq 50); do
        curl -sfI "$url" >/dev/null 2>&1 && break
        kill -0 "$server_pid" 2>/dev/null || { cat "$sandbox/server.log" >&2; exit 1; }
        sleep 0.1
    done
fi

echo "Sandbox:   $sandbox"
echo "HOME:      $home"
echo "Settings:  $settings"
echo "Downloads: $home/Downloads"
echo "URL:       $url"

# Runs inside `uv run`, so it sees uv's PATH (project venv first) and prepends
# the sandbox bin to that. Reports the yt-dlp Yoink will find, then execs Yoink
# (or, with --dry-run, prints the environment and exits).
launcher='
bin=$1 dry_run=$2; shift 2
PATH="$bin:$PATH"
if ytdlp=$(command -v yt-dlp); then
    if [[ -L "$ytdlp" ]]; then
        echo "yt-dlp:    $ytdlp -> $(readlink "$ytdlp")"
    else
        echo "yt-dlp:    $ytdlp"
    fi
else
    echo "WARNING: no yt-dlp on PATH; downloads will fail." >&2
    echo "         Use --pypi-yt-dlp or --yt-dlp PATH to provide one." >&2
fi
if ((dry_run)); then
    echo "PATH:      $PATH"
    echo "python:    $(command -v python)"
    env | grep -E "^(HOME|XDG_CONFIG_HOME|YOINK_SETTINGS_DIR)=" | sort
    # Only run a yt-dlp the sandbox provided; an inherited one may be a
    # quarantined build that Gatekeeper kills (with a dialog) on launch.
    if [[ "$ytdlp" == "$bin/yt-dlp" ]]; then
        if v=$(yt-dlp --version); then
            echo "version:   $v"
        else
            echo "version:   FAILED (yt-dlp --version exited non-zero)"
        fi
    elif [[ -n "$ytdlp" ]]; then
        echo "version:   (not run: inherited from PATH)"
    fi
    exit 0
fi
exec python -m yoink "$@"
'

# uv itself runs with the real environment (cache, interpreters); only Yoink
# sees the sandbox HOME, settings dir and PATH.
uv run --project "$repo" env HOME="$home" XDG_CONFIG_HOME="$xdg" \
    YOINK_SETTINGS_DIR="$settings" \
    bash -c "$launcher" sandbox-launcher "$bin" "$dry_run" "$@"
