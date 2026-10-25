# Yoink design spec

A small Qt front end for yt-dlp. yt-dlp's own config file is the source of
truth for every yt-dlp-native setting; Yoink stores only front-end state.
Downloads appear as rows in a table. The yt-dlp binary is driven as a child
process; nothing from yt-dlp is imported into the Python process.

## 1. Principles

1. **One source of truth per setting.** If yt-dlp has a flag for it, it lives
   in yt-dlp's config file and the CLI sees the same value Yoink does. If it
   is Yoink-only (window size, main-window overrides, per-domain rules), it
   lives in Yoink's own storage. No setting is stored in both places. Yoink writes
   to the yt-dlp config only from the Preferences dialog.
2. **The main window overrides, it never saves.** Each main-window control
   either follows the config, passing nothing and showing the config's
   value, or overrides it for Yoink's downloads by passing a flag on the
   command line. Overrides are Yoink state and never reach plain `yt-dlp`
   runs. A Reset button returns every control to following the config.
3. **Drive the binary, never import.** One `QProcess` per download. Cancel is
   `kill()`. Progress is parsed from stdout. No threads.
4. **Never clobber the user's config.** Edits to the yt-dlp config are
   line-level and round-trip: comments, ordering, and lines Yoink does not
   understand are preserved byte for byte.
5. **Defaults equal an empty yt-dlp config.** A fresh Yoink install with no
   yt-dlp config behaves exactly as `yt-dlp <url>` would from the OS
   Downloads folder. Yoink adds nothing the user did not configure, with the
   sole exception of the download directory, because a GUI app has no
   meaningful working directory.
6. **Keep it small.** Target under 1500 lines of application code. No plugin
   system, no database, no async framework.

## 2. Architecture

```
yoink/
  __main__.py        QApplication bootstrap
  app.py             paths, QSettings keys, logging setup
  binary.py          locate / download / update the yt-dlp executable
  ytdlp_config.py    probe loaded configs; read, edit, write (round-trip)
  overrides.py       per-domain override rules (load, match, save)
  argv.py            build the yt-dlp command line for one download
  job.py             DownloadJob: QProcess wrapper, progress line parser
  ui/
    main_window.py   URL input, override controls, downloads table
    config_notice.py config override details dialog
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
| Window geometry, main-window overrides (directory, cookies), binary path, update policy | QSettings (`Lyjia/Yoink`) |
| Per-domain overrides         | `overrides.json` in Yoink's app-data dir            |

Per-domain rules are a list of structured records; QSettings handles those
poorly, so they get a JSON file next to the QSettings store.

### 2.2 Command line assembly (`argv.py`)

Order matters because later flags override earlier ones, and yt-dlp applies
the config file before anything on the command line.

```
yt-dlp
  [domain override extra args]          # section 5
  [-P <dir>]                            # see 2.3
  [--cookies-from-browser <browser> | --no-cookies-from-browser]  # section 4
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

1. The directory field in the main window, if the user typed or picked
   one (an override).
2. The matching domain rule's `destination`.
3. A home path set by `--paths` / `-P` in any loaded config, where the value
   has no type prefix or includes `home`. Yoink passes no `-P` and lets
   yt-dlp resolve. The placeholder shows the path when all occurrences
   agree, and "Set by yt-dlp config" otherwise.
4. Otherwise the OS Downloads folder (`QStandardPaths.DownloadLocation`),
   passed as `-P`.

Step 3 comes before step 4 to keep principle 5: a user who set a directory
in their config never has it overridden by a Yoink fallback. The child's
working directory is always the Downloads folder, so a config with only
`-P temp:` still lands somewhere predictable.

### 2.4 Download job (`job.py`)

`DownloadJob(QObject)` owns one `QProcess`. It splits stdout on newlines,
routes lines starting with `YOINK\t` to typed signals
(`file_named`, `progress`, `postprocessing`, `done`), and appends everything
else to an in-memory log. States: `queued`, `starting`, `downloading`,
`postprocessing`, `finished`, `failed`, `cancelled`. Exit code non-zero with
no `DONE` line means `failed`; the last stderr lines become the row's error
text.

It also recognises yt-dlp's `Extracted <n> cookies from <browser>` line
(and the errors from extraction) and emits `cookies`, so each row shows
which browser yt-dlp actually used. Yoink does not pass `--quiet`, because
it would hide that line.

If a user config contains `--quiet` or `--no-progress`, no progress lines
arrive. The job then stays in `starting` with an indeterminate bar until
`DONE` or exit. This is treated as supported, not an error.

Playlists: each entry produces its own `FILE`/`DL`/`DONE` sequence. Phase 0
shows them in one row with the current filename; splitting into child rows
is backlog.

## 3. yt-dlp config editing (`ytdlp_config.py`)

### 3.1 Which file

Yoink edits the file the config probe (3.4) reports as yt-dlp's `User
config`. yt-dlp picks it from several candidates (`yt-dlp.conf`,
`yt-dlp/config`, `config.txt`, under XDG, APPDATA, or home), and Yoink does
not repeat that search. If yt-dlp loaded no user config, Yoink creates:

- Linux/macOS: `${XDG_CONFIG_HOME:-~/.config}/yt-dlp/config`
- Windows: `%APPDATA%\yt-dlp\config`

The Preferences dialog shows the path. Portable, home, system, and
`--config-locations` files are never edited.

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

### 3.4 Config probe and overrides indicator

`yt-dlp -v --no-update --no-cookies-from-browser`, run with no URL, prints
`[debug] <Label> config "<path>": [tokens]` for every config file it
loaded, then exits. Yoink parses those lines to learn which files yt-dlp
loaded and their contents, using yt-dlp's own tokenization. The
`--no-cookies-from-browser` stops yt-dlp opening a browser's cookie
database during the probe. The probe runs at startup, after each write
from Preferences, and on File > Refresh config.

Yoink never decides which file wins. When a setting shown on the main
window appears in more than one loaded file, the status bar shows a warning
icon and "Some configuration values overridden". Clicking it opens a
dialog listing each occurrence with its file. Rows in the downloads table
report what yt-dlp actually did (section 2.4).

Before saving, Phase 2's editor compares its line-level parse with the
probe's tokens for the same file. If they differ (for example a quoted
value spanning lines, or a `#` inside a word), the structured view is
read-only for that file.

## 4. Cookies from browser

Flag: `--cookies-from-browser BROWSER[+KEYRING][:PROFILE][::CONTAINER]`
(there is no `--use-cookies-from-browser`).

The main window has a single cookies combo, which is an override control
under principle 2:

| Item                          | Passes                               |
|-------------------------------|--------------------------------------|
| Config default (`<value>`)    | nothing                              |
| No cookies                    | `--no-cookies-from-browser`          |
| brave, chrome, chromium, edge, firefox, opera, safari, vivaldi, whale | `--cookies-from-browser <browser>` |

- The full spec (browser, keyring, profile, container) is a yt-dlp-native
  value. It is edited only in Preferences and used through
  **Config default**. A main-window override passes only the browser name.
- The default is **Config default**, so a fresh install with an empty
  config loads no cookies (principle 5).
- A per-domain rule may force cookies on or off (section 5).

Known pitfalls to surface in the UI as a tooltip or one-line warning:
Firefox must be closed or yt-dlp cannot open its locked cookie database;
Chrome on Windows 127+ uses app-bound encryption and extraction may fail
unless yt-dlp is current; Safari on macOS needs Full Disk Access. "Update yt-dlp" is one click away for that reason.

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
3. Main-window overrides are applied last: a non-empty directory field,
   and a cookies combo not set to **Config default**. Reset clears them,
   including a rule's prefilled destination, until the next URL is
   entered.

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

**Phase 1: Main-window overrides and cookies.**
Config probe (3.4). Cookies combo and directory field as override controls,
a Reset button, and restoring overrides on the next launch. Honour `-P` from
the config (2.3). Overrides indicator and dialog. Each row shows the
browser yt-dlp actually used for cookies. No config writes. Scope:
[PHASE1.md](PHASE1.md).

**Phase 2: Preferences dialog.**
Yoink tab (binary path, update policy). yt-dlp tab with the structured
view, "Other options" list, and raw text tab. This is the first config
write: the line model, round-trip writer, and consistency check (3.2,
3.4). Status bar shows yt-dlp version; Update button.

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

- The yt-dlp config is written only from Preferences. Main-window controls
  are overrides that are restored on the next launch and cleared by Reset
  (principle 2).
- Cookies default to **Config default**, which loads no cookies on an
  empty config (principle 5).
- Yoink does not search for config files or work out precedence. yt-dlp
  reports what it loaded, and Yoink warns about conflicts (3.4).
- Per-domain rules are edited in a flat table; the pin button is a
  convenience with a tooltip and a confirmation on overwrite.
- With no directory from the user, a rule, or the config, Yoink falls back to
  the OS Downloads folder (section 2.3).

## 10. Feature wishlist

* Explorer/Finder/file manager integration - "Yoink here" right-click menu entry for directories, which opens a new Yoink instance with the destination set to the directory. If a Yoink window is already open, the destination folder is instead set to the requested directory. This may require some sort of configuration override feature, if settings (such as per-domain override) already dictate the destination