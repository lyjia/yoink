import sys
import os
import uuid
from urllib.parse import urlparse
from PyQt6.QtWidgets import (QApplication)
import yt_dlp

from windows import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())