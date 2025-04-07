# Plan: Dynamic Dependency Discovery for yt-dlp in cx_freeze Build

This document outlines the plan to automatically include necessary third-party dependencies required by the dynamically loaded `yt-dlp` module when building the application using `cx_freeze`.

## Problem

The application downloads and loads the `yt-dlp` Python package dynamically at runtime using `ytdlp_manager.py`. Because `yt-dlp` is not directly imported in the application's source code analyzed by `cx_freeze`, its internal dependencies (e.g., `requests`, `certifi`) are not automatically included in the frozen executable. This leads to `ModuleNotFoundError` when the dynamically loaded `yt-dlp` code tries to import its requirements.

## Solution

Modify the `setup.py` script to perform the following steps *before* calling the main `cx_Freeze.setup()` function:

1.  **Fetch Latest Release Info:** Use the GitHub API (`https://api.github.com/repos/yt-dlp/yt-dlp/releases`) to find the URL for the source code archive (`.tar.gz` or `.zip`) of the *latest* `yt-dlp` release.
2.  **Download & Extract:** Download this archive to a temporary directory and extract its contents.
3.  **Locate `yt_dlp` Package:** Identify the `yt_dlp` package directory within the extracted files.
4.  **Analyze Imports:**
    *   Recursively walk through the `yt_dlp` directory.
    *   For each `.py` file, parse its Abstract Syntax Tree (AST) using Python's `ast` module to find all `import` and `from ... import ...` statements.
    *   Collect all unique imported module names.
5.  **Filter Dependencies:**
    *   From the collected set of imported names, remove:
        *   Python standard library modules.
        *   Relative import names (those starting with `.`).
        *   The `yt_dlp` package itself and its submodules (e.g., `yt_dlp.extractor`).
    *   The remaining names represent the required external third-party packages.
6.  **Update Build Options:** Dynamically add the filtered list of package names to the `build_options['packages']` list within `setup.py`.
7.  **Cleanup:** Delete the temporary download and extraction directories.
8.  **Execute `cx_freeze`:** Proceed with the `cx_Freeze.setup()` call. `cx_freeze` will now be aware of the necessary third-party packages and include them in the build, while still excluding the `yt_dlp` package itself (as configured in `build_options['excludes']`).

## Workflow Diagram

```mermaid
graph TD
    A[Start Build: python setup.py build_exe] --> B{Run setup.py};
    subgraph "Pre-cx_freeze Steps in setup.py"
        B --> C[Fetch Latest yt-dlp Source URL];
        C --> D[Download Archive];
        D --> E[Extract Archive to Temp Location];
        E --> F[Find 'yt_dlp' Directory];
        F --> G[Scan *.py files for Imports (using AST)];
        G --> H[Filter Imports (Keep 3rd-Party Only)];
        H --> I[Get List of Dependencies];
        I --> J[Add Dependencies to build_options['packages']];
        E --> K[Cleanup Temp Files];
        K --> J;
    end
    subgraph "cx_freeze Execution"
        J --> L[Call cx_Freeze setup(...)];
        L --> M[Build Executable];
    end
    M --> N[Result: Frozen App + Latest yt-dlp Dependencies];

    style N fill:#ccffcc,stroke:#333,stroke-width:2px
```

## Assumptions

*   The build environment has internet access to download the `yt-dlp` source code.
*   Analyzing the *latest* `yt-dlp` release is desired for dependency discovery.
*   `yt-dlp` does not require non-Python data files beyond those typically handled by its dependencies (like CA certificates via `certifi`).