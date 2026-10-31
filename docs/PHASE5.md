# Phase 5 scope: distribution

## Status

Not started. Branch `phase-5-distribution`.

Source: [DESIGN.md](DESIGN.md) section 8, Phase 5, plus section 7.

Deliverable: a tagged release on GitHub with a downloadable build for
Windows, macOS, and Linux, release notes that get a Mac user past
Gatekeeper, and a log viewer so a failed download can be diagnosed without
a terminal.

Decisions made while scoping:

- **No signing or notarization.** There is no Apple Developer ID. Nuitka
  already ad-hoc signs the `.app`, which is what Apple Silicon needs to
  launch an unsigned binary at all. The release notes carry the "Open
  Anyway" steps. Revisit when a certificate exists: Nuitka takes
  `--macos-sign-identity` and `--macos-sign-notarization`, and `notarytool`
  does the rest, so the code change is two flags.
- **One build script.** `scripts/build.sh` stays the only build entry
  point and gains a `--release` flag that zips the result and names it
  with the version. No separate release script, no CI. Builds are made by
  hand on each OS until CI builds leave the backlog.
- **The version lives in `pyproject.toml` only.** Bumping it is a commit;
  the tag matches it. No version derived from git, no version file.
- **Nuitka stays on `app-dist`**, not `onefile`, on every OS, for the
  startup reason in DESIGN.md section 7. The Windows and Linux artifact is
  a zip of the folder; the macOS artifact is a zip of the `.app`.
- **The log viewer is a dialog, not a panel.** Double-clicking a row opens
  a read-only text view of the yt-dlp output for that job. It updates
  live while the job runs. No filtering, search, or saving; Ctrl+A and
  copy cover the "send me the log" case.
- **No app icon yet.** Nuitka's default (the Python icon) ships in the
  first release. An icon is a separate, small follow-up once there is
  artwork.

## 1. Release build (`scripts/build.sh`)

`--release` is consumed by the script, not passed to Nuitka. It:

1. Reads the version from `pyproject.toml` with a one-line `sed`, and
   refuses to run if the working tree is dirty or `HEAD` is not tagged
   `v<version>`. This keeps the artifact and the tag in step.
2. Runs the existing Nuitka command. Windows keeps
   `--windows-console-mode=attach`: it opens no console when launched from
   Explorer, and shows logs when launched from a terminal, which is what a
   bug report needs.
3. Zips the output to `dist/yoink-<version>-<os>-<arch>.zip`, where
   `<os>` is `windows`, `macos`, or `linux` and `<arch>` is `uname -m`.
   On macOS the zip is made with `ditto -c -k --keepParent` so the
   bundle's resource forks and symlinks survive; elsewhere `zip -r` or
   Python's `shutil.make_archive`, whichever is on the machine.

The test build path (no flag) is unchanged.

## 2. Log viewer (`yoink/ui/log_dialog.py`, new)

`DownloadJob` gains `log_line = Signal(str)`, emitted from the two places
`_handle_line` appends to `self.log`. Protocol lines (progress, metadata)
are not logged, as today; the viewer shows what yt-dlp printed.

`LogDialog(job, parent)`:

- Title: the job's title if metadata has arrived, else the URL.
- A read-only `QPlainTextEdit` in a monospace font, seeded with the
  command line (`binary` and `argv`, shell-quoted on one line) and the
  current `job.log`, then appended to from `log_line`. Scrolls to the
  bottom on append only if it was already at the bottom.
- A Copy button that puts the whole text on the clipboard, and Close.
- `WA_DeleteOnClose`; opening the same row twice opens a second dialog,
  which is fine.

`MainWindow` connects `table.itemDoubleClicked` (and `cellDoubleClicked`
for cells holding a widget, the progress bar and action buttons) to open
the dialog for `self.jobs[row]`. The failed-row tooltip that shows the
last 20 lines stays; the dialog is the full version.

## 3. Release notes and README

- `README.md`: a "Download" section pointing at the Releases page, the
  macOS "Open Anyway" steps (right-click > Open, or Privacy & Security >
  Open Anyway), and the note that yt-dlp is fetched on first run. The
  status line moves to "Phases 0 to 5 done".
- The GitHub release body repeats the macOS steps and lists the three
  artifacts. Written by hand at tag time; no template file.
- DESIGN.md section 7: replace "Release builds and CI builds are backlog"
  with the `--release` flag and leave CI in the backlog.

## 4. Work items

| File | Change | Lines (approx.) |
|------|--------|-----------------|
| `scripts/build.sh` | `--release`: version check, zip | 30 |
| `yoink/job.py` | `log_line` signal | 4 |
| `yoink/ui/log_dialog.py` (new) | section 2 | 60 |
| `yoink/ui/main_window.py` | double-click handler | 10 |
| `README.md`, `docs/DESIGN.md` | section 3 | docs |

Total: about 100 new lines of application code.

### Tests

- `tests/test_job.py` (new, ~20 lines): feeding a non-protocol line emits
  `log_line` and appends to `log`; a protocol line does neither.
- The dialog and the build script are checked by hand (section 6).

## 5. Out of scope

- Signing, notarization, and an Apple Developer account.
- CI builds and automatic release publishing (backlog).
- `onefile` builds, installers (MSI, DMG, AppImage, deb).
- An app icon.
- Auto-update of Yoink itself.
- Log search, filtering, persistence across restarts, or a "save log"
  button.

## 6. Tasks

Each task is one commit and leaves the app runnable. T1 and T2 are
independent; T3 follows both.

```
T1 ─┐
    ├── T3
T2 ─┘
```

### T1. Log viewer (~75 lines, tests ~20)

- Section 2.

Done when `uv run pytest` passes, a double-click on a running sandbox
download opens a dialog that fills in as yt-dlp prints, and the same on a
failed row shows the `ERROR:` line.

### T2. Release build (~30 lines)

- Section 1.

Done when `scripts/build.sh --release` refuses on a dirty tree or an
untagged `HEAD`, and on a tagged commit produces the named zip on this
machine. On macOS, the unzipped `.app` launches after "Open Anyway" and
downloads the managed yt-dlp.

### T3. Docs and release

- Section 3, then bump `pyproject.toml` to `0.1.0`, tag `v0.1.0`, build
  on each OS, and publish the release with the three zips.

### Phase 5 exit check

- `uv run pytest` passes on Windows and on macOS or Linux.
- A fresh user on each OS downloads the zip from the Releases page,
  launches Yoink, is walked through yt-dlp setup, and completes a download.
- On macOS, the release notes alone get the user past Gatekeeper.
