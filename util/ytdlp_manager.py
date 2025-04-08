import os
import sys
import requests
import tarfile
import zipfile
import shutil
import importlib.util
from pathlib import Path
import logging

# requirements for yt-dlp
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


def get_source_archive_url(version=DEFAULT_VERSION, releases_api_url=DEFAULT_RELEASES_URL):
    """Fetches the source code archive URL (.tar.gz or .zip) for the specified version."""
    target_release_data = _get_release_data(version, releases_api_url)
    if not target_release_data:
        return None, None # Return None for URL and Tag

    tag_name = target_release_data.get("tag_name")
    assets = target_release_data.get("assets", [])
    source_url_tar = None
    source_url_zip = None

    # Check top-level archive URLs first (common for source)
    source_url_tar = target_release_data.get("tarball_url")
    source_url_zip = target_release_data.get("zipball_url")

    # If not found at top-level, check assets specifically named
    if not source_url_tar and not source_url_zip:
        logging.debug("Source URLs not found at top level, checking assets...")
        for asset in assets:
            name = asset.get("name", "").lower()
            url = asset.get("browser_download_url")
            if url:
                if name == "yt-dlp.tar.gz":
                    source_url_tar = url
                    break # Prefer tar.gz
                elif name == "source code (zip)" or (name.endswith(".zip") and "source" in name):
                    source_url_zip = url # Keep checking for tar.gz

    final_url = source_url_tar or source_url_zip # Prioritize tar.gz

    if not final_url:
        logging.warning(f"Could not find a source code download asset (.tar.gz or .zip) for version '{tag_name}'.")
        return None, tag_name # Return tag even if URL not found

    logging.info(f"Found source download URL for version {tag_name}: {final_url}")
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


def extract_release(archive_path: Path, extract_dir: Path) -> Path | None:
    """
    Extracts a .tar.gz or .zip archive.

    Args:
        archive_path: Path to the archive file.
        extract_dir: Directory where the archive should be extracted.

    Returns:
        Path to the primary extracted content directory (e.g., the folder named
        like 'yt-dlp-TAG') inside extract_dir, or None if extraction fails.
        Does NOT delete the archive file.
    """
    logging.info(f"Extracting {archive_path.name} to {extract_dir}...")
    extracted_content_path = None # Initialize path to return
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        if archive_path.name.endswith(".tar.gz"):
            with tarfile.open(archive_path, "r:gz") as tar:
                # Attempt to find the common top-level directory name
                members = tar.getmembers()
                if members:
                    prefix = os.path.commonprefix([m.name for m in members if m.name])
                    if prefix and ('/' in prefix or '\\' in prefix):
                         top_dir_name = prefix.split('/')[0].split('\\')[0]
                         extracted_content_path = extract_dir / top_dir_name
                    elif prefix: # Handle case where prefix is the only file/dir name
                         extracted_content_path = extract_dir / prefix

                logging.debug(f"Extracting tar.gz to {extract_dir}...")
                # Use filter='data' if available (Python 3.12+) for security
                if sys.version_info >= (3, 12):
                     tar.extractall(path=extract_dir, filter='data')
                else:
                     tar.extractall(path=extract_dir) # Older Python versions

        elif archive_path.name.endswith(".zip"):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                # Attempt to find the common top-level directory name
                namelist = zip_ref.namelist()
                if namelist:
                    prefix = os.path.commonprefix(namelist)
                    if prefix and ('/' in prefix or '\\' in prefix):
                         top_dir_name = prefix.split('/')[0].split('\\')[0]
                         extracted_content_path = extract_dir / top_dir_name
                    elif prefix:
                         extracted_content_path = extract_dir / prefix

                logging.debug(f"Extracting zip to {extract_dir}...")
                zip_ref.extractall(path=extract_dir)
        else:
            logging.error(f"Unsupported archive format: {archive_path.suffix}")
            return None # Return None on failure

        logging.info(f"Successfully extracted {archive_path.name}")
        # Find the actual 'yt_dlp' module directory after extraction
        # If we didn't determine the path via commonprefix, try finding a single dir
        if not extracted_content_path or not extracted_content_path.exists():
             extracted_items = list(extract_dir.iterdir())
             if len(extracted_items) == 1 and extracted_items[0].is_dir():
                  extracted_content_path = extracted_items[0]
             else:
                  # If multiple items or just files, assume content is directly in extract_dir
                  # This might happen if the archive doesn't have a single root folder
                  extracted_content_path = extract_dir
                  logging.warning("Could not determine single top-level extraction dir. Returning base extract dir.")

        return extracted_content_path # Return the path to the extracted content

    except (tarfile.TarError, zipfile.BadZipFile, OSError, EOFError) as e: # Added EOFError
        logging.error(f"Error extracting archive: {e}")
        # Clean up potentially partial extraction
        if extract_dir.exists():
             try:
                  shutil.rmtree(extract_dir)
             except OSError as clean_e:
                  logging.warning(f"Could not clean up extraction directory {extract_dir} on error: {clean_e}")
        return None # Return None on failure
    # *** REMOVED archive deletion from finally block ***
    # finally:
    #     # Clean up the downloaded archive file
    #     if archive_path.exists():
    #         logging.debug(f"Removing archive file: {archive_path}")
    #         os.remove(archive_path) # Changed to archive_path.unlink() if using Path

def _move_and_cleanup_extraction(extract_dir: Path, version_tag: str) -> Path | None:
    """
    Finds the 'yt_dlp' module within an extraction directory, moves it to the
    final versioned location (extract_dir / version_tag / 'yt_dlp'),
    and cleans up intermediate folders.

    Returns:
        Path to the final 'yt_dlp' module directory, or None on failure.
    """
    target_version_dir = extract_dir.parent / version_tag # e.g. .yoink_cache/2023.11.16
    final_module_path = target_version_dir / 'yt_dlp'

    # Find the actual 'yt_dlp' module directory after extraction
    source_module_dir = None
    extracted_items = list(extract_dir.iterdir())

    if len(extracted_items) == 1 and extracted_items[0].is_dir():
        # Likely extracted into a single top-level folder (e.g., yt-dlp-2023.11.16)
        base_search_dir = extracted_items[0]
        potential_module_dir = base_search_dir / 'yt_dlp'
        if potential_module_dir.is_dir() and (potential_module_dir / '__init__.py').is_file():
            source_module_dir = potential_module_dir
        else:
            # Look deeper, e.g., src/yt_dlp
            potential_module_dir = base_search_dir / 'src' / 'yt_dlp'
            if potential_module_dir.is_dir() and (potential_module_dir / '__init__.py').is_file():
                source_module_dir = potential_module_dir
            # Check if yt_dlp.py exists directly (older structure?) - less likely now
            elif (base_search_dir / 'yt_dlp.py').is_file():
                 logging.warning("Found 'yt_dlp.py' file, not package directory. Handling as package source dir.")
                 source_module_dir = base_search_dir # Treat the container dir as source

    elif (extract_dir / 'yt_dlp').is_dir() and (extract_dir / 'yt_dlp' / '__init__.py').is_file():
         # Extracted directly into the target dir (less common for source archives)
         source_module_dir = extract_dir / 'yt_dlp'

    if not source_module_dir:
        logging.error(f"Could not find the 'yt_dlp' module directory within the extracted files in {extract_dir}.")
        return None

    # Ensure target version directory exists
    target_version_dir.mkdir(parents=True, exist_ok=True)

    # Move the found yt_dlp package to the target version directory
    logging.info(f"Moving {source_module_dir} to {final_module_path}")
    try:
        # Use shutil.move for robustness (handles existing dirs if target is empty)
        # If final_module_path exists, shutil.move might raise Error. Remove first.
        if final_module_path.exists():
             logging.warning(f"Removing existing target path {final_module_path} before move.")
             if final_module_path.is_dir():
                  shutil.rmtree(final_module_path)
             else:
                  final_module_path.unlink() # Remove file or symlink

        shutil.move(str(source_module_dir), str(final_module_path))

        # Clean up the original extraction directory structure
        logging.debug(f"Cleaning up extraction directory: {extract_dir}")
        # Remove the now empty parent of the source module dir if it's not the main extract dir
        if source_module_dir.parent != extract_dir and source_module_dir.parent.exists():
             try:
                  # Only remove if empty
                  if not any(source_module_dir.parent.iterdir()):
                       source_module_dir.parent.rmdir()
             except OSError:
                  logging.warning(f"Could not remove empty parent dir: {source_module_dir.parent}")

        # Remove the original top-level extraction folder if it exists and is empty
        if len(extracted_items) == 1 and extracted_items[0].is_dir() and extracted_items[0].exists():
             try:
                  if not any(extracted_items[0].iterdir()):
                       extracted_items[0].rmdir()
             except OSError:
                  logging.warning(f"Could not remove empty top-level extraction dir: {extracted_items[0]}")

        # Optionally remove the base extract_dir itself if empty, but usually the caller handles this.

        logging.info(f"Successfully placed 'yt_dlp' module in {final_module_path.parent}")
        return final_module_path

    except (shutil.Error, OSError) as e:
        logging.error(f"Error moving or cleaning up extracted files: {e}")
        # Attempt to clean up target if move failed partially
        if final_module_path.exists():
             try: shutil.rmtree(final_module_path)
             except OSError: pass
        return None

# (Removed old extraction logic and finally block)


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

    actual_version_tag = None
    download_url = None

    # Resolve version tag and get source URL if needed
    if version == "latest" or force_download:
        logging.info(f"Resolving source URL for version '{version}'...")
        url, tag = get_source_archive_url(version, releases_api_url)
        if not url or not tag:
            logging.error("Failed to resolve download URL or version tag.")
            return None
        download_url = url
        actual_version_tag = tag
        logging.info(f"Resolved '{version}' to version tag '{actual_version_tag}' with URL: {download_url}")
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
    module_path = version_dir / "yt_dlp" # The final package directory path

    # 2. Check if Already Available
    if not force_download and module_path.is_dir() and (module_path / "__init__.py").exists():
        logging.info(f"Found existing yt-dlp version {actual_version_tag} at {module_path}")
    else:
        # 3. Download and Extract if Needed
        logging.info(f"yt-dlp version {actual_version_tag} not found locally or download forced.")

        # Ensure download URL is fetched if not already done (for specific versions)
        # Ensure download URL is fetched if not already done (for specific versions without force_download)
        if not download_url:
             url, tag = get_source_archive_url(actual_version_tag, releases_api_url)
             # Check if the resolved tag matches the requested specific version tag
             if not url or tag != actual_version_tag:
                 logging.error(f"Failed to get source download URL for specific version {actual_version_tag} (Tag mismatch or URL missing).")
                 return None
             download_url = url

        # Prepare download target
        # Use a temporary directory for download and initial extraction
        try:
            with tempfile.TemporaryDirectory(prefix=f"ytdlp_{actual_version_tag}_") as tmpdir:
                tmp_path = Path(tmpdir)
                archive_filename = Path(download_url).name
                download_target_path = tmp_path / archive_filename
                extract_target_dir = tmp_path / "extracted"

        # Clean up potentially incomplete previous attempts for this version
                # Clean up final destination *before* starting download/extract
                if version_dir.exists():
                    logging.warning(f"Removing existing destination directory {version_dir} before download/extraction.")
                    try:
                        shutil.rmtree(version_dir)
                    except OSError as e:
                         logging.error(f"Failed to remove existing directory {version_dir}: {e}")
                         return None
                # version_dir.mkdir(parents=True, exist_ok=True) # Create final dir later

                # Download
                if not download_release(download_url, download_target_path):
                    logging.error("Download failed.")
                    return None # Temp dir will be cleaned up

                # Extract to temporary location
                extracted_content_dir = extract_release(download_target_path, extract_target_dir)
                if not extracted_content_dir:
                    logging.error("Extraction failed.")
                    return None # Temp dir will be cleaned up

                # Remove archive file now that extraction is done
                logging.debug(f"Removing archive file: {download_target_path}")
                try:
                     download_target_path.unlink()
                except OSError:
                     logging.warning(f"Could not remove archive file: {download_target_path}")


                # Move the 'yt_dlp' package from extracted temp location to final version_dir
                final_module_path = _move_and_cleanup_extraction(extracted_content_dir, actual_version_tag)

                if not final_module_path or final_module_path != module_path:
                     logging.error("Failed to move extracted module to final destination.")
                     # Attempt cleanup of version_dir if move failed
                     if version_dir.exists():
                          try: shutil.rmtree(version_dir)
                          except OSError: pass
                     return None

                logging.info(f"Successfully downloaded and processed yt-dlp version {actual_version_tag}")

        except Exception as e:
             logging.error(f"Error during download/extraction process: {e}", exc_info=True)
             # Attempt cleanup of version_dir if process failed
             if version_dir.exists():
                  try: shutil.rmtree(version_dir)
                  except OSError: pass
             return None

        # If we reach here, download/extraction/move was successful


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
        logging.error(f"Failed to import the downloaded yt-dlp module: {e.__class__.__name__} {e}")
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