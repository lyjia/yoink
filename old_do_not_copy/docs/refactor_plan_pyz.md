# Refactoring Plan: Use yt-dlp.pyz via zipimport

**Goal:** Refactor the application to use the pre-packaged `yt-dlp.pyz` file from GitHub releases instead of downloading and extracting the source code. This simplifies dependency management for packaging (e.g., with `cx_freeze`) and leverages the platform-independent nature of the `.pyz` file.

**Core Approach:** Modify `util/ytdlp_manager.py` to download the `yt-dlp.pyz` asset and use Python's built-in `zipimport` module to load the `yt_dlp` package directly from the `.pyz` file. Changes to the worker (`workers/download.py`) and UI (`windows/main.py`) should be minimal as the manager will still provide a standard Python module object.

## Phase 1: Refactor `util/ytdlp_manager.py`

1.  **Identify `.pyz` Asset:**
    *   Create a helper function `_find_pyz_asset(release_data)` to locate the `yt-dlp.pyz` asset within the GitHub release data.
    *   Modify `get_pyz_asset_url` (or rename `get_source_archive_url`) to use `_find_pyz_asset` and return the `browser_download_url` and `tag_name` for the `.pyz` file.

2.  **Update `get_ytdlp_module`:**
    *   Keep logic for resolving `version` to `actual_version_tag`.
    *   Define the target cache path: `pyz_path = base_dir / actual_version_tag / "yt-dlp.pyz"`.
    *   Check if `pyz_path.is_file()` exists.
    *   **If Download Needed:**
        *   Ensure parent directory `version_dir` exists (`version_dir.mkdir(parents=True, exist_ok=True)`).
        *   Call `get_pyz_asset_url` to get the download URL.
        *   Use `download_release` to download the `.pyz` file to `pyz_path`. Handle failures.
    *   **Remove Extraction Logic:** Delete `extract_release`, `_move_and_cleanup_extraction`, and related calls/imports (`tarfile`, `zipfile`, `shutil`).
    *   **Implement `zipimport` Loading:** Replace the source loading section (approx. lines 451-501) with:
        ```python
        import zipimport
        import sys # Ensure sys is imported

        if not pyz_path.is_file():
             logging.error(f"Target yt-dlp.pyz file not found at {pyz_path}")
             return None

        try:
            importer = zipimport.zipimporter(str(pyz_path))
            # Load the 'yt_dlp' package from within the .pyz
            ytdlp_module = importer.load_module('yt_dlp')
            logging.info(f"Successfully imported yt-dlp module version {actual_version_tag} from {pyz_path}")
            # Add to sys.modules BEFORE use to handle internal relative imports
            sys.modules["yt_dlp"] = ytdlp_module
            return ytdlp_module
        except (zipimport.ZipImportError, ImportError, Exception) as e:
            logging.error(f"Failed to import yt-dlp module from {pyz_path}: {e}", exc_info=True)
            # Optional: Clean up sys.modules on failure
            if "yt_dlp" in sys.modules:
                 try:
                     del sys.modules["yt_dlp"]
                 except KeyError:
                     pass # Might already be gone
            return None
        ```

3.  **Update `find_available_versions`:** Modify the check to look for `(item / "yt-dlp.pyz").is_file()`.

4.  **Cleanup:** Remove unused imports and functions.

## Phase 2: Testing

1.  Test downloads with 'latest' and specific versions.
2.  Verify UI progress reporting.
3.  Test cancellation.
4.  Check logs for errors.
5.  (Optional) Test cross-platform.

## Diagram

```mermaid
graph TD
    subgraph User Interaction
        A[UI: Initiate Download] --> B{Worker: Start};
    end

    subgraph Worker Logic (workers/download.py)
        B --> C{Load yt-dlp Module};
        C --> D[Call Manager: get_ytdlp_module];
        D --> E{Use Loaded Module};
        E --> F[Instantiate ytdlp.YoutubeDL];
        F --> G[Run ydl.download with progress_hooks];
        G -- Progress Updates --> H[Emit UI Signals];
        G -- Completion/Error --> H;
    end

    subgraph Manager Logic (util/ytdlp_manager.py - Refactored)
        D -- Request Module --> I{get_ytdlp_module};
        I --> J{Resolve Version Tag};
        J --> K{Check Cache for .pyz};
        K -- Not Found/Force --> L[Get .pyz URL from GitHub API];
        L --> M[Download .pyz File];
        M --> N[Save .pyz to Cache];
        K -- Found --> O{Load Module via zipimport};
        N --> O;
        O -- Loaded Module --> D;
        I -- Failure --> D;
    end

    subgraph External
        L --> P[GitHub API];
        M --> P;
    end

    style P fill:#lightblue,stroke:#333,stroke-width:2px