# Phase 1 scope: cookies toggle

Source: [DESIGN.md](DESIGN.md) section 8, Phase 1, plus sections 3 and 4.

> Checkbox and browser combo on the main window; read-only parse of the
> yt-dlp config to find an existing `--cookies-from-browser` line and prefill
> the combo; write that one line back on change. This is the first use of
> `ytdlp_config.py` and proves the round-trip model on a single option.

Deliverable: tick **Use browser cookies**, pick a browser, download a
cookie-gated URL. Each row then shows which browser yt-dlp actually took
cookies from and how many it found.

## 1. Approach: yt-dlp is the authority

Yoink edits one config file and does not reproduce yt-dlp's config search
or its precedence rules. It asks yt-dlp what it loaded and displays what
yt-dlp reports. If an option Yoink manages is also set in another file
yt-dlp loads, Yoink shows a warning and leaves the outcome to yt-dlp.

### 1.1 Config probe

`yt-dlp -v --no-update --no-cookies-from-browser`, run with no URL, prints
every config file yt-dlp loaded, using yt-dlp's own tokenization, and then
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
  `ast.literal_eval` and gets a list of `(label, path, tokens)`.
- The probe runs once at startup and again after every config write, as a
  `QProcess`, so the UI never blocks.
- If the probe fails or its output can't be parsed, Yoink reports the
  config state as unknown in the UI. Editing still works.

### 1.2 Which file Yoink edits

- If the probe reports a `User config`, Yoink edits that file. This is
  whichever of `yt-dlp.conf`, `yt-dlp/config`, `config.txt`, and so on
  yt-dlp actually picked, and Yoink learns it without searching for it
  itself.
- Otherwise Yoink edits the DESIGN.md 3.1 path and creates it on the first
  write.
- Portable, Home, System, and `--config-locations` files are never edited.

### 1.3 Override warnings

When another loaded config also contains `--cookies-from-browser` or
`--no-cookies-from-browser`, the main window shows a one-line warning:
"Also set in `<path>` (`<label>` config). yt-dlp decides which applies."
Yoink does not compute the winner.

This only affects plain CLI use. Yoink always passes either
`--cookies-from-browser <spec>` or `--no-cookies-from-browser` on the
command line, and the command line beats every config file, so for
downloads started from Yoink the GUI setting always applies.

### 1.4 Ground truth in the downloads table

When it opens a browser's cookie store, yt-dlp prints
`Extracting cookies from <browser>` and then
`Extracted <n> cookies from <browser>`, or an `ERROR:` line. `DownloadJob`
recognises those lines, emits a `cookies` signal, and the row shows
something like "firefox, 446 cookies" (or the error) in a tooltip or
status cell.

**These lines are hidden by `--quiet`.** Phase 0 passes `--quiet` in
`argv.py`, and Phase 1 removes it. The `--progress-template` and `--print`
output still has to be checked against the binary once `--quiet` is gone.
If the user's own config has `--quiet`, the lines never appear and the row
shows the cookie state as unknown. That is supported, in the same way
DESIGN.md 2.4 treats `--no-progress`.

### 1.5 Consistency check

Yoink's line-level parser splits one line at a time. yt-dlp tokenizes the
whole file in one call (`shlex.split(contents, comments=True)`), so an
unquoted `#` starts a comment even inside a word, and a quoted string can
span lines. Yoink does not try to imitate those rules. It compares its own
tokens to the list the probe reported for the same file. If they differ,
the file is read-only in Yoink, the combo is disabled, and a tooltip
explains why.

## 2. Work items

### 2.1 `yoink/ytdlp_config.py` (new, ~150 lines)

- `probe(binary) -> list[LoadedConfig]`: the synchronous parser for the
  probe output. `MainWindow` runs the process through `QProcess` and passes
  the output in. `LoadedConfig(label, path, tokens)`.
- `default_user_config() -> Path`: the DESIGN.md 3.1 path.
- Line model from DESIGN.md 3.2: `Blank`, `Comment`, `Option(name, value,
  raw)`, `Opaque(raw)`. An `Option` is a line holding one long option with
  at most one value, written as either `--opt value` or `--opt=value`.
- **A trailing comment is part of the line.** `Option` stores whatever
  follows the value, such as `  # work laptop`, and writes it back
  unchanged when the value changes.
- `ConfigFile.load(path)`: reads the file and keeps its encoding, BOM, and
  line endings.
- `ConfigFile.matches(tokens) -> bool`: the consistency check from 1.5.
- `get(name) -> str | None`: the value from the last matching `Option`
  inside this file only. Repeated options in one file are within the
  file's own scope, and the last one wins, as in yt-dlp.
- `set(name, value)`: rewrites the last matching `Option` line in place,
  or appends a new line if there is none. Raises if the only match is
  inside an `Opaque` line.
- `save()`: writes atomically (temp file in the same directory, then
  `os.replace`) and creates parent directories when needed.
- **Read-modify-write.** Yoink reloads from disk before each `set` and
  `save`, so edits made outside Yoink are not lost.

### 2.2 Cookie spec helpers

- `BROWSERS = ["brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale"]`
- `parse_spec` / `format_spec` for
  `BROWSER[+KEYRING][:PROFILE][::CONTAINER]`. Choosing a different browser
  drops the profile, keyring, and container. Choosing the same browser
  keeps them.

### 2.3 `yoink/argv.py`

- `build_argv(url, directory, cookies_spec: str | None)`. If `cookies_spec`
  is `None`, append `--no-cookies-from-browser`. Otherwise append
  `--cookies-from-browser <spec>`. Both go right after `-P`, following
  DESIGN.md 2.2.
- Drop `--quiet` (see 1.4).

### 2.4 `yoink/job.py`

- Recognise the cookie lines from 1.4 and add a
  `cookies = Signal(str, object)` signal carrying the browser and either a
  count or an error.

### 2.5 `yoink/app.py`

- `KEY_USE_COOKIES = "main/use_cookies"`, default `False`, following
  DESIGN.md 9.

### 2.6 `yoink/ui/main_window.py` (~70 lines)

- A row with a **Use browser cookies** checkbox, a browser combo, and the
  override warning label from 1.3, hidden when there is nothing to warn
  about.
- On startup and after each write: run the probe, choose the file per 1.2,
  load it, run the 1.5 check, prefill the combo, and set the tooltip to the
  full spec and the file path.
- Changing the combo calls `set` and then `save`, and runs the probe again.
- The checkbox state is saved to QSettings when the window closes.
- At download start, pass `spec if checkbox else None`.
- The row's cookie cell is filled from the job's `cookies` signal.
- Pitfall text in the combo tooltip, refreshed when the selection changes:
  - Firefox must be closed.
  - Chrome on Windows 127+ needs a current yt-dlp.
  - Safari on macOS needs Full Disk Access.

### 2.7 Tests (new)

Add pytest as a uv dev dependency and `tests/test_ytdlp_config.py`:

- round-trip: load then save with no edits reproduces the file byte for
  byte, for each fixture: comments, blanks, CRLF, BOM, Opaque lines, and
  trailing comments
- `set` on the space form, the `=` form, a duplicated option, and an
  absent option
- probe-output parsing: the captured sample above, a path with spaces, a
  non-ASCII path, and garbage input
- `matches` against tokens produced by `shlex.split(..., comments=True)`,
  including `#` inside a word and a quoted value that spans lines
- `parse_spec` / `format_spec`, and where `build_argv` places the cookies
  flags
- the job's recognition of the cookie lines

## 3. Proposed addition: honour `-P` from the config

Phase 0 always passes `-P` (the OS Downloads folder when the field is
empty), so a `-P` in any config is overridden. That breaks principle 4.

With the probe in place the fix is small, and Yoink does not have to decide
which config wins. If any loaded config contains `-P` or `--paths`, and the
directory field is empty, Yoink passes no `-P`. yt-dlp then resolves the
directory itself, and the row's Filename column already shows the real
path from the `FILE` and `DONE` lines. The directory field's placeholder
says "set by yt-dlp config" rather than guessing a path.

Recommendation: include it.

## 4. Open question

**Saving the browser writes it to the config, so CLI yt-dlp starts using
browser cookies.** Changing the combo writes a live `--cookies-from-browser`
line, and from then on plain `yt-dlp` runs from a terminal load cookies,
even while the GUI checkbox is off. The options:

- **(a) Accept it, as designed.** The combo tooltip says it writes to the
  yt-dlp config.
- **(b) Write only when cookies are used.** Yoink keeps an unsaved choice in
  QSettings until the checkbox is on.

Recommendation: (a).

## 5. Out of scope for Phase 1

- Editing keyring, profile, or container in the UI (Phase 2).
- Other options, the Preferences dialog, and the raw text tab.
- Searching for config files, or working out precedence between them. Both
  are left to yt-dlp (section 1).
- Per-domain cookie overrides (Phase 3).

## 6. Estimate

About 280 lines of application code and 170 of tests. That brings the app
to about 860 of its 1500-line budget.

Suggested commits:

1. `ytdlp_config.py` (probe parser, line model, writer) and its tests
2. argv cookies flags, dropping `--quiet`, and job cookie-line parsing,
   checked against the real binary
3. main-window checkbox, combo, warning label, and row cookie display
4. `-P` handling (if accepted)
5. DESIGN.md: section 3.1 becomes "the user config yt-dlp reports, else
   this path"; add the probe and the ground-truth rule
