"""Preferences: a page list with the Yoink and yt-dlp pages (docs/PHASE2.md section 2)."""

import os
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from yoink import app

TITLE = "Preferences"
BINARY_TIP = "The yt-dlp program that Yoink runs. Leave empty to use the one Yoink finds on its own."


def _browse_row(edit: QLineEdit, pick: Callable[[str], str]) -> QWidget:
    """`edit` with a Browse… button; `pick(start)` returns the chosen path, or ""."""
    def browse() -> None:
        if chosen := pick(edit.text()):
            edit.setText(os.path.normpath(chosen))

    button = QPushButton("Browse…")
    button.clicked.connect(browse)
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(edit, 1)
    layout.addWidget(button)
    return row


class PrefsDialog(QDialog):
    """Save writes what changed; the caller then reads `binary_changed`."""

    def __init__(self, settings: QSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.settings = settings
        self.binary_changed = False

        self.page_list = QListWidget()
        self.page_list.setFixedWidth(120)
        self.stack = QStackedWidget()
        self.page_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self._add_page("Yoink", QStyle.StandardPixmap.SP_ComputerIcon, self._yoink_page())
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
        self.resize(760, 560)

    def _add_page(self, name: str, icon: QStyle.StandardPixmap, page: QWidget) -> None:
        QListWidgetItem(self.style().standardIcon(icon), name, self.page_list)
        self.stack.addWidget(page)

    # ---- Yoink page (2.5) -------------------------------------------------

    def _yoink_page(self) -> QWidget:
        self.binary_setting = self.settings.value(app.KEY_BINARY_PATH, "")
        self.binary_edit = QLineEdit(self.binary_setting, toolTip=BINARY_TIP)
        self.binary_edit.setClearButtonEnabled(True)
        row = _browse_row(
            self.binary_edit, lambda start: QFileDialog.getOpenFileName(self, "yt-dlp program", start)[0]
        )
        page = QWidget()
        form = QFormLayout(page)
        form.addRow("yt-dlp program:", row)
        return page

    # ---- saving -----------------------------------------------------------

    def accept(self) -> None:
        binary_path = self.binary_edit.text().strip()
        if binary_path and not Path(binary_path).expanduser().is_file():
            QMessageBox.warning(self, TITLE, f"The yt-dlp program must be a file:\n{binary_path}")
            return
        if binary_path != self.binary_setting:
            self.settings.setValue(app.KEY_BINARY_PATH, binary_path)
            self.binary_changed = True
        super().accept()
