import os
import sys
import subprocess
# Removed requests, tarfile, zipfile, shutil imports as they are handled by ytdlp_manager now
import tempfile
import ast
import logging
from pathlib import Path

from cx_Freeze import setup, Executable

# Import necessary functions from our manager module
try:
    import ytdlp_manager
except ImportError:
    logging.error("Failed to import ytdlp_manager. Ensure it's in the Python path.")
    sys.exit(1)


# --- Configuration ---
PROJ_ROOT = Path(__file__).parent
try:
    # Use stderr=subprocess.PIPE to suppress git errors if not a repo
    GIT_VERSION = subprocess.check_output(['git', 'describe', '--tags'], cwd=PROJ_ROOT, stderr=subprocess.PIPE).decode('ascii').strip()
except subprocess.CalledProcessError:
    GIT_VERSION = "0.0+unknown" # Fallback if not in git repo or git failed
    logging.warning("Could not determine git version using 'git describe --tags'. Using fallback.")
except FileNotFoundError:
     GIT_VERSION = "0.0+unknown" # Fallback if git is not installed
     logging.warning("git command not found. Could not determine git version. Using fallback.")


LOG_LEVEL = logging.INFO # Set to logging.DEBUG for more verbose output during build

# --- Logging Setup ---
# Use ytdlp_manager's logger configuration if needed, or keep separate setup logger
logging.basicConfig(level=LOG_LEVEL, format='%(asctime)s - %(levelname)s - SETUP - %(message)s')

# --- Helper Functions for Dependency Discovery (AST Parsing part remains here) ---

def find_ytdlp_package_dir(base_extract_path):
    """Finds the 'yt_dlp' package directory within the extracted structure."""
    if not base_extract_path or not base_extract_path.is_dir():
         logging.error(f"Invalid base extraction path provided: {base_extract_path}")
         return None

    logging.debug(f"Searching for 'yt_dlp' package directory under {base_extract_path}")

    # Check if base_extract_path itself is the package dir
    if base_extract_path.name == 'yt_dlp' and (base_extract_path / '__init__.py').is_file():
        logging.info(f"Found 'yt_dlp' package directory at: {base_extract_path}")
        return base_extract_path

    # Common locations relative to the base extraction path
    possible_paths = [
        base_extract_path / 'yt_dlp',
        base_extract_path / 'src' / 'yt_dlp',
    ]

    for path in possible_paths:
        logging.debug(f"Checking possible path: {path}")
        if path.is_dir() and (path / "__init__.py").is_file():
            logging.info(f"Found 'yt_dlp' package directory at: {path}")
            return path

    # Fallback: Deep search (might be slow)
    logging.warning(f"Standard locations failed, performing deeper search for 'yt_dlp' under {base_extract_path}...")
    try:
        for item in base_extract_path.rglob('yt_dlp'):
            if item.is_dir() and (item / "__init__.py").is_file():
                 logging.info(f"Found 'yt_dlp' package directory via rglob at: {item}")
                 return item
    except Exception as e:
         logging.error(f"Error during rglob search: {e}")


    logging.error(f"Could not find the 'yt_dlp' package directory within {base_extract_path}")
    return None


class ImportFinder(ast.NodeVisitor):
    """AST visitor to find all imported module names."""
    def __init__(self):
        self.imports = set()

    def visit_Import(self, node):
        for alias in node.names:
            # Get the top-level package name (e.g., 'os' from 'os.path')
            self.imports.add(alias.name.split('.')[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        # If it's a relative import (level > 0), ignore the module name
        # Only consider top-level imports from external modules
        if node.level == 0 and node.module:
            # Get the top-level package name
            self.imports.add(node.module.split('.')[0])
        self.generic_visit(node)

def get_imports_from_file(filepath):
    """Parses a Python file and returns a set of top-level imported module names."""
    imports = set()
    try:
        # Try reading with utf-8, fallback to system default if it fails
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except UnicodeDecodeError:
            logging.warning(f"UTF-8 decode failed for {filepath}, trying system default encoding.")
            with open(filepath, 'r', encoding=sys.getdefaultencoding(), errors='ignore') as f: # Added errors='ignore'
                content = f.read()

        tree = ast.parse(content, filename=str(filepath)) # ast.parse needs filename as string
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
        # Fallback for older Python: Use stdlib-list if available, else hardcoded list
        try:
            from stdlib_list import stdlib_list
            version_str = f"{sys.version_info.major}.{sys.version_info.minor}"
            logging.info(f"Using 'stdlib-list' package for Python {version_str}")
            return set(stdlib_list(version_str))
        except ImportError:
            logging.warning("Python < 3.10 and 'stdlib-list' package not found.")
            logging.warning("Using a basic hardcoded stdlib list. Build may include unnecessary packages or miss some.")
            # This list is NOT exhaustive and may be inaccurate!
            # Consider adding 'pip install stdlib-list' to your build requirements
            return set([
                '_ast', '_codecs', '_collections', '_functools', '_imp', '_io', '_locale',
                '_operator', '_signal', '_sre', '_stat', '_string', '_symtable', '_thread',
                '_tracemalloc', '_warnings', '_weakref', 'abc', 'argparse', 'array', 'ast',
                'atexit', 'base64', 'binascii', 'builtins', 'bz2', 'calendar', 'codecs',
                'collections', 'configparser', 'contextlib', 'copy', 'copyreg', 'csv',
                'datetime', 'decimal', 'difflib', 'email', 'encodings', 'enum', 'errno',
                'faulthandler', 'fnmatch', 'functools', 'gc', 'genericpath', 'getopt',
                'gettext', 'glob', 'gzip', 'hashlib', 'heapq', 'hmac', 'http', 'imp',
                'importlib', 'inspect', 'io', 'itertools', 'json', 'keyword', 'linecache',
                'locale', 'logging', 'lzma', 'marshal', 'math', 'mimetypes', 'multiprocessing',
                'nt', 'ntpath', 'numbers', 'opcode', 'operator', 'optparse', 'os', 'parser',
                'pathlib', 'pickle', 'platform', 'posixpath', 'pprint', 'pwd', 'py_compile',
                'pyclbr', 'queue', 'random', 're', 'reprlib', 'rlcompleter', 'runpy', 'select',
                'selectors', 'shlex', 'shutil', 'signal', 'site', 'socket', 'socketserver',
                'sre_compile', 'sre_constants', 'sre_parse', 'ssl', 'stat', 'string', 'struct',
                'subprocess', 'symbol', 'symtable', 'sys', 'sysconfig', 'tarfile', 'tempfile',
                'textwrap', 'threading', 'time', 'token', 'tokenize', 'traceback', 'tracemalloc',
                'types', 'typing', 'unicodedata', 'unittest', 'urllib', 'warnings', 'weakref',
                'winreg', 'zipfile', 'zlib',
            ])

def find_ytdlp_dependencies(ytdlp_dir_path):
    """Scans the yt_dlp package directory and returns a set of external dependencies."""
    all_imports = set()
    logging.info(f"Scanning for imports in {ytdlp_dir_path}...")
    if not ytdlp_dir_path or not ytdlp_dir_path.is_dir():
         logging.error("Invalid directory provided for dependency scan.")
         return set()

    # Use walk instead of rglob for potentially better control/error handling
    for root, _, files in os.walk(ytdlp_dir_path):
        for filename in files:
            if filename.endswith(".py"):
                py_file_path = Path(root) / filename
                logging.debug(f"Scanning file: {py_file_path}")
                imports_in_file = get_imports_from_file(py_file_path)
                all_imports.update(imports_in_file)

    logging.info(f"Found {len(all_imports)} unique top-level imports.")
    logging.debug(f"All imports found: {sorted(list(all_imports))}")

    stdlib = get_stdlib_modules()
    logging.debug(f"Excluding {len(stdlib)} stdlib modules.")

    dependencies = set()
    for imp in all_imports:
        # Basic filtering: not empty, not stdlib, not relative (already handled by finder), not yt_dlp itself
        if imp and imp not in stdlib and imp != 'yt_dlp':
            dependencies.add(imp)

    # Manually add known tricky dependencies if needed (example)
    # if 'requests' in dependencies:
    #     dependencies.add('idna') # Often needed by requests implicitly

    logging.info(f"Identified {len(dependencies)} potential external dependencies.")
    logging.debug(f"Dependencies: {sorted(list(dependencies))}")
    return dependencies

# --- Dynamic Dependency Discovery Logic ---

discovered_packages = set()
logging.info("--- Starting yt-dlp Dependency Discovery ---")
try:
    # Use a context manager for the temporary directory
    with tempfile.TemporaryDirectory(prefix="ytdlp_build_") as tmpdir:
        tmp_path = Path(tmpdir)
        logging.info(f"Created temporary directory: {tmp_path}")

        # 1. Get URL (using imported function)
        # Use 'latest' to match previous logic, ytdlp_manager handles the API endpoint
        source_url, tag_name = ytdlp_manager.get_source_archive_url(version="latest")
        if not source_url:
            raise RuntimeError(f"Failed to get yt-dlp source URL (tag: {tag_name}).")
        logging.info(f"Using source URL for tag {tag_name}: {source_url}")

        # 2. Download (using imported function)
        archive_name = Path(source_url).name
        archive_path = tmp_path / archive_name
        if not ytdlp_manager.download_release(source_url, archive_path):
            raise RuntimeError("Failed to download yt-dlp source archive.")

        # 3. Extract (using imported function)
        extract_base_dir = tmp_path / "extracted"
        # extract_release now returns the path to the main extracted content dir
        extracted_content_path = ytdlp_manager.extract_release(archive_path, extract_base_dir)
        if not extracted_content_path:
             # Attempt to delete archive before raising
             if archive_path.exists(): archive_path.unlink()
             raise RuntimeError("Failed to extract yt-dlp source archive.")

        # Delete archive now that extraction is successful
        logging.debug(f"Removing downloaded archive: {archive_path}")
        if archive_path.exists(): archive_path.unlink()


        # 4. Find yt_dlp package dir (using local helper)
        ytdlp_package_path = find_ytdlp_package_dir(extracted_content_path)
        if not ytdlp_package_path:
            raise RuntimeError("Failed to find yt_dlp package directory after extraction.")

        # 5. Analyze Dependencies (using local helper)
        discovered_packages = find_ytdlp_dependencies(ytdlp_package_path)

except Exception as e:
    logging.error(f"*** Failed to automatically discover yt-dlp dependencies: {e} ***", exc_info=True)
    logging.error("*** Build might fail or the executable might miss runtime dependencies. ***")
    # Continue without discovered packages, relying on manual entries or cx_freeze defaults
finally:
    logging.info("--- Finished yt-dlp Dependency Discovery ---")
    # Temporary directory is automatically cleaned up by the context manager

# --- cx_Freeze Build Options ---

# Start with manually known or potentially problematic packages
# Add packages known to be needed by yt-dlp or its common dependencies
# These act as a fallback if discovery fails or misses something.
build_packages = ['requests', 'certifi', 'idna', 'charset_normalizer', 'urllib3', 'mutagen'] # Added mutagen as example

# Add discovered packages, ensuring no duplicates
initial_package_count = len(build_packages)
final_packages = set(build_packages).union(discovered_packages)
added_count = len(final_packages) - initial_package_count
if added_count > 0:
    logging.info(f"Added {added_count} discovered packages to the build list.")
else:
     logging.info("No new packages discovered beyond the initial list.")

logging.info(f"Final list of packages to include ({len(final_packages)}): {sorted(list(final_packages))}")

# Dependencies are automatically detected, but fine-tuning needed.
# Exclude yt_dlp itself as it's loaded dynamically.
build_options = {
    'packages': list(final_packages), # Convert back to list for cx_Freeze
    'excludes': ['yt_dlp', 'test', 'tests', 'unittest', 'pydoc', 'tkinter', '_pytest', 'pytest'], # Exclude yt_dlp, tests, Tkinter, pytest
    'include_files': [], # Add any data files needed by your app here (e.g., ('data/', 'data/'))
    # Add other cx_freeze options if needed
    # 'zip_include_packages': ["*"], # May help with organization/size
    # 'zip_exclude_packages': [],
    # 'optimize': 2, # Example: Enable optimization
}

# --- Executable Definition ---
# Determine base: 'gui' for GUI apps on Windows, None for console apps
# Adjust 'gui' vs 'console' based on your main.py
base = None
main_script = 'main.py' # Assuming this is your entry point

if sys.platform == "win32":
    # Check if main.py seems like a GUI app (basic check)
    try:
        with open(main_script, "r", encoding="utf-8") as f:
            # Simple check for common GUI libraries
            content = f.read(2048) # Read first 2KB
            gui_libs = ['PyQt5', 'PySide2', 'tkinter', 'kivy', 'wx', 'dearpygui']
            if any(lib in content for lib in gui_libs):
                 base = "Win32GUI" # Use "Win32GUI" for GUI apps on Windows
                 logging.info(f"Detected GUI library usage in {main_script}.")
            else:
                 base = "console"
                 logging.info(f"No common GUI library detected in {main_script}, using 'console' base.")
    except FileNotFoundError:
         logging.error(f"Main script '{main_script}' not found. Cannot determine base. Defaulting to console.")
         base = "console" # Default to console if main.py not found
    except Exception as e:
         logging.error(f"Error reading main script '{main_script}': {e}. Defaulting to console.")
         base = "console"
else:
    # Keep base=None for non-Windows platforms (usually implies console)
    # Adjust if you need specific base for macOS/Linux GUI
    pass

logging.info(f"Setting executable base to: {base}")

executables = [
    Executable(main_script,
               base=base,
               target_name='yoink.exe' if sys.platform == "win32" else 'yoink'
               # icon='path/to/icon.ico' # Optional: Add an icon
               )
]

# --- Setup Execution ---

logging.info("--- Running cx_Freeze setup ---")
setup(name='Yoink!',
      version=GIT_VERSION,
      description='A GUI frontend for yt-dlp',
      options={'build_exe': build_options},
      executables=executables)

logging.info("--- cx_Freeze setup finished ---")
