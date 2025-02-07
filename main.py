import sys
import os
import uuid
from urllib.parse import urlparse
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLineEdit, QPushButton, QTableWidget,
                             QTableWidgetItem, QFileDialog, QHeaderView, QProgressBar)
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread
import yt_dlp

from windows import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())