#!/usr/bin/env python3
"""Write an app's .ico (or a Mac's .icns) from the same icon its window uses.

    python tools/make-ico.py [--app nb|ham] out.ico     (nb if not given)
    python tools/make-ico.py [--app nb|ham] out.icns    (on a Mac)

Windows wants an .ico for the .exe, the Start-menu shortcut and the
installer; each app's one icon is packaging/openhamshack-<app>.svg. Rather than
commit a second, binary copy that would drift from the SVG, the Windows
build renders the SVG (through the app's ui.appicon, so with the same
painted fallback the window has if Qt's SVG plugin is missing) at the sizes
Explorer asks for, and packs them as PNG-compressed ICO entries - valid
for every Windows since Vista, and no image library beyond Qt needed.

The Mac build (tools/build-macos.sh) wants an .icns for the .app, the Dock
and Finder. The same renders, at the sizes and @2x names Apple's .iconset
layout asks for, are packed by iconutil, which every Mac has; Qt's own
icns writer stores a single size only.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
# An .iconset's files: icon_<points>x<points>[@2x].png for these point sizes.
ICNS_POINTS = (16, 32, 128, 256, 512)


def png_bytes(pixmap) -> bytes:
    from PyQt6.QtCore import QBuffer, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buf, "PNG")
    return bytes(buf.data())


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    """ICONDIR, one ICONDIRENTRY per image, then the PNGs. A 256 px entry is
    written as 0 in the one-byte width/height fields, as the format says."""
    head = struct.pack("<HHH", 0, 1, len(images))
    offset = len(head) + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        b = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return head + entries + blobs


def write_icns(icon, out: Path) -> list[int]:
    """Render `icon` into a scratch .iconset and pack it with iconutil."""
    import shutil
    import subprocess
    import tempfile
    tool = shutil.which("iconutil")
    if tool is None:
        raise SystemExit("iconutil not found: an .icns can only be made on a Mac")
    sizes = set()
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "app.iconset"
        iconset.mkdir()
        for pt in ICNS_POINTS:
            for scale, suffix in ((1, ""), (2, "@2x")):
                s = pt * scale
                pm = icon.pixmap(s, s)
                if pm.width() != s:
                    pm = pm.scaled(s, s)
                (iconset / f"icon_{pt}x{pt}{suffix}.png").write_bytes(png_bytes(pm))
                sizes.add(s)
        subprocess.run([tool, "-c", "icns", "-o", str(out), str(iconset)], check=True)
    return sorted(sizes)


def main(argv=None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    app_name = "nb"
    if args[:1] == ["--app"] and len(args) >= 2:
        app_name, args = args[1], args[2:]
    if len(args) != 1 or app_name not in ("nb", "ham"):
        print("usage: make-ico.py [--app nb|ham] out.ico|out.icns", file=sys.stderr)
        return 2
    from PyQt6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 - pixmaps need one
    if app_name == "ham":
        from ohsradio.ui.appicon import app_icon
    else:
        from ohsnb.ui.appicon import app_icon
    icon = app_icon()
    if args[0].endswith(".icns"):
        sizes = write_icns(icon, Path(args[0]))
        print(f"wrote {args[0]} ({', '.join(str(s) for s in sizes)} px)")
        return 0
    images = []
    for s in SIZES:
        pm = icon.pixmap(s, s)
        if pm.width() != s:
            pm = pm.scaled(s, s)
        images.append((s, png_bytes(pm)))
    Path(args[0]).write_bytes(build_ico(images))
    print(f"wrote {args[0]} ({', '.join(str(s) for s in SIZES)} px)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
