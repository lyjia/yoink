import os
import sys
import subprocess
from pathlib import Path

SETTINGS_APP_NAME = "Yoink"
SETTINGS_APP_ORG = "Lyjia"

SETTINGS_LAST_DOWNLOAD_FOLDER = "Last Download Folder"
SETTINGS_YTDLP_VERSION = "ytdlp_version"

APP_NAME = f"{SETTINGS_APP_NAME}!"
APP_DESC = "A yt-dlp GUI"

# --- Dynamic Configuration ---
PROJ_ROOT = Path(__file__).parent
try:
    # Use stderr=subprocess.PIPE to suppress git errors if not a repo
    GIT_VERSION = (
        subprocess.check_output(
            ["git", "describe", "--tags"], cwd=PROJ_ROOT, stderr=subprocess.PIPE
        )
        .decode("ascii")
        .strip()
    )
except subprocess.CalledProcessError:
    GIT_VERSION = "0.0+CalLProcessError"  # Fallback if not in git repo or git failed
except FileNotFoundError:
    GIT_VERSION = "0.0+FileNotFoundError"  # Fallback if git is not installed
