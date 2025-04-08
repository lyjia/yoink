import os
from PyQt6.QtCore import pyqtSignal, QObject
# import yt_dlp # Removed static import
import logging
from util.ytdlp_manager import get_ytdlp_module # Import the manager function


class DownloadWorker(QObject):
    progress_updated = pyqtSignal(str, dict)  # download_id, progress_info
    finished = pyqtSignal(str)                # download_id
    error_occurred = pyqtSignal(str, str)     # download_id, error_msg

    def __init__(self, url, dest_dir, download_id, ytdlp_version="latest"):
        super().__init__()
        self.url = url
        self.dest_dir = dest_dir
        self.download_id = download_id
        self.ytdlp_version = ytdlp_version # Allow specifying version
        self._cancelled = False
        self.ytdlp = None # Placeholder for the loaded module

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
        except self.ytdlp.utils.DownloadError as e: # Catch specific yt-dlp errors if needed
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
            # Ensure DownloadCancelled is available before raising
            if self.ytdlp and hasattr(self.ytdlp, 'DownloadCancelled'):
                raise self.ytdlp.DownloadCancelled('Download cancelled by user')
            else:
                # Fallback if ytdlp module wasn't loaded or doesn't have the exception
                raise Exception('Download cancelled by user (yt-dlp module unavailable)')
        # Only emit progress if the download is actually running
        if d['status'] == 'downloading':
             self.progress_updated.emit(self.download_id, d)
        elif d['status'] == 'finished':
             # Optionally emit a final 100% progress update here if needed
             # self.progress_updated.emit(self.download_id, {'status': 'finished', 'total_bytes': d.get('total_bytes'), 'downloaded_bytes': d.get('downloaded_bytes')})
             logging.info(f"Worker {self.download_id}: yt-dlp reported status 'finished'.")


    def cancel(self):
        self._cancelled = True