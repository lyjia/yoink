import os
import sys
import tempfile
import ast
import logging
import re # Added for version parsing
import argparse # Added for command-line argument parsing
from pathlib import Path
import shutil
import tarfile
import zipfile
import contextlib
import requests # Needed for downloading source if not reusing manager func

# --- Python Version Check ---
if sys.version_info < (3, 10):
    raise RuntimeError("This script requires Python 3.10 or later for sys.stdlib_module_names.")

from cx_Freeze import setup, Executable

# Import necessary functions from our manager module
try:
    from util import ytdlp_manager
    from util.const import GIT_VERSION, SETTINGS_APP_NAME
except ImportError:
    logging.error("Failed to import local modules. Ensure they are in the Python path!")
    sys.exit(1)


LOG_LEVEL = logging.INFO  # Set to logging.DEBUG for more verbose output during build

# --- Logging Setup ---
# Use ytdlp_manager's logger configuration if needed, or keep separate setup logger
logging.basicConfig(
    level=LOG_LEVEL, format="%(asctime)s - %(levelname)s - SETUP - %(message)s"
)

# --- Argument Parsing ---
# We create a separate parser for our custom args to avoid conflicts with cx_Freeze
build_parser = argparse.ArgumentParser(add_help=False)
build_parser.add_argument(
    '--build-type',
    choices=['debug', 'production'],
    default='debug',
    help='Specify the build type: debug (with console) or production (no console for GUI).'
)
build_parser.add_argument(
    '--ytdlp-tag',
    type=str,
    default=None, # Default is None, meaning fetch latest
    help='Specify a yt-dlp git tag (e.g., 2023.07.06) to scan for dependencies. Defaults to latest release.'
)

# Parse only the known arguments defined above, leave the rest for cx_Freeze
build_args, unknown_args = build_parser.parse_known_args()
build_type = build_args.build_type
target_ytdlp_tag_arg = build_args.ytdlp_tag # Store the tag argument

# Reconstruct sys.argv for cx_Freeze, removing our custom arguments
sys.argv = [sys.argv[0]] + unknown_args

logging.info(f"Build type selected: {build_type}")
logging.info(f"Target yt-dlp tag specified: {target_ytdlp_tag_arg if target_ytdlp_tag_arg else 'Latest (default)'}")
# --- End Argument Parsing ---

# --- Build Support Setup ---
BUILD_SUPPORT_DIR = Path("build_support")
STDLIB_CACHE_FILE = BUILD_SUPPORT_DIR / "yt-dlp_stdlib_cache.txt"

def ensure_build_support_dir():
    """Creates the build_support directory if it doesn't exist."""
    BUILD_SUPPORT_DIR.mkdir(exist_ok=True)
    # No logging here, might be called before logging is fully set up depending on placement

def read_stdlib_cache(path):
    """Reads the cache file and returns a set of module names."""
    modules = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                module_name = line.strip()
                if module_name and not module_name.startswith("#"):
                    modules.add(module_name)
        logging.info(f"Read {len(modules)} modules from cache: {path}")
    except FileNotFoundError:
        logging.warning(f"Stdlib cache file not found: {path}")
    except Exception as e:
        logging.error(f"Error reading stdlib cache file {path}: {e}")
    return modules

def write_stdlib_cache(path, modules):
    """Writes a set of module names to the cache file."""
    try:
        ensure_build_support_dir() # Ensure directory exists before writing
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Auto-generated list of yt-dlp stdlib dependencies\n")
            f.write(f"# Target Tag: {target_ytdlp_tag_arg if target_ytdlp_tag_arg else 'Latest'}\n") # Add tag info
            for module_name in sorted(list(modules)):
                f.write(f"{module_name}\n")
        logging.info(f"Wrote {len(modules)} modules to cache: {path}")
    except Exception as e:
        logging.error(f"Error writing stdlib cache file {path}: {e}")

# Ensure the directory exists early, although write_stdlib_cache also ensures it
ensure_build_support_dir()
# --- End Build Support Setup ---

# --- Helper Functions for Dependency Discovery (AST Parsing part remains here) ---
logging.info(f"====== Init setup for {SETTINGS_APP_NAME} v{GIT_VERSION} ======")


def find_ytdlp_package_dir(base_extract_path):
    """Finds the 'yt_dlp' package directory within the extracted structure."""
    if not base_extract_path or not base_extract_path.is_dir():
        logging.error(f"Invalid base extraction path provided: {base_extract_path}")
        return None

    logging.debug(f"Searching for 'yt_dlp' package directory under {base_extract_path}")

    # Check if base_extract_path itself is the package dir
    if (
        base_extract_path.name == "yt_dlp"
        and (base_extract_path / "__init__.py").is_file()
    ):
        logging.info(f"Found 'yt_dlp' package directory at: {base_extract_path}")
        return base_extract_path

    # Common locations relative to the base extraction path
    possible_paths = [
        base_extract_path / "yt_dlp",
        base_extract_path / "src" / "yt_dlp",
    ]

    for path in possible_paths:
        logging.debug(f"Checking possible path: {path}")
        if path.is_dir() and (path / "__init__.py").is_file():
            logging.info(f"Found 'yt_dlp' package directory at: {path}")
            return path

    # Fallback: Deep search (might be slow)
    logging.warning(
        f"Standard locations failed, performing deeper search for 'yt_dlp' under {base_extract_path}..."
    )
    try:
        for item in base_extract_path.rglob("yt_dlp"):
            if item.is_dir() and (item / "__init__.py").is_file():
                logging.info(f"Found 'yt_dlp' package directory via rglob at: {item}")
                return item
    except Exception as e:
        logging.error(f"Error during rglob search: {e}")

    logging.error(
        f"Could not find the 'yt_dlp' package directory within {base_extract_path}"
    )
    return None


class ImportFinder(ast.NodeVisitor):
    """AST visitor to find all imported module names/paths."""
    def __init__(self):
        self.imports = set()

    def visit_Import(self, node):
        for alias in node.names:
            # Add the full import name and its top-level package
            # e.g., for 'import xml.etree.ElementTree': add 'xml.etree.ElementTree' and 'xml'
            self.imports.add(alias.name)
            self.imports.add(alias.name.split(".")[0])
            # Optionally add intermediate parts too, though maybe overkill:
            # parts = alias.name.split('.')
            # for i in range(1, len(parts)):
            #     self.imports.add('.'.join(parts[:i]))
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        # If it's a relative import (level > 0), ignore
        if node.level == 0 and node.module:
            # Try to capture the full path if possible, otherwise top-level
            # Example: from xml.etree import ElementTree -> add 'xml.etree'
            # Example: from . import compat -> ignore (relative)
            # Example: from yt_dlp import X -> add 'yt_dlp'
            # Example: from requests import X -> add 'requests'
            # We primarily care about the base package for stdlib check,
            # but including submodules might help cx_Freeze later.
            self.imports.add(node.module) # Store potentially full path like 'xml.etree'
            # Also add the top-level package for easier stdlib checking
            self.imports.add(node.module.split(".")[0])
        self.generic_visit(node)


def get_imports_from_file(filepath):
    """Parses a Python file and returns a set of top-level imported module names."""
    imports = set()
    try:
        # Try reading with utf-8, fallback to system default if it fails
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            logging.warning(
                f"UTF-8 decode failed for {filepath}, trying system default encoding."
            )
            with open(
                filepath, "r", encoding=sys.getdefaultencoding(), errors="ignore"
            ) as f:  # Added errors='ignore'
                content = f.read()

        tree = ast.parse(
            content, filename=str(filepath)
        )  # ast.parse needs filename as string
        finder = ImportFinder()
        finder.visit(tree)
        imports = finder.imports
    except SyntaxError as e:
        logging.warning(f"Syntax error parsing {filepath}: {e}. Skipping file.")
    except FileNotFoundError:
        logging.warning(f"File not found during import scan: {filepath}. Skipping.")
    except Exception as e:
        logging.error(f"Error parsing {filepath}: {e}. Skipping file.")
    return imports


def get_stdlib_modules():
    """Returns a set of Python standard library module names."""
    if sys.version_info >= (3, 10):
        logging.debug("Using sys.stdlib_module_names (Python 3.10+)")
        # Ensure it's a set for efficient lookup
        return set(sys.stdlib_module_names)
    else:
       raise Exception("Python version must be 3.10 or greater")

def find_stdlib_imports(source_dir_path):
    """Scans the source directory and returns a set of required stdlib dependencies."""
    all_imports = set()
    logging.info(f"Scanning for stdlib imports in {source_dir_path}...")
    if not source_dir_path or not source_dir_path.is_dir():
        logging.error("Invalid directory provided for stdlib dependency scan.")
        return set()

    # Use the existing get_imports_from_file which uses the updated ImportFinder
    for root, _, files in os.walk(source_dir_path):
        for filename in files:
            if filename.endswith(".py"):
                py_file_path = Path(root) / filename
                # logging.debug(f"Scanning file: {py_file_path}") # Too verbose
                imports_in_file = get_imports_from_file(py_file_path)
                all_imports.update(imports_in_file)

    logging.info(f"Found {len(all_imports)} unique import strings.")
    logging.debug(f"All import strings found: {sorted(list(all_imports))}")

    stdlib_modules = get_stdlib_modules()
    logging.debug(f"Checking against {len(stdlib_modules)} known stdlib modules.")

    required_stdlib = set()
    for imp in all_imports:
        # Check if the top-level part of the import is in the stdlib set
        top_level_module = imp.split(".")[0]
        if top_level_module in stdlib_modules:
            # Add the specific import found (e.g., 'xml.etree') AND the top-level ('xml')
            # cx_Freeze 'includes' often works best with top-level names.
            required_stdlib.add(imp)
            required_stdlib.add(top_level_module)

    # Remove any empty strings or potentially problematic entries if necessary
    required_stdlib.discard('')

    logging.info(f"Identified {len(required_stdlib)} required stdlib modules/submodules.")
    logging.debug(f"Required stdlib: {sorted(list(required_stdlib))}")
    return required_stdlib


# --- yt-dlp Source Handling ---

# Attempt to import from util.ytdlp_manager
try:
    # Assuming these functions exist and are suitable for build-time use
    # We might need more specific functions than the generic ones if they exist
    # Trying with potential internal function names based on common patterns
    from util.ytdlp_manager import get_latest_release_tag, _download_file as download_file, _extract_archive as extract_archive
    logging.info("Successfully imported download/extract functions from util.ytdlp_manager.")
    CAN_REUSE_MANAGER_FUNCS = True
except ImportError as e:
    logging.warning(f"Could not import from util.ytdlp_manager ({e}). Defining local fallbacks for download/extraction.")
    CAN_REUSE_MANAGER_FUNCS = False

    # Define local fallbacks if import fails
    def get_latest_release_tag(repo="yt-dlp/yt-dlp"):
        """Gets the latest release tag from GitHub API (requires requests)."""
        api_url = f"https://api.github.com/repos/{repo}/releases/latest"
        try:
            response = requests.get(api_url, timeout=15) # Increased timeout
            response.raise_for_status()
            data = response.json()
            tag = data.get("tag_name")
            if not tag:
                raise ValueError("Could not find 'tag_name' in GitHub API response.")
            logging.info(f"Fetched latest yt-dlp release tag: {tag}")
            return tag
        except Exception as e:
            logging.error(f"Failed to fetch latest release tag from GitHub: {e}")
            return None # Indicate failure

    def download_file(url, dest_path):
        """Downloads a file from a URL to a destination path (requires requests)."""
        try:
            logging.info(f"Downloading {url} to {dest_path}...")
            with requests.get(url, stream=True, timeout=60) as r: # Increased timeout
                r.raise_for_status()
                with open(dest_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            logging.info("Download complete.")
            return True
        except Exception as e:
            logging.error(f"Failed to download {url}: {e}")
            # Clean up partial download
            if dest_path.exists():
                try:
                    dest_path.unlink()
                except OSError:
                    pass
            return False

    def extract_archive(archive_path, extract_to_dir):
        """Extracts a .zip or .tar.gz archive."""
        extract_to_dir.mkdir(parents=True, exist_ok=True)
        logging.info(f"Extracting {archive_path} to {extract_to_dir}...")
        try:
            if str(archive_path).endswith(".zip"):
                with zipfile.ZipFile(archive_path, "r") as zip_ref:
                    zip_ref.extractall(extract_to_dir)
            elif str(archive_path).endswith(".tar.gz"):
                with tarfile.open(archive_path, "r:gz") as tar_ref:
                    tar_ref.extractall(extract_to_dir)
            else:
                raise ValueError(f"Unsupported archive format: {archive_path}")
            logging.info("Extraction complete.")
            return True
        except Exception as e:
            logging.error(f"Failed to extract {archive_path}: {e}")
            return False


@contextlib.contextmanager
def temporary_ytdlp_source(tag):
    """Context manager to download, extract, and cleanup yt-dlp source."""
    with tempfile.TemporaryDirectory(prefix="ytdlp_build_src_") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        source_dir = None
        archive_path = None
        logging.info(f"Using temporary directory: {temp_dir}")

        try:
            # Construct download URL (adjust if repo/URL structure changes)
            source_zip_url = f"https://github.com/yt-dlp/yt-dlp/archive/refs/tags/{tag}.zip"
            source_tar_url = f"https://github.com/yt-dlp/yt-dlp/archive/refs/tags/{tag}.tar.gz"

            # Prefer zip, fallback to tar.gz
            archive_path_zip = temp_dir / f"yt-dlp-{tag}.zip"
            archive_path_tar = temp_dir / f"yt-dlp-{tag}.tar.gz"

            if download_file(source_zip_url, archive_path_zip):
                 archive_path = archive_path_zip
            elif download_file(source_tar_url, archive_path_tar):
                 archive_path = archive_path_tar
            else:
                logging.error(f"Failed to download source archive for tag {tag}.")
                yield None # Indicate failure to the caller
                return # Exit context manager

            extract_dir = temp_dir / "extracted"
            if not extract_archive(archive_path, extract_dir):
                logging.error(f"Failed to extract archive {archive_path}.")
                yield None # Indicate failure
                return

            # Find the actual source root dir (often contains tag name, e.g., yt-dlp-2023.07.06)
            # There should ideally be only one directory after extraction
            extracted_items = list(extract_dir.iterdir())
            if len(extracted_items) == 1 and extracted_items[0].is_dir():
                 source_root_dir = extracted_items[0]
                 # Now find the 'yt_dlp' package dir within the extracted source root
                 ytdlp_package_dir = find_ytdlp_package_dir(source_root_dir) # Reuse existing helper
                 if ytdlp_package_dir:
                     logging.info(f"Found yt-dlp package source at: {ytdlp_package_dir}")
                     yield ytdlp_package_dir # Provide the path to the caller
                 else:
                     logging.error(f"Could not locate 'yt_dlp' package within extracted source at {source_root_dir}")
                     yield None
            else:
                logging.error(f"Unexpected structure in extracted archive at {extract_dir}. Expected single root directory.")
                yield None

        except Exception as e:
            logging.error(f"Error during temporary source handling for tag {tag}: {e}")
            yield None # Indicate failure
        finally:
            # Cleanup is handled automatically by TemporaryDirectory context manager
            logging.debug(f"Temporary directory {temp_dir} will be cleaned up.")

# --- End yt-dlp Source Handling ---


# --- Determine Required Stdlib Includes ---
logging.info("--- Determining required stdlib modules for yt-dlp ---")

modules_to_include = set()
target_tag = target_ytdlp_tag_arg # Use tag from arg if provided

if not target_tag:
    logging.info("No specific yt-dlp tag provided, fetching latest release tag...")
    target_tag = get_latest_release_tag()
    if not target_tag:
        logging.warning("Failed to fetch latest tag. Attempting fallback to cache.")
    else:
        logging.info(f"Latest release tag determined: {target_tag}")

scan_successful = False
if target_tag:
    logging.info(f"Attempting to scan source for tag: {target_tag}")
    try:
        # Use the context manager for download, extraction, and cleanup
        with temporary_ytdlp_source(target_tag) as ytdlp_src_path:
            if ytdlp_src_path and ytdlp_src_path.is_dir():
                discovered_modules = find_stdlib_imports(ytdlp_src_path)
                if discovered_modules is not None: # find_stdlib_imports returns set() on error, check not None
                    modules_to_include = discovered_modules
                    # Update the cache file with the newly discovered modules
                    write_stdlib_cache(STDLIB_CACHE_FILE, modules_to_include)
                    scan_successful = True
                    logging.info(f"Successfully scanned tag {target_tag} and updated cache.")
                else:
                    # Scan function indicated an error internally
                    logging.warning(f"Scan function failed for tag {target_tag}.")
            else:
                logging.warning(f"Failed to obtain or validate source directory for tag {target_tag}.")
    except Exception as e:
        logging.error(f"An unexpected error occurred during source scanning for tag {target_tag}: {e}", exc_info=True)
        # Ensure scan_successful remains False

if not scan_successful:
    logging.warning("Online scan failed or was skipped. Attempting to use cached stdlib includes.")
    cached_modules = read_stdlib_cache(STDLIB_CACHE_FILE)
    if cached_modules:
        modules_to_include = cached_modules
        logging.info(f"Using {len(modules_to_include)} modules from cache file: {STDLIB_CACHE_FILE}")
    else:
        logging.error("Online scan failed AND cache is unavailable or empty. Build might fail due to missing stdlib modules.")
        # modules_to_include remains empty set()

# --- Platform-Specific Filtering ---
initial_module_count = len(modules_to_include)
platform_specific_removals = set()
if sys.platform == "win32":
    # Remove Unix-specific modules if building on Windows
    unix_only = {"fcntl", "pty"}
    platform_specific_removals = modules_to_include.intersection(unix_only)
    modules_to_include -= platform_specific_removals
elif sys.platform == "darwin": # macOS
    # Potentially remove Windows-specific modules if needed (example)
    windows_only = {"msvcrt", "_winapi", "winreg"}
    platform_specific_removals = modules_to_include.intersection(windows_only)
    modules_to_include -= platform_specific_removals
else: # Linux/Other Unix
    windows_only = {"msvcrt", "_winapi", "winreg"}
    platform_specific_removals = modules_to_include.intersection(windows_only)
    modules_to_include -= platform_specific_removals

if platform_specific_removals:
    logging.info(f"Removed {len(platform_specific_removals)} platform-specific stdlib modules for {sys.platform}: {sorted(list(platform_specific_removals))}")

logging.info(f"Final stdlib modules to include in build after platform filtering: {sorted(list(modules_to_include))}")
# --- End Determine Required Stdlib Includes ---


# --- cx_Freeze Build Options ---

# Define external packages that definitely need to be included
# (Dependencies of our app code, or things cx_Freeze might miss)
build_packages = [
    "requests", # Still needed if local download fallback is used, and generally useful
    "certifi",
    "idna",
    "charset_normalizer",
    "urllib3"
]
logging.info(f"Manually specified external packages: {build_packages}")
final_packages = set(build_packages) # Start with manual list
# Note: The old 'discovered_packages' logic for *external* deps is not used here.

# Dependencies are automatically detected, but fine-tuning needed.
# Exclude yt_dlp itself as it's loaded dynamically.
build_options = {
    "packages": list(final_packages),  # External packages needed
    "excludes": [
        "yt_dlp", # Exclude the dynamically loaded package itself
        "test",
        "tests",
        "unittest",
        "pydoc",
        "tkinter", # Usually not needed unless GUI uses Tkinter directly
        "_pytest",
        "pytest",
        "distutils", # Often safe to exclude
        "setuptools",
        "pip",
        "wheel",
        "Cython", # Common build dependencies to exclude
        "numpy", # Exclude large packages if not directly used by *your* code
        "pandas",
        "matplotlib",
        "scipy",
        "IPython",
        "jupyter",
    ],
    "includes": list(modules_to_include), # Dynamically determined stdlib modules
    "include_files": [],  # Add any data files needed by your app here
    # Add other cx_freeze options if needed
    # 'zip_include_packages': ["*"],
    # 'zip_exclude_packages': [],
    # 'optimize': 2, # Example: Enable optimization level
}

# --- Executable Definition ---
# Determine base: 'gui' for GUI apps on Windows (production), 'console' otherwise or for debug
base = None
main_script = "main.py"  # Assuming this is your entry point

if sys.platform == "win32":
    if build_type == "debug":
        base = "console"
        logging.info("Debug build selected: Forcing 'console' base on Windows.")
    elif build_type == "production":
        # Check if main.py seems like a GUI app (basic check)
        try:
            with open(main_script, "r", encoding="utf-8") as f:
                # Simple check for common GUI libraries
                content = f.read(2048)  # Read first 2KB
                gui_libs = ["PyQt6", "PySide6", "tkinter", "kivy", "wx", "dearpygui"]
                if any(lib in content for lib in gui_libs):
                    base = "Win32GUI"  # Use "Win32GUI" for GUI apps on Windows
                    logging.info(f"Production build: Detected GUI library usage in {main_script}. Using 'Win32GUI' base.")
                else:
                    base = "console"
                    logging.info(
                        f"Production build: No common GUI library detected in {main_script}. Using 'console' base."
                    )
        except FileNotFoundError:
            logging.error(
                f"Main script '{main_script}' not found. Cannot determine base for production build. Defaulting to console."
            )
            base = "console"  # Default to console if main.py not found
        except Exception as e:
            logging.error(
                f"Error reading main script '{main_script}' for production build: {e}. Defaulting to console."
            )
            base = "console"
    # No else needed here as argparse handles invalid choices and defaults
else:
    # Keep base=None for non-Windows platforms (usually implies console)
    # Debug/Production distinction mainly affects Windows console visibility here
    logging.info(f"Non-Windows platform. Using default base (None). Build type '{build_type}' has no effect on base.")
    pass # base remains None

logging.info(f"Setting executable base to: {base}")

executables = [
    Executable(
        main_script,
        base=base,
        target_name="yoink.exe" if sys.platform == "win32" else "yoink",
        # icon='path/to/icon.ico' # Optional: Add an icon
    )
]

# --- Setup Execution ---

logging.info("--- Running cx_Freeze setup ---")
# GIT_VERSION from util.const now contains the uniform version string.
logging.info(f"Using uniform version for package and build: {GIT_VERSION}")

setup(
    name=SETTINGS_APP_NAME,
    version=GIT_VERSION, # Use the uniform version from util.const
    description="A GUI frontend for yt-dlp",
    options={"build_exe": build_options},
    executables=executables,
)

logging.info("--- cx_Freeze setup finished ---")
