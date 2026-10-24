# Yoink design spec

A small Qt front end for yt-dlp. yt-dlp's own config file is the source of
truth for every yt-dlp-native setting; Yoink stores only front-end state.
Downloads appear as rows in a table. The yt-dlp binary is driven as a child
process; nothing from yt-dlp is imported into the Python process.

## 1. Principles

1. **One source of truth per setting.** If yt-dlp has a flag for it, it lives
   in yt-dlp's config file and the CLI sees the same value Yoink does. If it
   is Yoink-only (window size, last directory, per-domain rules), it lives in
   Yoink's own storage. No setting is stored in both places.
2. **Drive the binary, never import.** One `QProcess` per download. Cancel is
   `kill()`. Progress is parsed from stdout. No threads.
3. **Never clobber the user's config.** Edits to the yt-dlp config are
   line-level and round-trip: comments, ordering, and lines Yoink does not
   understand are preserved byte for byte.
4. **Defaults equal an empty yt-dlp config.** A fresh Yoink install with no
   yt-dlp config behaves exactly as `yt-dlp <url>` would from the OS
   Downloads folder. Yoink adds nothing the user did not configure, with the
   sole exception of the download directory, because a GUI app has no
   meaningful working directory.
5. **Keep it small.** Target under 1500 lines of application code. No plugin
   system, no database, no async framework.

## 2. Architecture

```
yoink/
  __main__.py        QApplication bootstrap
  app.py             paths, QSettings keys, logging setup
  binary.py          locate / download / update the yt-dlp executable
  ytdlp_config.py    read, edit, write yt-dlp's config file (round-trip)
  overrides.py       per-domain override rules (load, match, save)
  argv.py            build the yt-dlp command line for one download
  job.py             DownloadJob: QProcess wrapper, progress line parser
  ui/
    main_window.py   URL/dir inputs, cookies toggle, downloads table
    prefs_dialog.py  tabbed preferences (Yoink / yt-dlp / Domains)
    log_view.py      per-job raw output viewer
docs/DESIGN.md
pyproject.toml
build/nuitka.sh, build/nuitka.ps1
```

Dependencies: PySide6, requests (binary download only). Python 3.11+.

### 2.1 Storage

| Data                         | Where                                               |
|------------------------------|-----------------------------------------------------|
| yt-dlp-native options        | yt-dlp user config file (section 3)                 |
| Window geometry, last dir, cookies toggle state, binary path, update policy | QSettings (`Lyjia/Yoink`) |
| Per-domain overrides         | `overrides.json` in Yoink's app-data dir            |

Per-domain rules are a list of structured records; QSettings handles those
poorly, so they get a JSON file next to the QSettings store.

### 2.2 Command line assembly (`argv.py`)

Order matters because later flags override earlier ones, and yt-dlp applies
the config file before anything on the command line.

```
yt-dlp
  [domain override extra args]          # section 5
  -P <dir>                              # see 2.3
  --cookies-from-browser <spec> | --no-cookies-from-browser   # section 4
  --no-simulate --progress --newline
  --progress-template "download:<YOINK-TSV>"
  --progress-template "postprocess:<YOINK-PP-TSV>"
  --print "before_dl:YOINK\tFILE\t%(filename)s"
  --print "after_move:YOINK\tDONE\t%(filepath)s"
  -- <url>
```

The progress template uses explicit fields, not `%(progress)j`, because the
full progress dict embeds `info_dict` and produces multi-kilobyte lines:

```
download:YOINK\tDL\t%(progress.status)s\t%(progress.downloaded_bytes)s\t%(progress.total_bytes)s\t%(progress.total_bytes_estimate)s\t%(progress.speed)s\t%(progress.eta)s
```

`--print` implies `--simulate`, hence the explicit `--no-simulate`. Both
exact flag behaviour and the postprocess template fields must be verified
against the shipped binary during Phase 0.

### 2.3 Effective download directory

1. Directory field in the main window, if the user typed or picked one.
2. Matching domain rule's `destination`.
3. `--paths` / `-P` from the yt-dlp config: Yoink passes no `-P` and shows
   that directory greyed as placeholder text in the field.
4. Otherwise the OS Downloads folder (`QStandardPaths.DownloadLocation`),
   passed as `-P`.

Step 3 before step 4 is what keeps principle 4 intact: a user who set a
directory in their config never has it overridden by a Yoink fallback.

### 2.4 Download job (`job.py`)

`DownloadJob(QObject)` owns one `QProcess`. It splits stdout on newlines,
routes lines starting with `YOINK\t` to typed signals
(`file_named`, `progress`, `postprocessing`, `done`), and appends everything
else to an in-memory log. States: `queued`, `starting`, `downloading`,
`postprocessing`, `finished`, `failed`, `cancelled`. Exit code non-zero with
no `DONE` line means `failed`; the last stderr lines become the row's error
text.

If a user config contains `--quiet` or `--no-progress`, no progress lines
arrive. The job then stays in `starting` with an indeterminate bar until
`DONE` or exit. This is treated as supported, not an error.

Playlists: each entry produces its own `FILE`/`DL`/`DONE` sequence. Phase 0
shows them in one row with the current filename; splitting into child rows
is backlog.

## 3. yt-dlp config editing (`ytdlp_config.py`)

### 3.1 Which file

Yoink manages the **user** config:

- Linux/macOS: `${XDG_CONFIG_HOME:-~/.config}/yt-dlp/config`
- Windows: `%APPDATA%\yt-dlp\config`

Created on first write if absent. The dialog shows the path. yt-dlp also reads
portable, home, and system configs; Yoink does not touch those but shows a
note that they may exist and take precedence for some options.

### 3.2 Format and round-trip model

The file is a list of command-line arguments, one or more per line, shell-style
quoting, `#` comments. Yoink parses it into a list of `Line` records:

- `Comment` / `Blank`: preserved verbatim.
- `Option(name, value, raw)`: a line containing exactly one long option with
  an optional value. Editable.
- `Opaque(raw)`: anything else (multiple options on one line, short flags,
  unparseable). Preserved verbatim, shown read-only in the structured view.

Editing an option rewrites only that line. Adding one appends at the end.
Removing one deletes the line. Writing re-emits every record in order. A raw
text tab offers full control and bypasses the structured model; saving from
it re-parses.

### 3.3 Structured view

A curated subset of options gets proper widgets. Initial set:

| Option                       | Widget                      |
|------------------------------|-----------------------------|
| `--paths` / `-P`             | directory picker            |
| `--output` / `-o`            | line edit with hint         |
| `--format` / `-f`            | combo of presets + free text|
| `--cookies-from-browser`     | browser combo + profile     |
| `--cookies`                  | file picker                 |
| `--embed-thumbnail`, `--embed-metadata`, `--embed-subs`, `--write-subs` | checkboxes |
| `--sub-langs`                | line edit                   |
| `--merge-output-format`      | combo                       |
| `--download-archive`         | file picker                 |
| `--sponsorblock-remove`      | line edit                   |
| `--proxy`                    | line edit                   |
| `--limit-rate`               | line edit                   |

Everything else is visible in an "Other options" list (name and value, edit as
text) and in the raw tab. Growing the curated set is cheap: one table entry
mapping option name to widget type.

## 4. Cookies from browser

Flag: `--cookies-from-browser BROWSER[+KEYRING][:PROFILE][::CONTAINER]`
(there is no `--use-cookies-from-browser`).

Main window gets a checkbox **Use browser cookies** and a browser combo
(chrome, chromium, brave, edge, firefox, opera, safari, vivaldi, whale).

- The **browser spec** (browser, keyring, profile) is a yt-dlp-native value
  and lives in the yt-dlp config as `--cookies-from-browser`. Changing the
  combo on the main window writes that line.
- The **on/off state** is a Yoink preference (QSettings), default off, per
  principle 4. Off appends
  `--no-cookies-from-browser`, which overrides the config line. On appends
  `--cookies-from-browser <spec>` even if the config already has it, so the
  CLI and GUI agree.
- A per-domain override may force the toggle on or off (section 5).

Known pitfalls to surface in the UI as a tooltip or one-line warning:
Firefox must be closed or yt-dlp cannot open its locked cookie database;
Chrome on Windows 127+ uses app-bound encryption and extraction may fail
unless yt-dlp is current. "Update yt-dlp" is one click away for that reason.

## 5. Per-domain overrides (`overrides.json`)

A rule matches a URL by host suffix: `youtube.com` matches `www.youtube.com`
and `m.youtube.com`. Most specific suffix wins. One rule may carry any
subset of:

```json
{
  "domain": "youtube.com",
  "destination": "/media/video/yt",
  "cookies": "on" | "off" | null,
  "extra_args": ["-f", "bv*[height<=1080]+ba", "--embed-subs"]
}
```

Resolution per download:

1. yt-dlp config supplies defaults for everything.
2. Matching domain rule's `extra_args` are appended, then its `destination`
   as `-P`, then its `cookies` state if non-null.
3. Explicit main-window values applied last: a non-empty directory field and
   the cookies toggle, if the user touched either for this URL.

UI:

- The primary editor is the Domains tab in Preferences: a flat table with
  one row per domain and one column per supported override (domain,
  destination, cookies, extra args). Add / edit / remove rows in place.
  New override types become new columns.
- When a URL is pasted or typed, Yoink resolves the host and fills the
  directory field per section 2.3, showing the matched domain in a small
  label next to the field.
- Optional shorthand: a pin button next to the directory field saves the
  current directory as the rule's `destination` for this host. It has a
  tooltip stating exactly what it will write, and it asks for confirmation
  before replacing a destination that already exists for that domain.
  Creating a new rule needs no confirmation.

Not a goal: pattern matching beyond host suffix, per-URL-path rules, or
rules that reference other rules.

## 6. Binary management (`binary.py`)

Resolution order: QSettings override path, `yt-dlp` on PATH, Yoink-managed
copy in the app-data dir. If none, offer to download the platform asset
(`yt-dlp`, `yt-dlp.exe`, `yt-dlp_macos`) from the latest GitHub release.
Update uses the binary's own `-U` when it is the managed copy or writable;
otherwise the UI says to update via the package manager that installed it.
Version string comes from `yt-dlp --version`, shown in the status bar.

## 7. Packaging

Nuitka, `--standalone --enable-plugin=pyside6`, optional `--onefile`. The
yt-dlp binary is not bundled; it is fetched on first run or found on PATH.
Build scripts for Linux and Windows live under `build/`. CI builds are
backlog.

## 8. Phases

Each phase ends in a runnable, committed state.

**Phase 0: Walking skeleton.**
Layout, pyproject, binary discovery (PATH only), `argv.py`, `DownloadJob`,
main window with URL, directory, Start, and the table (status, URL, host,
filename, downloaded, total, speed, progress, cancel). Verify the progress
template and `--print` behaviour against a real binary. Deliverable: paste a
URL, watch it download, cancel it.

**Phase 1: Cookies toggle.**
Checkbox and browser combo on the main window; read-only parse of the yt-dlp
config to find an existing `--cookies-from-browser` line and prefill the
combo; write that one line back on change. This is the first use of
`ytdlp_config.py` and proves the round-trip model on a single option.

**Phase 2: Preferences dialog.**
Yoink tab (binary path, default directory, update policy). yt-dlp tab with
the structured view, "Other options" list, and raw text tab. Status bar shows
yt-dlp version; Update button.

**Phase 3: Per-domain overrides.**
`overrides.py`, Domains tab, URL-driven directory prefill, pin button,
cookies override. `argv.py` grows the resolution order from section 5.

**Phase 4: Distribution.**
Managed binary download and update, Nuitka build scripts, a log viewer on
row double-click, first tagged release.

**Backlog, unscheduled.**
Concurrency limit and queue, playlist entries as child rows, clipboard watch,
retry failed, drag-and-drop URLs, system tray, CI builds.

## 9. Resolved questions

- Cookies toggle defaults off on a fresh install (principle 4).
- Per-domain rules are edited in a flat table; the pin button is a
  convenience with a tooltip and a confirmation on overwrite.
- With no directory from the user, a rule, or the config, Yoink falls back to
  the OS Downloads folder (section 2.3).
