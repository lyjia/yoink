"""Pre-commit hook: let ruff fix and format the staged files, then re-stage them.

pre-commit fails a commit whenever a hook changes a file, so style fixes would
block every commit until re-staged. Re-adding the files here makes the commit
go through with the fixes in it. Lint errors ruff cannot fix still block.
"""

import subprocess
import sys

# --force-exclude: ruff ignores pyproject's excludes for files named explicitly.
files = ["--force-exclude", *sys.argv[1:]]
code = subprocess.call(["ruff", "check", "--fix", *files])
subprocess.run(["ruff", "format", *files], check=True)
subprocess.run(["git", "add", "--", *sys.argv[1:]], check=True)
sys.exit(code)
