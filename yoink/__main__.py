import sys

from PySide6.QtWidgets import QApplication

from yoink import app
from yoink.ui.main_window import MainWindow


def main() -> int:
    app.setup_logging()
    qapp = QApplication(sys.argv)
    qapp.setOrganizationName(app.ORG_NAME)
    qapp.setApplicationName(app.APP_NAME)
    win = MainWindow()
    win.show()
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
