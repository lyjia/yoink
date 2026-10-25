"""Dialog listing settings that more than one yt-dlp config file sets (docs/PHASE1.md 1.3)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from yoink.ytdlp_config import LoadedConfig, Occurrence

COLUMNS = ["Setting", "Value", "File", "Loaded as"]
STDIN = "(standard input)"


class ConfigNoticeDialog(QDialog):
    def __init__(self, loaded: list[LoadedConfig], conflicts: list[Occurrence],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("yt-dlp configuration")
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("yt-dlp loaded these config files:"))
        # An included file is indented under the file that included it.
        files = QLabel("\n".join(
            f"{'    ' * c.depth}{c.label}: {c.path or STDIN}" for c in loaded
        ))
        files.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(files)

        layout.addWidget(QLabel("These settings appear in more than one of them:"))
        self.table = QTableWidget(len(conflicts), len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        for row, o in enumerate(conflicts):
            for col, text in enumerate((o.setting, o.value, o.path or STDIN, o.label)):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.table.setItem(row, col, item)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table, 1)

        note = QLabel(
            "yt-dlp decides which of these values applies. Settings chosen in "
            "Yoink's main window apply to Yoink's downloads whatever the config says."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(720, 360)
