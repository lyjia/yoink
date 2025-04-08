import os
from PyQt6.QtCore import pyqtSignal, QObject
# import yt_dlp # Removed static import
import logging

from util.const import STA_RUNNING
from util.ytdlp_manager import get_ytdlp_module # Import the manager function

class DownloadWorker(QObject):
    progress_updated = pyqtSignal(str, dict)  # download_id, progress_info
    finished = pyqtSignal(str)                # download_id
    started_running = pyqtSignal(str)
    error_occurred = pyqtSignal(str, str)     # download_id, error_msg

    def __init__(self, url, dest_dir, download_id, ytdlp_version="latest"):
        super().__init__()
        self.url = url
        self.dest_dir = dest_dir
        self.download_id = download_id
        self.ytdlp_version = ytdlp_version # Allow specifying version
        self._cancelled = False
        self.ytdlp = None # Placeholder for the loaded module
        self.accumulated_bytes = 0  # Track total downloaded bytes

    def run(self):
        # --- Load yt-dlp module ---
        logging.info(f"Worker {self.download_id}: Attempting to load yt-dlp version '{self.ytdlp_version}'...")
        self.ytdlp = get_ytdlp_module(version=self.ytdlp_version)
        if not self.ytdlp:
            error_msg = f"Failed to load yt-dlp version '{self.ytdlp_version}'. Check logs or network."
            logging.error(f"Worker {self.download_id}: {error_msg}")
            self.error_occurred.emit(self.download_id, error_msg)
            return # Stop execution if module loading fails
        logging.info(f"Worker {self.download_id}: Successfully loaded yt-dlp.")
        # --- End loading ---

        ydl_opts = {
            'progress_hooks': [self.progress_hook],
            'outtmpl': os.path.join(self.dest_dir, '%(title)s.%(ext)s'),
            'noprogress': True, # Set to True because we use progress_hooks
            'quiet': True, # Reduce console noise from yt-dlp itself
            'logger': logging.getLogger(f'yt-dlp_{self.download_id}'), # Integrate with our logging
        }

        try:
            # Use the dynamically loaded module instance
            with self.ytdlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url])
            if not self._cancelled:
                self.finished.emit(self.download_id)
        except self.ytdlp.DownloadError as e: # Catch specific yt-dlp errors if needed
             if not self._cancelled:
                 # Try to provide a cleaner error message
                 error_msg = f"Download Error: {e.msg}" if hasattr(e, 'msg') else str(e)
                 logging.error(f"Worker {self.download_id}: {error_msg}")
                 self.error_occurred.emit(self.download_id, error_msg)
        except Exception as e:
            # Catch broader exceptions, including potential DownloadCancelled
            if isinstance(e, self.ytdlp.DownloadCancelled):
                 logging.info(f"Worker {self.download_id}: Download explicitly cancelled.")
                 # Optionally emit a specific signal or just finish silently
                 # self.finished.emit(self.download_id) # Or maybe not if cancelled
            elif not self._cancelled:
                 error_msg = f"Unexpected Error: {str(e)}"
                 logging.error(f"Worker {self.download_id}: {error_msg}")
                 self.error_occurred.emit(self.download_id, error_msg)


    def progress_hook(self, d):
        if self._cancelled:
            if self.ytdlp and hasattr(self.ytdlp, 'DownloadCancelled'):
                raise self.ytdlp.DownloadCancelled('Download cancelled by user')
            else:
                raise Exception('Download cancelled by user (yt-dlp module unavailable)')
        
        if d['status'] == 'downloading':
            # Update accumulated bytes and total
            self.accumulated_bytes += d.get('downloaded_bytes', 0)
            progress_data = {
                'status': 'downloading',
                'total_bytes': d.get('total_bytes') or self.accumulated_bytes,
                'downloaded_bytes': self.accumulated_bytes,
                'speed': d.get('speed', 0),
                'percent': d.get('percent', 0)
            }
            self.progress_updated.emit(self.download_id, progress_data)
            # Update status to running on first progress update
            if self.accumulated_bytes == d.get('downloaded_bytes', 0):
                self.started_running.emit(self.download_id)
        elif d['status'] == 'finished':
            self.progress_updated.emit(self.download_id, {
                'status': 'finished',
                'percent': 100,
                'total_bytes': self.accumulated_bytes,
                'downloaded_bytes': self.accumulated_bytes
            })
            logging.info(f"Worker {self.download_id}: yt-dlp reported status 'finished'.")


    def cancel(self):
        self._cancelled = True