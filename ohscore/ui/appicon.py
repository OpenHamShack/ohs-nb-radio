"""Finding and loading an app's icon: the same SVG its package installs.

One file, packaging/<app>.svg, is both the desktop icon and the window
icon. Installed, it is under share/icons/hicolor next to the lib directory
the launcher puts on PYTHONPATH; from a source tree it is in packaging/; in
the Windows build it sits in the frozen bundle beside an <app>.ico made
from it (the .ico is what Explorer and the Start menu show; Qt reads either,
so the .ico is the fallback should the SVG plugin be missing there). If none
is found, or this Qt has no SVG image plugin (qt6-svg-plugins), the app's
simplified painted version stands in rather than a blank square.

The searching is shared; the artwork - the file's name and the painted
stand-in - is each app's (ohsnb/ui/appicon.py for QO-100 NB).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtGui import QIcon, QPixmap

from .. import host


def find(name: str, pkg_dir: Path) -> Path | None:
    """The icon file for app `name` (e.g. "openhamshack-nb") whose Python
    package is the directory `pkg_dir` (e.g. .../ohsnb)."""
    bundle = host.bundle_dir()
    cands = [bundle / f"{name}.svg", bundle / f"{name}.ico"] if bundle is not None else []
    cands += [pkg_dir.parent / "packaging" / f"{name}.svg",
              # /usr/lib/<app>/<pkg> -> /usr/share/icons/...
              pkg_dir.parents[2] / "share" / "icons" / "hicolor" / "scalable" / "apps" / f"{name}.svg",
              Path(f"/usr/share/icons/hicolor/scalable/apps/{name}.svg")]
    return next((c for c in cands if c.is_file()), None)


def load(path: Path | None, painted: Callable[[int], QPixmap]) -> QIcon:
    """The icon at `path`, or one built from `painted(size)` if there is no
    file or this Qt cannot read it."""
    if path is not None:
        ic = QIcon(str(path))
        if not ic.isNull() and not ic.pixmap(32, 32).isNull():
            return ic
    ic = QIcon()
    for s in (16, 32, 48, 64, 128, 256):
        ic.addPixmap(painted(s))
    return ic


def pixmap(icon: QIcon, size: int, dpr: float = 1.0) -> QPixmap:
    pm = icon.pixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    return pm
