"""The pinned shared libraries (tools/vendor) into a package build.

Since M3 both apps import ohs-libs' shack_bandplan (band limits and
transmit permission), shack_client (the shared logbook, pairing),
shack_pad (the pad) and shack_cw (the CW decoder, since 10/10/2026) at run
time, so every package must carry them: the
.deb beside ohscore, and the frozen builds (Windows, macOS, AppImage) on
PyInstaller's path with their data files. A checkout finds them through
ohscore/shacklibs.py instead.

Since Radio's SDR milestone 1 they also carry shack_sdr (the decoder host
and the Rust RTTY decoder both apps' RTTY mode now uses, the codec loader,
the RTL-SDR and SDRplay sources). It is the one wheel with native code, so
there is one per platform (tools/vendor/shack-sdr.lock) and a build names
the platform it is for: the .deb its architecture, a frozen build the
machine it runs on (PyInstaller builds natively). A platform with no
pinned wheel - macOS, until its universal2 build is pinned - stops the
build with a sentence; it never quietly ships a Radio that cannot decode
RTTY.

Each wheel is checked against the locks (tools/vendor/requirements.lock,
shack-sdr.lock) before it is unpacked, as the store image does: a build
never ships a library the lock does not pin. Wheels are zips with nothing
to run at install, so unpacking is installing.

    python3 packaging/shack_vendor.py <dest> [<platform>]    # the .deb (build-deb.sh): linux_x86_64 ...
    python3 packaging/shack_vendor.py --check-encumbered <path>...

The second is the build-time check that no installer carries, links or
defines an encumbered library (RADIO-SDR-PLAN 5.5): ohs-libs'
check-encumbered.py and its denylist, vendored in tools/vendor/encumbered
and hash-checked here before they run.

and from a PyInstaller spec:

    sys.path.insert(0, str(ROOT / "packaging"))
    import shack_vendor
    path = shack_vendor.unpack(ROOT, Path(workpath) / "shack")
    datas += shack_vendor.datas(path); hiddenimports += shack_vendor.hidden(path)
"""
from __future__ import annotations

import hashlib
import platform as _platform
import re
import subprocess
import sys
import zipfile
from pathlib import Path

RUNTIME = ("shack_bandplan", "shack_client", "shack_pad", "shack_cw", "shack_sdr")
LOCKS = ("requirements.lock", "shack-sdr.lock")
# Native code inside the runtime packages (shack_sdr's _native). Never
# collected as data: named as a hidden import instead (hidden()), so
# PyInstaller's analysis finds it on the unpacked folder the specs put in
# pathex and collects it as the extension module it is - with its
# dependencies, and signed with the rest of the bundle on macOS.
NATIVE = (".so", ".pyd", ".dylib")


def pins(root: Path) -> dict[str, set[str]]:
    """{distribution name with underscores: the sha256s pinned for it}."""
    out: dict[str, set[str]] = {}
    for lock in LOCKS:
        f = Path(root) / "tools" / "vendor" / lock
        if not f.is_file():
            continue
        for line in f.read_text().splitlines():
            m = re.match(r"^([A-Za-z0-9_.-]+)==\S+\s+--hash=sha256:([0-9a-f]{64})", line.strip())
            if m:
                out.setdefault(m.group(1).replace("-", "_"), set()).add(m.group(2))
    return out


def platform_tag(system: str | None = None, machine: str | None = None) -> str:
    """The machine a build is for, as wheel tags name it (the same rule as
    ohscore/shacklibs.py, which a build cannot import before it has
    unpacked the libraries this module unpacks)."""
    system = (system or sys.platform).lower()
    machine = (machine or _platform.machine()).lower()
    if system.startswith("win"):
        return "win_amd64"
    if system == "darwin":
        return "macosx"
    return "linux_" + {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)


def runs_on(wheel_name: str, tag: str) -> bool:
    plat = wheel_name[:-len(".whl")].rsplit("-", 1)[-1] if wheel_name.endswith(".whl") else ""
    for t in plat.split("."):
        if t == "any":
            return True
        if tag.startswith("linux_") and t.startswith(("manylinux", "musllinux", "linux")):
            if t.endswith("_" + tag[len("linux_"):]):
                return True
        elif tag == "macosx" and t.startswith("macosx"):
            return True
        elif t == tag:
            return True
    return False


def unpack(root: Path, dest: Path, platform: str | None = None) -> Path:
    """Unpack the runtime wheels for `platform` (platform_tag(): this
    machine when None; "pure": only the wheels that run anywhere) into
    `dest` (created); returns it."""
    root, dest = Path(root), Path(dest)
    tag = platform or platform_tag()
    dest.mkdir(parents=True, exist_ok=True)
    want = pins(root)
    for name in RUNTIME:
        wheels = [w for w in sorted((root / "tools" / "vendor").glob(f"{name}-*.whl")) if runs_on(w.name, tag)]
        if not wheels and tag == "pure":
            continue    # a package for any machine (the .deb's "all") carries no native wheel
        if not wheels and name == "shack_sdr":
            raise SystemExit(f"shack_vendor: no shack_sdr wheel for {tag} is pinned in tools/vendor/shack-sdr.lock. "
                             f"Build it in ohs-libs (tools/build-sdr-wheels.sh; macOS on the Mac mini), pin it "
                             f"and vendor it first: without it this build could not decode RTTY.")
        if len(wheels) != 1:
            raise SystemExit(f"shack_vendor: expected one {name} wheel for {tag} in tools/vendor, found {len(wheels)}")
        got = hashlib.sha256(wheels[0].read_bytes()).hexdigest()
        if got not in want.get(name, set()):
            raise SystemExit(f"shack_vendor: {wheels[0].name} is not a wheel the locks in tools/vendor pin")
        with zipfile.ZipFile(wheels[0]) as z:
            z.extractall(dest)
    return dest


def encumbered(root: Path, paths, *, skip=(), python: str | None = None) -> int:
    """Run the vendored encumbered check over `paths`; its exit status (0
    clean). `skip` drops denylist patterns from the files and libraries the
    check refuses - only store/radio's SDRplay API while the image must
    still carry it (store-check.sh says when) - never the codecs."""
    root = Path(root)
    folder = root / "tools" / "vendor" / "encumbered"
    lock = (root / "tools" / "vendor" / "shack-sdr.lock").read_text()
    for f in ("check-encumbered.py", "encumbered.json"):
        m = re.search(rf"^encumbered/{re.escape(f)} sha256:([0-9a-f]{{64}})", lock, re.M)
        if not m or hashlib.sha256((folder / f).read_bytes()).hexdigest() != m.group(1):
            raise SystemExit(f"shack_vendor: tools/vendor/encumbered/{f} is not the copy shack-sdr.lock pins")
    spec = folder / "encumbered.json"
    if skip:
        import json
        import tempfile
        data = json.loads(spec.read_text())
        for key in ("files", "libraries", "symbols"):
            data[key] = [p for p in data[key] if p not in skip]
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(data, tmp)
        tmp.close()
        spec = Path(tmp.name)
    try:
        return subprocess.call([python or sys.executable, str(folder / "check-encumbered.py"), "--spec", str(spec),
                                *[str(p) for p in paths]])
    finally:
        if skip:
            spec.unlink(missing_ok=True)


def datas(path: Path) -> list[tuple[str, str]]:
    """Every non-Python, non-native file of the runtime packages, as
    PyInstaller datas."""
    out = []
    for name in RUNTIME:
        for p in sorted((Path(path) / name).rglob("*")):
            if (p.is_file() and p.suffix not in (".py", ".pyc") + NATIVE and "__pycache__" not in p.parts):
                out.append((str(p), str(p.parent.relative_to(path))))
    return out


def hidden(path: Path) -> list[str]:
    """Every module of the runtime packages, native ones included:
    ohscore/shacklibs.py imports them by name at run time, which
    PyInstaller's analysis cannot see."""
    out = []
    for name in RUNTIME:
        for p in sorted((Path(path) / name).rglob("*")):
            if not p.is_file() or not (p.suffix == ".py" or p.suffix in NATIVE):
                continue
            rel = p.relative_to(path)
            parts = list(rel.parts)
            parts[-1] = parts[-1].split(".")[0]      # _native.abi3.so -> _native
            if parts[-1] == "__init__":
                parts = parts[:-1]
            if "tests" not in parts:
                out.append(".".join(parts))
    return out


if __name__ == "__main__":
    _root = Path(__file__).resolve().parent.parent
    if sys.argv[1:2] == ["--check-encumbered"]:
        sys.exit(encumbered(_root, sys.argv[2:]))
    unpack(_root, Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else None)
