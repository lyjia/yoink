# Phase 1 scope: cookies toggle

Source: [DESIGN.md](DESIGN.md) section 8, Phase 1, plus sections 3 and 4.

> Checkbox and browser combo on the main window; read-only parse of the
> yt-dlp config to find an existing `--cookies-from-browser` line and prefill
> the combo; write that one line back on change. This is the first use of
> `ytdlp_config.py` and proves the round-trip model on a single option.

Deliverable: tick **Use browser cookies**, pick a browser, download a
cookie-gated URL. The choice of browser is in the yt-dlp config, so plain
`yt-dlp <url>` from a terminal uses the same browser.

## 1. Findings from yt-dlp's source (2026.03.17)

These change or sharpen what DESIGN.md says. Phase 1 should update
DESIGN.md to match.

1. **The user config isn't always at one fixed path.** yt-dlp takes the
   *first existing* file from this list as the user config and ignores the
   rest (`options.py`, `_load_from_config_dirs`):

   1. `${XDG_CONFIG_HOME:-~/.config}/yt-dlp.conf`
   2. `${XDG_CONFIG_HOME:-~/.config}/yt-dlp/config`
   3. `${XDG_CONFIG_HOME:-~/.config}/yt-dlp/config.txt`
   4. `%APPDATA%/yt-dlp.conf`, `%APPDATA%/yt-dlp/config`, `%APPDATA%/yt-dlp/config.txt`
   5. `~/yt-dlp.conf`, `~/yt-dlp.conf.txt`, `~/.yt-dlp/config`, `~/.yt-dlp/config.txt`

   The XDG paths are checked before APPDATA on Windows too. Yoink must edit
   the file yt-dlp will actually read, so it runs the same search and only
   falls back to DESIGN.md 3.1's path when none of these files exist.

2. **yt-dlp tokenizes the whole file in one call:**
   `shlex.split(contents, comments=True)`. Two consequences:
   - An unquoted `#` starts a comment anywhere, even inside a word:
     `--cookies-from-browser chrome#x` means `chrome`.
   - A quoted string can span lines.

   So Yoink's per-line parse is only valid when splitting each line on its
   own gives the same tokens as splitting the whole file. Phase 1 checks
   exactly that. If the two differ, the file is treated as read-only and
   the UI says why.

3. **The `=` form is valid:** `--cookies-from-browser=firefox:abc` is one
   token. The parser has to accept both `--opt value` and `--opt=value`.

4. **When an option appears twice, the last one wins.** The prefill reads
   the last `--cookies-from-browser` line, and edits rewrite that same line.

5. **`--no-cookies-from-browser` exists** and is the default. DESIGN.md 4
   is correct.

6. **Encoding:** `determine_file_encoding` honours a BOM or a `# coding:`
   header. On write, Yoink keeps the file's detected encoding, BOM, and line
   endings.

## 2. Work items

### 2.1 `yoink/ytdlp_config.py` (new, ~150 lines)

- `find_user_config() -> Path | None`: runs the search from finding 1.
- `default_user_config() -> Path`: the DESIGN.md 3.1 path, used when
  creating the file.
- Line model from DESIGN.md 3.2: `Blank`, `Comment`, `Option(name, value,
  raw)`, `Opaque(raw)`. An `Option` is a line holding one long option with
  at most one value, in either the space or `=` form.
- **A trailing comment is part of the line.** `Option` stores whatever
  follows the value, such as `  # work laptop`, and writes it back
  unchanged when the value changes. Without that, the commonest annotated
  line would end up `Opaque`, and the cookies option could not be edited.
- `ConfigFile.load(path)`: reads the file, detects encoding and line
  endings, parses it into records, and runs the consistency check from
  finding 2 (setting `editable`).
- `get(name) -> str | None`: the value from the last matching `Option`.
- `set(name, value)`: rewrites the last matching `Option` line in place,
  or appends a new line if there is none. Raises if the file isn't
  editable, or if the only match is inside an `Opaque` line.
- `save()`: writes atomically (temp file in the same directory, then
  `os.replace`) and creates parent directories when needed.
- **Read-modify-write on every change.** Yoink reloads from disk right
  before each `set` and `save` and never writes from a copy held in memory,
  so edits made to the file outside Yoink are not lost.

### 2.2 Cookie spec helpers (inside `ytdlp_config.py`, or a small `cookies.py`)

- `BROWSERS = ["brave", "chrome", "chromium", "edge", "firefox", "opera", "safari", "vivaldi", "whale"]`
- `parse_spec("chrome+gnomekeyring:Profile 1::Personal") -> (browser, keyring, profile, container)`
  and `format_spec(...)`. The combo's selection maps to `browser`.
  Choosing a different browser drops the profile, keyring, and container,
  which belonged to the old browser. Choosing the same browser keeps them.

### 2.3 `yoink/argv.py`

- `build_argv(url, directory, cookies_spec: str | None)`. If `cookies_spec`
  is `None`, append `--no-cookies-from-browser`. Otherwise append
  `--cookies-from-browser <spec>`. Both go right after `-P`, following
  DESIGN.md 2.2.

### 2.4 `yoink/app.py`

- `KEY_USE_COOKIES = "main/use_cookies"`, default `False`. The DESIGN.md 9
  resolution and principle 4 both require off as the default.

### 2.5 `yoink/ui/main_window.py` (~50 lines)

- New row with a **Use browser cookies** checkbox and a browser combo.
- On startup, load the config. If it has a `--cookies-from-browser` line,
  select that browser in the combo and show the full spec as a tooltip.
- Changing the combo calls `config.set("--cookies-from-browser", spec)` and
  then `save()`. If the file is read-only, or the line is inside an
  `Opaque` record, the combo is disabled and a tooltip explains why.
- The checkbox state is saved to QSettings when the window closes, like
  the directory field.
- At download start, pass `spec if checkbox else None` to `build_argv`.
- Pitfall text in the combo tooltip, refreshed whenever the selection
  changes:
  - Firefox has to be closed.
  - Chrome on Windows 127+ needs a current yt-dlp.
  - Safari on macOS needs Full Disk Access granted to Yoink (or to the
    terminal it was launched from).

### 2.6 Tests (new)

There are no tests yet. `ytdlp_config.py` is pure logic and is the riskiest
code in this phase, so add pytest as a uv dev dependency
(`[dependency-groups] dev = ["pytest"]`) and a `tests/test_ytdlp_config.py`
that covers:

- round-trip: load then save with no edits reproduces the file byte for
  byte, for each fixture: comments, blank lines, CRLF, BOM, Opaque lines,
  and trailing comments
- `set` on the space form, the `=` form, a duplicated option (only the
  last occurrence changes), and an absent option (appended)
- a quoted value that spans lines is detected and makes the file read-only
- `#` inside a word, and `#` inside quotes
- `parse_spec` / `format_spec` round-trip
- `build_argv` places the cookies flags in the right spot

`find_user_config` takes the home and env roots as parameters so it can be
tested with `tmp_path`.

## 3. Proposed addition: read `--paths` from the config

The Phase 0 code always falls back to the OS Downloads folder and passes
`-P`, which overrides any `-P` in the user's config. That breaks principle 4
and DESIGN.md 2.3 step 3. The fix is about 10 lines on top of the parser
built here: with an empty directory field, check `config.get("--paths")`.
If it is set, pass no `-P` and show that path as the field's placeholder.
A `-P` buried in an `Opaque` line is not detected in this phase.

Recommendation: include it. It is read-only, it uses the new module, and it
closes a gap in the current behaviour. It also needs `get` to handle the
short alias `-P`, which DESIGN.md 3.3 already lists.

## 4. Open question

**Saving the browser writes it to the config, so CLI yt-dlp starts using
browser cookies.** DESIGN.md 4 stores the spec as a live
`--cookies-from-browser` line, and every plain `yt-dlp` run from a terminal
will then load cookies, even while the GUI checkbox is off. That follows
"one source of truth", but it could surprise a user who only wanted cookies
for one GUI download. The options:

- **(a) Accept it, as designed.** The combo tooltip says it writes to the
  yt-dlp config.
- **(b) Write only when the checkbox is on.** The combo still prefills from
  the config, but Yoink keeps an unsaved browser choice in QSettings until
  cookies are actually used.
- **(c) Never write. The combo is a Yoink preference.** This contradicts
  principle 1 and the stated Phase 1 goal of proving round-trip writes.

Recommendation: (a). It is the documented design, and the tooltip makes
the side effect visible. This needs a decision before implementation
starts.

## 5. Out of scope for Phase 1

- Editing keyring, profile, or container in the UI. The values are kept
  but not shown, and come with the Phase 2 yt-dlp tab.
- Any other option, the Preferences dialog, and the raw text tab.
- Portable, home, and system configs, `--config-locations`, and
  `--ignore-config` inside the user config. Yoink reads and edits only the
  user config file.
- Per-domain cookie overrides (Phase 3).

## 6. Estimate

About 250 lines of application code and 150 lines of tests. That brings
the app to about 830 of its 1500-line budget.

Suggested commits:

1. `ytdlp_config.py` and its tests
2. argv cookies flags and their test
3. main-window checkbox and combo
4. `--paths` placeholder (if accepted)
5. DESIGN.md updates for findings 1 and 2
