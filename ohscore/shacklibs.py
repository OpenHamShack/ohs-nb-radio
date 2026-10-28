"""The shared OpenHamShack libraries (ohs-libs) where both apps need them:
shack_bandplan (band limits and transmit permission from the station
profile), shack_client (the local logbook and station profile, pairing and
sync with a controller), shack_pad (the AKP03E controller), shack_cw (the
CW decoder and Morse tables, which began in ohscore and moved there so Icom
and Flex share them), shack_rec (recordings on the controller, for the
store form's server only), shack_spectrum (the spectrum/1 encoder behind
api/spectrum/v1, also the store form's server only) and shack_sdr (the
decoder host, the Rust RTTY decoder, the codec loader and the RTL-SDR and
SDRplay sources).

Every package form unpacks the pinned wheels beside ohscore (tools/build-deb.sh,
build-windows.ps1, build-macos.sh, the store Containerfile), so there an
import just works. A checkout - the test suite, a developer running
`python3 -m ohsnb` - has the same wheels vendored in tools/vendor (REPO-LAYOUT
4: exact pins with hashes, one commit per bump), and this unpacks them into
a cache folder once and puts them on sys.path.

Unpacked rather than imported from the zip as tools/i18n.py does with the
string check: shack-bandplan reads its dataset beside its own __file__,
which a zipped import has no folder for. The folder is named after the
wheel's SHA-256, so a new pin is a new folder and an old one is never
half-reused. The same scheme as the QO-100 WB app's
appliance/openhamshacklib/shacklibs.py, so one cache serves every app on a
developer's machine.

The hash is checked against the lock before unpacking: a wheel that is
not the pinned one is refused rather than run.

shack_sdr is the one wheel with native code in it, so it comes once per
platform (tools/vendor/shack-sdr.lock, a line for each) and the wheel for
this machine is the one whose tag names its OS and architecture. The
pure wheels' tag (py3-none-any) runs anywhere, so they need no choice.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import platform
import re
import sys
import tempfile
import zipfile
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "tools" / "vendor"
LOCK = "requirements.lock"
# Every lock whose lines are `name==version --hash=sha256:...`: the pure
# wheels', and shack-sdr's with one line per platform.
LOCKS = (LOCK, "shack-sdr.lock")


class SharedLibraryMissing(ImportError):
    """A shared library is neither installed nor vendored: a broken
    install, never a normal state (the band check needs shack_bandplan)."""


def _cache() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "openhamshack" / "wheels"


def _pinned(folder: Path) -> dict[str, set[str]]:
    """{wheel distribution name with underscores: its pinned sha256s} from
    the locks (more than one for a wheel built per platform)."""
    out: dict[str, set[str]] = {}
    for lock in LOCKS:
        try:
            text = (folder / lock).read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            m = re.match(r"^([A-Za-z0-9_.-]+)==\S+\s+--hash=sha256:([0-9a-f]{64})", line.strip())
            if m:
                out.setdefault(m.group(1).replace("-", "_"), set()).add(m.group(2))
    return out


def platform_tag(system: str | None = None, machine: str | None = None) -> str:
    """This machine as wheel tags name it: "linux_x86_64", "linux_aarch64",
    "win_amd64", "macosx" (every macOS wheel we pin is universal2)."""
    system = (system or sys.platform).lower()
    machine = (machine or platform.machine()).lower()
    if system.startswith("win"):
        return "win_amd64"
    if system == "darwin":
        return "macosx"
    return "linux_" + {"amd64": "x86_64", "arm64": "aarch64"}.get(machine, machine)


def runs_on(wheel_name: str, tag: str) -> bool:
    """Whether a wheel file's platform tag suits `tag` (platform_tag())."""
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


def _unpack(wheel: Path, digest: str) -> Path:
    tmp_root = Path(tempfile.gettempdir()) / f"openhamshack-wheels-{getattr(os, 'getuid', lambda: 0)()}"
    for root in (_cache(), tmp_root):
        dest = root / f"{wheel.stem}-{digest[:16]}"
        if (dest / ".complete").is_file():
            return dest
        try:
            root.mkdir(parents=True, exist_ok=True)
            tmp = Path(tempfile.mkdtemp(prefix=".unpack-", dir=root))
            with zipfile.ZipFile(wheel) as z:
                z.extractall(tmp)
            (tmp / ".complete").write_text(wheel.name)
            try:
                tmp.rename(dest)
            except OSError:
                pass        # another process got there first; theirs is complete
            if (dest / ".complete").is_file():
                return dest
        except OSError:
            continue
    raise OSError(f"could not unpack {wheel.name}")


def load(name: str, vendor: Path | None = None):
    """The module `name` (e.g. "shack_bandplan"): installed, else from the
    pinned wheel in tools/vendor for this machine. Raises
    SharedLibraryMissing when neither has it, when no vendored wheel is
    built for this platform, or when the wheel is not the pinned one."""
    try:
        return importlib.import_module(name)
    except ImportError:
        pass
    folder = vendor or VENDOR
    wheels = sorted(folder.glob(f"{name}-*.whl")) if folder.is_dir() else []
    if not wheels:
        raise SharedLibraryMissing(f"{name} is not installed and not in {folder}")
    tag = platform_tag()
    mine = [w for w in wheels if runs_on(w.name, tag)]
    if not mine:
        raise SharedLibraryMissing(f"{name} has no wheel for this platform ({tag}) in {folder}")
    wheel = mine[-1]
    got = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if got not in _pinned(folder).get(name, set()):
        raise SharedLibraryMissing(f"{wheel.name} is not a wheel the locks in {folder.name}/ pin")
    path = str(_unpack(wheel, got))
    if path not in sys.path:
        sys.path.append(path)
    return importlib.import_module(name)


def bandplan():
    return load("shack_bandplan")


def client():
    return load("shack_client")


def pad():
    return load("shack_pad")


def cw():
    return load("shack_cw")


def rec():
    return load("shack_rec")


def spectrum():
    return load("shack_spectrum")


def sdr():
    return load("shack_sdr")
