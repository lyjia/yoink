# Phase 4 scope: onboarding

## Status

Not started. Branch `phase-4-onboarding`.

Source: [DESIGN.md](DESIGN.md) section 8, Phase 4, plus sections 6.2 and
6.5 to 6.7.

Deliverable: on a Mac with no yt-dlp, or with a browser-downloaded and
blocked copy, a new user gets from first launch to a working download
without opening Terminal or System Settings. On Windows and Linux, the same
dialog downloads the single-file binary.

Decisions made while scoping, which change DESIGN.md sections 6.2, 6.5,
6.6, and 6.7:

- **Setup options.** The managed copy is the default button. Homebrew
  guidance is a secondary button on macOS, package-manager guidance on
  Windows and Linux. Repair appears only when the found copy is
  quarantined. pip, pipx, and uv are not offered.
- **Repair only verifies.** "Allow this copy" is enabled only when the copy
  matches the release's `SHA2-256SUMS`: a single-file binary is hashed
  directly, a folder build is compared with the zip the user points at.
  Otherwise the button stays disabled and the warning says why. The
  design's fallback of fetching a fresh zip to compare against is dropped.
- **Discovery stays flat.** Four steps (section 1). The Preferences binary
  path field lists every copy found, as paths only; no copy is probed.
- **The managed copy has a fixed path**, `<appdata>/yt-dlp/current/`, not
  a versioned directory and a settings key. Switching is a rename.
- **No new dependency.** Downloads use `QNetworkAccessManager`. Release
  assets come from `github.com/yt-dlp/yt-dlp/releases/latest/download/`,
  which redirects to the latest release, so there is no API call.
- **No staleness link** from the status bar to the setup dialog. The
  Update button already covers a stale copy.

## 1. Discovery (`yoink/binary.py`)

`find_binary(override)` looks in this order and stops at the first hit:

1. The binary path set in Preferences, used as given (unchanged).
2. The managed copy: `managed_path()` if it is a file.
3. `shutil.which("yt-dlp")`.
4. Well-known directories, through `shutil.which("yt-dlp", path=...)`:
   - macOS: `/opt/homebrew/bin`, `/usr/local/bin`, `/opt/local/bin`,
     `~/.local/bin`
   - Linux: `/usr/local/bin`, `~/.local/bin`
   - Windows: `%LOCALAPPDATA%\Microsoft\WinGet\Links`,
     `%USERPROFILE%\scoop\shims`, `%ChocolateyInstall%\bin`

   Step 4 exists because an app launched from Finder gets launchd's PATH,
   which has no `/opt/homebrew/bin` (DESIGN.md 6.2).

`candidates() -> list[Path]`: every copy that steps 2 to 4 find, in that
order, one `shutil.which` per directory. A copy reachable from two
directories (the same directory twice, or a symlink) is listed once, under
the path where it was first found. `find_binary` without an override
returns the first.

`managed_path() -> Path`: `<appdata>/yt-dlp/current/` joined with the
platform's executable name: `yt-dlp_macos/yt-dlp_macos` on macOS (the
folder build's layout), `yt-dlp.exe` on Windows, `yt-dlp_linux` on Linux.
`<appdata>` is the same branch as `overrides.rules_path()`:
`YOINK_SETTINGS_DIR` when set, else `AppDataLocation`.

`is_managed(path) -> bool`: `path == managed_path()`. The Update button and
the status bar use it.

`is_quarantined(path) -> bool`: macOS only, else `False`. One
`xattr -lr <folder>` subprocess on the binary's directory, true if the
output names `com.apple.quarantine`. The folder covers `_internal/` too.
`xattr` missing or failing counts as not quarantined, with a log warning.

`is_blocked(exited, output, path) -> bool`: the probe produced no output,
either crashed or timed out, and the binary is quarantined. This is the
SIGKILL and library-load patterns of DESIGN.md 6.6, judged after the
fact. `MainWindow._probe_done` calls it.

## 2. Managed copy (`yoink/managed.py`, new)

```
RELEASE = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"
ASSET = {"darwin": "yt-dlp_macos.zip", "win32": "yt-dlp.exe", "linux": "yt-dlp_linux"}
```

`Installer(QObject)` runs the whole sequence on the event loop and
reports with signals: `progress(int received, int total)`,
`status(str)`, `finished(str error)` with `""` on success.

1. Download `SHA2-256SUMS`, then the platform asset, into
   `<appdata>/yt-dlp/new/`. `QNetworkAccessManager` with
   `RedirectPolicyAttribute` set to follow the redirect. Body streamed to
   the file from `readyRead`. A `QNetworkReply` error or a non-200 status
   fails the step with the reply's error string.
2. `verify(asset, sums_text)`: SHA-256 of the file against the line for
   its name. Mismatch fails with "The download didn't match the published
   checksum" and deletes `new/`.
3. macOS: `ditto -x -k <zip> new/` and delete the zip. `ditto` keeps
   permission bits and symlinks, which `zipfile` does not. Other
   platforms: `chmod +x` on Linux, nothing on Windows.
4. Warm-up: run the new binary with `PROBE_ARGS` through `QProcess` with
   the probe's timeout, status "Preparing yt-dlp…". It passes when the
   process exits normally and prints the version header; the exit code is
   not the test, because yt-dlp exits 2 without a URL. A crash, timeout, or
   missing header fails with the output, so a broken download never
   replaces a working copy.
5. Switch: rename `current/` to `old/` if it exists, `new/` to `current/`,
   then delete `old/`. On any failure before this step, `current/` is
   untouched and `new/` is deleted.

`verify` and the switch are plain functions, tested against `tmp_path`.
The download is tested against the sandbox's HTTP server by hand.

`install_hint() -> tuple[str, str] | None`: the package-manager guidance
for the platform, `(label, command)`, when the manager is on PATH:
`brew install yt-dlp` on macOS (`/opt/homebrew/bin/brew` or
`/usr/local/bin/brew`), `winget install yt-dlp.yt-dlp`,
`scoop install yt-dlp`, or `choco install yt-dlp` on Windows, and
`pipx install yt-dlp` on Linux. The first one found wins.

## 3. Setup dialog (`yoink/ui/setup_dialog.py`, new)

One `QDialog`, "Set up yt-dlp", opened for every trigger and from
Help > Set up yt-dlp…. Modal over the main window. Contents, top to
bottom:

- A message label. The first sentence depends on the trigger:
  - not found: "Yoink needs yt-dlp to download videos, and couldn't find
    it."
  - quarantined: "Yoink found yt-dlp at <path>, but macOS blocks programs
    downloaded in a browser."
  - probe failed: "Yoink found yt-dlp at <path>, but it didn't run."
  - from the Help menu with a working copy: "yt-dlp <version> (<method>)
    is working."
- A read-only text box with yt-dlp's output, shown only when the probe
  failed.
- The option buttons:
  - **Download yt-dlp for me** (default). Starts `Installer`; the
    progress bar and status label below it show the steps. The other
    buttons are disabled while it runs.
  - **I use Homebrew** (macOS) or the package manager's name (Windows,
    Linux), shown when `install_hint()` finds one: the command in a
    read-only field with a Copy button, and "then click Check again".
  - **Allow this copy** (quarantined only). Enabled only after
    verification succeeds (section 4). Confirms with a Yes/No question
    naming the folder, then runs `xattr -dr com.apple.quarantine <folder>`.
  - **Check again**: runs discovery and the probe again.
- A progress bar and status label, hidden until the download starts.

The dialog does not own the probe. It emits `check_requested`, the main
window runs `refresh_config`, and `_probe_done` calls
`dialog.show_result(...)`. When the result is a working binary, the dialog
shows the version and install method with a Close button. When it is
not, the message updates and the options stay. Nothing in the flow ends
without a next step.

## 4. Repair verification (macOS)

Shown only when the found copy is quarantined. A warning box in the
dialog, red icon, states that the copy is blocked and that Yoink will
only unblock a copy it can verify.

- Single-file binary (`yt-dlp_macos`, variant `darwin_exe` or the file
  name): hash the file against the downloaded `SHA2-256SUMS`.
- Folder build: a **Choose the zip you downloaded…** button. The zip is
  hashed against the sums, then every file in the install folder is
  compared with the zip's entry of the same path. Any missing or differing
  file fails.
- Pass: "This copy matches yt-dlp <version>", button enabled.
- Fail or no zip chosen: the warning says the copy can't be verified and
  recommends the download; the button stays disabled.

After a repair, the dialog runs Check again, which warms the copy up
through the probe.

## 5. Main window and Preferences

`main_window.py`:

- `Help > Set up yt-dlp…` opens the dialog.
- `refresh_config`: no binary, or a quarantined one, opens the dialog
  instead of the status-bar text. The quarantined copy is not launched.
- `_probe_done`: a failed probe with `is_blocked` true, or with no version
  line, opens the dialog with the output. A probe that fails only to list
  its configs keeps today's "config: unknown" status.
- On startup, the dialog opens after the window is shown, through a
  zero-delay `QTimer`, so it sits over the window.
- Status bar: `(Yoink)` as the install method for the managed copy.

`prefs_dialog.py`:

- The binary path field is an editable dropdown of `candidates()`. Empty
  still means "let Yoink find it".
- **Set up yt-dlp…** beside Update emits `setup_requested`; `show_prefs`
  connects it to `show_setup`. The setup dialog opens over Preferences.
- `_update` for a `_dir` build that is not managed: the `DIR_BUILD`
  message gains a **Download Yoink's own copy** button that opens the
  setup dialog. For the managed `_dir` build, Update runs `Installer`
  directly with the same progress UI. On Windows the managed exe keeps
  using `-U` (DESIGN.md 6.4).

## 6. Sandbox (`scripts/sandbox.sh`)

New flags, each a trigger from DESIGN.md 6.7:

- `--no-yt-dlp`: a PATH without yt-dlp (`$bin` only, plus the project
  venv), and `HOME` with no well-known directories.
- `--quarantine PATH` (macOS): copy PATH into the sandbox, add the flag
  with `xattr -w com.apple.quarantine "0081;$(printf %x $(date +%s));Safari;"`
  to every file, and link it as the sandbox yt-dlp.
- `--broken-yt-dlp`: link `/usr/bin/false` (or a script that exits 1).
- `--stale-yt-dlp`: a script that prints a probe header with a version
  date more than 90 days old.

The managed copy lands in `$YOINK_SETTINGS_DIR/yt-dlp/`, so the real app
data is never touched.

## 7. Work items

| File | Change | Lines (approx.) |
|------|--------|-----------------|
| `yoink/binary.py` | steps 2 and 4, `managed_path`, `is_managed`, `is_quarantined`, `is_blocked` | 50 |
| `yoink/managed.py` (new) | `Installer`, `verify`, switch, `install_hint` | 130 |
| `yoink/ui/setup_dialog.py` (new) | sections 3 and 4 | 170 |
| `yoink/ui/main_window.py` | triggers, Help action, status bar | 40 |
| `yoink/ui/prefs_dialog.py` | Update for `_dir` builds | 20 |
| `scripts/sandbox.sh` | section 6 | 40 |

Total: about 410 new lines, bringing the app to about 2700.

### Tests (new)

- `tests/test_binary.py`: step order with a fake managed path, a
  well-known directory, and neither; `is_blocked` for crash, timeout,
  output present, and not quarantined.
- `tests/test_managed.py` (~60 lines): `verify` passing, failing, and
  with the asset absent from the sums; the switch with and without
  `current/`, and after a failed warm-up; `install_hint` with a fake
  PATH.

## 8. Out of scope

- A candidate list in Preferences (DESIGN.md 6.2), and `whereis`.
- Fetching a fresh zip to verify a folder build the user has no zip for.
- Installing Homebrew or a package manager.
- pip, pipx, and uv guidance on macOS.
- A staleness notice that opens the setup dialog.
- Checking a browser-downloaded `yt-dlp.exe` for Mark-of-the-Web. A
  manual check belongs in the exit check; code only if it fails.

## 9. Tasks

Each task is one commit and leaves the app runnable. T1 and T2 do not
depend on each other. T3 needs both.

```
T1 ─┐
    ├── T3 ── T4 ── T5 ── T6
T2 ─┘
```

### T1. Discovery and quarantine (~50 lines, tests ~40)

- Section 1.

Done when `uv run pytest` passes, including the section 7 tests, and a
Homebrew yt-dlp is found with `PATH=/usr/bin:/bin`.

### T2. Managed copy (~130 lines, tests ~60)

- Section 2.

Done when:
- `uv run pytest` passes.
- A download from a sandbox HTTP server serving a fake asset and sums
  file lands in `current/`, and a wrong sum leaves `current/` untouched.
- On macOS, the real asset downloads, extracts, warms up, and runs with
  no Gatekeeper prompt.

### T3. Setup dialog (~170 lines)

- Sections 3 and 4.

Done when:
- With `--no-yt-dlp`, the dialog opens on startup, the download completes,
  and the dialog shows the version.
- The Homebrew or package-manager button shows the right command.
- With `--quarantine`, the warning shows, the button is disabled until a
  matching zip is chosen, and the repair clears the flag.

### T4. Triggers and Update (~60 lines)

- Section 5.

Done when:
- Each of the four sandbox triggers opens the dialog with its own first
  sentence, and Help > Set up yt-dlp… opens it with a working copy.
- Update on a managed `_dir` build re-downloads; on a user's `_dir`
  build it offers the managed copy.
- The status bar shows `(Yoink)` for the managed copy.

### T5. Sandbox (~40 lines)

- Section 6. Written alongside T3 and T4 as their checks need it, and
  committed last.

### T6. Docs

- Fill in this file's Status section, update DESIGN.md sections 6.2 and
  6.5 to 6.7 for the decisions above, mark Phase 4 done in section 8, and
  update the README status line.

### Phase 4 exit check

- `uv run pytest` passes on Windows and on macOS or Linux.
- The deliverable, on a Mac with no yt-dlp and on a Mac with a quarantined
  folder build.
- A download with the managed copy on Windows and Linux.
- A browser-downloaded `yt-dlp.exe` launched by Yoink on Windows, to
  settle the SmartScreen question in DESIGN.md 6.7.
