# Phase 1 scope: main-window overrides and cookies

Source: [DESIGN.md](DESIGN.md) section 8, Phase 1, plus sections 2.3, 3.4,
and 4.

Deliverable: pick a browser in the cookies combo and download a
cookie-gated URL. The row shows which browser yt-dlp took cookies from.
With both controls left on **Config default**, a download behaves exactly
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
  shows a warning when a setting appears in more than one file (1.3), and
  each row reports what yt-dlp actually did (1.4).

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
- Yoink parses each `[debug] <Label> config "<path>": [...]` line with
  `ast.literal_eval` and gets a list of `LoadedConfig(label, path, tokens)`.
  The `Command-line` entry is ignored.
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
  or Custom)
- a table with one row per occurrence: setting, value, file, and label
- a note that yt-dlp decides which value applies, and that main-window
  overrides apply to Yoink downloads whatever the config says

Repeating an option inside a single file does not trigger the indicator.

### 1.4 Ground truth in the downloads table

When it opens a browser's cookie store, yt-dlp prints
`Extracting cookies from <browser>` and then
`Extracted <n> cookies from <browser>`, or an `ERROR:` line. A pure
function `parse_cookie_line(line)` in `job.py` recognises those lines, and
`DownloadJob` emits `cookies = Signal(str, object)` carrying the browser and
either a count or an error. The row shows something like "firefox, 446
cookies" as a tooltip on the Status cell. If no cookies were loaded, there
is no tooltip.

The Filename column already shows the real path from the `FILE` and `DONE`
lines. That is how a user following the config can see where a file
actually went.

**These lines are hidden by `--quiet`.** Phase 0 passes `--quiet`, and
Phase 1 removes it. With `--quiet` gone, the `--progress-template` and
`--print` output must be checked again against the real binary. If the
user's own config has `--quiet`, the cookie lines never appear. The row
then shows nothing for cookies, which is supported in the same way
DESIGN.md 2.4 treats `--no-progress`.

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
| `yoink/argv.py` | `build_argv(url, directory: str \| None, cookies: str \| None)`. `None` means pass nothing, `"none"` passes `--no-cookies-from-browser`, any other value passes `--cookies-from-browser <value>`. Drop `--quiet`. | 15 |
| `yoink/job.py` | `parse_cookie_line`, `cookies` signal, working directory | 25 |
| `yoink/app.py` | `KEY_DIR`, `KEY_COOKIES`, `main/last_dir` migration | 10 |
| `yoink/ui/config_notice.py` (new) | `ConfigNoticeDialog` | 50 |
| `yoink/ui/main_window.py` | cookies combo, directory field changes, Reset, status-bar indicator, Refresh config, probe `QProcess`, row cookie tooltip | 90 |

Total: about 270 lines, bringing the app to about 850 of its 1500-line
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
  left out for each state, and `--quiet` is absent
- `tests/test_job.py`: `parse_cookie_line` on an extraction line, a count
  line, an error line, and an unrelated line

## 4. Out of scope

- Any write to the yt-dlp config, the line-level parser, and the
  round-trip writer. All move to Phase 2.
- Cookie profile, keyring, and container in the UI (Phase 2).
- Searching for config files, or working out precedence between them.
  Both are left to yt-dlp.
- Domain rules (Phase 3).

## 5. Suggested commits

1. `ytdlp_config.py` and its tests
2. argv and job changes (cookie flags, dropping `--quiet`, cookie-line
   parsing), checked against the real binary
3. main window: cookies combo, directory field, Reset, persistence
4. probe, override indicator, and `ConfigNoticeDialog`
5. README status line
