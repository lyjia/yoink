import sys
import os
import uuid
from urllib.parse import urlparse
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QFileDialog, QHeaderView, QProgressBar)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread
from workers import DownloadWorker

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("yt-dlp GUI")
        self.setGeometry(100, 100, 1024, 600)

        # Download tracking
        self.downloads = {}  # {download_id: {'worker': worker, 'thread': thread}}

        # Setup UI
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        # Input fields
        input_layout = QHBoxLayout()
        self.url_input = QLineEdit(placeholderText="Enter URL")
        self.dir_input = QLineEdit(placeholderText="Download directory")
        self.browse_btn = QPushButton("Browse")
        self.browse_btn.clicked.connect(self.browse_directory)
        input_layout.addWidget(self.url_input)
        input_layout.addWidget(self.dir_input)
        input_layout.addWidget(self.browse_btn)

        # Control buttons
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("Start Download")
        self.start_btn.clicked.connect(self.start_download)
        self.cancel_btn = QPushButton("Cancel Selected")
        self.cancel_btn.clicked.connect(self.cancel_download)
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.cancel_btn)

        # Downloads table
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels([
            "URL", "Domain", "Filename", "Downloaded", "Total", "Speed", "Progress"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        # Assemble layout
        layout.addLayout(input_layout)
        layout.addLayout(btn_layout)
        layout.addWidget(self.table)

    def browse_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Select Download Directory")
        if directory:
            self.dir_input.setText(directory)

    def start_download(self):
        url = self.url_input.text().strip()
        directory = self.dir_input.text().strip()

        if not url or not directory:
            return  # Add error handling

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

    def add_table_row(self, download_id, url):
        row = self.table.rowCount()
        self.table.insertRow(row)

        # URL and domain
        domain = urlparse(url).netloc
        url_item = QTableWidgetItem(url[:50] + '...' if len(url) > 50 else url)
        url_item.setData(Qt.UserRole, download_id)
        self.table.setItem(row, 0, url_item)
        self.table.setItem(row, 1, QTableWidgetItem(domain))

        # Initialize other columns
        for col in range(2, 6):
            self.table.setItem(row, col, QTableWidgetItem(""))
        self.table.setCellWidget(row, 6, QProgressBar())

    def update_progress(self, download_id, progress_info):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == download_id:
                # Update progress information
                self.update_row(row, progress_info)
                break

    def update_row(self, row, data):
        # Filename
        if filename := data.get('filename'):
            self.table.item(row, 2).setText(os.path.basename(filename))

        # Bytes
        downloaded = data.get('downloaded_bytes', 0)
        total = data.get('total_bytes', 0) or data.get('total_bytes_estimate', 0)
        self.table.item(row, 3).setText(self.format_bytes(downloaded))
        self.table.item(row, 4).setText(self.format_bytes(total))

        # Speed
        speed = data.get('speed', 0)
        self.table.item(row, 5).setText(f"{self.format_bytes(speed)}/s")

        # Progress bar
        progress = self.table.cellWidget(row, 6)
        progress.setValue(int(data.get('percent', 0)))

    def format_bytes(self, bytes):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes < 1024.0:
                return f"{bytes:.1f} {unit}"
            bytes /= 1024.0
        return f"{bytes:.1f} TB"

    def download_finished(self, download_id):
        self.cleanup_download(download_id)

    def download_error(self, download_id, error_msg):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(Qt.UserRole) == download_id:
                self.table.item(row, 2).setText(f"Error: {error_msg}")
                break
        self.cleanup_download(download_id)

    def cleanup_download(self, download_id):
        if download_id in self.downloads:
            thread = self.downloads[download_id]['thread']
            thread.quit()
            thread.wait()
            del self.downloads[download_id]

    def cancel_download(self):
        selected = self.table.currentRow()
        if selected >= 0:
            item = self.table.item(selected, 0)
            download_id = item.data(Qt.UserRole)
            if download_id in self.downloads:
                self.downloads[download_id]['worker'].cancel()
                self.cleanup_download(download_id)
                self.table.removeRow(selected)
