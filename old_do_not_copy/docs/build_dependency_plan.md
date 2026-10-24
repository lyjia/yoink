# Plan: Dynamic Stdlib Dependency Discovery for cx_Freeze Build

**Goal:** Dynamically scan the `yt-dlp` source code during the `cx_Freeze` build process to identify required standard library modules and automatically add them to the `includes` option, with caching and version flexibility.

**Revised Plan:**

1.  **Define Cache File:**
    *   **Location:** Create a directory `build_support/` if it doesn't exist.
    *   **File:** Use `build_support/yt-dlp_stdlib_cache.txt`. This file should be added to `.gitignore` initially.
    *   **Format:** Plain text, one standard library module name per line.

2.  **Add Command-Line Argument for Tag:**
    *   Modify `argparse` in `setup.py` to add an optional `--ytdlp-tag <tag>` argument.
    *   If `--ytdlp-tag` is provided, use that specific tag.
    *   If not provided, the script will determine the *latest* release tag from GitHub.

3.  **Refactor Download/Extraction Logic (Prioritizing Reuse):**
    *   **Import:** Attempt to import necessary functions from `util.ytdlp_manager`. If problematic, isolate/duplicate minimal logic in `setup.py` or `build_support`.
    *   **Implement:** Add logic in `setup.py` to determine tag, download source archive, and extract it to temporary directories.

4.  **Implement Caching Read/Write:**
    *   Create `read_stdlib_cache(path)` -> `set` (handles `FileNotFoundError`).
    *   Create `write_stdlib_cache(path, modules)` (overwrites file).

5.  **Adapt Import Scanning Logic:**
    *   Modify `ImportFinder` (optional) for full paths.
    *   Create `find_stdlib_imports(source_dir_path)` -> `set` (scans `.py` files, filters for stdlib modules).

6.  **Integrate Scanning and Caching into Build Flow:**
    *   Define `cache_file_path`.
    *   Determine `target_ytdlp_tag`.
    *   **Try Online Scan:**
        *   Attempt download/extract/scan for `target_ytdlp_tag`.
        *   If successful:
            *   `discovered_modules = result_of_scan`
            *   `write_stdlib_cache(cache_file_path, discovered_modules)`
            *   Log success & cache update.
            *   `modules_to_include = discovered_modules`
    *   **Handle Scan Failure / Fallback to Cache:**
        *   If online scan fails:
            *   Log warning, attempt cache fallback.
            *   `cached_modules = read_stdlib_cache(cache_file_path)`
            *   If `cached_modules` not empty:
                *   Log using cache.
                *   `modules_to_include = cached_modules`
            *   Else (cache empty/missing):
                *   Log error: "Failed to scan dependencies and no cache available."
                *   `modules_to_include = set()` (Proceed with empty includes for now).

7.  **Integrate Results into `cx_Freeze` Options:**
    *   In `build_options`, set `"includes": list(modules_to_include)`.

8.  **Add Cleanup:**
    *   Ensure temporary directories are cleaned up (`try...finally` or context managers).

9.  **Refine `get_stdlib_modules` & Python Version Check:**
    *   Ensure Python >= 3.10 check is present and effective.

**Mermaid Sequence Diagram:**

```mermaid
sequenceDiagram
    participant CLI
    participant BuildProcess as setup.py Execution
    participant CacheFile as build_support/yt-dlp_stdlib_cache.txt
    participant YTDLPManager as util.ytdlp_manager (imported)
    participant GitHub
    participant TempDir
    participant YTDLP_Source as Extracted Source
    participant Scanner as find_stdlib_imports()
    participant CX_Freeze

    CLI->>BuildProcess: Run setup.py (optional --ytdlp-tag=X)
    BuildProcess->>BuildProcess: Determine target_tag (arg or latest via YTDLPManager/GitHub)
    BuildProcess->>BuildProcess: Try Online Scan:
    activate BuildProcess
    BuildProcess->>YTDLPManager: Download Source(target_tag) to TempDir
    alt Download/Extract OK
        YTDLPManager-->>BuildProcess: Extracted source path (YTDLP_Source)
        BuildProcess->>Scanner: Scan(YTDLP_Source path)
        alt Scan OK
            Scanner-->>BuildProcess: discovered_modules (Set)
            BuildProcess->>CacheFile: write_stdlib_cache(discovered_modules)
            BuildProcess->>BuildProcess: modules_to_include = discovered_modules
            BuildProcess->>BuildProcess: Log success & cache update
        else Scan Fails
            BuildProcess->>BuildProcess: Log scan failure, fallback to cache
            deactivate BuildProcess
            BuildProcess->>BuildProcess: Handle Scan Failure:
            activate BuildProcess
            BuildProcess->>CacheFile: cached_modules = read_stdlib_cache()
            alt Cache OK
                 CacheFile-->>BuildProcess: cached_modules (Set)
                 BuildProcess->>BuildProcess: modules_to_include = cached_modules
                 BuildProcess->>BuildProcess: Log using cache
            else Cache Empty/Missing
                 CacheFile-->>BuildProcess: Empty Set / Error
                 BuildProcess->>BuildProcess: Log error: No scan, no cache!
                 BuildProcess->>BuildProcess: modules_to_include = set() # Proceeding with empty
            end
            deactivate BuildProcess
        end
    else Download/Extract Fails
        BuildProcess->>BuildProcess: Log download failure, fallback to cache
        deactivate BuildProcess
        BuildProcess->>BuildProcess: Handle Scan Failure: # Same fallback logic as above
        activate BuildProcess
        BuildProcess->>CacheFile: cached_modules = read_stdlib_cache()
        alt Cache OK
             CacheFile-->>BuildProcess: cached_modules (Set)
             BuildProcess->>BuildProcess: modules_to_include = cached_modules
             BuildProcess->>BuildProcess: Log using cache
        else Cache Empty/Missing
             CacheFile-->>BuildProcess: Empty Set / Error
             BuildProcess->>BuildProcess: Log error: No scan, no cache!
             BuildProcess->>BuildProcess: modules_to_include = set() # Proceeding with empty
        end
        deactivate BuildProcess
    end


    BuildProcess->>CX_Freeze: Define build_options("includes": list(modules_to_include))
    BuildProcess->>CX_Freeze: Run setup()
    CX_Freeze->>BuildProcess: Build completes
    BuildProcess->>TempDir: Clean up temporary files/dirs