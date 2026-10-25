# Phase 1 scope: main-window overrides and cookies

## Status

Implemented on branch `phase-1-cookies-toggle`. `uv run pytest` passes
(72 tests). Application code is about 1010 lines, comments and blank lines
included.

| Task | Commit |
|------|--------|
| Scope | `da5fe54`, `ecae052`, `febf7f0`, `74535ea`, `4dd6335`, `4674a28` |
| T0 | `4fb1229` |
| T1 | `1a12905` |
| T2 | `6cfb30f` |
| T4 | `ef428ab` |
| Sandbox and IDE run configs | `9451d22` |
| T5 | `2c0e409` |
| T6 | `9bb3e78` |
| T7 | the docs commit that adds this note |

The macOS Gatekeeper design commits on the same branch (`43fdcf6` to
`6cd44e6`) are not Phase 1 work.

Dropped: T3, per-row cookie reporting (`4674a28`). Phase 0's `--quiet`
stays, and a cookie failure shows only through the row's error text.

Changed or added during implementation (DESIGN.md 2.1 and 3.4 have the
details):

- Download is disabled while the probe runs. Until it reports, an empty
  directory field can't tell "pass no `-P`" from "pass Downloads".
- The probe has a 20 s timeout, and its working directory is the
  Downloads folder too, because yt-dlp looks for a Home config there.
- `parse_probe` also returns `None` when yt-dlp reports any error other
  than the missing URL, or prints no `Command-line config` line. A probe
  that is killed or times out counts as failed even if it listed some
  files.
- A failed **Refresh config** resets to the unknown state. It does not
  keep the previous result.
- The unknown state reads "yt-dlp <version> (<variant>), config: unknown"
  when the version could still be parsed, and "yt-dlp config: unknown"
  otherwise.
- `YOINK_SETTINGS_DIR` moves QSettings into an INI file, so the sandbox
  doesn't touch the real settings. The sandbox gained `--pypi-yt-dlp`,
  `--yt-dlp PATH`, `--clean`, and `--dry-run`.
- On macOS the sandbox can't redirect the Downloads folder:
  `QStandardPaths` ignores `$HOME`. Checks that expect files in the sandbox
  Downloads folder hold on Linux. On macOS, type the sandbox path into the
  directory field.

The T4–T6 "done when" checks were run headlessly (Qt offscreen, scripted
by the implementing agents, with a PyPI yt-dlp, a temp HOME and temp
settings). Nobody has yet clicked through them in the visible GUI.

Remaining for the exit check:

- A manual click-through of the T4–T6 checks in the real window, using
  the "Yoink (sandbox)" run configuration.
- One real cookie-gated download by hand, with a browser chosen in the
  combo.
- A real download from the developer's normal environment, once the
  yt-dlp on their PATH runs (it is currently blocked by Gatekeeper,
  DESIGN.md 6.6).

Source: [DESIGN.md](DESIGN.md) section 8, Phase 1, plus sections 2.3, 3.4,
and 4.

Deliverable: pick a browser in the cookies combo and download a
cookie-gated URL. With both controls left on **Config default**, a download behaves exactly
like `yt-dlp <url>`. **Reset** clears all main-window overrides.

## 1. Model

- **The yt-dlp config holds the defaults.** Phase 1 never writes to it.
  Editing it is the job of the Preferences dialog in Phase 2.
- **The main window holds local overrides.** Each control either follows
  the config (it shows the config's value and passes nothing) or overrides
  it (it passes a flag on the command line). The command line beats every
  config file, so an override always applies to Yoink's downloads and never
  affects plain `yt-dlp` runs.
- **yt-dlp is the authority.** Yoink does not search for config files and
  does not decide which file wins. It asks yt-dlp what it loaded (1.1),
  and shows a warning when a setting appears in more than one file (1.3).
  The Filename column already shows the real path yt-dlp wrote to.

### 1.1 Config probe

`yt-dlp -v --no-update --no-cookies-from-browser`, run with no URL, prints
every config file it loaded, using yt-dlp's own tokenization, and then
exits on "You must provide at least one URL". Tested against 2026.03.17:

```
[debug] Command-line config: ['-v', '--no-update', '--no-cookies-from-browser']
[debug] User config "/home/u/.config/yt-dlp.conf": ['--cookies-from-browser', 'firefox']
```

- It takes about 0.3 s and makes no network requests.
- `--no-cookies-from-browser` matters: without it, yt-dlp opens the browser's
  cookie database at startup. On macOS, Chrome would then show a Keychain
  prompt.
- Yoink parses lines of the form
  `[debug] (| )*[<Label> ]config "<path>": [...]` and reads the token list
  with `ast.literal_eval`, giving a list of
  `LoadedConfig(label, path, tokens, depth)`. The `Command-line` entry is
  ignored.
- A file pulled in with `--config-locations` appears nested under the file
  that included it, with one `| ` per level and no label:
  `[debug] | Config "/path/extra.conf": ['-P', '/tmp/b']`. Yoink labels
  these **Included**. This was checked against 2026.03.17 and is also the
  easiest way to set up two config files for testing.
- The probe runs at startup through `QProcess`, so the UI never blocks.
  **Refresh config** in the File menu runs it again. Phase 2 also reruns it
  after every write.
- If the probe fails or its output can't be parsed, the combo reads
  **Config default** with no value shown, the status bar says the config
  state is unknown, and downloads still work.

### 1.2 Managed settings

A managed setting is a group of options that Yoink shows on the main window.
Phase 1 manages two:

| Setting   | Options in config                                   | Value shown                    |
|-----------|-----------------------------------------------------|--------------------------------|
| cookies   | `--cookies-from-browser X`, `--no-cookies-from-browser` | `X`, or `none`             |
| directory | `-P` / `--paths`, home path only                    | the path                       |

`--paths` takes `[TYPES:]PATH`. A value sets the home directory only when
it has no type prefix, or when `home` is one of its types. `-P temp:/tmp`
does not count: with only that in the config, yt-dlp would download into
Yoink's working directory. The allowed types come from yt-dlp's
`options.py` (`home`, `temp`, and the `OUTTMPL_TYPES` keys). A Windows
drive letter such as `C:` is not a type.

Both the `--opt value` and `--opt=value` token forms are accepted.

`config_values(loaded, setting) -> list[Occurrence]` returns every
occurrence across all loaded configs, as
`Occurrence(setting, value, path, label)`, in probe order. It does not
rank them.

### 1.3 Override indicator

The indicator appears when a managed setting occurs in more than one
loaded config file. The status bar then shows a yellow warning icon
(`QStyle.StandardPixmap.SP_MessageBoxWarning`, 16 px) next to link-styled
text reading **Some configuration values overridden**. Both are hidden
otherwise.

Clicking the text opens `ConfigNoticeDialog`, which lists:

- every loaded config file with its label (User, Portable, Home, System,
  or Included)
- a table with one row per occurrence: setting, value, file, and label
- a note that yt-dlp decides which value applies, and that main-window
  overrides apply to Yoink downloads whatever the config says

Repeating an option inside a single file does not trigger the indicator.

## 2. Main window

### 2.1 Cookies combo

The old checkbox-and-combo pair becomes a single combo, because there are
three states and a checkbox can only express two:

| Item                          | Passes                               |
|-------------------------------|--------------------------------------|
| Config default (`<value>`)    | nothing                              |
| No cookies                    | `--no-cookies-from-browser`          |
| brave, chrome, … whale        | `--cookies-from-browser <browser>`   |

- The first item shows the value in parentheses when every occurrence of
  the cookies setting has the same value: "Config default (firefox)", or
  "Config default (none)". If there is no occurrence, it reads
  "Config default (none)". If the values disagree, it reads
  "Config default", and the indicator from 1.3 explains.
- Choosing a browser passes only the browser name. A config spec with a
  profile or keyring (`chrome:Profile 2`) is used only through
  **Config default**. Editing the spec is part of the Phase 2 Preferences.
- The tooltip carries the pitfall text and is refreshed when the
  selection changes:
  - Firefox must be closed.
  - Chrome on Windows 127+ needs a current yt-dlp.
  - Safari on macOS needs Full Disk Access.
- Browser list: brave, chrome, chromium, edge, firefox, opera, safari,
  vivaldi, whale.

### 2.2 Directory field

- An empty field follows the config. If any loaded config sets a home
  path, Yoink passes no `-P`. The placeholder shows the path when every
  occurrence agrees, or "Set by yt-dlp config" when they disagree. If no
  config sets a home path, Yoink passes the OS Downloads folder as `-P`,
  and the placeholder shows that path (principle 5's one exception).
- A typed or browsed value is an override and is passed as `-P`.
- `setClearButtonEnabled(True)`, so one click returns to following the
  config.
- **Browse…** opens at the field's value, then the placeholder path, then
  the Downloads folder, whichever is first available.
- With no `-P` passed, `QProcess` sets the working directory to the
  Downloads folder anyway. A config that sets only `-P temp:` cannot then
  leave files in an unpredictable place.

### 2.3 Reset button

- A **Reset** button on the directory and cookies row clears the
  directory field and sets the combo to **Config default**.
- It is enabled only while at least one override is active.
- Its tooltip reads "Clear main-window overrides and use the yt-dlp
  config".
- Each control's tooltip says whether it is following the config or
  overriding it.
- From Phase 3 on, Reset also clears a destination prefilled by a domain
  rule. The rule applies again the next time a URL is entered.

### 2.4 Persistence

Overrides are restored on the next launch. Both controls are always
visible, so an active override is never hidden, and Reset or
**Config default** undoes it in one click.

| Key               | Values                                             |
|-------------------|----------------------------------------------------|
| `main/dir`        | override path, or empty to follow the config      |
| `main/cookies`    | empty (config default), `none`, or a browser name |

`main/dir` replaces Phase 0's `main/last_dir`, which has the same meaning.
The old value is migrated once.

## 3. Work items

| File | Change | Lines (approx.) |
|------|--------|-----------------|
| `yoink/ytdlp_config.py` (new) | probe output parser, `LoadedConfig`, managed settings, `--paths` type handling, `config_values` | 80 |
| `yoink/argv.py` | `build_argv(url, directory: str \| None, cookies: str \| None)`. `None` means pass nothing, `"none"` passes `--no-cookies-from-browser`, any other value passes `--cookies-from-browser <value>`. | 15 |
| `yoink/job.py` | working directory set to the Downloads folder | 2 |
| `yoink/app.py` | `KEY_DIR`, `KEY_COOKIES`, `main/last_dir` migration | 10 |
| `yoink/ui/config_notice.py` (new) | `ConfigNoticeDialog` | 50 |
| `yoink/ui/main_window.py` | cookies combo, directory field changes, Reset, status-bar indicator, Refresh config, probe `QProcess` | 85 |

Total: about 240 lines, bringing the app to about 820 of its 1500-line
budget.

### Tests (new)

Add pytest as a uv dev dependency (`[dependency-groups] dev = ["pytest"]`).
All of the following are pure functions, so no Qt event loop is needed.

- `tests/test_ytdlp_config.py`
  - probe parsing: the captured sample, a path with spaces, a non-ASCII
    path, no user config, and garbage input
  - `config_values`:
    - the `--opt value` and `--opt=value` forms
    - `--no-cookies-from-browser`
    - `-P home:/x` and bare `-P /x` count; `-P temp:/x` and
      `-P thumbnail:/x` do not; `-P C:\x` counts
    - several files that agree, and several that disagree
- `tests/test_argv.py`: the cookies and `-P` flags are placed correctly or
  left out for each of the three cookies states and both directory states.
  This is the check that cookies are requested; that yt-dlp then honours
  the flag is yt-dlp's job.

## 4. Out of scope

- Any write to the yt-dlp config, the line-level parser, and the
  round-trip writer. All move to Phase 2.
- Cookie profile, keyring, and container in the UI (Phase 2).
- Searching for config files, or working out precedence between them.
  Both are left to yt-dlp.
- Domain rules (Phase 3).

## 5. Tasks

Each task is one commit and leaves the app runnable. T1 and T2 do not
depend on each other and can be done in parallel.

```
T0 ─┬─ T1 ─┬─ T4 ── T5 ── T6
    └─ T2 ─┘
```

Manual checks read the flags Yoink passed from the `Starting: ...` line
that `DownloadJob` already logs to the console.

### T0. Test scaffolding and dev sandbox (~20 lines + script)

- Add `[dependency-groups] dev = ["pytest"]` and an empty `tests/`, so
  `uv run pytest` works.
- Add `scripts/sandbox.sh`. It creates a temp `HOME` with
  `XDG_CONFIG_HOME` under it, an optional user config, a second config
  pulled in with `--config-locations`. It serves a 3 MB dummy `clip.mp4` over `http://127.0.0.1:8765`,
  then runs `python -m yoink` with that environment. Manual checks then
  never touch the real yt-dlp config.

Done when `uv run pytest` passes with no tests collected, and the sandbox
launches Yoink and downloads `clip.mp4` to the Downloads fallback.

### T1. `ytdlp_config.py` (~80 lines, tests ~90)

- `parse_probe(text) -> list[LoadedConfig] | None`. It returns `None` for
  unparseable output, as distinct from an empty list (no configs).
- Settings table for cookies and directory, and the `--paths` home-path
  rule (1.2).
- `config_values(loaded, setting)`, and
  `shared_value(occurrences) -> str | None`, which returns the value when
  all occurrences agree.
- `find_conflicts(loaded) -> list[Occurrence]`: the settings that occur in
  more than one file (1.3).

Done when the `test_ytdlp_config.py` cases in section 3 pass, plus nested
`| Config` lines and the `Included` label. No Qt imports.

### T2. argv and job (~20 lines, tests ~30)

- New `build_argv` signature.
- `setWorkingDirectory` set to the Downloads folder.
- `MainWindow.start_download` passes `cookies=None` for now, so behaviour
  is unchanged.

Done when `test_argv.py` passes, and a sandbox download still shows
progress, filename, Finished, and a working Cancel.

### T4. Main-window override controls (~60 lines)

- `KEY_DIR`, `KEY_COOKIES`, and the `main/last_dir` migration.
- Cookies combo: "Config default", "No cookies", and the browsers. Until T5
  there is no value in parentheses.
- Directory field: clear button, and Browse… starting points.
- Reset button, enabled only while an override is active, and tooltips
  stating each control's mode.
- Persistence on close and restore on launch, with both values passed to
  `build_argv`.
- The empty-field fallback stays at the Downloads folder in this task. T5
  makes it config-aware.

Done when:
- The logged command line has `--cookies-from-browser chrome` when chrome
  is chosen, `--no-cookies-from-browser` for **No cookies**, and neither
  for **Config default**.
- Reset returns both controls to their defaults and disables itself.
- A restart restores the overrides.
- An existing Phase 0 `last_dir` value shows up in the field.

### T5. Config probe in the UI (~50 lines)

- Run the probe `QProcess` at startup and from File > Refresh config, with
  results going to `MainWindow.loaded_configs`.
- The combo's first item gets its value in parentheses (1.2, 2.1), and the
  directory placeholder its text (2.2).
- With an empty directory field and a home path set in the config, pass no
  `-P`.
- Probe failure: "Config default" with no value, "yt-dlp config: unknown"
  in the status bar, and the Downloads folder as the fallback.
- Version from the probe (DESIGN.md 6.3): add
  `parse_version(text) -> tuple[str, str] | None` (version and variant) to
  `ytdlp_config.py`, with tests, and show "yt-dlp <version> (<variant>)" in
  the status bar. Remove the synchronous `binary.get_version` call from
  `MainWindow.__init__`, which blocks startup for 6.5 s with the macOS
  single-file build. Until the probe returns, the status bar reads
  "Checking yt-dlp…". The install-method label and staleness warning come
  in Phase 2.
- Close the probe's stdin as soon as it starts, so a config containing
  `--config-locations -` can't hang it.

Done when these sandbox checks pass:
- No config: "Config default (none)", the Downloads placeholder, and files
  land in the sandbox Downloads folder.
- `-P <dir>` and `--cookies-from-browser firefox`: the label reads
  "Config default (firefox)", the placeholder is `<dir>`, no `-P` is
  logged, and files land in `<dir>`.
- Only `-P temp:<t>`: the placeholder is the Downloads folder and `-P` is
  passed.
- Edit the config, then File > Refresh config: the labels update without
  a restart.
- Binary path pointed at `/usr/bin/false`: the unknown state appears and
  the app does not crash.
- The status bar shows the version and variant, for example
  `2026.10.21 (pip)`, and the window appears immediately instead of
  waiting for yt-dlp.

### T6. Override indicator and dialog (~60 lines)

- Status-bar icon and link text, shown when `find_conflicts` is non-empty.
- `ConfigNoticeDialog` (1.3).

Done when:
- A sandbox where the user config and an included config both set `-P`
  shows the indicator, and the dialog lists both files with their labels
  and values.
- Removing the include and refreshing hides the indicator.
- Repeating `-P` twice within one file does not show it.

### T7. Docs

- README status line, and Phase 1 marked done in DESIGN.md section 8.
- Note in DESIGN.md anything the implementation changed.

### Phase 1 exit check

- `uv run pytest` passes.
- Every T4–T6 sandbox check passes in one session.
- A real download from the user's normal environment, with **Config
  default** and no yt-dlp config, behaves exactly as in Phase 0.
- One real cookie-gated download by hand, with a browser chosen in the
  combo, succeeds.
