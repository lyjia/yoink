#!/usr/bin/env python3
"""
Generate every icon format Yoink needs from the master docs/icon-1254.png.

Writes:
    yoink/icon.png       the window icon shown while running (commit this)
    dist/icons/yoink.ico Windows executable icon
    dist/icons/yoink.icns macOS app bundle icon

scripts/build.sh runs this before Nuitka, so after editing the master you
only need to commit the regenerated yoink/icon.png.
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MASTER = ROOT / "docs" / "icon-1254.png"
WINDOW_ICON = ROOT / "yoink" / "icon.png"
OUT = ROOT / "dist" / "icons"
WINDOW_SIZE = 256


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with Image.open(MASTER) as master:
        img = master.convert("RGBA")
    assert img.width == img.height, f"{MASTER.name} must be square"

    window = img.resize((WINDOW_SIZE, WINDOW_SIZE), Image.Resampling.LANCZOS)
    # Write only on change so an up-to-date checkout stays clean for --release.
    tmp = WINDOW_ICON.with_suffix(".tmp")
    window.save(tmp, format="PNG", optimize=True)
    if not WINDOW_ICON.exists() or tmp.read_bytes() != WINDOW_ICON.read_bytes():
        tmp.replace(WINDOW_ICON)
    else:
        tmp.unlink()

    # Pillow resamples these to the standard size sets for each format.
    img.save(OUT / "yoink.ico", sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    img.save(OUT / "yoink.icns")
    print(f"Icons: {WINDOW_ICON}, {OUT / 'yoink.ico'}, {OUT / 'yoink.icns'}")


if __name__ == "__main__":
    main()
