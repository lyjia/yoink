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

If `YOINK_SETTINGS_DIR` is set, QSettings is stored as `yoink.ini` in that
directory instead of the OS-native store. The sandbox
(`scripts/sandbox.sh`) uses it, because on macOS QSettings ignores `$HOME`.

### 2.2 Command line assembly (`argv.py`)

Order matters because later flags override earlier ones, and yt-dlp applies
the config file before anything on the command line.

```
yt-dlp
  [domain override extra args]          # section 5
  [-P <dir>]                            # see 2.3
  [--cookies-from-browser <browser> | --no-cookies-from-browser]  # section 4
  --no-simulate --progress --newline --quiet
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

Yoink passes `--progress` on the command line, which beats `--quiet` or
`--no-progress` in a user config, so the protocol lines still arrive.
Phase 0 checked this for `--quiet`; a config's `--no-progress` has not
been tested. If progress lines don't arrive anyway, the job stays in
`starting` with an indeterminate bar until `DONE` or exit. This is treated
as supported, not an error.

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

The probe is a `QProcess`, like a download:

- Its working directory is the Downloads folder, as for downloads (2.3).
  With no `-P`, yt-dlp looks for a Home config in the working directory.
  Known edge case, not handled: yt-dlp looks for its Home config
  (`yt-dlp.conf`) in the home path. A download with a directory override
  passes `-P <dir>`, so yt-dlp looks in `<dir>` instead, and could load a
  Home config the probe never saw. This only matters if the user keeps a
  `yt-dlp.conf` inside their download directories.
- Stdin is closed at start, so a config containing `--config-locations -`
  can't hang it.
- It is killed after 20 s. That leaves room for the 6.5 s macOS
  single-file build and catches a quarantined copy that hangs (6.6).
- Download is disabled while it runs. Until it reports, Yoink can't tell
  whether an empty directory field means no `-P` or the Downloads folder.
- A run that is killed, times out, or reports any error other than the
  missing URL (a bad config, a missing include) may have listed only some
  files. Yoink then treats the config as unknown, even after a failed
  Refresh: **Config default** with no value, no indicator, and the
  Downloads folder as `-P`.
- Every probe also prints yt-dlp's warning "Long argument string
  detected. Use -- to separate parameters and URLs, like this: …", with a
  suggested command line containing `--no-update`. It is harmless, and the
  parser ignores it.

Status bar text:

| State | Text |
|-------|------|
| No yt-dlp on PATH | "yt-dlp not found on PATH", and Download stays disabled |
| Probe running | "Checking yt-dlp…" |
| Probe succeeded | "yt-dlp 2026.10.21 (pip)", or "yt-dlp unknown version" if the debug header can't be parsed |
| Probe failed | "yt-dlp 2026.10.21 (pip), config: unknown", or "yt-dlp config: unknown" with no version |

Yoink never decides which file wins. When a setting shown on the main
window appears in more than one loaded file, the status bar shows a warning
icon and "Some configuration values overridden". Clicking it opens a
dialog listing each occurrence with its file. The Filename column shows
the path yt-dlp actually wrote to.

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

Users install yt-dlp in many different ways, and Yoink has to work with
whichever one they used, without asking them to reinstall. Yoink never
changes how yt-dlp was installed. It finds the binary (6.2), asks yt-dlp
what kind of build it is (6.3), and fits updates and warnings to that
(6.4). It downloads a copy of its own only when the user agrees (6.5).

### 6.1 Install methods

The startup times were measured on macOS 15.8.2 with yt-dlp 2026.10.21.
The other values come from yt-dlp's `update.py`.

| Method | Typical location | yt-dlp reports | Startup | Updated by |
|--------|------------------|----------------|---------|------------|
| Homebrew | `/opt/homebrew/bin` (Apple silicon), `/usr/local/bin` (Intel), linked from `Cellar/` | `(pip)` | fast | `brew upgrade yt-dlp` |
| pip, pipx, uv tool | a venv's `bin/`, `~/.local/bin` | `(pip)` | fast | the same tool |
| MacPorts, Linux distro packages | `/opt/local/bin`, `/usr/bin` | `(pip)`, or a packager's own variant marked `*` | fast | the package manager |
| Single-file binary: `yt-dlp_macos`, `yt-dlp_linux`, `yt-dlp.exe` | wherever the user saved it | `(darwin_exe)`, `(linux_exe)`, `(win_exe)` | macOS: **6.5–6.8 s on every launch** | `-U`, if the file is writable |
| Folder build: `yt-dlp_macos.zip` and the other platforms' equivalents | wherever the user unpacked it | `(darwin_dir)` and the like | 6.6 s on the first launch, then 0.19 s | re-download only; `-U` refuses |
| Python zipapp: `yt-dlp` | anywhere | `(zip)` | fast | `-U` |
| Yoink-managed (Phase 4) | `<appdata>/yt-dlp/<version>/` | `(darwin_dir)` on macOS | as for the folder build | Yoink re-downloads it (6.5) |

Notes:

- On macOS, single-file binaries and folder builds downloaded in a
  browser are quarantined and blocked by Gatekeeper (6.6). The folder
  build is effectively uninstallable this way, with one block per bundled
  native library (102 of them). Homebrew, pip, and copies Yoink downloads
  itself are not affected. For a manual install on a Mac, Homebrew is the
  realistic choice.
- The zipapp needs Python 3.10 or later on PATH. The `python3` that comes
  with Apple's Command Line Tools is 3.9.6, so on a stock Mac the zipapp
  does not run.
- One machine can have several installs at once, for example a stale
  Homebrew copy alongside a newer single-file binary.

### 6.2 Finding the binary

Yoink looks in this order and stops at the first hit:

1. The binary path set in Preferences.
2. The Yoink-managed copy, if there is one. It comes before PATH because
   the user chose it, possibly to get away from a blocked or stale copy on
   PATH (6.6).
3. `yt-dlp` on PATH.
4. Well-known locations that might not be on PATH: `/opt/homebrew/bin`,
   `/usr/local/bin`, `/opt/local/bin`, `~/.local/bin`, and `~/bin`, plus the
   usual winget, Scoop, and Chocolatey shim directories on Windows. This
   step matters on macOS. An app launched from Finder or the Dock gets
   launchd's PATH, `/usr/bin:/bin:/usr/sbin:/sbin` (checked on this
   machine), so a packaged Yoink.app would never see a Homebrew or pipx
   install through PATH alone.
5. Nothing found: open the setup screen (6.7).

Preferences lists every candidate found, with its version and install
method, so the user can choose between several installs. The status bar
shows the binary in use and its method.

PATH entries are often symlinks; Homebrew's always are. Yoink launches the
path as it found it and resolves the link only to identify the install
method. A folder build symlinked onto PATH has not been verified yet:
PyInstaller has to find `_internal/` through the link.

### 6.3 Identifying the build

The config probe (3.4) already runs `yt-dlp -v`, and its debug header says
which build yt-dlp is:

```
[debug] yt-dlp version stable@2026.10.21 from yt-dlp/yt-dlp [8cdf4fea4] (darwin_dir)
```

From this line Yoink takes the version, channel, and variant. A trailing
`*` means a repackager set its own variant. The probe replaces the
separate `yt-dlp --version` call, which costs 6.5 s on the macOS single-file
build and runs on the UI thread in Phase 0.

`(pip)` covers pip, pipx, uv, and Homebrew alike, so Yoink narrows it down
using the resolved path:

| Path contains | Install method |
|---------------|----------------|
| `/Cellar/` | Homebrew |
| `/opt/local/` | MacPorts |
| `pipx/venvs` | pipx |
| `uv/tools` | uv tool |
| anything else | pip |

The probe also passes on yt-dlp's own staleness warning ("Your yt-dlp
version (…) is older than 90 days!"). Yoink shows it in the status bar,
because an old yt-dlp is the usual reason that sites and cookie extraction
break.

On the macOS single-file build (`darwin_exe`), the status bar warns that
each download starts about 6 s late, and suggests the folder build or
Yoink's own copy.

### 6.4 Updating

Yoink offers an update action only when yt-dlp itself supports one, and
otherwise tells the user what to run:

| Variant | Update button does |
|---------|--------------------|
| `zip`, `*_exe` (the variants yt-dlp can update) | runs `-U` if the binary is writable, shows its output, and runs the probe again |
| `*_dir`, user's own copy | explains that yt-dlp can't update this build itself, and offers to switch to Yoink's copy |
| `*_dir`, Yoink-managed | Yoink re-downloads it (6.5) |
| `pip` | shows the right command for the detected method (`brew upgrade yt-dlp`, `pipx upgrade yt-dlp`, `uv tool upgrade yt-dlp`, or `python3 -m pip install -U yt-dlp`) with a Copy button; Yoink never runs package managers itself |
| starred or unknown | shows yt-dlp's own update hint |

### 6.5 Yoink-managed copy (Phase 4)

If the user agrees, Yoink downloads the platform asset from the latest
GitHub release and checks it against the release's `SHA2-256SUMS`:
`yt-dlp_macos.zip` on macOS (the reason is in 6.6), `yt-dlp_linux` on
Linux, and `yt-dlp.exe` on Windows. The procedure on macOS is in 6.6.

### 6.6 macOS: Gatekeeper and quarantine

Getting yt-dlp onto a Mac by hand is a real failure point for users, and
the most likely reason a new user reports "Yoink doesn't work". The facts
below were checked on 2026-10-25 against macOS 15.8.2 and yt-dlp
2026.10.21.

**What blocks a manual install**

- Both macOS assets, `yt-dlp_macos` (single file) and `yt-dlp_macos.zip`
  (a folder with an `_internal/` directory), are universal2 binaries with
  an ad-hoc signature only. They have no Developer ID and are not
  notarized, so `spctl --assess` rejects them.
- A browser download gets the `com.apple.quarantine` attribute. Unzipping
  passes it on to the extracted files, even when the command-line `unzip`
  does the extraction.
- Gatekeeper enforces its verdict only on quarantined files. When a user
  downloads the zip in a browser and opens it in Finder, the binary is
  blocked. Since macOS 15 the Control-click > Open bypass is gone (that is
  Apple's documented change and was not re-tested here): the user has to
  try to run it, then go to System Settings > Privacy & Security >
  "Open Anyway", or run `xattr -dr com.apple.quarantine <folder>` in
  Terminal. Neither is something most GUI users will find on their own.
- Homebrew installs are not quarantined and just work. They are only as
  current as the user's last `brew upgrade`, and `-U` does not apply to
  them.

**Field report: installing the folder build by hand (2026-10-25)**

Downloading `yt-dlp_macos.zip` in Firefox and unpacking it produced an
endless run of Gatekeeper blocks. Approving the main executable is not
enough. Every native library in the bundled Python is quarantined too, and
each one is blocked separately when yt-dlp loads it. The zip contains 102
of them (`.so` and `.dylib` files in `_internal/`, among them `libssl`,
`libcrypto`, and the extension modules), so the user faces up to 102
separate "Open Anyway" trips through System Settings. In practice the
folder build cannot be installed through the GUI.

The single-file build should need only one approval, because it unpacks
its libraries itself, as a process that doesn't add quarantine. This has
not been verified, and the build still costs 6.5 s on every launch.

**Conclusion:** of the ways a user can install yt-dlp by hand, Homebrew is
the only one a typical Mac user can actually get working. Release assets
downloaded in a browser need Terminal (`xattr -dr com.apple.quarantine`),
and pip, pipx, and uv need a newer Python than macOS ships (6.1). The
other painless path is a copy that Yoink downloads itself (below).

**What doesn't block**

Files written by a program that isn't marked as quarantine-aware, such as
`curl` or Python's `requests`, get no quarantine attribute. Both assets,
downloaded that way, ran with no prompt even though `spctl` still reports
"rejected". This is why the Yoink-managed copy is the frictionless path
on macOS.

**Which asset to use**

| Asset | Size | Startup | `-U` |
|-------|------|---------|------|
| `yt-dlp_macos` (single file) | ~35 MB | 6.5–6.8 s **on every launch** (it unpacks itself each time) | supported |
| `yt-dlp_macos.zip` (folder) | 123 MB unpacked | 6.6 s on the first launch, then 0.18–0.19 s; the probe takes 0.33 s | not supported: "Re-download the latest release" |

Yoink starts yt-dlp for the probe and for every download, so a 6.5 s
startup is unacceptable. **Yoink manages the folder build.**

**Plan for the managed copy (Phase 4)**

1. Download `yt-dlp_macos.zip` and `SHA2-256SUMS` from the release with
   `requests`, and check the SHA-256 before extracting anything.
2. Extract into a new versioned directory under app data, such as
   `<appdata>/yt-dlp/2026.10.21/`. Python's `zipfile` drops permission
   bits, so restore the executable bits from each entry's `external_attr`,
   or extract with `ditto -x -k`.
3. Run `--version` once as a warm-up while showing "Preparing yt-dlp…", so
   the slow first launch never happens during a download.
4. Switch over atomically by recording the new path in QSettings, then
   delete the old version. If any step fails, the previous version stays
   in use.
5. Updating means repeating steps 1–4 with the latest release. The folder
   build cannot update itself with `-U`.

**A user-supplied binary that is quarantined** (on PATH or set as the
binary path):

- Before launching it, check the binary and its `_internal/` folder for
  `com.apple.quarantine`. Python's `os.getxattr` doesn't exist on macOS,
  so use `xattr -p`, or `getxattr` through `ctypes`.
- If it is quarantined, don't launch it. Show a dialog that explains why
  macOS blocks it and offers:
  1. **Use Yoink's own copy** (recommended): starts the managed download
     above.
  2. **Allow this copy**: after an explicit confirmation naming the path,
     run `xattr -dr com.apple.quarantine` on the binary's folder. Offer
     this only if the user owns the files. Never do it silently.
  3. A short guide to Privacy & Security > Open Anyway.
- **What happens if Yoink launches a quarantined binary anyway** (checked
  on 2026-10-25). There are two patterns:
  - **Killed at launch.** A freshly unpacked copy is killed with SIGKILL
    before it writes any output, and macOS may show its blocked-app
    dialog.
  - **Hangs on a library load.** In a real install whose main executable
    had already been allowed, the executable started, but loading the
    first bundled library (`_internal/.../_struct.cpython-314-darwin.so`)
    was refused ("library load disallowed by system policy" in the
    kernel log), with a dialog each time. The process then hung until
    Phase 0's 15 s `--version` timeout killed it.

  So a yt-dlp that times out with no output, from a folder that carries
  the quarantine flag, should be treated as blocked, the same as a
  SIGKILL. Every probe and download needs a timeout for this reason. The
  probe has had one since Phase 1 (20 s, 3.4); downloads don't yet.

  In `QProcess` terms, the first should show up as `CrashExit` with no
  output, and the second as a timeout with no output. Either one, together
  with a quarantine flag on the binary, lets Yoink explain the failure
  after the fact as well as preventing it with the check before launch.
  Confirm the exact `QProcess` signals in Phase 4.

The same applies to any binary the user chooses in Preferences (Phase 2).

### 6.7 Onboarding: first-run setup (Phase 4)

Most of the friction a new user meets is getting a working yt-dlp, not
using Yoink. Instead of a "yt-dlp not found" message in the status bar,
Yoink walks the user to a working install with a setup screen. The same
screen stays reachable later through Help > Set up yt-dlp….

**When it appears**

| Situation | How Yoink knows | Behaviour |
|-----------|-----------------|-----------|
| No yt-dlp found | discovery (6.2) finds nothing | setup screen |
| Found, but macOS will block it | quarantine flag on the binary or `_internal/` (6.6) | setup screen offering repair (C) |
| Found, but it doesn't run | the probe fails: SIGKILL with no output (6.6), a zipapp with too old a Python (6.1), or a crash | setup screen with yt-dlp's error text |
| Found and working, but stale or slow | the probe's staleness warning; `darwin_exe` (6.3) | non-blocking status-bar notice linking to the screen |

**Flow**

1. Say in one sentence what is wrong ("Yoink needs yt-dlp to download
   videos, and couldn't find it"), then list the options below in order
   of preference for the platform.
2. After any action, run discovery and the probe again. If they succeed,
   show the version and install method, then close.
3. Run the warm-up before closing (6.6), so the first download doesn't
   pay the 6 s first launch.
4. Never leave the user at a dead end. Each failure leads back to the
   screen with yt-dlp's own error text and the remaining options.

**Options on macOS** (decision pending):


- **A. Homebrew guidance.**
  - If `brew` exists (`/opt/homebrew/bin/brew` or `/usr/local/bin/brew`),
    show `brew install yt-dlp` with a Copy button, or open Terminal with
    the command ready to run, then re-run discovery.
  - If `brew` is missing, point to brew.sh. Installing Homebrew itself
    needs an admin password and the Command Line Tools, which is a lot to
    ask of a non-technical user.
  - Updates later go through `brew upgrade` (6.4).
- **B. Yoink downloads its own copy (6.5).** One button, no Gatekeeper
  prompts (tested in 6.6), and checksum-verified. The costs: 123 MB, Yoink
  takes on updates, and Yoink downloads and runs an unnotarized binary on
  the user's behalf.
- **C. Repair a blocked copy.** If the user already downloaded a release
  asset, one confirmed "Allow this copy" replaces up to 102 System Settings
  trips. **Verified 2026-10-25:**
  - Unzipping the browser-downloaded zip left 163 quarantined files.
  - `xattr -dr com.apple.quarantine <folder>` cleared all of them in under
    10 ms, and **without sudo**, because the user owns files they
    downloaded.
  - yt-dlp then ran with no prompts at all: 6.35 s on the first launch
    (macOS scanning the bundle), then 0.19 s.
  - Control: a copy that still had the flag, launched the same way, was
    killed at launch (SIGKILL, before printing anything). So Gatekeeper was
    enforcing in the test environment, and the clean run is not explained
    by a "Developer Tools" exemption for the launching app. With no
    quarantine attribute, Gatekeeper doesn't assess the file at all, so
    there is no "Open Anyway" or "downloaded from the internet" prompt on
    first run. The 6 s first launch is the background malware scan, and it
    shows no dialog.

  Details:
  - **Admin rights only when needed.** They are required only if the files
    belong to another user, for example something an admin copied into
    `/usr/local`. Ask for them only then, through the standard macOS
    password dialog (`osascript -e 'do shell script "…" with administrator
    privileges'`), never through a sudo prompt in a terminal.
  - **No `spctl`.** `spctl --add` and changing Gatekeeper's global settings
    are not needed. They require admin rights, and macOS 15 restricts them.
  - **Integrity.** Removing quarantine skips Gatekeeper's check for that
    code, so Yoink should confirm the files are genuine first. That is
    only possible while the original download exists. If the zip, or the
    single-file binary, is still there, Yoink checks its SHA-256 against
    the release's `SHA2-256SUMS`. The published sums cover only the zip
    and the single-file binary. An unpacked folder can still be checked
    file by file against a zip that passes that check: either the user's
    original download, or a fresh copy of the same release that Yoink
    fetches. This was done on 2026-10-25 for a real manual install:
    134 of 134 files were identical. If no matching zip is available, the
    dialog says the copy can't be verified and recommends B. The user's
    explicit confirmation stays mandatory either way.
  - Do the same warm-up as in the managed-copy plan, so the 6 s first
    launch doesn't land on a download.
- **D. pip, pipx, or uv.** Not for typical users: they need Python 3.10
  or later, and stock macOS has 3.9.6.


A likely shape: offer B as the default and A as "I prefer Homebrew", and
show C only when a quarantined copy is detected. This needs a decision
before Phase 4 starts, and possibly before Phase 2's binary picker.

**Other platforms**

- Windows:
  - B (managed `yt-dlp.exe`, which can update itself with `-U`, 6.4).
  - Package-manager guidance, shown when one is detected:
    `winget install yt-dlp.yt-dlp`, `scoop install yt-dlp`, or
    `choco install yt-dlp`.
  - Still to check: whether a browser-downloaded `yt-dlp.exe` carrying a
    Mark-of-the-Web triggers SmartScreen when Yoink launches it with
    `CreateProcess`.
- Linux:
  - B (managed `yt-dlp_linux`).
  - Guidance for pipx, or for the distribution's package. Distribution
    packages are often months behind, so the staleness notice matters
    most here.

**Testing**

The sandbox (`scripts/sandbox.sh`) needs to cover each trigger:

- **No yt-dlp:** a PATH without yt-dlp, and no binary path setting.
- **Quarantined copy:** add the flag to a copy with
  `xattr -w com.apple.quarantine "0081;$(printf %x $(date +%s));Safari;" <file>`.
- **Non-running binary:** a binary path pointing at `/usr/bin/false`.
- **Stale version:** a fake binary script that prints the probe output,
  including the staleness warning.

## 7. Packaging

Nuitka, `--standalone --enable-plugin=pyside6`, optional `--onefile`. The
yt-dlp binary is not bundled; it is fetched on first run or found on PATH.
Build scripts for Linux and Windows live under `build/`. CI builds are
backlog.

macOS: Yoink.app runs into the same Gatekeeper problem as yt-dlp (6.6). An
unsigned app downloaded in a browser is blocked until the user clicks
"Open Anyway" in Privacy & Security. Removing that friction takes a
Developer ID certificate (Apple Developer Program) plus notarization in the
release build. Until then, the release notes must spell out the "Open
Anyway" steps. Prefer the standalone `.app` over `--onefile` on macOS,
because the onefile startup penalty measured for yt-dlp (6.6) applies here
too. A notarized Yoink must not set `LSFileQuarantineEnabled`, or the
yt-dlp it downloads would be quarantined (6.6).

## 8. Phases

Each phase ends in a runnable, committed state.

**Phase 0: Walking skeleton.**
Layout, pyproject, binary discovery (PATH only), `argv.py`, `DownloadJob`,
main window with URL, directory, Start, and the table (status, URL, host,
filename, downloaded, total, speed, progress, cancel). Verify the progress
template and `--print` behaviour against a real binary. Deliverable: paste a
URL, watch it download, cancel it.

**Phase 1: Main-window overrides and cookies.**
Config probe (3.4), which also provides the yt-dlp version shown in the
status bar (6.3) instead of the blocking `--version` call. Cookies combo
and directory field as override controls, a Reset button, and restoring overrides on the next launch. Honour `-P` from
the config (2.3). Overrides indicator and dialog. No config writes. Scope:
[PHASE1.md](PHASE1.md). Done; the status and deviations are at the top of
PHASE1.md.

**Phase 2: Preferences dialog.**
Yoink tab: binary path, with every candidate found by 6.2 listed along
with its version and install method, and update policy. yt-dlp tab with
the structured view, "Other options" list, and raw text tab. This is the
first config write: the line model, round-trip writer, and consistency
check (3.2, 3.4). The status bar, which shows the version since Phase 1,
gains the install method (6.3), yt-dlp's staleness warning, and the
slow-start warning for the macOS single-file build. Update button per 6.4.

**Phase 3: Per-domain overrides.**
`overrides.py`, Domains tab, URL-driven directory prefill, pin button,
cookies override. `argv.py` grows the resolution order from section 5.

**Phase 4: Onboarding.**
Decide the setup-flow options first (6.7). Then build:

- The first-run setup screen and its triggers (6.7), including Help > Set
  up yt-dlp….
- The managed binary download and update (6.5). On macOS that is the
  folder build with checksum verification and a warm-up (6.6).
- Quarantine detection before launch, and recognising the SIGKILL pattern
  after launch.
- The confirmed repair flow (6.6, option C).
- Homebrew and package-manager guidance.
- Discovery in well-known locations (6.2), if Phase 2 hasn't already added
  it.
- Sandbox coverage for each trigger.

Deliverable: on a Mac with no yt-dlp, or with a browser-downloaded and
blocked copy, a new user gets from first launch to a working download
without opening Terminal or System Settings.

**Phase 5: Distribution.**
Nuitka build scripts, macOS signing and notarization or documented "Open
Anyway" steps (section 7), a log viewer on row double-click, first tagged
release.

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