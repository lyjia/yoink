import os
import sys
import requests
# import tarfile # Removed
import zipimport # Added
# import shutil # Removed
# import importlib.util # Removed
from pathlib import Path
import logging
# import tempfile # Removed as it's no longer used

# requirements for yt-dlp (Keep for now, might be needed by loaded module)
import optparse
import glob
import xml

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Constants ---
DEFAULT_RELEASES_URL = "https://api.github.com/repos/yt-dlp/yt-dlp/releases"
DEFAULT_DOWNLOAD_BASE_DIR = Path.home() / ".yoink_ytdlp_cache" # Persistent location
DEFAULT_VERSION = "latest" # Or specify a version like "2023.07.06"

# --- Helper Functions ---

def _get_release_data(version=DEFAULT_VERSION, releases_api_url=DEFAULT_RELEASES_URL):
    """Fetches release data for the specified yt-dlp version from GitHub API."""
    target_url = releases_api_url
    headers = {'Accept': 'application/vnd.github.v3+json'}
    if version == "latest":
        # Ensure we query the 'latest' endpoint if specifically requested
        if not target_url.endswith("/latest"):
             # Construct the 'latest' URL if given the general releases URL
             if '/releases' in target_url:
                  target_url = target_url.split('/releases')[0] + '/releases/latest'
             else:
                  # Assume base repo URL, append /releases/latest
                  target_url = target_url.rstrip('/') + '/releases/latest'
    else:
        # For specific versions, we need to fetch all releases and find the tag
        if target_url.endswith("/latest"):
             target_url = target_url.replace("/latest", "") # Get the general releases URL

    logging.info(f"Fetching release info from {target_url} for version '{version}'")
    try:
        response = requests.get(target_url, timeout=30, headers=headers)
        response.raise_for_status() # Raise an exception for bad status codes
        release_data = response.json()

        target_release_data = None
        if version == "latest":
            # The /latest endpoint returns a single release object
            target_release_data = release_data
        else:
            # The general /releases endpoint returns a list
            releases_list = release_data
            for release in releases_list:
                if release.get("tag_name") == version:
                    target_release_data = release
                    break

        if not target_release_data:
            logging.error(f"Could not find release data for version '{version}'.")
            return None

        return target_release_data

    except requests.exceptions.RequestException as e:
        logging.error(f"Error fetching releases from GitHub API: {e}")
        return None
    except (IndexError, KeyError) as e: # Added KeyError for potentially missing fields
        logging.error(f"No releases found or data malformed at the specified API URL: {e}")
        return None
    except Exception as e:
        logging.error(f"An unexpected error occurred while fetching release info: {e}")
        return None


def _find_zipimport_asset(release_data):
    """Finds the platform-independent zipimport asset (named 'yt-dlp') within the release data."""
    assets = release_data.get("assets", [])
    for asset in assets:
        # The asset for zipimport is named simply 'yt-dlp'
        if asset.get("name") == "yt-dlp":
            logging.debug(f"Found zipimport asset ('yt-dlp'): {asset.get('browser_download_url')}")
            return asset
    return None

def get_zipimport_asset_url(version=DEFAULT_VERSION, releases_api_url=DEFAULT_RELEASES_URL):
    """Fetches the zipimport asset ('yt-dlp') URL for the specified version."""
    target_release_data = _get_release_data(version, releases_api_url)
    if not target_release_data:
        return None, None # Return None for URL and Tag

    tag_name = target_release_data.get("tag_name")
    zipimport_asset = _find_zipimport_asset(target_release_data) # Use renamed helper

    if not zipimport_asset:
        logging.warning(f"Could not find zipimport download asset ('yt-dlp') for version '{tag_name}'.")
        return None, tag_name # Return tag even if URL not found

    final_url = zipimport_asset.get("browser_download_url")
    if not final_url:
        logging.warning(f"Found zipimport asset ('yt-dlp') for version '{tag_name}' but it has no download URL.")
        return None, tag_name

    logging.info(f"Found zipimport ('yt-dlp') download URL for version {tag_name}: {final_url}")
    return final_url, tag_name

def download_release(url: str, target_file: Path) -> bool:
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
            try:
                target_file.unlink() # Use unlink for Path objects
            except OSError:
                 logging.warning(f"Could not remove partial download on error: {target_file}")
        return False


# --- Removed extract_release function ---
# --- Removed _move_and_cleanup_extraction function ---
# --- Main Function ---

def get_ytdlp_module(version=DEFAULT_VERSION,
                     base_dir=DEFAULT_DOWNLOAD_BASE_DIR,
                     releases_api_url=DEFAULT_RELEASES_URL,
                     force_download=False):
    """
    Ensures the specified yt-dlp version's zipimport file ('yt-dlp') is available locally
    and returns the loaded module using zipimport.

    Downloads the zipimport release ('yt-dlp') if it's not found or if force_download is True.
    Dynamically imports and returns the yt-dlp module from the downloaded file.
    """
    base_dir = Path(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    # 1. Determine Target Version and Download URL
    # If version is 'latest', we need to resolve it to a specific tag name first
    # to check if we already have it.
    actual_version_tag = version
    download_url = None

    actual_version_tag = None
    download_url = None

    # Resolve version tag and get source URL if needed
    if version == "latest" or force_download:
        logging.info(f"Resolving zipimport asset URL for version '{version}'...")
        url, tag = get_zipimport_asset_url(version, releases_api_url) # Use renamed function
        if not url or not tag:
            logging.error("Failed to resolve zipimport download URL or version tag.")
            return None
        download_url = url
        actual_version_tag = tag
        logging.info(f"Resolved '{version}' to version tag '{actual_version_tag}' with zipimport URL: {download_url}")
    else:
        # For specific versions, assume the tag is the version string
        actual_version_tag = version

    # If we didn't resolve 'latest' above, we need the tag name now
    if not actual_version_tag:
         release_data = _get_release_data(version, releases_api_url)
         if not release_data:
              logging.error(f"Could not get release data for specific version {version}.")
              return None
         actual_version_tag = release_data.get("tag_name")
         if not actual_version_tag:
              logging.error(f"Could not determine tag name for version {version}.")
              return None

    version_dir = base_dir / actual_version_tag # e.g., ~/.yoink_cache/2023.11.16
    zipimport_path = version_dir / "yt-dlp" # Target the 'yt-dlp' file for zipimport

    # 2. Check if Already Available and Determine if Download is Needed
    needs_download = False
    if not zipimport_path.is_file():
        logging.info(f"yt-dlp zipimport file not found locally at {zipimport_path}.")
        needs_download = True
    elif force_download:
        logging.info(f"Forcing download for yt-dlp zipimport file even though it exists at {zipimport_path}.")
        needs_download = True
    else:
        # File exists and force_download is False
        logging.info(f"Found existing yt-dlp zipimport file for version {actual_version_tag} at {zipimport_path}. Using cached version.")
        # Proceed directly to loading below, skip download block

    # 3. Download zipimport file if Needed
    if needs_download:
        logging.info(f"Proceeding with download actions for yt-dlp version {actual_version_tag}.")

        # Ensure download URL is fetched if not already done (e.g., if needs_download=True because file was missing)
        if not download_url:
             url, tag = get_zipimport_asset_url(actual_version_tag, releases_api_url)
             if not url or tag != actual_version_tag:
                 logging.error(f"Failed to get zipimport download URL for specific version {actual_version_tag} (Tag mismatch or URL missing).")
                 return None
             download_url = url

        # Prepare download destination
        try:
            # Ensure the target directory exists
            version_dir.mkdir(parents=True, exist_ok=True)

            # Attempt to remove existing file *only if forcing download*
            if force_download and zipimport_path.exists():
                 logging.warning(f"Attempting to remove existing destination file {zipimport_path} due to force_download=True.")
                 try:
                     # This is the critical point where the error occurred.
                     # If this still fails, the file handle might be held by something external
                     # or the zipimporter from a previous load wasn't garbage collected yet.
                     zipimport_path.unlink()
                     logging.info(f"Successfully removed existing file {zipimport_path} for forced download.")
                 except OSError as e:
                     logging.error(f"Failed to remove existing file {zipimport_path} during forced download: {e}. Cannot proceed with forced download.")
                     # Fail explicitly if we cannot remove the file when forced to.
                     return None

            # Download directly to the final destination ('yt-dlp')
            logging.info(f"Downloading zipimport file ('yt-dlp') for version {actual_version_tag}...")
            if not download_release(download_url, zipimport_path):
                logging.error("Download failed.")
                # Attempt cleanup of potentially partial download
                if zipimport_path.exists():
                    try: zipimport_path.unlink()
                    except OSError: pass
                return None

            logging.info(f"Successfully downloaded zipimport file ('yt-dlp') for version {actual_version_tag} to {zipimport_path}")

        except Exception as e:
             logging.error(f"Error during download preparation/execution: {e}", exc_info=True)
             # Attempt cleanup if download failed mid-way
             # We might have created the dir or partially downloaded
             if zipimport_path.exists() and needs_download: # Only cleanup if we were the ones downloading
                 try: zipimport_path.unlink()
                 except OSError: pass
             return None
        # If we reach here, download was successful or skipped because file existed and force_download=False

    # 4. Load Module using zipimport
    logging.info(f"Attempting to load yt-dlp module from {zipimport_path} using zipimport...")
    if not zipimport_path.is_file():
         logging.error(f"Target zipimport file ('yt-dlp') not found at {zipimport_path}")
         return None

    try:
        importer = zipimport.zipimporter(str(zipimport_path))
        # Load the 'yt_dlp' package from within the zipimport file
        # Ensure the package name 'yt_dlp' matches what's inside the file structure
        ytdlp_module = importer.load_module('yt_dlp')
        logging.info(f"Successfully imported yt-dlp module version {actual_version_tag} from {zipimport_path}")

        # Add to sys.modules BEFORE use to handle internal relative imports within yt_dlp
        # This is crucial for the loaded module to function correctly.
        sys.modules["yt_dlp"] = ytdlp_module

        return ytdlp_module
    except zipimport.ZipImportError as e:
        logging.error(f"Failed to import yt-dlp module from {zipimport_path} (ZipImportError): {e}", exc_info=True)
        # Clean up sys.modules if import failed partially?
        if "yt_dlp" in sys.modules and isinstance(sys.modules["yt_dlp"], zipimport.zipimporter):
             del sys.modules["yt_dlp"] # Or if it's the module object itself
        return None
    except ImportError as e:
         logging.error(f"Failed to import yt-dlp module from {zipimport_path} (ImportError): {e}", exc_info=True)
         if "yt_dlp" in sys.modules: # Clean up if partially registered
              try: del sys.modules["yt_dlp"]
              except KeyError: pass
         return None
    except Exception as e:
        logging.error(f"An unexpected error occurred during zipimport: {e}", exc_info=True)
        if "yt_dlp" in sys.modules: # Clean up if partially registered
             try: del sys.modules["yt_dlp"]
             except KeyError: pass
        return None


def find_available_versions(base_dir=DEFAULT_DOWNLOAD_BASE_DIR):
    """Lists the locally available yt-dlp versions."""
    base_dir = Path(base_dir)
    if not base_dir.is_dir():
        return []

    versions = []
    for item in base_dir.iterdir():
        # Check if it's a directory containing the zipimport file ('yt-dlp')
        if item.is_dir() and (item / "yt-dlp").is_file():
            versions.append(item.name) # The directory name is the version tag
    return sorted(versions, reverse=True) # Sort newest first


# --- Example Usage (Optional) ---
if __name__ == "__main__":
    print("Finding available versions...")
    available = find_available_versions()
    print(f"Available local versions: {available}")

    print("\nAttempting to get latest yt-dlp module...")
    # Set force_download=True to test downloading even if present
    ytdlp = get_ytdlp_module(version="latest", force_download=False) # Set force_download=True to test

    if ytdlp:
        print("\nSuccessfully obtained yt-dlp module.")
        # You can now use the module, e.g., access its version
        try:
            # Accessing version might still work if the loaded module has it
            if hasattr(ytdlp, 'version') and hasattr(ytdlp.version, '__version__'):
                 print(f"Loaded yt-dlp version: {ytdlp.version.__version__}")
            else:
                 print("Loaded yt-dlp module, but could not determine version attribute.")
            # Example: Create a YoutubeDL object (optional, just to test)
            # opts = {'quiet': True, 'logger': logging.getLogger('yt-dlp-test')}
            # try:
            #     with ytdlp.YoutubeDL(opts) as ydl:
            #         print("YoutubeDL object created successfully.")
            #         # info = ydl.extract_info("https://www.youtube.com/watch?v=dQw4w9WgXcQ", download=False)
            #         # print(f"Video Title: {info.get('title')}")
            # except Exception as test_e:
            #      print(f"Error during YoutubeDL test: {test_e}")
        except AttributeError:
            print("Could not retrieve version from the loaded module (attribute missing or structure differs).")
        except Exception as e:
            print(f"Error using the loaded yt-dlp module: {e}")
    else:
        print("\nFailed to obtain yt-dlp module.")

    # Example: Get a specific version
    # print("\nAttempting to get specific version '2023.07.06'...")
    # SPECIFIC_VERSION = "2023.11.16" # Example specific version
    # print(f"\nAttempting to get specific version '{SPECIFIC_VERSION}'...")
    # ytdlp_specific = get_ytdlp_module(version=SPECIFIC_VERSION)
    # if ytdlp_specific:
    #     if hasattr(ytdlp_specific, 'version') and hasattr(ytdlp_specific.version, '__version__'):
    #          print(f"Loaded specific yt-dlp version: {ytdlp_specific.version.__version__}")
    #     else:
    #          print(f"Loaded specific yt-dlp module ({SPECIFIC_VERSION}), but could not determine version attribute.")
    # else:
    #     print("Failed to obtain specific version.")