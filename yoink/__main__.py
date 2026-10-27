import logging
import sys

from PySide6.QtWidgets import QApplication

from yoink import __version__, app
from yoink.ui.main_window import MainWindow


def main() -> int:
    app.setup_logging()
    logging.getLogger("yoink").info("Yoink %s", __version__)
    qapp = QApplication(sys.argv)
    qapp.setOrganizationName(app.ORG_NAME)
    qapp.setApplicationName(app.APP_NAME)
    app.apply_style(str(app.settings().value(app.KEY_STYLE, "")))
    win = MainWindow()
    win.show()
    return qapp.exec()


if __name__ == "__main__":
    sys.exit(main())
