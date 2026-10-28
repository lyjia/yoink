"""Preferences: a page list with the Yoink, yt-dlp, and Domains pages (docs/PHASE2.md
section 2, docs/PHASE3.md section 4)."""

from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDialogButtonBox,
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
    QStackedWidget,
    QStyle,
    QStyleFactory,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from yoink import app, argv, binary, overrides
from yoink.ui.options_form import PLACEHOLDERS, OptionsForm, browse_row, side_by_side
from yoink.ytdlp_config import (
    ConfigChanged,
    ConfigFile,
    LoadedConfig,
    decode_output,
    default_config_path,
    matches_probe,
    owned_lines,
    read_config,
    set_option,
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

RULE_TITLE = "Domain rule"
DOMAIN_TIP = ("A site name such as youtube.com. The rule also applies to its subdomains, "
              "such as www.youtube.com.")


def _missing(path: str) -> bool:
    """A non-empty path with no file at it."""
    return bool(path) and not Path(path).expanduser().is_file()


class RuleDialog(QDialog):
    """Edits one domain rule (PHASE3.md 4). OK leaves the results in `domain` and `options`."""

    def __init__(self, domain: str, options: dict[str, str | bool],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(RULE_TITLE)
        self.domain_edit = QLineEdit(domain, toolTip=DOMAIN_TIP)
        domain_row = QFormLayout()
        domain_row.addRow("Domain:", self.domain_edit)
        domain_row.labelForField(self.domain_edit).setToolTip(DOMAIN_TIP)
        self.form = OptionsForm()
        self.form.load(options)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(domain_row)
        layout.addWidget(QLabel("An empty setting follows the yt-dlp config.", wordWrap=True))
        layout.addWidget(self.form, 1)
        layout.addWidget(buttons)
        self.resize(560, 640)

    def accept(self) -> None:
        self.domain = overrides.normalize_domain(self.domain_edit.text())
        if not self.domain:
            QMessageBox.warning(self, RULE_TITLE, "Enter a domain, such as youtube.com.")
            return
        if msg := self.form.validate():
            QMessageBox.warning(self, RULE_TITLE, msg)
            return
        self.options = {k: v for k, v in self.form.values().items() if v}
        super().accept()


class PrefsDialog(QDialog):
    """Save writes what changed. The caller then reads `binary_changed`, `config_written`,
    and `rules_written`, and `updated` and `table_reset`, which Cancel does not reset."""

    def __init__(self, settings: QSettings, loaded: list[LoadedConfig] | None,
                 binary_path: Path | None, variant: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.settings = settings
        self.binary_path, self.variant = binary_path, variant  # the binary in use
        self.binary_changed = self.config_written = self.rules_written = False
        self.updated = self.table_reset = False

        self.page_list = QListWidget()
        self.page_list.setFixedWidth(120)
        self.stack = QStackedWidget()
        self.page_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self._add_page("Yoink", QStyle.StandardPixmap.SP_ComputerIcon, self._yoink_page())
        self._add_page("yt-dlp", QStyle.StandardPixmap.SP_FileIcon, self._ytdlp_page(loaded))
        self._add_page("Domains", QStyle.StandardPixmap.SP_DriveNetIcon, self._domains_page())
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
        row = side_by_side(browse_row(self.binary_edit), update)
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
        self.form = OptionsForm({"--paths": argv.default_download_dir(), **PLACEHOLDERS})
        path, self.config, self.readonly = self._load(loaded)
        lines = self.config.lines if self.config else []
        owned = owned_lines(lines, self.form.fields)
        self.form.load({name: True if o[0].value is None else o[0].value
                        for name, o in owned.items() if len(o) == 1})
        for name, field in self.form.fields.items():
            if len(owned[name]) > 1:
                field.row.setEnabled(False)
                for w in (field.row, *field.row.findChildren(QWidget)):
                    w.setToolTip(REPEATED_TIP)
        self.baseline = self.form.values()
        self.form.widget().setEnabled(not self.readonly)

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
        layout.addWidget(self.form, 1)
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

    # ---- Domains page (PHASE3.md 4) ---------------------------------------

    def _domains_page(self) -> QWidget:
        self.rules_path = overrides.rules_path()
        self.rules_setting = overrides.load_rules(self.rules_path)
        self.rules = dict(self.rules_setting)  # an edit replaces a whole entry
        table = self.rules_table = QTableWidget(0, 2, wordWrap=False)
        table.setHorizontalHeaderLabels(["Domain", "Settings"])
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().hide()
        table.itemDoubleClicked.connect(lambda _: self._edit_rule(self._selected_rule()))
        add, edit, remove = QPushButton("Add…"), QPushButton("Edit…"), QPushButton("Remove")
        add.clicked.connect(lambda: self._edit_rule(""))
        edit.clicked.connect(lambda: self._edit_rule(self._selected_rule()))
        remove.clicked.connect(self._remove_rule)
        for button in (edit, remove):
            button.setEnabled(False)
            table.itemSelectionChanged.connect(
                lambda b=button: b.setEnabled(bool(self._selected_rule())))
        self._fill_rules()
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(table, 1)
        layout.addWidget(side_by_side(add, edit, remove, stretch=None))
        return page

    def _fill_rules(self, select: str = "") -> None:
        """Show `rules`, sorted by domain, with the `select` row selected."""
        self.rules_table.setRowCount(0)
        self.rules_table.setRowCount(len(self.rules))
        for row, domain in enumerate(sorted(self.rules)):
            flags = " ".join(overrides.rule_argv(self.rules[domain]))
            settings = QTableWidgetItem(flags)
            settings.setToolTip(flags)
            self.rules_table.setItem(row, 0, QTableWidgetItem(domain))
            self.rules_table.setItem(row, 1, settings)
            if domain == select:
                self.rules_table.selectRow(row)

    def _selected_rule(self) -> str:
        """The selected row's domain, or ""."""
        rows = self.rules_table.selectionModel().selectedRows()
        return self.rules_table.item(rows[0].row(), 0).text() if rows else ""

    def _edit_rule(self, domain: str) -> None:
        """Edit the rule for `domain`, or add one if it is ""."""
        dialog = RuleDialog(domain, self.rules.get(domain, {}), self)
        if not dialog.exec():
            return
        if dialog.domain != domain and dialog.domain in self.rules:
            QMessageBox.warning(self, TITLE, f"A rule for {dialog.domain} already exists.")
            return
        self.rules.pop(domain, None)
        self.rules[dialog.domain] = dialog.options
        self._fill_rules(dialog.domain)

    def _remove_rule(self) -> None:
        del self.rules[self._selected_rule()]
        self._fill_rules()

    # ---- saving -----------------------------------------------------------

    def accept(self) -> None:
        binary_path = self.binary_edit.text().strip()
        if _missing(binary_path):
            QMessageBox.warning(self, TITLE, f"The yt-dlp program must be a file:\n{binary_path}")
            return
        if msg := self.form.validate():
            QMessageBox.warning(self, TITLE, msg)
            return
        if not self._save_config():
            return
        if self.rules != self.rules_setting:
            try:
                overrides.save_rules(self.rules_path, self.rules)
            except OSError as e:
                QMessageBox.warning(self, TITLE, f"Yoink couldn't save the domain rules:\n{e}")
                return
            self.rules_written = True
        if binary_path != self.binary_setting:
            self.settings.setValue(app.KEY_BINARY_PATH, binary_path)
            self.binary_changed = True
        if (style := self.style_combo.currentData()) != self.style_setting:
            self.settings.setValue(app.KEY_STYLE, style)
            app.apply_style(style)
        super().accept()

    def _save_config(self) -> bool:
        """Write the changed yt-dlp options, if any; False if the dialog should stay open."""
        changed = {name: value for name, value in self.form.values().items()
                   if value != self.baseline[name]}
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
