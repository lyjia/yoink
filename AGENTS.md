This application is a GUI frontend to the yt-dlp open-source project. It is designed to allow users to quickly and easily download videos from streaming tube sites, with some specific customizations.

See `docs/DESIGN.md` for more information about the design principles and architecture.

## About this codebase

* Application code generally goes in `yoink/`.
* Tests generally go in `tests/`.
* Documentation generally goes in `docs/`.
* This project is written in Python and uses uv for environment/package management, and QT for the GUI framework.
* yt-dlp is executed as a binary using `QProcess`. We do not import yt-dlp directly.
* This project is compiled to binaries using `nuitka`.

## Agent rules

* DRY wherever possible. Minimize code duplication and redundancy.
* KISS. Avoid unnecessary complexity and keep the codebase simple.
* When finishing a task, do another pass over the code looking for issues around readability, simplicity, maintainability, and compliance with these rules.
