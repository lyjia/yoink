import os
import sys
import subprocess
import re # Added for regex matching
from pathlib import Path

SETTINGS_APP_NAME = "Yoink"
SETTINGS_APP_ORG = "Lyjia"

SETTINGS_LAST_DOWNLOAD_FOLDER = "Last Download Folder"
SETTINGS_YTDLP_VERSION = "ytdlp_version"

APP_NAME = f"{SETTINGS_APP_NAME}!"
APP_DESC = "A yt-dlp GUI"

STA_STARTING = "🏁"
STA_RUNNING = "🏃"
STA_FINISHED = "✔️"
STA_ERROR = "❌"

# --- Dynamic Configuration ---
PROJ_ROOT = Path(__file__).resolve().parent # Use resolve() for robustness


def get_uniform_version():
    """
    Gets the version from git describe and formats it into a uniform,
    PEP 440 compliant format suitable for setuptools and potentially cx_Freeze.
    Format aims for 0.TAG_NUMERIC.COMMITS (e.g., 0.20250407.3)
    """
    try:
        git_output = (
            subprocess.check_output(
                ["git", "describe", "--tags"], cwd=PROJ_ROOT, stderr=subprocess.PIPE, text=True, encoding='utf-8'
            )
            .strip()
        )
        # Regex to match 'tag-commits-ghash'
        match = re.match(r"^(.*)-(\d+)-g([0-9a-f]+)$", git_output)
        if match:
            tag, commits = match.group(1), match.group(2)
            # Extract numeric part of the tag (remove non-digits)
            tag_numeric = re.sub(r'\D', '', tag)
            if not tag_numeric: # Handle tags with no numbers?
                tag_numeric = "0"
            # Format as 0.TAG_NUMERIC.COMMITS
            return f"0.{tag_numeric}.{commits}"
        else:
            # Assume it's just a tag. Try to make it numeric-ish.
            tag_numeric = re.sub(r'\D', '', git_output)
            if not tag_numeric:
                tag_numeric = "0" # Default if tag has no numbers
            # Check if original tag was purely numeric or standard like X.Y.Z
            if re.match(r"^\d+(\.\d+)*$", git_output):
                return git_output # Use tag directly if it looks like X.Y.Z
            else:
                # Use 0.TAG_NUMERIC.0 for non-standard tags at the commit
                return f"0.{tag_numeric}.0"

    except subprocess.CalledProcessError:
        return "0.0.0+git.CalledProcessError"
    except FileNotFoundError:
        return "0.0.0+git.NotFoundError"
    except Exception as e:
        print(f"Warning: Unexpected error getting git version: {e}", file=sys.stderr)
        return "0.0.0+git.UnknownError"


GIT_VERSION = get_uniform_version()
