import os
import sys
import requests
import tarfile
import zipfile
import shutil
import importlib.util
from pathlib import Path
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Constants ---
DEFAULT_RELEASES_URL = "https://api.github.com/repos/yt-dlp/yt-dlp/releases"
DEFAULT_DOWNLOAD_BASE_DIR = Path.home() / ".yoink_ytdlp_cache" # Persistent location
DEFAULT_VERSION = "latest" # Or specify a version like "2023.07.06"

# --- Helper Functions ---

def _get_download_url_for_version(version=DEFAULT_VERSION, releases_api_url=DEFAULT_RELEASES_URL):
    """Fetches the download URL for the specified yt-dlp version from GitHub API."""
    logging.info(f"Fetching release info from {releases_api_url} for version '{version}'")
    try:
        response = requests.get(releases_api_url)
        response.raise_for_status() # Raise an exception for bad status codes
        releases = response.json()

        target_release = None
        if version == "latest":
            target_release = releases[0] # First one is the latest
        else:
            for release in releases:
                if release.get("tag_name") == version:
                    target_release = release
                    break

        if not target_release:
            logging.error(f"Could not find release version '{version}'.")
            return None, None

        tag_name = target_release.get("tag_name")
        assets = target_release.get("assets", [])
        # Prefer .tar.gz, then .zip containing the source/module
        download_url = None
        for asset in assets:
            # Look for standard source archives or platform-independent executables
            # Adjust this logic if yt-dlp release assets change format
            name = asset.get("name", "").lower()
            if name == "yt-dlp.tar.gz": # Prioritize source tarball
                 download_url = asset.get("browser_download_url")
                 break
            elif name == "yt-dlp": # Standalone executable (might need different handling)
                 # For now, let's stick to source/module archives
                 pass
            elif name.endswith(".zip") and "source" in name: # Source zip as fallback
                 download_url = asset.get("browser_download_url")
                 # Don't break yet, prefer tar.gz

        if not download_url:
             logging.warning(f"Could not find a suitable download asset for version '{tag_name}'.")
             return None, None

        logging.info(f"Found download URL for version {tag_name}: {download_url}")
        return download_url, tag_name

    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching releases from GitHub API: {e}")
        return None, None
    except IndexError:
        logging.error("No releases found at the specified API URL.")
        return None, None
    except Exception as e:
        logging.error(f"An unexpected error occurred while fetching release info: {e}")
        return None, None


def download_release(url, target_file):
    """Downloads a file from a URL to a target path."""
    logging.info(f"Downloading {url} to {target_file}...")
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(target_file, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        logging.info(f"Successfully downloaded {target_file.name}")
        return True
    except requests.exceptions.RequestException as e:
        logging.error(f"Error downloading file: {e}")
        if target_file.exists():
            os.remove(target_file) # Clean up partial download
        return False
    except Exception as e:
        logging.error(f"An unexpected error occurred during download: {e}")
        if target_file.exists():
            os.remove(target_file)
        return False


def extract_release(archive_path, extract_dir):
    """Extracts a .tar.gz or .zip archive."""
    logging.info(f"Extracting {archive_path.name} to {extract_dir}...")
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        if archive_path.name.endswith(".tar.gz"):
            with tarfile.open(archive_path, "r:gz") as tar:
                # Extract safely, avoiding path traversal vulnerabilities
                # Check if members are safe before extracting
                # Python 3.12+ has tar.extractall(..., filter='data')
                # For older versions, manual check or rely on library defaults if trusted source
                tar.extractall(path=extract_dir)
        elif archive_path.name.endswith(".zip"):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                # Similar safety considerations for zipfile
                zip_ref.extractall(path=extract_dir)
        else:
            logging.error(f"Unsupported archive format: {archive_path.suffix}")
            return False

        # yt-dlp archives often extract into a subdirectory like 'yt-dlp-{version}'
        # We want the 'yt_dlp' module directory directly inside extract_dir/{version}
        # Find the actual 'yt_dlp' module directory after extraction
        extracted_items = list(extract_dir.iterdir())
        source_module_dir = None

        if len(extracted_items) == 1 and extracted_items[0].is_dir():
            # Likely extracted into a single top-level folder
            potential_module_dir = extracted_items[0] / 'yt_dlp'
            if potential_module_dir.is_dir():
                 source_module_dir = potential_module_dir
            # Check if yt_dlp is directly inside the single top-level folder
            elif (extracted_items[0] / 'yt_dlp.py').is_file(): # Older structure?
                 # Handle case where it's just files, not a package dir
                 # This might require adjusting the import logic later
                 logging.warning("Found individual files, not 'yt_dlp' package directory. Import might need adjustment.")
                 # For now, assume we need the directory containing these files
                 source_module_dir = extracted_items[0] # Treat the container dir as source
            else:
                 # Look deeper if needed, e.g. src/yt_dlp
                 potential_module_dir = extracted_items[0] / 'src' / 'yt_dlp'
                 if potential_module_dir.is_dir():
                     source_module_dir = potential_module_dir

        elif (extract_dir / 'yt_dlp').is_dir():
             # Extracted directly into the target dir
             source_module_dir = extract_dir / 'yt_dlp'

        if source_module_dir and source_module_dir.exists():
            final_module_path = extract_dir / 'yt_dlp'
            if final_module_path.exists() and final_module_path != source_module_dir:
                 logging.warning(f"Removing existing directory/link at {final_module_path} before moving.")
                 if final_module_path.is_symlink() or final_module_path.is_file():
                     final_module_path.unlink()
                 else:
                     shutil.rmtree(final_module_path)

            if source_module_dir.parent != extract_dir:
                 logging.info(f"Moving {source_module_dir} to {final_module_path}")
                 shutil.move(str(source_module_dir), str(final_module_path))
                 # Clean up the potentially empty parent directory created by extraction
                 if extracted_items[0].is_dir() and not any(extracted_items[0].iterdir()):
                     logging.info(f"Removing empty extraction directory: {extracted_items[0]}")
                     extracted_items[0].rmdir()
            elif source_module_dir != final_module_path:
                 # If source is already yt_dlp but in the wrong place (e.g. extract_dir/yt_dlp)
                 # and we want extract_dir/yt_dlp - this case should be handled by the move above
                 # If source_module_dir is already extract_dir/yt_dlp, do nothing.
                 pass

            logging.info(f"Successfully extracted and placed 'yt_dlp' module in {extract_dir}")
            return True
        else:
            logging.error(f"Could not find the 'yt_dlp' module directory within the extracted files in {extract_dir}.")
            # Optional: Clean up extraction directory if failed?
            # shutil.rmtree(extract_dir)
            return False

    except (tarfile.TarError, zipfile.BadZipFile, OSError, shutil.Error) as e:
        logging.error(f"Error extracting archive: {e}")
        # Clean up extraction directory on error
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        return False
    finally:
        # Clean up the downloaded archive file
        if archive_path.exists():
            logging.debug(f"Removing archive file: {archive_path}")
            os.remove(archive_path)


# --- Main Function ---

def get_ytdlp_module(version=DEFAULT_VERSION,
                     base_dir=DEFAULT_DOWNLOAD_BASE_DIR,
                     releases_api_url=DEFAULT_RELEASES_URL,
                     force_download=False):
    """
    Ensures the specified yt-dlp version is available locally and returns the module.

    Downloads and extracts the release if it's not found or if force_download is True.
    Dynamically imports and returns the yt-dlp module.
    """
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    # 1. Determine Target Version and Download URL
    # If version is 'latest', we need to resolve it to a specific tag name first
    # to check if we already have it.
    actual_version_tag = version
    download_url = None

    if version == "latest" or force_download:
        logging.info(f"Resolving version '{version}'...")
        url, tag = _get_download_url_for_version(version, releases_api_url)
        if not url or not tag:
            logging.error("Failed to resolve download URL or version tag.")
            return None
        download_url = url
        actual_version_tag = tag # Use the resolved tag name (e.g., "2023.11.16")
        logging.info(f"Resolved '{version}' to version tag '{actual_version_tag}'")
    else:
        # For specific versions, assume the tag is the version string
        actual_version_tag = version

    version_dir = base_dir / actual_version_tag
    module_path = version_dir / "yt_dlp" # The actual package directory

    # 2. Check if Already Available
    if not force_download and module_path.is_dir() and (module_path / "__init__.py").exists():
        logging.info(f"Found existing yt-dlp version {actual_version_tag} at {module_path}")
    else:
        # 3. Download and Extract if Needed
        logging.info(f"yt-dlp version {actual_version_tag} not found locally or download forced.")

        # Ensure download URL is fetched if not already done (for specific versions)
        if not download_url:
             url, tag = _get_download_url_for_version(actual_version_tag, releases_api_url)
             if not url or tag != actual_version_tag: # Ensure the tag matches requested version
                 logging.error(f"Failed to get download URL for specific version {actual_version_tag}.")
                 return None
             download_url = url

        # Prepare download target
        archive_filename = Path(download_url).name
        download_target_path = base_dir / archive_filename # Download to base, then extract to version_dir

        # Clean up potentially incomplete previous attempts for this version
        if version_dir.exists():
            logging.warning(f"Removing existing directory {version_dir} before download/extraction.")
            shutil.rmtree(version_dir)
        version_dir.mkdir(parents=True, exist_ok=True) # Recreate after cleaning

        if not download_release(download_url, download_target_path):
            logging.error("Download failed.")
            return None

        if not extract_release(download_target_path, version_dir):
            logging.error("Extraction failed.")
            # version_dir might be partially created, clean up?
            if version_dir.exists():
                 shutil.rmtree(version_dir)
            return None

        logging.info(f"Successfully downloaded and extracted yt-dlp version {actual_version_tag}")


    # 4. Dynamically Load and Return the Module
    module_init_file = module_path / "__init__.py"
    if not module_init_file.is_file():
        logging.error(f"Could not find __init__.py in {module_path}. Cannot import module.")
        return None

    try:
        # Add the *parent* directory of the 'yt_dlp' package to sys.path temporarily
        # This allows Python to find the 'yt_dlp' module itself.
        parent_dir = str(module_path.parent)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
            logging.debug(f"Temporarily added {parent_dir} to sys.path")

        # Import the module
        # Using importlib is cleaner than exec
        spec = importlib.util.spec_from_file_location("yt_dlp", str(module_init_file))
        if spec and spec.loader:
             ytdlp_module = importlib.util.module_from_spec(spec)
             # Add the loaded module to sys.modules BEFORE executing it
             # This is crucial for handling relative imports within the yt_dlp package
             sys.modules["yt_dlp"] = ytdlp_module
             spec.loader.exec_module(ytdlp_module)
             logging.info(f"Successfully imported yt-dlp module version {actual_version_tag} from {module_path}")

             # Optional: Clean up sys.path if strict isolation is needed,
             # but often leaving it is fine for the duration of the script.
             # Be cautious if this manager is used long-term in a complex app.
             # sys.path.remove(parent_dir)
             # logging.debug(f"Removed {parent_dir} from sys.path")

             return ytdlp_module
        else:
             logging.error(f"Could not create module spec for {module_init_file}")
             # Clean up sys.path if added
             if parent_dir in sys.path and sys.path[0] == parent_dir:
                 sys.path.pop(0)
             return None

    except ImportError as e:
        logging.error(f"Failed to import the downloaded yt-dlp module: {e}")
        # Clean up sys.path if added
        if parent_dir in sys.path and sys.path[0] == parent_dir:
            sys.path.pop(0)
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred during module import: {e}")
        # Clean up sys.path if added
        if parent_dir in sys.path and sys.path[0] == parent_dir:
            sys.path.pop(0)
        return None


def find_available_versions(base_dir=DEFAULT_DOWNLOAD_BASE_DIR):
    """Lists the locally available yt-dlp versions."""
    base_dir = Path(base_dir)
    if not base_dir.is_dir():
        return []

    versions = []
    for item in base_dir.iterdir():
        # Check if it's a directory containing a valid yt_dlp module
        if item.is_dir() and (item / "yt_dlp" / "__init__.py").is_file():
            versions.append(item.name) # The directory name is the version tag
    return sorted(versions, reverse=True) # Sort newest first


# --- Example Usage (Optional) ---
if __name__ == "__main__":
    print("Finding available versions...")
    available = find_available_versions()
    print(f"Available local versions: {available}")

    print("\nAttempting to get latest yt-dlp module...")
    # Set force_download=True to test downloading even if present
    ytdlp = get_ytdlp_module(version="latest", force_download=False)

    if ytdlp:
        print("\nSuccessfully obtained yt-dlp module.")
        # You can now use the module, e.g., access its version
        try:
            print(f"Loaded yt-dlp version: {ytdlp.version.__version__}")
            # Example: Create a YoutubeDL object (optional, just to test)
            # opts = {'quiet': True, 'logger': logging.getLogger('yt-dlp-test')}
            # with ytdlp.YoutubeDL(opts) as ydl:
            #     print("YoutubeDL object created successfully.")
            #     info = ydl.extract_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ", download=False)
            #     print(f"Video Title: {info.get('title')}")
        except AttributeError:
            print("Could not retrieve version from the loaded module (structure might differ).")
        except Exception as e:
            print(f"Error using the loaded yt-dlp module: {e}")
    else:
        print("\nFailed to obtain yt-dlp module.")

    # Example: Get a specific version
    # print("\nAttempting to get specific version '2023.07.06'...")
    # ytdlp_specific = get_ytdlp_module(version="2023.07.06")
    # if ytdlp_specific:
    #     print(f"Loaded specific yt-dlp version: {ytdlp_specific.version.__version__}")
    # else:
    #     print("Failed to obtain specific version.")