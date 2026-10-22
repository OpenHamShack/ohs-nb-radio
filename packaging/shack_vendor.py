"""The pinned shared libraries (tools/vendor) into a package build.

Since M3 both apps import ohs-libs' shack_bandplan (band limits and
transmit permission), shack_client (the shared logbook, pairing),
shack_pad (the pad) and shack_cw (the CW decoder, since 10/10/2026) at run
time, so every package must carry them: the
.deb beside ohscore, and the frozen builds (Windows, macOS, AppImage) on
PyInstaller's path with their data files. A checkout finds them through
ohscore/shacklibs.py instead.

Each wheel is checked against tools/vendor/requirements.lock before it is
unpacked, as the store image does: a build never ships a library the lock
does not pin. Wheels are zips of pure Python with data beside it, so
unpacking is installing.

    python3 packaging/shack_vendor.py <dest>       # the .deb (build-deb.sh)

and from a PyInstaller spec:

    sys.path.insert(0, str(ROOT / "packaging"))
    import shack_vendor
    path = shack_vendor.unpack(ROOT, Path(workpath) / "shack")
    datas += shack_vendor.datas(path); hiddenimports += shack_vendor.hidden(path)
"""
from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from pathlib import Path

RUNTIME = ("shack_bandplan", "shack_client", "shack_pad", "shack_cw")


def pins(root: Path) -> dict[str, str]:
    out = {}
    for line in (root / "tools" / "vendor" / "requirements.lock").read_text().splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==\S+\s+--hash=sha256:([0-9a-f]{64})", line.strip())
        if m:
            out[m.group(1).replace("-", "_")] = m.group(2)
    return out


def unpack(root: Path, dest: Path) -> Path:
    """Unpack the runtime wheels into `dest` (created); returns it."""
    root, dest = Path(root), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    want = pins(root)
    for name in RUNTIME:
        wheels = sorted((root / "tools" / "vendor").glob(f"{name}-*.whl"))
        if len(wheels) != 1:
            raise SystemExit(f"shack_vendor: expected one {name} wheel in tools/vendor, found {len(wheels)}")
        got = hashlib.sha256(wheels[0].read_bytes()).hexdigest()
        if want.get(name) != got:
            raise SystemExit(f"shack_vendor: {wheels[0].name} is not the wheel requirements.lock pins")
        with zipfile.ZipFile(wheels[0]) as z:
            z.extractall(dest)
    return dest


def datas(path: Path) -> list[tuple[str, str]]:
    """Every non-Python file of the runtime packages, as PyInstaller datas."""
    out = []
    for name in RUNTIME:
        for p in sorted((Path(path) / name).rglob("*")):
            if p.is_file() and p.suffix not in (".py", ".pyc") and "__pycache__" not in p.parts:
                out.append((str(p), str(p.parent.relative_to(path))))
    return out


def hidden(path: Path) -> list[str]:
    """Every module of the runtime packages: ohscore/shacklibs.py imports
    them by name at run time, which PyInstaller's analysis cannot see."""
    out = []
    for name in RUNTIME:
        for p in sorted((Path(path) / name).rglob("*.py")):
            rel = p.relative_to(path).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if "tests" not in parts:
                out.append(".".join(parts))
    return out


if __name__ == "__main__":
    unpack(Path(__file__).resolve().parent.parent, Path(sys.argv[1]))
