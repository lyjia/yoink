# Phase 5 scope: distribution

## Status

Not started. Branch `phase-5-distribution`.

Source: [DESIGN.md](DESIGN.md) section 8, Phase 5, plus section 7.

Deliverable: a tagged release on GitHub with a downloadable build for
Windows, macOS, and Linux, and release notes that get a Mac user past
Gatekeeper.

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
- **The version comes from git tags via `uv-dynamic-versioning`**, in
  YAAMT's scheme: `M.m.p` on a clean `v*.*.*` tag, `M.m.p+N.<hash>` N
  commits past it, `.dirty` with uncommitted changes, `0.0.0+N.<hash>`
  with no tag reachable. The plugin (hatchling plus dunamai) renders that
  from a format string in pyproject at install and build time, so
  pyproject follows the tag with no bump commit and no version code of
  our own. The build backend moves from setuptools to hatchling.
  `yoink.__version__` keeps reading `importlib.metadata`, which Nuitka's
  `--include-distribution-metadata` already ships. `[tool.uv]
  cache-keys` on commit and tags makes `uv sync` recompute it. A dirty
  tree is not a cache key, so `.dirty` in a source run reflects the last
  sync; accepted.
- **About says when Yoink runs from source.** `yoink.FROZEN` is
  `"__compiled__" in globals()`, which Nuitka sets in compiled modules.
  When false, About reads `Yoink 0.1.0+3.abc1234 (running from source)`.
  The startup log line gets the same suffix.
- **Nuitka stays on `app-dist`**, not `onefile`, on every OS, for the
  startup reason in DESIGN.md section 7. The Windows and Linux artifact is
  a zip of the folder; the macOS artifact is a zip of the `.app`.
- **No log viewer.** DESIGN.md listed one for this phase; it is moved to
  the backlog so the phase is release machinery only.
- **No app icon yet.** Nuitka's default (the Python icon) ships in the
  first release. An icon is a separate, small follow-up once there is
  artwork.

## 1. Release build (`scripts/build.sh`)

`--release` is consumed by the script, not passed to Nuitka. It:

1. Runs `uv sync` so the installed metadata matches the current commit,
   reads the version with
   `uv run python -c "import yoink; print(yoink.__version__)"`, and
   refuses to run unless it is a bare `M.m.p` (clean tree, on a tag).
   This is YAAMT's publish check, done locally.
2. Runs the existing Nuitka command. The test build also runs `uv sync`
   first, so `dist/` builds report their commit. Windows keeps
   `--windows-console-mode=attach`: it opens no console when launched from
   Explorer, and shows logs when launched from a terminal, which is what a
   bug report needs.
3. Zips the output to `dist/yoink-<version>-<os>-<arch>.zip`, where
   `<os>` is `windows`, `macos`, or `linux` and `<arch>` is `uname -m`.
   On macOS the zip is made with `ditto -c -k --keepParent` so the
   bundle's resource forks and symlinks survive; elsewhere `zip -r` or
   Python's `shutil.make_archive`, whichever is on the machine.

The test build path (no flag) is unchanged.

## 2. Release notes and README

- `README.md`: a "Download" section pointing at the Releases page, the
  macOS "Open Anyway" steps (right-click > Open, or Privacy & Security >
  Open Anyway), and the note that yt-dlp is fetched on first run. The
  status line moves to "Phases 0 to 5 done".
- The GitHub release body repeats the macOS steps and lists the three
  artifacts. Written by hand at tag time; no template file.
- DESIGN.md section 7: replace "Release builds and CI builds are backlog"
  with the `--release` flag and leave CI in the backlog.

## 3. Work items

| File | Change | Lines (approx.) |
|------|--------|-----------------|
| `pyproject.toml` | hatchling, `uv-dynamic-versioning`, format, cache keys | 12 |
| `yoink/__init__.py`, `main_window.py` | `FROZEN`, About suffix | 5 |
| `scripts/build.sh` | sync, `--release`: version check, zip | 30 |
| `README.md`, `docs/DESIGN.md` | section 2 | docs |

Total: about 50 new lines.

### Tests

- The version format is checked by hand in T1: `uv sync` then
  `__version__` on a tag, one commit past it, and with a dirty tree. It
  is the plugin's logic, not ours.
- The build script is checked by hand (section 5).

## 4. Out of scope

- Signing, notarization, and an Apple Developer account.
- CI builds and automatic release publishing (backlog).
- `onefile` builds, installers (MSI, DMG, AppImage, deb).
- An app icon.
- Auto-update of Yoink itself.
- The log viewer (backlog).

## 5. Tasks

Each task is one commit and leaves the app runnable. T2 follows T1.

### T1. Versioning and release build (~45 lines)

- Section 1, the pyproject change, `FROZEN`, and the About suffix.

Done when `scripts/build.sh --release` refuses on a dirty tree or an
untagged `HEAD`, and on a tagged commit produces the named zip on this
machine. On macOS, the unzipped `.app` launches after "Open Anyway" and
downloads the managed yt-dlp.

### T2. Docs and release

- Section 2, then tag `v0.1.0`, build on each OS, and publish the
  release with the three zips.

### Phase 5 exit check

- `uv run pytest` passes on Windows and on macOS or Linux.
- About shows `0.1.0` in the release build and `0.1.0+N.<hash> (running
  from source)` from a checkout one commit later.
- A fresh user on each OS downloads the zip from the Releases page,
  launches Yoink, is walked through yt-dlp setup, and completes a download.
- On macOS, the release notes alone get the user past Gatekeeper.
