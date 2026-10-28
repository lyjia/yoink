# Phase 3 scope: per-domain rules

## Status

Implemented on branch `phase-3-domains`. `uv run pytest` passes (172
tests, plus 1 skipped on Windows). Application code is about 2280 lines,
against the roughly 2250 estimated in section 6.

| Task | Commit |
|------|--------|
| Scope | `f24535e` |
| T1 | `2a917a9` |
| T2 | `521c7e2` |
| T3 | `cd8cf61` |
| T4 | `f00e7ee` |
| T5 | `15123d4` |
| T6 | `3d11115` |
| Review fixes | `6ef2c71` |

Changed or added during implementation:

- A URL without a scheme (`youtube.com/watch?v=x`) also matches a rule.
  The host is parsed as if `//` preceded it, because yt-dlp accepts such
  URLs.
- The green border is a style sheet scoped to the widget's class
  (`QComboBox { border: ... }`), so the combo's popup list keeps its own
  frame.
- `_refresh_defaults` calls `_overrides_changed`, not the reverse as in
  section 5. The defaults are set first, then the borders and tooltips, in
  one place.
- `options_form.py` exposes `browse_row(edit, kind)` as a module function,
  which the Yoink page's binary field also uses. The browser field builder
  is a module function too. `_Field.set` takes `set_option`'s vocabulary:
  `""` or `False`, `True`, or a string.
- The Domains page sorts rules by domain, and keeps **Edit…** and
  **Remove** disabled until a row is selected. One `_edit_rule` handles
  both **Add…** and **Edit…**. The rule editor rejects a domain another
  rule has, so a duplicate does not discard what was typed.
- The pin's confirmation shows the old and new folder. The first pin for a
  host creates the rule without asking. The pin's domain is the matched
  rule's domain, else the URL's host without `www.`.
- `PrefsDialog` gained `rules_written`. Save writes `overrides.json` only
  when the rules changed, before the yt-dlp config, so a failed rules
  write keeps the dialog open and Save can be retried.
- `load_rules` keeps only well-formed entries: a domain that normalizes to
  something, an object value, and string or boolean settings. Anything
  else is dropped with one warning. A rule's `--paths` counts only when it
  is a home path, as the config's does.
- `rule_lines` formats a rule for the Domains page and the rule label;
  `rule_argv` builds on it.
- `normalize_domain(" www. ")` yields `www`, which the rule editor
  accepts. This is harmless and left alone.

Remaining for the exit check:

- A visible click-through of the T3 to T5 checks in the real window. They
  were checked headless (`QT_QPA_PLATFORM=offscreen`), and the deliverable
  download has not been run.
- The look of the green border under the Windows and Fusion styles.
- The sandbox run with a `127.0.0.1` rule.
- `uv run pytest` on macOS or Linux, and a plain `yt-dlp` run with a rule
  present, to confirm the config file is untouched.

Source: [DESIGN.md](DESIGN.md) section 8, Phase 3, plus sections 2.1 to
2.3, 4, and 5.

Deliverable: add a rule for `youtube.com` in Preferences > Domains with a
download folder and "Embed subtitles". Paste a `www.youtube.com` URL: the
Save to placeholder shows the rule's folder with a green border, a label
names the rule, and the download lands there with subtitles embedded. A URL
from another site behaves as in Phase 2.

Decisions made while scoping, which change DESIGN.md section 5:

- **A rule is a set of yt-dlp options.** It is not three fixed fields
  (`destination`, `cookies`, `extra_args`). It is edited with the same
  widgets as the yt-dlp page of Preferences, in one rule editor dialog per
  domain row.
- **A rule changes defaults, never controls.** A matched rule changes the
  default of each unset main-window control. It never writes into a
  control, so field text stays purely the user's override. Controls whose
  default comes from a rule get a green border.
- **Cookies follow the config's pattern.** The rule's cookies value shows
  as the cookies combo's first item, as the config value does today. A
  rule cannot force cookies off, because the browser field's unchecked
  state means "follow the config". This is accepted.
- **`overrides.json` lives with Yoink's app data.** It is in
  `QStandardPaths.AppDataLocation` (`%APPDATA%\Lyjia\Yoink` on Windows), or
  in `YOINK_SETTINGS_DIR` when that is set.
- **The border costs the native frame.** A stylesheet border forces a
  non-native frame on that widget while a rule applies. This is accepted;
  `f6033d0` already does the same in red for the binary field.

## 1. Rules (`yoink/overrides.py`, new)

- Storage: `overrides.json`, a JSON object keyed by domain:

  ```json
  {
    "youtube.com": {
      "--paths": "D:/video/yt",
      "--format": "bv*[height<=1080]+ba",
      "--embed-subs": true
    }
  }
  ```

  Values are exactly what the option form's `values()` returns
  (`set_option`'s vocabulary: a string, or `True` for a bare flag); unset
  options are omitted. Paths are stored with forward slashes
  (`to_config_path`), as in the yt-dlp config (DESIGN.md 3.2).
- `rules_path()`: `YOINK_SETTINGS_DIR/overrides.json` if the variable is
  set (the sandbox), else `QStandardPaths.writableLocation(AppDataLocation)`.
  Same branch as `app.settings()`.
- `load_rules(path) -> dict[str, dict]`: `{}` for a missing file; a
  malformed file logs a warning and returns `{}`.
- `save_rules(path, rules)`: creates the directory, writes `indent=2`.
- `match(host, rules) -> str | None`: the host is `urlparse(url).hostname`
  (lowercase, no port). A domain matches when `host == d` or
  `host.endswith("." + d)`, so `notyoutube.com` does not match
  `youtube.com`. The longest matching domain wins.
- `normalize_domain(text)`: strip whitespace and dots, lowercase. A
  leading `www.` is dropped, so pinning on `www.youtube.com` creates a
  `youtube.com` rule.
- `rule_argv(options) -> list[str]`: `[name]` for `True`, `[name, value]`
  for a string, in the order of the option table.

## 2. Command line (`yoink/argv.py`)

- `build_argv(url, directory, cookies, extra=())`: `extra` goes first, in
  the domain rule slot of DESIGN.md 2.2. Config, then rule, then
  main-window overrides, then Yoink's fixed flags.
- `MainWindow.start_download` passes `rule_argv(rule)`. The
  Downloads-folder fallback is skipped when the rule sets `--paths` (it
  joins "the config sets a home path" in that test). The directory-exists
  check applies only to a typed directory, as now.

## 3. Option form (`yoink/ui/options_form.py`, new)

A refactor of `prefs_dialog.py`. The yt-dlp page's option table,
tooltips, `_Field`, `_make_field`, the browser and cookies-file builders,
and `_browse_row` move into `OptionsForm(QScrollArea)`. No behaviour change
on the yt-dlp page.

- `OptionsForm(placeholders: dict[str, str])`: the group boxes from
  `OPTIONS`. `fields: dict[str, _Field]` stays public for the page's
  repeated-line handling (`owned_lines(lines, form.fields)`).
- `values() -> dict[str, str | bool]`: every field's `get()`.
- `load(values: Mapping[str, str | bool])`: missing keys are unset.
  `_Field.set` changes from `Callable[[Option | None], None]` to
  `Callable[[str | bool], None]`, using `set_option`'s vocabulary: `""` or
  `False` unset, `True` a bare flag, a string a value. The yt-dlp page
  converts a line with `True if line.value is None else line.value`.
- `validate() -> str`: the error message now in `PrefsDialog.accept` for a
  checked cookies file with no path, or `""`.
- `prefs_dialog.py` keeps `PrefsDialog`, the pages, and `RuleDialog`. It
  ends near 420 lines; `options_form.py` near 280.

## 4. Preferences: Domains page and rule editor (`yoink/ui/prefs_dialog.py`)

- Third page, "Domains", icon `SP_DriveNetIcon` (PHASE2.md 2.1). A
  read-only two-column `QTableWidget`, Domain and Settings, one row per
  rule; Settings is `" ".join(rule_argv(options))`. Buttons **Add…**,
  **Edit…**, **Remove**; double-click edits.
- `RuleDialog(domain, options, parent)`: a Domain line edit (tooltip: "A
  site name such as youtube.com. The rule also applies to its subdomains,
  such as www.youtube.com.") above an `OptionsForm` with no placeholders
  and a note that an empty field follows the yt-dlp config. OK rejects an
  empty domain and runs `form.validate()`. Results in `.domain` and
  `.options` (truthy values only).
- The page rejects a domain that another row already has.
- Save writes `save_rules` only if the rules changed, and sets
  `rules_written`; the main window reloads them (as it does for
  `config_written`). Cancel discards.

## 5. Main window (`yoink/ui/main_window.py`)

- `self.rules` loaded at startup, after Preferences Save with
  `rules_written`, and after a pin.
- `url_edit.textChanged` → `_url_changed`: match the host; store
  `self.rule_domain` and `self.rule` (`{}` when none). Then
  `_refresh_defaults()`, also called from `_probe_done` and
  `_overrides_changed`:
  - Directory placeholder: the rule's `--paths` (display form) if set,
    else the Phase 1 logic (config path, "Set by yt-dlp config", or
    Downloads).
  - Cookies first item: `Config default (<rule spec>)` if the rule sets
    `--cookies-from-browser`, else the config value. `self.config_cookies`
    becomes the effective default, so the Phase 1 tooltip and pitfall text
    follow it.
  - Green border (`setStyleSheet("border: 2px solid green")`) on the
    directory field while the rule sets `--paths` and the field is empty,
    and on the cookies combo while the rule sets cookies and the combo is
    on the first item. Cleared otherwise. Tooltips for both say "Default
    from the <domain> rule."
- Rule label: a `QLabel` in a third grid row, "Rule for youtube.com
  applies", hidden when nothing matches. Tooltip: the rule's flags one per
  line, since most options have no main-window control.
- Pin: a `QToolButton` (`SP_DialogSaveButton`) after **Browse…**. Enabled
  when the URL has a host and the directory field has text. Tooltip states
  the exact write: "Save <dir> as the download folder for <domain>". If
  the matched rule already has a different `--paths`, a Yes/No question
  names the old and new folder first. Writes `save_rules`, reloads, and
  refreshes the defaults. The field keeps its text; it is still an
  override until cleared.
- PHASE1.md 2.3's "Reset also clears a destination prefilled by a domain
  rule" no longer applies: a rule is a default, not a prefill. Reset is
  unchanged.

## 6. Work items

| File | Change | Lines (approx.) |
|------|--------|-----------------|
| `yoink/overrides.py` (new) | storage, matching, `rule_argv` | 60 |
| `yoink/argv.py` | `extra` parameter | 5 |
| `yoink/ui/options_form.py` (new) | moved from `prefs_dialog.py`, plus `values`, `load`, `validate` | 280 (net +30) |
| `yoink/ui/prefs_dialog.py` | Domains page, `RuleDialog`, uses `OptionsForm` | +90 net of the move |
| `yoink/ui/main_window.py` | rule matching, defaults, borders, label, pin | 80 |
| `yoink/app.py` | nothing (the settings-dir branch is reused from `overrides.rules_path`) | 0 |

Total: about 270 new lines, bringing the app to about 2250.

### Tests (new)

- `tests/test_overrides.py` (~60 lines): `match` for exact host,
  subdomain, a non-label suffix (`notyoutube.com`), longest wins,
  uppercase host; `normalize_domain` for `www.`, dots, case; `load_rules`
  for a missing file, malformed JSON, and a save/load round trip in
  `tmp_path` with `YOINK_SETTINGS_DIR`; `rule_argv` for a flag, a value,
  and skipped falsy values.
- `tests/test_argv.py`: `extra` precedes `-P` and the cookies flag.

## 7. Out of scope

- Matching beyond host suffix, per-path rules, domain aliases
  (`youtu.be` is its own rule).
- A rule that forces cookies off.
- Options outside the yt-dlp page's table; a raw extra-args field.
- Importing or exporting rules.

## 8. Tasks

Each task is one commit and leaves the app runnable. T1 and T2 do not
depend on each other. T3 needs both; T4 needs T3, because its checks add
the rule through Preferences.

```
T1 ─┐
    ├── T3 ── T4 ── T5 ── T6
T2 ─┘
```

### T1. `overrides.py` (~60 lines, tests ~60)

- Section 1.
- The `build_argv` change in section 2, with its test.

Done when `uv run pytest` passes, including the section 6 tests.

### T2. `OptionsForm` extraction (~30 lines net)

- Section 3.

Done when:
- `uv run pytest` passes.
- The T4 checks in PHASE2.md still pass in the sandbox for Save, Cancel,
  the repeated-line disable, and the cookies-file message.

### T3. Domains page and `RuleDialog` (~90 lines)

- Section 4.

Done when:
- A rule added, edited, and removed round-trips through `overrides.json`.
- A duplicate domain is rejected.
- After Save, `overrides.json` has the shape in section 1, with forward
  slashes in paths.

### T4. Main-window defaults (~65 lines)

- Section 5, without the pin.
- The `start_download` change in section 2.

Done when:
- The deliverable check passes.
- The cookies combo shows a rule's browser.
- Both borders appear, and clear as the fields are filled.
- A URL with no rule shows the Phase 2 behaviour.
- In the sandbox with a user config that sets `--paths`, add a
  `127.0.0.1` rule with a different folder and paste the clip URL. The
  placeholder, border, label, and landing folder all follow the rule.
  Clear the rule's folder: the config's folder returns.
- With a rule active, type a folder into Save to: the border clears and
  the typed folder wins. Clear the field: the rule's default returns.

### T5. Pin button (~15 lines)

- The pin in section 5.

Done when:
- `uv run pytest` passes.
- Pinning a new host creates a rule.
- Pinning over an existing folder asks first, and answering No leaves the
  file unchanged.
- After a pin, `overrides.json` has the shape in section 1, with forward
  slashes in paths.

### T6. Docs

- Fill in this file's Status section, mark Phase 3 done in DESIGN.md
  section 8, and update the README status line.

### Phase 3 exit check

- `uv run pytest` passes on Windows and on macOS or Linux.
- The deliverable, run in the sandbox with a `127.0.0.1` rule (the sandbox
  clip's host).
- A plain `yt-dlp` run is unaffected by any rule (rules never touch the
  config file).
