# Phase 2 scope: Preferences dialog

## Status

Not started. When the phase is done, this section records the commits, the
test count, the application size, and any deviations, as in PHASE1.md.

Source: [DESIGN.md](DESIGN.md) section 8, Phase 2, plus sections 3.1 to 3.4,
4, 6.3, and 6.4.

Deliverable: open File > Preferences…, set a download folder and a speed
limit on the yt-dlp page, and save. The user config gains exactly those two
lines, every other line is unchanged, and a plain `yt-dlp` run in a terminal
uses the new values. Clearing both fields and saving removes the two lines
again.

## 1. Config file model

- **Preferences is the only writer.** Yoink writes the yt-dlp config only
  from the yt-dlp page (principle 1), and only the file the probe labels
  `User` (1.1).
- **Widgets, not text.** Each option in DESIGN.md 3.3 gets a widget. Every
  other line is listed read-only in a warning box (2.4) and preserved byte
  for byte. There is no raw text editor and no editable "Other options"
  list.
- **An unset option writes nothing.** A blank field or an unchecked box
  means the option has no line in the file, so an empty config stays empty
  (principle 5). Saving with no changes writes nothing, and does not create
  the file.
- **yt-dlp stays the authority.** Before the page is editable, Yoink checks
  that it reads the file the same way yt-dlp does (1.4). After every save,
  `MainWindow.refresh_config` runs the probe again.

### 1.1 Which file

- The `LoadedConfig` with label `User` from the last probe is the file
  Yoink edits. `Included` files under it are not edited.
- If yt-dlp loaded no user config, Yoink creates the path from DESIGN.md
  3.1 on the first save that has something to write, along with its parent
  directory: `${XDG_CONFIG_HOME:-~/.config}/yt-dlp/config` on Linux and
  macOS, `%APPDATA%\yt-dlp\config` on Windows.
- Portable, home, system, and included files are never shown on the page.
  The override indicator and `ConfigNoticeDialog` already cover settings
  that come from them.

### 1.2 Line model

`parse_lines(text) -> list[Line]` splits the decoded file into lines, each
keeping its own line ending, and classifies each one:

| Record | Line | Shown |
|--------|------|-------|
| `Blank(raw)` | empty or whitespace only | nowhere |
| `Comment(raw)` | only a `#` comment | nowhere |
| `Option(name, value, raw)` | exactly one long option, with an optional value, as `--opt value` or `--opt=value`, and an optional trailing comment | in its widget if the option is managed (2.2), otherwise in the warning box |
| `Opaque(raw)` | anything else: short flags, several options, a stray value, a line `shlex` can't split | in the warning box |

`format_lines(lines) -> str` joins the `raw` fields in order, so parsing and
formatting an unchanged file gives back the same text.

`set_option(lines, name, value) -> list[Line]` applies one widget's state:

- A changed value rewrites only that option's line. A trailing comment on
  the line is kept.
- A value for an option with no line appends a new line at the end, using
  the file's line ending (the first line's, or `\n` for a new file).
- An empty value, or an unchecked box, removes the line.
- A checkbox writes the bare flag. Every other value is quoted with
  `shlex.quote`.

Which lines a widget owns:

- An `Option` line whose name is in the option table (2.2) belongs to that
  widget. Aliases (`-P`, `-o`, `-f`, `-r`, `--rate-limit`, and the like) do
  not count; short flags are `Opaque`, and long aliases are unmanaged.
- A `--paths` line counts only if it sets the home path alone: no type
  prefix, or exactly `home:`. Lines such as `--paths temp:/tmp` go to the
  warning box. The existing `_TYPED_PATH` pattern decides this.
- If a managed option appears on more than one line, all of its lines go
  to the warning box and its widget is disabled, with a tooltip saying to
  edit the file. Some options add up across lines (`--sub-langs`,
  `--sponsorblock-remove`) and others take the last value, so Yoink can't
  show one value that means the same thing in every case.

### 1.3 Reading and writing

yt-dlp reads the file with `Config.read_file`. It picks the encoding from a
byte-order mark (UTF-8, UTF-16, or UTF-32) or a `# coding: <name>` first
line, otherwise the locale encoding (cp1252 on most Western Windows
systems). It then runs `shlex.split(contents, comments=True)` over the whole
file in POSIX mode. Yoink mirrors that:

- `read_config(path) -> ConfigFile` returns the lines, the encoding, the
  byte-order mark, and the original bytes. The encoding is chosen exactly as
  above, with `locale.getpreferredencoding(False)` as the fallback.
- `write_config(config, lines)` encodes with the same encoding and writes
  the same byte-order mark. A new file is written as UTF-8 with a BOM, so
  yt-dlp never falls back to the locale encoding on Windows.
- The write goes to a temporary file in the same directory, which then
  replaces the original through `os.replace`. A symlinked config is
  resolved first, so the link survives and its target is replaced.
- If a value can't be encoded in the file's encoding (an emoji in a
  cp1252 file, say), the save fails with a message and the file is left
  untouched.
- Before writing, Yoink reads the file again. If its bytes differ from the
  ones the dialog loaded (the user edited it through **Open in editor**,
  for example), the save stops and asks the user to reopen Preferences.

### 1.4 Consistency check

`matches_probe(lines, tokens) -> bool` compares Yoink's parse with the
probe's tokens for the same file. It splits each line with
`shlex.split(raw, comments=True)`, joins the results, and compares them
with the `User` entry's tokens. A line that `shlex` can't split on its own
fails the check.

The probe prints login values as `PRIVATE` (yt-dlp's `hide_login_info`,
checked against 2026.10.21): the value after `-p`, `--password`, `-u`,
`--username`, `--video-password`, `--ap-password`, or `--ap-username`, and
the `--opt=value` forms of the same options. `matches_probe` masks Yoink's
tokens the same way before comparing.

The check fails on a quoted value that spans lines, a backslash at the end
of a line, or non-ASCII text decoded with a different encoding than
yt-dlp used. Whenever Yoink can't be sure it reads the file correctly, the
whole page is read-only:

| Situation | yt-dlp page | Warning box says |
|-----------|------------|------------------|
| Probe failed (config unknown) | read-only | yt-dlp didn't report its config; fix the file, then use File > Refresh config |
| User config loaded, check passes | editable | the unmanaged lines |
| User config loaded, check fails | read-only | Yoink reads this file differently from yt-dlp, so it can't edit it safely; edit it in a text editor |
| No user config, default path absent | editable | nothing yet; **Open in editor** is disabled |
| No user config, but the default path exists | read-only | yt-dlp doesn't load this file, so editing it would have no effect |
| File can't be read or decoded | read-only | the error |

### 1.5 Paths

DESIGN.md 3.2 already sets the rule; Phase 2 applies both halves.

- **Display.** Every path shown to the user is native
  (`os.path.normpath`). This covers the folder and file widgets, and also
  the two places that show probe values since Phase 1: the main window's
  directory placeholder, and the directory values in `ConfigNoticeDialog`.
- **Write and compare.** Every path written to the config, or compared with
  probe tokens, uses forward slashes (`Path.as_posix()`), so a Windows path
  survives yt-dlp's POSIX `shlex`.
- Paths are the values of `--paths`, `--cookies`, and `--download-archive`.
  `--output` is a template and is written as typed; `shlex.quote` keeps any
  backslash in it.
- `to_config_path(path) -> str` and `to_display_path(value) -> str` in
  `ytdlp_config.py` hold the two conversions.

## 2. Preferences dialog

### 2.1 Opening and saving

- File > Preferences… opens `PrefsDialog` (`yoink/ui/prefs_dialog.py`), a
  modal dialog. A list box down the left side names the pages, each with
  an icon; a `QStackedWidget` on the right shows the selected page. Phase 2
  has two pages, Yoink and yt-dlp. The Domains page arrives in Phase 3.
- Icons come from Qt's standard set (`QStyle.StandardPixmap`), so no image
  files ship with the app: `SP_ComputerIcon` for Yoink, `SP_FileIcon` for
  yt-dlp, and `SP_DriveNetIcon` for Domains. Swapping in drawn icons later
  is one line per page.
- The menu item is disabled while the probe runs, like Download, so the
  dialog always opens with a finished probe result.
- **Save** writes the yt-dlp config if any yt-dlp widget changed, and the
  binary path if it changed, then closes. **Cancel** discards both.
- After a config write or a binary path change, the main window reruns the
  probe.

### 2.2 yt-dlp page: widgets

The option table in `prefs_dialog.py` maps each option to its group,
label, widget, and tooltip (2.3). Growing the set means adding a row.
Each group is a `QGroupBox`, in the order below, and the page scrolls if
it is taller than the dialog.

| Group | Option | Label | Widget |
|-------|--------|-------|--------|
| Files | `--paths` | Download folder | line edit + **Browse…** (directory) |
| Files | `--output` | File name | line edit |
| Files | `--download-archive` | Download archive | line edit + **Browse…** (file, may not exist yet) |
| Video | `--format` | Format | editable combo with presets |
| Video | `--merge-output-format` | Merged file type | editable combo: blank, mp4, mkv, webm, mov |
| Video | `--embed-thumbnail` | Embed thumbnail | checkbox |
| Video | `--embed-metadata` | Embed metadata | checkbox |
| Video | `--sponsorblock-remove` | Remove SponsorBlock segments | line edit |
| Subtitles | `--write-subs` | Save subtitles | checkbox |
| Subtitles | `--embed-subs` | Embed subtitles | checkbox |
| Subtitles | `--sub-langs` | Subtitle languages | line edit |
| Sign-in | `--cookies-from-browser` | Use cookies from browser | checkbox with the browser combo on the same line; below it, indented: profile, container, and keyring fields |
| Sign-in | `--cookies` | Use cookies from a file | checkbox, then line edit + **Browse…** (file) on the same line |
| Network | `--proxy` | Proxy | line edit |
| Network | `--limit-rate` | Speed limit | line edit |

Format presets. The first item is blank, which means yt-dlp's default (the
best quality available). Choosing a preset puts its format string in the
edit field, where it can be changed freely:

| Preset | Writes |
|--------|--------|
| 1080p or lower | `bv*[height<=1080]+ba/b[height<=1080]` |
| 720p or lower | `bv*[height<=720]+ba/b[height<=720]` |
| 480p or lower | `bv*[height<=480]+ba/b[height<=480]` |
| Audio only | `ba/b` |

Browser cookies. The spec is one value, `BROWSER[+KEYRING][:PROFILE][::CONTAINER]`:
the browser is required and the other three parts are optional
refinements of it. `split_cookie_spec(spec)` and `join_cookie_spec(browser,
keyring, profile, container)` in `ytdlp_config.py` convert between it and
the fields, following yt-dlp's own pattern for the spec.

```
[x] Use cookies from browser  [firefox   v]
    Profile:    [__________]
    Container:  [__________]
    Keyring:    [          v]
```

- Unchecked: no line. The fields below are disabled. Checking the box
  enables the browser combo, which defaults to the first browser.
- Browser combo: `BROWSERS`. The list moves from `main_window.py` to
  `ytdlp_config.py` so both windows share it.
- Profile: enabled for every browser.
- Container: enabled only for Firefox.
- Keyring combo (blank, `BASICTEXT`, `GNOMEKEYRING`, `KWALLET`,
  `KWALLET5`, `KWALLET6`): enabled only for a Chromium-based browser
  (brave, chrome, chromium, edge, opera, vivaldi, whale) and only on
  Linux, where yt-dlp uses it.
- A disabled field keeps its text but is left out of the spec. Its
  tooltip says which browsers it applies to.

Cookies file. Unchecked: no line. Checked: the path field and **Browse…**
are enabled, and Save rejects an empty path with a message.

### 2.3 Tooltips

Every widget has a tooltip written for nontechnical users: short sentences,
no jargon, and no flag names. The text below is final unless a review
changes it.

| Option | Tooltip |
|--------|---------|
| `--paths` | The folder where videos are saved. Leave empty to save them in your Downloads folder. The Save to field in the main window can still choose a different folder for one download. |
| `--output` | How downloaded files are named. Leave empty for the usual name: the video title followed by its ID. Example: %(title)s.%(ext)s names each file after its video title only. |
| `--format` | Which version of the video to download. Leave empty to get the best quality available. Pick a preset, or type your own. |
| `--cookies-from-browser`, checkbox | Uses your sign-in from a web browser, so you can download videos that need an account. Turn it off to download without signing in. |
| `--cookies-from-browser`, browser | The browser you are signed in with. |
| `--cookies-from-browser`, profile | The browser profile to use, if you have more than one. Leave empty for the one you used most recently. |
| `--cookies-from-browser`, container | Firefox only. The container tab to take your sign-in from. Leave empty to use all of them. Type none to use only tabs outside any container. |
| `--cookies-from-browser`, keyring | Only used on Linux, with Chrome and similar browsers. Tells yt-dlp where the browser keeps its saved passwords. Leave empty to find it automatically. |
| `--cookies`, checkbox | Uses a cookies file saved from your browser, for videos that need an account. Most people should use cookies from browser instead. Downloads also save updated cookies back to this file, including any from the browser when both are on. |
| `--cookies`, path | The cookies file to use. |
| `--embed-thumbnail` | Adds the video's thumbnail picture to the file, so it shows as cover art. |
| `--embed-metadata` | Adds details such as the title, uploader, and date to the file. |
| `--embed-subs` | Puts subtitles inside the video file, so video players can show them. Works with MP4, MKV, and WebM files. |
| `--write-subs` | Saves subtitles as separate files next to the video. |
| `--sub-langs` | Which subtitle languages to get, separated by commas. Example: en,es gets English and Spanish. Type all for every language. Leave empty for English. |
| `--merge-output-format` | The file type to use when the picture and sound are downloaded separately and joined. Leave empty to choose automatically. MP4 plays almost everywhere. |
| `--download-archive` | Keeps a list of videos you already downloaded, so they are skipped next time. Pick any file name; the file is created if it doesn't exist. |
| `--sponsorblock-remove` | Cuts sponsor messages and similar parts out of YouTube videos, using a list shared by other viewers. Type the kinds of parts to cut, separated by commas. Example: sponsor,selfpromo. Type all to cut every kind. |
| `--proxy` | Sends downloads through another server. Only needed if your network or a proxy service requires it. Leave empty to connect directly. Example: socks5://127.0.0.1:1080 |
| `--limit-rate` | Slows downloads so they use less of your internet connection. Leave empty for full speed. Example: 5M means 5 megabytes per second. |
| Yoink page, binary path | The yt-dlp program that Yoink runs. Leave empty to use the one Yoink finds on its own. |
| Yoink page, **Update** | Updates the yt-dlp program that Yoink is using, or shows how to update it. |

A disabled widget (1.2, repeated option) replaces its tooltip with: "This
setting appears on more than one line of your config file. Edit the file to
change it."

### 2.4 Warning box

A read-only box at the bottom of the yt-dlp page.

- The header shows the config file's path (native form) and an **Open in
  editor** button, which calls `QDesktopServices.openUrl` with
  `QUrl.fromLocalFile(path)`. The button is disabled while the file does not
  exist. On Windows a file named `config` has no extension, so the system may
  ask which program to use; that is acceptable.
- Below the header, a list of every line Yoink does not manage, each shown
  exactly as written: unmanaged options, short flags, lines carrying several
  options, lines that can't be split, and repeated managed options (1.2).
  A short note says these lines are kept as they are.
- When the page is read-only (1.4), the box says why in place of the note,
  and every widget is disabled.
- With nothing to list and an editable page, the box shows only the header.

### 2.5 Yoink page

- **yt-dlp program**: a line edit with **Browse…**, stored in the existing
  `KEY_BINARY_PATH`. Empty means `yt-dlp` on PATH, through
  `binary.find_binary`. Save rejects a path that is not a file, with a
  message.
- **Update** sits next to the field and acts on the binary in use (3.3). Its
  tooltip names that binary's path.
- When the path changes, the main window resolves the binary again and
  reruns the probe.

## 3. Status bar and update

### 3.1 Install method

`binary.install_method(path, variant) -> str`, per DESIGN.md 6.3:

- For variant `pip`, it classifies `path.resolve().as_posix()`: `/Cellar/`
  gives Homebrew, `/opt/local/` MacPorts, `pipx/venvs` pipx, `uv/tools` uv
  tool, and anything else pip.
- Any other variant is returned unchanged (`win_exe`, `darwin_dir`, a
  starred variant). An empty variant gives `unknown`.
- Known limit: on Windows, pipx and uv put copies of `yt-dlp.exe` on PATH
  rather than links, so those installs show as pip.

The status bar shows the method in place of the variant: "yt-dlp 2026.10.21
(Homebrew)", "yt-dlp 2026.10.21 (win_exe)". The tooltip keeps the binary
path.

### 3.2 Staleness warning

yt-dlp's own warning ("Your yt-dlp version (…) is older than 90 days!")
never appears in the probe output. yt-dlp sets `warn_when_outdated` only
when `--update` / `--no-update` is absent, and the probe passes
`--no-update` (checked in the 2026.10.26 source). The probe must keep that
flag, or a config containing `--update` would update yt-dlp on every probe.

Yoink therefore applies yt-dlp's own rule to the debug header:
`is_stale(text, today) -> bool` in `ytdlp_config.py` is true when the origin
starts with `yt-dlp/` and the date in the version is more than 90 days before
`today`. The status bar then reads "yt-dlp 2026.01.02 (Homebrew), over 90
days old", with this tooltip: "This copy of yt-dlp is more than 90 days old.
Sites change often, so an old copy is the usual reason downloads or cookies
stop working. Update it from File > Preferences."

### 3.3 Update button

Per DESIGN.md 6.4. Yoink never runs a package manager.

| Variant | Update does |
|---------|-------------|
| `zip`, or ending in `_exe` | runs `<binary> -U` through a `QProcess`, shows its combined output in a simple dialog, then reruns the probe. Closing the dialog kills the process if it is still running. An unwritable binary is reported by yt-dlp itself in that output. |
| `pip` | shows the command for the install method in a read-only field with a **Copy** button (table below) |
| ending in `_dir`, starred, or unknown | shows an explanation (below) |

| Method | Command |
|--------|---------|
| Homebrew | `brew upgrade yt-dlp` |
| MacPorts | `sudo port upgrade yt-dlp` |
| pipx | `pipx upgrade yt-dlp` |
| uv tool | `uv tool upgrade yt-dlp` |
| pip | `python3 -m pip install -U yt-dlp`, or `python -m pip install -U yt-dlp` on Windows |

Explanations:

- `_dir`: "This copy of yt-dlp can't update itself. To update it, download
  the latest release from github.com/yt-dlp/yt-dlp and replace the folder
  it came in."
- Starred or unknown: "Yoink can't tell how this copy of yt-dlp was
  installed. Update it the same way you installed it."

`binary.can_self_update(variant)` and `binary.update_command(method)` hold
the two tables.

## 4. Work items

| File | Change | Lines (approx.) |
|------|--------|-----------------|
| `yoink/ytdlp_config.py` | line model, `read_config`, `write_config`, `set_option`, managed-line rules, `matches_probe`, cookie spec, path conversions, `is_stale`, `BROWSERS` moved here | 135 |
| `yoink/binary.py` | `install_method`, `can_self_update`, `update_command` | 30 |
| `yoink/ui/prefs_dialog.py` (new) | `PrefsDialog`: page list, both pages, group boxes, option table and tooltips, warning box, update dialogs | 280 |
| `yoink/ui/main_window.py` | File > Preferences…, binary path change, install method, staleness text, native directory placeholder | 40 |
| `yoink/ui/config_notice.py` | native display of directory values | 3 |

Total: about 490 lines, bringing the app to about 1500. `ytdlp_config.py`
grows to about 335 lines, under the 350 at which it should be split.

### Tests (new)

Nearly all pure functions; no Qt event loop. About 150 lines.

- `tests/test_ytdlp_config.py`
  - line model: blanks, comments, `--opt value` and `--opt=value`, a
    trailing comment, short flags, two options on one line, an unbalanced
    quote; `format_lines(parse_lines(text)) == text` for each, including
    CRLF endings
  - `set_option`: rewrite, append, remove, a checkbox, quoting of spaces and
    `'`, a trailing comment kept; `Opaque` lines unchanged byte for byte
  - managed lines: `--paths temp:` is unmanaged, `--paths home:` is
    managed, a repeated option is unmanaged
  - `read_config` and `write_config` (in `tmp_path`): UTF-8 BOM, UTF-16
    BOM, a `# coding:` line and no marker all round-trip; a new file gets a
    UTF-8 BOM; an unencodable value raises and leaves the file untouched
  - `matches_probe`: an exact match, a value spanning two lines,
    `--password x` against `PRIVATE`, `--username=x` against
    `--username=PRIVATE`
  - `split_cookie_spec` and `join_cookie_spec`: browser only, each part
    alone, all four, container without profile
  - `is_stale`: 89 and 91 days old, a non-`yt-dlp/` origin, an unparseable
    header
  - path conversions: forward slashes written, native form shown (Windows
    cases skipped elsewhere)
- `tests/test_binary.py`: `install_method` for each path in 3.1 and a
  non-pip variant; `can_self_update` and `update_command` for every row of
  the 3.3 tables.

## 5. Out of scope

- Listing every candidate binary with its version and install method, and
  discovery in well-known locations (DESIGN.md 6.2). Both move to Phase 4.
- A Yoink-managed binary download (Phase 4).
- "Update policy". It is dropped: nothing defines or uses it.
- Any widget beyond the table in 2.2, a raw text editor, and an editable
  list of other options.
- Editing portable, home, system, or included config files.
- The Domains page (Phase 3).

## 6. Tasks

Each task is one commit and leaves the app runnable. T1, T2, and T3 do not
depend on each other. T4 needs T1 and T3; T5 needs T2 and T3.

```
T0 ─┬─ T1 ─────────┐
    ├─ T3 ─┬───────┴── T4 ─┐
    │      └───┐           ├─ T6
    └─ T2 ─────┴────── T5 ─┘
```

### T0. Phase 1 leftovers (~1 line)

- Run the remaining Phase 1 exit checks listed in PHASE1.md: a visible
  click-through of the T4 to T6 checks with the "Yoink (sandbox)" run
  configuration, and one real cookie-gated download with a browser chosen
  in the combo. Record the results in PHASE1.md's Status section.
- Fix the Windows-only failure in `tests/test_app.py`:
  `QSettings.fileName()` returns forward slashes, so compare
  `Path(s.fileName()) == tmp_path / "yoink.ini"` instead of strings.

Done when `uv run pytest` passes on Windows, and PHASE1.md lists the manual
checks as passed, or names any failure and its fix.

### T1. Config file model (~125 lines, tests ~95)

- `Blank`, `Comment`, `Option`, `Opaque`, `parse_lines`, `format_lines`,
  and `set_option` (1.2).
- Managed-line rules, given the set of option names (1.2).
- `ConfigFile`, `read_config`, `write_config` (1.3).
- `matches_probe` with login masking (1.4).
- `split_cookie_spec`, `join_cookie_spec`, `to_config_path`,
  `to_display_path`.

Done when the T1 cases in section 4 pass. No Qt imports.

### T2. Build identification and status bar (~60 lines, tests ~45)

- `install_method`, `can_self_update`, `update_command` in `binary.py`.
- `is_stale` in `ytdlp_config.py`.
- Status bar text and tooltip per 3.1 and 3.2.
- `to_display_path` (or `os.path.normpath` directly, if T1 isn't merged
  yet) for the directory placeholder and `ConfigNoticeDialog` values.

Done when:
- `tests/test_binary.py` and the `is_stale` cases pass.
- The sandbox with `--pypi-yt-dlp` shows "(pip)"; a Windows `yt-dlp.exe`
  shows "(win_exe)"; a Homebrew install shows "(Homebrew)".
- A yt-dlp release more than 90 days old, set as the binary path, shows the
  staleness text and tooltip.
- On Windows, a user config with `--paths C:/Users/<you>/Videos` shows
  `C:\Users\<you>\Videos` in the directory placeholder and in the override
  dialog.

### T3. Preferences dialog and Yoink page (~60 lines)

- `PrefsDialog` with Save and Cancel, and File > Preferences…, disabled
  while the probe runs.
- Yoink page: the binary path field and **Browse…** (2.5). The **Update**
  button arrives in T5.
- `MainWindow` resolves the binary again and reruns the probe when the path
  changes.

Done when:
- Pointing the field at a second yt-dlp changes the version in the status
  bar after Save.
- Clearing the field returns to the yt-dlp on PATH.
- A path that is not a file is rejected with a message.
- Cancel changes nothing.

### T4. yt-dlp page (~200 lines)

- The option table with labels, widgets, and tooltips (2.2, 2.3).
- Loading from `read_config` and the `User` entry of
  `MainWindow.loaded_configs`; the read-only states (1.4).
- The warning box and **Open in editor** (2.4).
- Save through `set_option` and `write_config`, with the changed-file check
  (1.3), then a probe rerun.

Done when these sandbox checks pass:
- No user config: open Preferences and Save with no changes; no file is
  created. Set a speed limit and Save; the file appears at the DESIGN.md
  3.1 path, starts with a UTF-8 BOM, and contains one line.
- A hand-written config with comments, blank lines, `--no-mtime`, and
  `-f best`: change the format and Save. A diff against a copy shows one
  appended `--format` line and nothing else changed. `--no-mtime` and
  `-f best` are in the warning box.
- Clear the format and Save: the file matches the copy again.
- Pick `C:\Users\<you>\Videos` as the download folder on Windows. The file
  has `--paths C:/Users/<you>/Videos`, the widget and the main window
  placeholder show the native path, and a sandbox download lands there.
- Check **Use cookies from browser**, pick Firefox, and fill in a
  profile and container: the file has
  `--cookies-from-browser firefox:<profile>::<container>`, and reopening
  Preferences shows the same fields. Switching to Chrome grays out the
  container field and drops it from the saved line. Unchecking the box
  removes the line.
- Check **Use cookies from a file** with an empty path: Save shows a
  message. With a path, the file has `--cookies <path>` with forward
  slashes.
- A quoted value that spans two lines: the page is read-only and the box
  says why. A config with `--password x`: the page stays editable.
- `--sub-langs` on two lines: both lines are in the box and the widget is
  disabled.
- Edit the file through **Open in editor** while Preferences is open, then
  Save: Yoink refuses and the external edit survives.

### T5. Update button (~35 lines)

- **Update** on the Yoink page, per 3.3.

Done when:
- An older `yt-dlp.exe` (or a zipapp) copied to a temp directory and set as
  the binary path updates through **Update**; the dialog shows yt-dlp's
  output and the status bar shows the new version afterwards.
- The `--pypi-yt-dlp` sandbox shows `python3 -m pip install -U yt-dlp`, and
  **Copy** puts it on the clipboard.
- A folder build shows the `_dir` explanation.

### T6. Docs

- Fill in this file's Status section, mark Phase 2 done in DESIGN.md
  section 8, and update the README status line.
- Note in DESIGN.md anything the implementation changed.

### Phase 2 exit check

- `uv run pytest` passes on Windows and on macOS or Linux.
- Every T2 to T5 check passes in one session.
- A real, hand-written user config survives a change and a save with only
  the changed line different.
- A plain `yt-dlp` run in a terminal picks up options set in Preferences.
