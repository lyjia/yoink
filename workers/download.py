import sys
import os
import uuid
from urllib.parse import urlparse
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QFileDialog, QHeaderView, QProgressBar)
from PyQt6.QtCore import Qt, pyqtSignal, QObject, QThread
import yt_dlp


class DownloadWorker(QObject):
    progress_updated = pyqtSignal(str, dict)  # download_id, progress_info
    finished = pyqtSignal(str)                # download_id
    error_occurred = pyqtSignal(str, str)     # download_id, error_msg

    def __init__(self, url, dest_dir, download_id):
        super().__init__()
        self.url = url
        self.dest_dir = dest_dir
        self.download_id = download_id
        self._cancelled = False

    def run(self):
        ydl_opts = {
            'progress_hooks': [self.progress_hook],
            'outtmpl': os.path.join(self.dest_dir, '%(title)s.%(ext)s'),
            'noprogress': True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
            if not self._cancelled:
                self.finished.emit(self.download_id)
        except Exception as e:
            if not self._cancelled:
                self.error_occurred.emit(self.download_id, str(e))

    def progress_hook(self, d):
        if self._cancelled:
            raise yt_dlp.DownloadCancelled('Download cancelled')
        self.progress_updated.emit(self.download_id, d)

    def cancel(self):
        self._cancelled = True