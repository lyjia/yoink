"""Preferences: a page list with the Yoink and yt-dlp pages (docs/PHASE2.md section 2)."""

import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

from PySide6.QtCore import QProcess, QSettings, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QStyle,
    QStyleFactory,
    QVBoxLayout,
    QWidget,
)

from yoink import app, argv, binary
from yoink.ytdlp_config import (
    BROWSERS,
    ConfigChanged,
    ConfigFile,
    LoadedConfig,
    Option,
    decode_output,
    default_config_path,
    home_path,
    join_cookie_spec,
    matches_probe,
    owned_lines,
    read_config,
    set_option,
    split_cookie_spec,
    to_config_path,
    to_display_path,
    unmanaged,
    write_config,
)

TITLE = "Preferences"
BINARY_TIP = "The yt-dlp program that Yoink runs. Leave empty to use the one Yoink finds on its own."
UPDATE_TIP = "Updates the yt-dlp program that Yoink is using, or shows how to update it."
UPDATE_TITLE = "Update yt-dlp"
STYLE_TIP = "How windows, buttons, and lists are drawn. System default matches the rest of your computer."
RESET_TIP = "Puts the download table's columns back to their default widths, order, and visibility."
# What Update says for a build that yt-dlp can't update itself (3.3).
DIR_BUILD = ("This copy of yt-dlp can't update itself. To update it, download the latest "
             "release from github.com/yt-dlp/yt-dlp and replace the folder it came in.")
UNKNOWN_BUILD = ("Yoink can't tell how this copy of yt-dlp was installed. "
                 "Update it the same way you installed it.")
REPEATED_TIP = ("This setting appears on more than one line of your config file. "
                "Edit the file to change it.")

# Why the yt-dlp page is read-only (1.4), or the note under the unmanaged lines.
PROBE_FAILED = "yt-dlp didn't report its config. Fix the file, then use File > Refresh config."
MISMATCH = ("Yoink reads this file differently from yt-dlp, so it can't edit it safely. "
            "Edit it in a text editor.")
NOT_LOADED = "yt-dlp doesn't load this file, so editing it would have no effect."
KEPT = "Yoink doesn't manage these lines. They are kept as they are."

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

# The option table (2.2, 2.3): group, option, label, widget kind, tooltip. A dict
# kind is an editable combo of {item: value}; the other kinds are in _make_field.
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
# What an empty field means, for the options whose default is known (2.5).
PLACEHOLDERS = {"--output": "%(title)s [%(id)s].%(ext)s", "--sub-langs": "en"}


class _Field(NamedTuple):
    row: QWidget  # disabled as a whole when the option is repeated
    get: Callable[[], str | bool]  # the value for set_option
    set: Callable[[Option | None], None]  # show the option's line, or None


def _value(line: Option | None) -> str:
    return (line.value or "") if line else ""


def _missing(path: str) -> bool:
    """A non-empty path with no file at it."""
    return bool(path) and not Path(path).expanduser().is_file()


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


class PrefsDialog(QDialog):
    """Save writes what changed. The caller then reads `binary_changed` and
    `config_written`, and `updated` and `table_reset`, which Cancel does not reset."""

    def __init__(self, settings: QSettings, loaded: list[LoadedConfig] | None,
                 binary_path: Path | None, variant: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.settings = settings
        self.binary_path, self.variant = binary_path, variant  # the binary in use
        self.binary_changed = self.config_written = self.updated = self.table_reset = False

        self.page_list = QListWidget()
        self.page_list.setFixedWidth(120)
        self.stack = QStackedWidget()
        self.page_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self._add_page("Yoink", QStyle.StandardPixmap.SP_ComputerIcon, self._yoink_page())
        self._add_page("yt-dlp", QStyle.StandardPixmap.SP_FileIcon, self._ytdlp_page(loaded))
        self.page_list.setCurrentRow(0)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        body = QHBoxLayout()
        body.addWidget(self.page_list)
        body.addWidget(self.stack, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)
        self.resize(760, 640)

    def _add_page(self, name: str, icon: QStyle.StandardPixmap, page: QWidget) -> None:
        QListWidgetItem(self.style().standardIcon(icon), name, self.page_list)
        self.stack.addWidget(page)

    def _browse_row(self, edit: QLineEdit, kind: str = "file") -> QWidget:
        """`edit` with a Browse… button for an existing file, a "folder", or an "archive"."""
        def browse() -> None:
            start = edit.text()
            if kind == "folder":
                chosen = QFileDialog.getExistingDirectory(self, "", start)
            elif kind == "archive":  # the file need not exist yet
                chosen = QFileDialog.getSaveFileName(
                    self, "", start, options=QFileDialog.Option.DontConfirmOverwrite)[0]
            else:
                chosen = QFileDialog.getOpenFileName(self, "", start)[0]
            if chosen:
                edit.setText(os.path.normpath(chosen))

        button = QPushButton("Browse…")
        button.clicked.connect(browse)
        return side_by_side(edit, button)

    # ---- Yoink page (2.5) -------------------------------------------------

    def _yoink_page(self) -> QWidget:
        self.binary_setting = self.settings.value(app.KEY_BINARY_PATH, "")
        self.binary_edit = QLineEdit(self.binary_setting, toolTip=BINARY_TIP)
        self.binary_edit.setClearButtonEnabled(True)
        self.binary_edit.setPlaceholderText(
            str(self.binary_path) if self.binary_path else "yt-dlp not found on PATH")
        # A red border while the path points at nothing (a file deleted since it was set).
        self.binary_edit.textChanged.connect(lambda text: self.binary_edit.setStyleSheet(
            "border: 1px solid red" if _missing(text.strip()) else ""))
        self.binary_edit.textChanged.emit(self.binary_edit.text())
        update = QPushButton("Update", toolTip=f"{UPDATE_TIP}\n{self.binary_path}")
        update.setEnabled(self.binary_path is not None and self.binary_path.is_file())
        update.clicked.connect(self._update)
        page = QWidget()
        form = QFormLayout(page)
        row = side_by_side(self._browse_row(self.binary_edit), update)
        form.addRow("yt-dlp program:", row)
        form.labelForField(row).setToolTip(BINARY_TIP)
        self.style_setting = self.settings.value(app.KEY_STYLE, "")
        self.style_combo = QComboBox(toolTip=STYLE_TIP)
        self.style_combo.addItem("System default", "")
        for name in QStyleFactory.keys():
            self.style_combo.addItem(name, name)
        self.style_combo.setCurrentIndex(max(self.style_combo.findData(self.style_setting), 0))
        row = side_by_side(self.style_combo, stretch=None)
        form.addRow("Theme:", row)
        form.labelForField(row).setToolTip(STYLE_TIP)
        reset = QPushButton("Reset table layout", toolTip=RESET_TIP)
        reset.clicked.connect(lambda: setattr(self, "table_reset", True))
        reset.clicked.connect(lambda: reset.setEnabled(False))  # applies when the dialog closes
        form.addRow("", side_by_side(reset, stretch=None))
        return page

    def _update(self) -> None:
        """Run `yt-dlp -U`, or say how to update this build (3.3)."""
        if binary.can_self_update(self.variant):
            output = QPlainTextEdit(readOnly=True, placeholderText="Updating yt-dlp…")
            proc = QProcess(self)
            proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
            proc.finished.connect(
                lambda: output.setPlainText(decode_output(bytes(proc.readAll()))))
            proc.errorOccurred.connect(lambda _: output.setPlainText(proc.errorString()))
            proc.start(str(self.binary_path), ["-U"])
            self._simple_dialog(output)
            proc.kill()  # if it is still running
            proc.waitForFinished(1000)
            self.updated = True
        elif command := binary.update_command(binary.install_method(self.binary_path, self.variant)):
            field = QLineEdit(command, readOnly=True)
            copy = QPushButton("Copy")
            copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(command))
            self._simple_dialog(QLabel("To update yt-dlp, run this command:"),
                                side_by_side(field, copy))
        else:
            QMessageBox.information(self, UPDATE_TITLE,
                                    DIR_BUILD if self.variant.endswith("_dir") else UNKNOWN_BUILD)

    def _simple_dialog(self, *widgets: QWidget) -> None:
        dialog = QDialog(self, windowTitle=UPDATE_TITLE)
        layout = QVBoxLayout(dialog)
        for w in widgets:
            layout.addWidget(w)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.setMinimumWidth(560)
        dialog.exec()

    # ---- yt-dlp page (2.2 to 2.4) -----------------------------------------

    def _ytdlp_page(self, loaded: list[LoadedConfig] | None) -> QWidget:
        content = QWidget()
        groups = QVBoxLayout(content)
        forms: dict[str, QFormLayout] = {}
        self.fields: dict[str, _Field] = {}
        placeholders = {"--paths": argv.default_download_dir(), **PLACEHOLDERS}
        for group, name, label, kind, tip in OPTIONS:
            if group not in forms:
                box = QGroupBox(group)
                forms[group] = QFormLayout(box)
                groups.addWidget(box)
            form_label, self.fields[name] = self._make_field(kind, label, tip, placeholders.get(name, ""))
            forms[group].addRow(form_label, self.fields[name].row)
            if form_label:
                forms[group].labelForField(self.fields[name].row).setToolTip(tip)
        groups.addStretch()
        scroll = QScrollArea(widgetResizable=True)
        scroll.setWidget(content)

        path, self.config, self.readonly = self._load(loaded)
        lines = self.config.lines if self.config else []
        owned = owned_lines(lines, self.fields)
        for name, field in self.fields.items():
            field.set(owned[name][0] if len(owned[name]) == 1 else None)
            if len(owned[name]) > 1:
                field.row.setEnabled(False)
                for w in (field.row, *field.row.findChildren(QWidget)):
                    w.setToolTip(REPEATED_TIP)
        self.baseline = {name: field.get() for name, field in self.fields.items()}
        content.setEnabled(not self.readonly)

        # The warning box (2.4): the file, then every line no widget shows.
        path_label = QLabel(to_display_path(str(path)))
        open_btn = QPushButton("Open in editor")
        open_btn.setEnabled(path.exists())
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))
        other = "\n".join(line.raw.rstrip("\r\n") for line in unmanaged(lines, owned))
        note = QLabel(self.readonly or KEPT, wordWrap=True)
        note.setHidden(not (self.readonly or other))
        listing = QPlainTextEdit(other, readOnly=True, maximumHeight=110)
        listing.setHidden(not other)
        warning = QGroupBox("Config file")
        box = QVBoxLayout(warning)
        box.addWidget(side_by_side(path_label, open_btn))
        box.addWidget(note)
        box.addWidget(listing)

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll, 1)
        layout.addWidget(warning)
        return page

    @staticmethod
    def _load(loaded: list[LoadedConfig] | None) -> tuple[Path, ConfigFile | None, str]:
        """The file to edit, its contents, and why the page is read-only ("" if editable)."""
        user = next((c for c in loaded or [] if c.label == "User"), None)
        path = Path(user.path) if user and user.path else default_config_path()
        if loaded is None:
            return path, None, PROBE_FAILED
        if not user and path.exists():
            return path, None, NOT_LOADED
        try:
            config = read_config(path)
        except (OSError, UnicodeDecodeError, LookupError) as e:  # LookupError: bad "# coding:"
            return path, None, f"Yoink can't read this file: {e}"
        if user and (config.data is None or not matches_probe(config.lines, user.tokens)):
            return path, config, MISMATCH
        return path, config, ""

    def _make_field(self, kind: str | dict, label: str, tip: str,
                    placeholder: str = "") -> tuple[str, _Field]:
        """The form label and field for one row of OPTIONS."""
        if kind == "check":
            box = QCheckBox(label, toolTip=tip)
            return "", _Field(box, box.isChecked, lambda line: box.setChecked(line is not None))
        if kind == "browser":
            return "", self._browser_field(label, tip)
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
                                 lambda line: combo.setEditText(_value(line)))
        edit = QLineEdit(toolTip=tip, placeholderText=placeholder)
        if kind == "text":
            return label, _Field(edit, lambda: edit.text().strip(),
                                 lambda line: edit.setText(_value(line)))
        # A folder or archive path: native in the widget, forward slashes in the config.
        def set_(line: Option | None) -> None:
            value = _value(line)
            if kind == "folder":  # --paths: drop a "home:" prefix
                value = home_path(value)
            edit.setText(to_display_path(value))

        return label, _Field(self._browse_row(edit, kind),
                             lambda: to_config_path(edit.text().strip()), set_)

    def _browser_field(self, label: str, tip: str) -> _Field:
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

        def set_(line: Option | None) -> None:
            check.setChecked(line is not None)
            if line:
                name, ring, prof, cont = split_cookie_spec(_value(line))
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

    def _cookies_file_field(self, label: str, tip: str) -> _Field:
        self.cookies_check = QCheckBox(label, toolTip=tip)
        self.cookies_edit = QLineEdit(toolTip=COOKIES_PATH_TIP)
        path_row = self._browse_row(self.cookies_edit)
        path_row.setEnabled(False)
        self.cookies_check.toggled.connect(path_row.setEnabled)

        def get() -> str:
            checked = self.cookies_check.isChecked()
            return to_config_path(self.cookies_edit.text().strip()) if checked else ""

        def set_(line: Option | None) -> None:
            self.cookies_check.setChecked(line is not None)
            self.cookies_edit.setText(to_display_path(_value(line)))

        return _Field(side_by_side(self.cookies_check, path_row, stretch=1), get, set_)

    # ---- saving -----------------------------------------------------------

    def accept(self) -> None:
        binary_path = self.binary_edit.text().strip()
        if _missing(binary_path):
            QMessageBox.warning(self, TITLE, f"The yt-dlp program must be a file:\n{binary_path}")
            return
        if self.cookies_check.isChecked() and not self.cookies_edit.text().strip():
            QMessageBox.warning(self, TITLE, "Choose a cookies file, or turn off "
                                             "Use cookies from a file.")
            return
        if not self._save_config():
            return
        if binary_path != self.binary_setting:
            self.settings.setValue(app.KEY_BINARY_PATH, binary_path)
            self.binary_changed = True
        if (style := self.style_combo.currentData()) != self.style_setting:
            self.settings.setValue(app.KEY_STYLE, style)
            app.apply_style(style)
        super().accept()

    def _save_config(self) -> bool:
        """Write the changed yt-dlp options, if any; False if the dialog should stay open."""
        changed = {name: value for name, field in self.fields.items()
                   if (value := field.get()) != self.baseline[name]}
        if self.readonly or self.config is None or not changed:
            return True
        lines = self.config.lines
        for name, value in changed.items():
            lines = set_option(lines, name, value)
        try:
            write_config(self.config, lines)
        except UnicodeEncodeError:
            error = (f"A value can't be saved in this file's encoding ({self.config.encoding}). "
                     "Nothing was saved.")
        except ConfigChanged:
            error = ("The config file changed after Preferences opened, so Yoink didn't save "
                     "over it. Close Preferences and open it again.")
        except OSError as e:
            error = f"Yoink couldn't save the config file:\n{e}"
        else:
            self.config_written = True
            return True
        QMessageBox.warning(self, TITLE, error)
        return False
