"""The shared OpenHamShack libraries (ohs-libs) where both apps need them:
shack_bandplan (band limits and transmit permission from the station
profile), shack_client (the local logbook and station profile, pairing and
sync with a controller), shack_pad (the AKP03E controller), shack_cw (the
CW decoder and Morse tables, which began in ohscore and moved there so Icom
and Flex share them) and shack_rec (recordings on the controller, for the
store form's server only).

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

The hash is checked against tools/vendor/requirements.lock before
unpacking: a wheel that is not the pinned one is refused rather than run.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "tools" / "vendor"
LOCK = "requirements.lock"


class SharedLibraryMissing(ImportError):
    """A shared library is neither installed nor vendored: a broken
    install, never a normal state (the band check needs shack_bandplan)."""


def _cache() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "openhamshack" / "wheels"


def _pinned(folder: Path) -> dict[str, str]:
    """{wheel distribution name with underscores: sha256} from the lock."""
    out = {}
    try:
        text = (folder / LOCK).read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)==\S+\s+--hash=sha256:([0-9a-f]{64})", line.strip())
        if m:
            out[m.group(1).replace("-", "_")] = m.group(2)
    return out


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
    pinned wheel in tools/vendor. Raises SharedLibraryMissing when neither
    has it or the wheel is not the pinned one."""
    try:
        return importlib.import_module(name)
    except ImportError:
        pass
    folder = vendor or VENDOR
    wheels = sorted(folder.glob(f"{name}-*.whl")) if folder.is_dir() else []
    if not wheels:
        raise SharedLibraryMissing(f"{name} is not installed and not in {folder}")
    wheel = wheels[-1]
    want = _pinned(folder).get(name)
    got = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if want != got:
        raise SharedLibraryMissing(f"{wheel.name} is not the wheel {LOCK} pins")
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
