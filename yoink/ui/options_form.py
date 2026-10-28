"""The yt-dlp option widgets, shared by the yt-dlp page and the rule editor (docs/PHASE3.md section 3)."""

import os
import sys
from collections.abc import Callable, Mapping
from typing import NamedTuple

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from yoink.ytdlp_config import (
    BROWSERS,
    home_path,
    join_cookie_spec,
    split_cookie_spec,
    to_config_path,
    to_display_path,
)

FORMATS = {
    "": "",
    "1080p or lower": "bv*[height<=1080]+ba/b[height<=1080]",
    "720p or lower": "bv*[height<=720]+ba/b[height<=720]",
    "480p or lower": "bv*[height<=480]+ba/b[height<=480]",
    "Audio only": "ba/b",
}
MERGE_FORMATS = {f: f for f in ("", "mp4", "mkv", "webm", "mov")}
KEYRINGS = ["", "BASICTEXT", "GNOMEKEYRING", "KWALLET", "KWALLET5", "KWALLET6"]
CHROMIUM = {"brave", "chrome", "chromium", "edge", "opera", "vivaldi", "whale"}

# The option table (PHASE2.md 2.2, 2.3): group, option, label, widget kind, tooltip. A
# dict kind is an editable combo of {item: value}; the other kinds are in _make_field.
OPTIONS = [
    ("Files", "--paths", "Download folder", "folder",
     "The folder where videos are saved. Leave empty to save them in your Downloads folder. "
     "The Save to field in the main window can still choose a different folder for one download."),
    ("Files", "--output", "File name", "text",
     "How downloaded files are named. Leave empty for the usual name: the video title followed "
     "by its ID. Example: %(title)s.%(ext)s names each file after its video title only."),
    ("Files", "--download-archive", "Download archive", "archive",
     "Keeps a list of videos you already downloaded, so they are skipped next time. "
     "Pick any file name; the file is created if it doesn't exist."),
    ("Video", "--format", "Format", FORMATS,
     "Which version of the video to download. Leave empty to get the best quality available. "
     "Pick a preset, or type your own."),
    ("Video", "--merge-output-format", "Merged file type", MERGE_FORMATS,
     "The file type to use when the picture and sound are downloaded separately and joined. "
     "Leave empty to choose automatically. MP4 plays almost everywhere."),
    ("Video", "--embed-thumbnail", "Embed thumbnail", "check",
     "Adds the video's thumbnail picture to the file, so it shows as cover art."),
    ("Video", "--embed-metadata", "Embed metadata", "check",
     "Adds details such as the title, uploader, and date to the file."),
    ("Video", "--sponsorblock-remove", "Remove SponsorBlock segments", "text",
     "Cuts sponsor messages and similar parts out of YouTube videos, using a list shared by "
     "other viewers. Type the kinds of parts to cut, separated by commas. "
     "Example: sponsor,selfpromo. Type all to cut every kind."),
    ("Subtitles", "--write-subs", "Save subtitles", "check",
     "Saves subtitles as separate files next to the video."),
    ("Subtitles", "--embed-subs", "Embed subtitles", "check",
     "Puts subtitles inside the video file, so video players can show them. "
     "Works with MP4, MKV, and WebM files."),
    ("Subtitles", "--sub-langs", "Subtitle languages", "text",
     "Which subtitle languages to get, separated by commas. Example: en,es gets English and "
     "Spanish. Type all for every language. Leave empty for English."),
    ("Sign-in", "--cookies-from-browser", "Use cookies from browser", "browser",
     "Uses your sign-in from a web browser, so you can download videos that need an account. "
     "Turn it off to download without signing in."),
    ("Sign-in", "--cookies", "Use cookies from a file", "cookies",
     "Uses a cookies file saved from your browser, for videos that need an account. Most people "
     "should use cookies from browser instead. Downloads also save updated cookies back to this "
     "file, including any from the browser when both are on."),
    ("Network", "--proxy", "Proxy", "text",
     "Sends downloads through another server. Only needed if your network or a proxy service "
     "requires it. Leave empty to connect directly. Example: socks5://127.0.0.1:1080"),
    ("Network", "--limit-rate", "Speed limit", "text",
     "Slows downloads so they use less of your internet connection. Leave empty for full speed. "
     "Example: 5M means 5 megabytes per second."),
]
BROWSER_TIPS = {
    "browser": "The browser you are signed in with.",
    "profile": "The browser profile to use, if you have more than one. "
               "Leave empty for the one you used most recently.",
    "container": "Firefox only. The container tab to take your sign-in from. Leave empty to use "
                 "all of them. Type none to use only tabs outside any container.",
    "keyring": "Only used on Linux, with Chrome and similar browsers. Tells yt-dlp where the "
               "browser keeps its saved passwords. Leave empty to find it automatically.",
}
COOKIES_PATH_TIP = "The cookies file to use."
# What an empty field means, for the options whose default is known (PHASE2.md 2.5).
PLACEHOLDERS = {"--output": "%(title)s [%(id)s].%(ext)s", "--sub-langs": "en"}


class _Field(NamedTuple):
    row: QWidget  # disabled as a whole when the option is repeated
    get: Callable[[], str | bool]  # the value for set_option
    set: Callable[[str | bool], None]  # show a value, in set_option's terms


def _text(value: str | bool) -> str:
    return value if isinstance(value, str) else ""


def side_by_side(*widgets: QWidget, stretch: int | None = 0) -> QWidget:
    """Widgets side by side; widgets[stretch] takes the spare room, or nothing if None."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    for i, w in enumerate(widgets):
        layout.addWidget(w, int(i == stretch))
    if stretch is None:
        layout.addStretch()
    return row


def browse_row(edit: QLineEdit, kind: str = "file") -> QWidget:
    """`edit` with a Browse… button for an existing file, a "folder", or an "archive"."""
    def browse() -> None:
        start = edit.text()
        if kind == "folder":
            chosen = QFileDialog.getExistingDirectory(edit, "", start)
        elif kind == "archive":  # the file need not exist yet
            chosen = QFileDialog.getSaveFileName(
                edit, "", start, options=QFileDialog.Option.DontConfirmOverwrite)[0]
        else:
            chosen = QFileDialog.getOpenFileName(edit, "", start)[0]
        if chosen:
            edit.setText(os.path.normpath(chosen))

    button = QPushButton("Browse…")
    button.clicked.connect(browse)
    return side_by_side(edit, button)


class OptionsForm(QScrollArea):
    """A widget for each row of OPTIONS, in group boxes. Values use set_option's terms."""

    def __init__(self, placeholders: dict[str, str] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent, widgetResizable=True)
        content = QWidget()
        groups = QVBoxLayout(content)
        forms: dict[str, QFormLayout] = {}
        self.fields: dict[str, _Field] = {}
        for group, name, label, kind, tip in OPTIONS:
            if group not in forms:
                box = QGroupBox(group)
                forms[group] = QFormLayout(box)
                groups.addWidget(box)
            form_label, self.fields[name] = self._make_field(
                kind, label, tip, (placeholders or {}).get(name, ""))
            forms[group].addRow(form_label, self.fields[name].row)
            if form_label:
                forms[group].labelForField(self.fields[name].row).setToolTip(tip)
        groups.addStretch()
        self.setWidget(content)

    def values(self) -> dict[str, str | bool]:
        return {name: field.get() for name, field in self.fields.items()}

    def load(self, values: Mapping[str, str | bool]) -> None:
        """Show `values`; an option not in it is unset."""
        for name, field in self.fields.items():
            field.set(values.get(name, ""))

    def validate(self) -> str:
        """Why the values can't be saved, or ""."""
        if self.cookies_check.isChecked() and not self.cookies_edit.text().strip():
            return "Choose a cookies file, or turn off Use cookies from a file."
        return ""

    def _make_field(self, kind: str | dict, label: str, tip: str,
                    placeholder: str = "") -> tuple[str, _Field]:
        """The form label and field for one row of OPTIONS."""
        if kind == "check":
            box = QCheckBox(label, toolTip=tip)
            return "", _Field(box, box.isChecked, lambda value: box.setChecked(bool(value)))
        if kind == "browser":
            return "", _browser_field(label, tip)
        if kind == "cookies":
            return "", self._cookies_file_field(label, tip)
        if isinstance(kind, dict):
            combo = QComboBox(editable=True, toolTip=tip)
            combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            for item, value in kind.items():
                combo.addItem(item, value)
            # A preset puts its value in the edit field, where it can be changed.
            combo.activated.connect(lambda i: combo.setEditText(combo.itemData(i)))
            return label, _Field(combo, lambda: combo.currentText().strip(),
                                 lambda value: combo.setEditText(_text(value)))
        edit = QLineEdit(toolTip=tip, placeholderText=placeholder)
        if kind == "text":
            return label, _Field(edit, lambda: edit.text().strip(),
                                 lambda value: edit.setText(_text(value)))
        # A folder or archive path: native in the widget, forward slashes in the config.
        def set_(value: str | bool) -> None:
            path = _text(value)
            if kind == "folder":  # --paths: drop a "home:" prefix
                path = home_path(path)
            edit.setText(to_display_path(path))

        return label, _Field(browse_row(edit, kind),
                             lambda: to_config_path(edit.text().strip()), set_)

    def _cookies_file_field(self, label: str, tip: str) -> _Field:
        self.cookies_check = QCheckBox(label, toolTip=tip)
        self.cookies_edit = QLineEdit(toolTip=COOKIES_PATH_TIP)
        path_row = browse_row(self.cookies_edit)
        path_row.setEnabled(False)
        self.cookies_check.toggled.connect(path_row.setEnabled)

        def get() -> str:
            checked = self.cookies_check.isChecked()
            return to_config_path(self.cookies_edit.text().strip()) if checked else ""

        def set_(value: str | bool) -> None:
            self.cookies_check.setChecked(bool(value))
            self.cookies_edit.setText(to_display_path(_text(value)))

        return _Field(side_by_side(self.cookies_check, path_row, stretch=1), get, set_)


def _browser_field(label: str, tip: str) -> _Field:
    check = QCheckBox(label, toolTip=tip)
    browser = QComboBox(toolTip=BROWSER_TIPS["browser"])
    browser.addItems(BROWSERS)
    profile = QLineEdit(toolTip=BROWSER_TIPS["profile"])
    container = QLineEdit(toolTip=BROWSER_TIPS["container"])
    keyring = QComboBox(toolTip=BROWSER_TIPS["keyring"])
    keyring.addItems(KEYRINGS)

    def applies() -> tuple[bool, bool]:
        """Whether the keyring and container fields apply to the chosen browser."""
        name = browser.currentText()
        return name in CHROMIUM and sys.platform.startswith("linux"), name == "firefox"

    def update() -> None:
        on, (has_keyring, has_container) = check.isChecked(), applies()
        browser.setEnabled(on)
        profile.setEnabled(on)
        keyring.setEnabled(on and has_keyring)
        container.setEnabled(on and has_container)

    def get() -> str:
        if not check.isChecked():
            return ""
        has_keyring, has_container = applies()  # a disabled field is left out
        return join_cookie_spec(browser.currentText(),
                                keyring.currentText() if has_keyring else "",
                                profile.text().strip(),
                                container.text().strip() if has_container else "")

    def set_(value: str | bool) -> None:
        check.setChecked(bool(value))
        name, ring, prof, cont = split_cookie_spec(_text(value))
        browser.setCurrentIndex(max(browser.findText(name), 0))
        keyring.setCurrentIndex(max(keyring.findText(ring), 0))
        profile.setText(prof)
        container.setText(cont)
        update()

    check.toggled.connect(update)
    browser.currentIndexChanged.connect(update)
    sub = QFormLayout()
    sub.setContentsMargins(24, 0, 0, 0)
    for text, widget in (("Profile:", profile), ("Container:", container), ("Keyring:", keyring)):
        sub.addRow(text, widget)
        sub.labelForField(widget).setToolTip(widget.toolTip())
    row = QWidget()
    layout = QVBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(side_by_side(check, browser, stretch=None))
    layout.addLayout(sub)
    return _Field(row, get, set_)
