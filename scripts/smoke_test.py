#!/usr/bin/env python3
"""
Smoke-test a built Yoink executable: it must start and stay up.

Catches the failures unit tests cannot, such as a missing module, shared
library, or Qt plugin in the Nuitka build. Runs the app under Qt's
offscreen platform, with its settings in a throwaway directory.

Stdlib-only so it runs on every CI runner without an install step.

Usage:
    python scripts/smoke_test.py <path-to-yoink-executable>
"""

import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STARTUP_SECONDS = 15


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("exe", type=Path, help="The built Yoink executable")
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as settings, tempfile.TemporaryFile() as log:
        env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "YOINK_SETTINGS_DIR": settings}
        print(f"$ {args.exe} (offscreen, {STARTUP_SECONDS}s)", flush=True)
        proc = subprocess.Popen([args.exe.resolve()], env=env, stdout=log, stderr=subprocess.STDOUT)
        time.sleep(STARTUP_SECONDS)
        code = proc.poll()
        if code is None:
            proc.kill()
            proc.wait()
            print("Smoke test passed.")
            return 0
        log.seek(0)
        print(log.read().decode(errors="replace"), flush=True)
        print(f"FAIL: Yoink exited during startup with code {code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
