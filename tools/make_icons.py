"""Generate ``assets/ezrename.ico`` and a PNG logo from the vector mark.

Run this after changing the logo::

    python tools/make_icons.py

The .ico is only needed for the Windows executables and the README, so it is
generated from code rather than being an opaque binary committed by hand.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtCore, QtWidgets

    from ezrename.gui import icons
    from ezrename.gui.theme import ACCENTS

    # A QApplication is required before any pixmap can be rendered.
    if QtWidgets.QApplication.instance() is None:
        QtWidgets.QApplication(["ezrename-icons"])
    accent, accent_dark = ACCENTS["blue"]
    assets = ROOT / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    sizes = (16, 24, 32, 48, 64, 128, 256)
    images: list[tuple[int, bytes]] = []
    for size in sizes:
        pixmap = icons.logo_pixmap(size, accent, accent_dark)
        buffer = QtCore.QBuffer()
        buffer.open(QtCore.QIODevice.WriteOnly)
        pixmap.save(buffer, "PNG")
        images.append((size, bytes(buffer.data())))

    # A PNG-in-ICO container: Windows Vista and later read every entry.
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    payload = b""
    for size, data in images:
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0,
            0,
            1,
            32,
            len(data),
            offset,
        )
        payload += data
        offset += len(data)

    ico = assets / "ezrename.ico"
    ico.write_bytes(header + entries + payload)

    logo = assets / "ezrename-logo.png"
    icons.logo_pixmap(256, accent, accent_dark).save(str(logo), "PNG")

    print(f"wrote {ico} ({ico.stat().st_size // 1024} KB, {len(images)} sizes)")
    print(f"wrote {logo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
