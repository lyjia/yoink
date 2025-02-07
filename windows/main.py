import sys
import os
import uuid
from urllib.parse import urlparse
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QFileDialog, QHeaderView, QProgressBar,
                             QAbstractItemView, QMessageBox)
from PyQt6.QtCore import Qt, QObject, QThread, QSettings

from const import SETTINGS_LAST_DOWNLOAD_FOLDER
from workers import DownloadWorker


COL_URL = "URL"
COL_DOMAIN = "Domain"
COL_FILENAME = "Filename"
COL_DOWNLOADED = "Downloaded"
COL_TOTAL = "Total"
COL_SPEED = "Speed"
COL_PROGRESS = "Progress"
COL_ACTIONS = "Actions"
TABLE_COLUMNS = [COL_URL, COL_DOMAIN, COL_FILENAME, COL_DOWNLOADED, COL_TOTAL, COL_SPEED, COL_PROGRESS, COL_ACTIONS]

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Yoink! A yt-dlp GUI")
        self.setGeometry(100, 100, 1024, 600)
        self.settings = QSettings("settings.json")

        # Download tracking
        self.downloads = {}  # {download_id: {'worker': worker, 'thread': thread}}

        # Setup UI
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Input fields
        input_layout = QHBoxLayout()
        input_sub_layout = QVBoxLayout()
        self.url_input = QLineEdit(placeholderText="Enter URL")
        input_sub_layout.addWidget(self.url_input)

        input_sub_dir_layout = QHBoxLayout()
        self.dir_input = QLineEdit(placeholderText="Download directory")
        self.dir_input.setText(self.settings.value(SETTINGS_LAST_DOWNLOAD_FOLDER))
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.browse_directory)
        input_sub_dir_layout.addWidget(self.dir_input)
        input_sub_dir_layout.addWidget(self.browse_btn)
        input_sub_layout.addLayout(input_sub_dir_layout)
        input_layout.addLayout(input_sub_layout)

        # Control buttons
        self.start_btn = QPushButton("Start Download")
        self.start_btn.clicked.connect(self.start_download)
        input_layout.addWidget(self.start_btn)

        # Downloads table
        self.table = QTableWidget(0, len(TABLE_COLUMNS))
        self.table.setHorizontalHeaderLabels(TABLE_COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        # Assemble layout


        layout.addLayout(input_layout)
        layout.addWidget(self.table)

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if directory:
            self.dir_input.setText(directory)

    def start_download(self):
        url = self.url_input.text().strip()
        directory = self.dir_input.text().strip()

        if not url or not directory:
            title = "Invalid input"
            text = "Please ensure both the URL and directory are valid."
            self.popup_warning_box(text, title)
            return  # Add error handling

        if not os.path.isdir(directory):
            title = "Invalid input"
            text = "Given directory does not exist or is not a valid directory."
            self.popup_warning_box(text, title)
            return  # Add error handling for invalid directory

        download_id = str(uuid.uuid4())
        self.add_table_row(download_id, url)

        # Setup worker thread
        worker = DownloadWorker(url, directory, download_id)
        thread = QThread()
        worker.moveToThread(thread)

        # Connect signals
        worker.progress_updated.connect(self.update_progress)
        worker.finished.connect(self.download_finished)
        worker.error_occurred.connect(self.download_error)
        thread.started.connect(worker.run)

        # Store references
        self.downloads[download_id] = {
            'worker': worker,
            'thread': thread,
            'row': self.table.rowCount() - 1
        }

        thread.start()

    def popup_warning_box(self, text, title):
        message_box = QMessageBox(self)
        message_box.setIcon(QMessageBox.Icon.Warning)
        message_box.setWindowTitle(title)
        message_box.setText(text)
        message_box.setStandardButtons(QMessageBox.StandardButton.Ok)
        message_box.exec()

    def add_table_row(self, download_id, url):
        row = self.table.rowCount()
        self.table.insertRow(row)

        # URL and domain
        domain = urlparse(url).netloc
        url_item = QTableWidgetItem(url[:50] + '...' if len(url) > 50 else url)
        url_item.setData(Qt.ItemDataRole.UserRole, download_id)
        self.table.setItem(row, 0, url_item)
        self.table.setItem(row, 1, QTableWidgetItem(domain))

        # Initialize other columns
        for col in range(2, 6):
            self.table.setItem(row, col, QTableWidgetItem(""))
        self.table.setCellWidget(row, 6, QProgressBar())

        # Add 'X' button in the Actions column
        cancel_button = QPushButton("X")
        cancel_button.setFixedSize(20, 20)
        cancel_button.clicked.connect(lambda checked, did=download_id: self.handle_cancel(did))
        self.table.setCellWidget(row, 7, cancel_button)

    def update_progress(self, download_id, progress_info):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == download_id:
                self.update_row(row, progress_info)
                break

    def update_row(self, row, data):
        if filename := data.get('filename'):
            self.table.item(row, 2).setText(os.path.basename(filename))

        downloaded = data.get('downloaded_bytes', 0)
        total = data.get('total_bytes', 0) or data.get('total_bytes_estimate', 0)
        self.table.item(row, 3).setText(self.format_bytes(downloaded))
        self.table.item(row, 4).setText(self.format_bytes(total))

        speed = data.get('speed', 0)
        self.table.item(row, 5).setText(f"{self.format_bytes(speed)}/s")

        progress = self.table.cellWidget(row, 6)
        progress.setValue(int(data.get('percent', 0)))

    def format_bytes(self, bytes):
        if bytes is None:
            return "--"
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024.0:
                return f"{bytes:.1f} {unit}"
            bytes /= 1024.0
        return f"{bytes:.1f} TB"

    def download_finished(self, download_id):
        self.cleanup_download(download_id)

    def download_error(self, download_id, error_msg):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.ItemDataRole.UserRole) == download_id:
                self.table.item(row, 2).setText(f"Error: {error_msg}")
                break
        self.cleanup_download(download_id)

    def cleanup_download(self, download_id):
        if download_id in self.downloads:
            thread = self.downloads[download_id]['thread']
            thread.quit()
            thread.wait()
            del self.downloads[download_id]

    def handle_cancel(self, download_id):
        # Find the row with the given download_id
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item.data(Qt.ItemDataRole.UserRole) == download_id:
                # Cancel the download if it's active
                if download_id in self.downloads:
                    self.downloads[download_id]['worker'].cancel()
                    self.cleanup_download(download_id)
                # Remove the row from the table
                self.table.removeRow(row)
                break
