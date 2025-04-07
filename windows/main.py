import sys
import os
import uuid
from urllib.parse import urlparse
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QFileDialog, QHeaderView, QProgressBar,
                             QAbstractItemView, QMessageBox, QMenu, QComboBox, QLabel)  # Added QComboBox
from PyQt6.QtCore import Qt, QObject, QThread, QSettings
import logging # Added logging

from workers import DownloadWorker
# Import the manager function to find versions
from ytdlp_manager import find_available_versions, DEFAULT_DOWNLOAD_BASE_DIR
from const import SETTINGS_LAST_DOWNLOAD_FOLDER, SETTINGS_APP_ORG, SETTINGS_APP_NAME, \
    SETTINGS_YTDLP_VERSION, GIT_VERSION, APP_NAME, APP_DESC  # Ensure these are imported if needed elsewhere



COL_STATUS = "Status"
COL_URL = "URL"
COL_DOMAIN = "Domain"
COL_FILENAME = "Filename"
COL_DOWNLOADED = "Downloaded"
COL_TOTAL = "Total"
COL_SPEED = "Speed"
COL_PROGRESS = "Progress"
COL_ACTIONS = "Actions"
TABLE_COLUMNS = [COL_STATUS, COL_URL, COL_DOMAIN, COL_FILENAME, COL_DOWNLOADED, COL_TOTAL, COL_SPEED, COL_PROGRESS, COL_ACTIONS]

STA_STARTING = "🏁"
STA_RUNNING = "🏃"
STA_FINISHED = "✔️"
STA_ERROR = "❌"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_DESC} v{GIT_VERSION}")
        self.setGeometry(100, 100, 1024, 600)
        self.settings = QSettings(SETTINGS_APP_ORG, SETTINGS_APP_NAME)
        logging.info(f"Settings file location: {self.settings.fileName()}")


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

        # --- yt-dlp Version Selector ---
        version_layout = QHBoxLayout()
        self.version_label = QLabel("yt-dlp Version:") # Add QLabel import if needed
        self.version_selector = QComboBox()
        self.populate_version_selector() # Populate the dropdown
        # Load last used version or default to "latest"
        last_version = self.settings.value(SETTINGS_YTDLP_VERSION, "latest")
        self.version_selector.setCurrentText(last_version)
        version_layout.addWidget(self.version_label)
        version_layout.addWidget(self.version_selector)
        input_sub_layout.addLayout(version_layout)
        # --- End Version Selector ---

        input_layout.addLayout(input_sub_layout)


        # Control buttons
        self.start_btn = QPushButton("Start Download")
        self.start_btn.clicked.connect(self.start_download)
        input_layout.addWidget(self.start_btn)


        # Downloads table
        self.table = QTableWidget(0, len(TABLE_COLUMNS))
        self.table.setHorizontalHeaderLabels(TABLE_COLUMNS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Status column
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)  # Actions column
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)

        # Menu bar
        menu_bar = self.menuBar()
        menu_bar.setNativeMenuBar(False)
        file_menu = menu_bar.addMenu("File")
        about_action = file_menu.addAction("About")
        options_action = file_menu.addAction("Options")
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)
        about_action.triggered.connect(self.show_about)
        options_action.triggered.connect(self.show_options)

        # Assemble layout
        layout.addLayout(input_layout)
        layout.addWidget(self.table)

    def populate_version_selector(self):
        """Populates the version selector dropdown."""
        current_selection = self.version_selector.currentText() # Save current selection
        self.version_selector.clear()
        self.version_selector.addItem("latest") # Always offer latest

        try:
            # Use the manager function to find locally cached versions
            cached_versions = find_available_versions()
            logging.info(f"Found cached yt-dlp versions: {cached_versions}")
            # Add cached versions, ensuring no duplicates with "latest" if it resolves to one
            for version in sorted(cached_versions, reverse=True):
                 if self.version_selector.findText(version) == -1: # Avoid duplicates
                     self.version_selector.addItem(version)
        except Exception as e:
            logging.error(f"Error finding cached yt-dlp versions: {e}")
            # Optionally inform the user via status bar or dialog

        # Restore previous selection if still available, otherwise default to latest
        if self.version_selector.findText(current_selection) != -1:
             self.version_selector.setCurrentText(current_selection)
        else:
             self.version_selector.setCurrentText("latest")


    def show_about(self):
        QMessageBox.information(self, "About", "Yoink! A yt-dlp GUI\nVersion 1.0")

    def show_options(self):
        # TODO: Implement a proper options dialog
        # Could include:
        # - Default download directory
        # - yt-dlp version management (select default, clear cache)
        # - API URL configuration?
        # - Option to refresh version list
        self.populate_version_selector() # Refresh list when opening options for now
        QMessageBox.information(self, "Options", "Options dialog placeholder.\nVersion list refreshed.")

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if directory:
            self.dir_input.setText(directory)

    def start_download(self):
        url = self.url_input.text().strip()
        directory = self.dir_input.text().strip()

        if not url or not directory:
            self.popup_warning_box("Please ensure both the URL and directory are valid.", "Invalid input")
            return

        if not os.path.isdir(directory):
            self.popup_warning_box("Given directory does not exist or is not valid.", "Invalid input")
            return

        download_id = str(uuid.uuid4())
        self.add_table_row(download_id, url)

        # Get selected yt-dlp version
        selected_version = self.version_selector.currentText()
        logging.info(f"Starting download for {url} using yt-dlp version: {selected_version}")

        # Setup worker thread with selected version
        worker = DownloadWorker(url, directory, download_id, ytdlp_version=selected_version)
        thread = QThread()
        worker.moveToThread(thread)

        # Connect signals
        worker.progress_updated.connect(self.update_progress)
        worker.finished.connect(self.download_finished)
        worker.error_occurred.connect(self.download_error)
        thread.started.connect(worker.run)
        thread.started.connect(lambda: self.update_status(download_id, STA_RUNNING))

        # Store references
        self.downloads[download_id] = {
            'worker': worker,
            'thread': thread,
            'row': self.table.rowCount() - 1
        }

        thread.start()

    def popup_warning_box(self, text, title):
        QMessageBox.warning(self, title, text)

    def add_table_row(self, download_id, url):
        row = self.table.rowCount()
        self.table.insertRow(row)

        # Status column
        status_item = QTableWidgetItem(STA_STARTING)
        self.table.setItem(row, 0, status_item)

        # URL and domain
        domain = urlparse(url).netloc
        url_item = QTableWidgetItem(url[:50] + '...' if len(url) > 50 else url)
        url_item.setData(Qt.ItemDataRole.UserRole, download_id)
        self.table.setItem(row, 1, url_item)
        self.table.setItem(row, 2, QTableWidgetItem(domain))

        # Initialize other columns
        for col in range(3, 7):
            self.table.setItem(row, col, QTableWidgetItem(""))

        # Progress bar
        progress_bar = QProgressBar()
        self.table.setCellWidget(row, 7, progress_bar)

        # Cancel button
        cancel_button = QPushButton("✖")
        cancel_button.setFixedSize(20, 20)
        cancel_button.clicked.connect(lambda checked, did=download_id: self.handle_cancel(did))
        self.table.setCellWidget(row, 8, cancel_button)

    def update_status(self, download_id, status):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item.data(Qt.ItemDataRole.UserRole) == download_id:
                self.table.item(row, 0).setText(status)
                break

    def update_progress(self, download_id, progress_info):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 1).data(Qt.ItemDataRole.UserRole) == download_id:
                self.update_row(row, progress_info)
                break

    def update_row(self, row, data):
        if filename := data.get('filename'):
            self.table.item(row, 3).setText(os.path.basename(filename))

        downloaded = data.get('downloaded_bytes', 0)
        total = data.get('total_bytes', 0) or data.get('total_bytes_estimate', 0)
        self.table.item(row, 4).setText(self.format_bytes(downloaded))
        self.table.item(row, 5).setText(self.format_bytes(total))

        speed = data.get('speed', 0)
        self.table.item(row, 6).setText(f"{self.format_bytes(speed)}/s")

        progress = self.table.cellWidget(row, 7)
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
        self.update_status(download_id, STA_FINISHED)
        self.cleanup_download(download_id)

    def download_error(self, download_id, error_msg):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item.data(Qt.ItemDataRole.UserRole) == download_id:
                self.table.item(row, 0).setText(STA_ERROR)
                self.table.item(row, 3).setText(f"Error: {error_msg}")
                break
        self.cleanup_download(download_id)

    def cleanup_download(self, download_id):
        if download_id in self.downloads:
            thread = self.downloads[download_id]['thread']
            thread.quit()
            thread.wait()
            del self.downloads[download_id]

    def handle_cancel(self, download_id):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 1)
            if item.data(Qt.ItemDataRole.UserRole) == download_id:
                if download_id in self.downloads:
                    self.downloads[download_id]['worker'].cancel()
                    self.cleanup_download(download_id)
                self.table.removeRow(row)
                break

    def closeEvent(self, event):
        """Handle window close event."""
        # Save settings
        last_dir = self.dir_input.text().strip()
        if last_dir:
            self.settings.setValue(SETTINGS_LAST_DOWNLOAD_FOLDER, last_dir)

        last_version = self.version_selector.currentText()
        if last_version:
            self.settings.setValue(SETTINGS_YTDLP_VERSION, last_version)

        # Ensure all download threads are stopped (basic cleanup)
        active_downloads = list(self.downloads.keys()) # Copy keys as dict changes size
        for download_id in active_downloads:
             logging.info(f"Stopping download {download_id} due to application close.")
             self.handle_cancel(download_id) # Attempt graceful cancellation

        logging.info("Application closing.")
        super().closeEvent(event)


if __name__ == "__main__":
    # Configure basic logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    app = QApplication(sys.argv)
    # Settings are now handled inside MainWindow using QSettings standard paths
    # app.setOrganizationName(SETTINGS_APP_ORG) # No longer needed here
    # app.setApplicationName(SETTINGS_APP_NAME) # No longer needed here
    window = MainWindow()
    window.show()
    sys.exit(app.exec())