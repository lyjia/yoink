import sys
from PyQt6.QtWidgets import (QApplication)
# import yt_dlp # Removed unused import

from util.const import SETTINGS_APP_ORG, SETTINGS_APP_NAME
from windows import MainWindow

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setOrganizationName(SETTINGS_APP_ORG)
    app.setApplicationName(SETTINGS_APP_NAME)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())