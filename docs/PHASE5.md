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
- **Versioning is YAAMT's, code and scheme.** `yoink/version.py` is
  YAAMT's `src/util/version.py` with its logging import swapped for
  `logging.getLogger`: `M.m.p` on a clean `v*.*.*` tag, `M.m.p+N.<hash>`
  N commits past it, `.dirty` with uncommitted changes, `0.0.0+N.<hash>`
  with no tag reachable, `0.0.0` without git. A source checkout runs
  `git describe` at startup; a frozen build reads a stamped constant.
  Keeping the file identical to YAAMT's is deliberate, so the two can be
  merged into one module later. `importlib.metadata` and
  `--include-distribution-metadata` go away.
- **The stamp is a generated file, not a patched source.** `build.sh`
  writes `yoink/_version.py` containing `VERSION_STRING = "..."` before
  Nuitka runs and deletes it after; the file is gitignored.
  `version.py` does `from yoink._version import VERSION_STRING` inside a
  `try`, falling back to git. No temp workspace copy as in YAAMT.
- **pyproject follows the tag** through setuptools' dynamic version:
  `dynamic = ["version"]` and
  `[tool.setuptools.dynamic] version = {attr = "yoink.version.__version__"}`.
  setuptools imports the module at build time, which runs the same
  `git describe`. No plugin, no bump commit.
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

1. Reads the version with `uv run python -m yoink.version` and refuses
   to run unless it is a bare `M.m.p` (clean tree, on a tag). This is
   YAAMT's publish check, done locally.
2. Writes `yoink/_version.py`, runs the existing Nuitka command without
   `--include-distribution-metadata`, and removes the file in a `trap`
   so a failed build does not leave a stale stamp behind. The test build
   writes the stamp too, so `dist/` builds report their commit. Windows keeps
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
| `yoink/version.py` (new) | YAAMT's module, `__version__` | 120 |
| `yoink/__init__.py`, `pyproject.toml`, `.gitignore` | dynamic version, stamp file | 10 |
| `scripts/build.sh` | stamp, `--release`: version check, zip | 35 |
| `yoink/job.py` | `log_line` signal | 4 |
| `yoink/ui/log_dialog.py` (new) | section 2 | 60 |
| `yoink/ui/main_window.py` | double-click handler | 10 |
| `README.md`, `docs/DESIGN.md` | section 3 | docs |

Total: about 200 new lines, 120 of them copied from YAAMT.

### Tests

- `tests/test_job.py` (new, ~20 lines): feeding a non-protocol line emits
  `log_line` and appends to `log`; a protocol line does neither.
- `tests/test_version.py` (~40 lines): the describe-output formats
  (clean tag, past tag, dirty, untagged, no git), using a `git init`
  tempdir rather than mocking subprocess, and the stamp taking
  precedence over git.
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

### T2. Versioning and release build (~160 lines, tests ~40)

- Section 1, `yoink/version.py`, and the pyproject change. `About` and
  the startup log line already read `yoink.__version__` and need no
  change.

Done when `scripts/build.sh --release` refuses on a dirty tree or an
untagged `HEAD`, and on a tagged commit produces the named zip on this
machine. On macOS, the unzipped `.app` launches after "Open Anyway" and
downloads the managed yt-dlp.

### T3. Docs and release

- Section 3, then tag `v0.1.0`, build on each OS, and publish the
  release with the three zips.

### Phase 5 exit check

- `uv run pytest` passes on Windows and on macOS or Linux.
- About shows `0.1.0` in the release build and `0.1.0+N.<hash>` from a
  source checkout one commit later.
- A fresh user on each OS downloads the zip from the Releases page,
  launches Yoink, is walked through yt-dlp setup, and completes a download.
- On macOS, the release notes alone get the user past Gatekeeper.
