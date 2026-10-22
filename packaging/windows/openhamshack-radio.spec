# -*- mode: python -*-
# PyInstaller spec for OpenHamShack Radio's Windows build: openhamshack-nb.spec's
# twin (read that first - onedir, and why there are two executables), run
# by tools/build-windows.ps1 -App ham with the same OHSNB_VENDOR and
# OHSNB_ICO. A separate file rather than one spec with an app switch, as
# packaging/ already has a openhamshack-radio.* beside each openhamshack-nb.* for the
# .deb: what goes into one app's bundle can then change without touching
# the other's.
#
# The bundle carries its own copy of ohscore, as each .deb does, so the two
# install side by side at different versions.
import os
import sys
from pathlib import Path

sys.path.insert(0, SPECPATH)                       # noqa: F821 - for bundle_prune beside this file
from bundle_prune import without_qt_pdf             # noqa: E402
from bundle_licences import with_licences           # noqa: E402

ROOT = Path(SPECPATH).resolve().parents[1]          # noqa: F821 - SPECPATH is PyInstaller's
VENDOR = Path(os.environ["OHSNB_VENDOR"])
ICO = os.environ["OHSNB_ICO"]

datas = [
    (str(ROOT / "ohsradio" / "VERSION"), "ohsradio"),     # read by the welcome screen
    (str(ROOT / "packaging" / "openhamshack-radio.svg"), "."),
    (ICO, "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "packaging" / "windows" / "THIRD-PARTY.txt"), "."),
    # The noise reduction's gain tables (WDSP's), loaded beside nr.py.
    (str(ROOT / "ohscore" / "dsp" / "nr_tables.npz"), "ohscore/dsp"),
    # AD1C's cty.dat and its notice, beside dxcc.py: see openhamshack-nb.spec.
    (str(ROOT / "ohscore" / "data" / "cty.dat"), "ohscore/data"),
    (str(ROOT / "ohscore" / "data" / "cty.dat-copyright.txt"), "ohscore/data"),
    (str(ROOT / "ohscore" / "data" / "cty-source.txt"), "ohscore/data"),
    # The decode lists' short country names (ohscore/dxcc.py Entity.short).
    (str(ROOT / "ohscore" / "data" / "dxcc-short.json"), "ohscore/data"),
]
datas += [(str(p), "licences") for p in sorted((VENDOR / "licences").glob("*"))]
# The compiled string catalogs, the shared one and this app's, where
# ohscore/i18n looks for them (beside each package); the en_XA pseudo-locale
# is a developer's and never ships.
datas += [(str(p), f"{pkg}/i18n") for pkg in ("ohscore", "ohsradio")
          for p in sorted((ROOT / pkg / "i18n").glob("*.qm")) if not p.stem.endswith("_en_XA")]

# The shared OpenHamShack libraries (band limits, the shared logbook, the
# pad), exactly the pinned wheels, unpacked into the build folder and put
# on the path; ohscore/shacklibs.py imports them by name at run time, so
# every module is named (packaging/shack_vendor.py). And the app's pad
# declaration, which ohscore/ui/padlink.py reads beside the package.
sys.path.insert(0, str(ROOT / "packaging"))
import shack_vendor                                  # noqa: E402
# PyInstaller's build folder when there is one (a test reading the spec has none).
_work = globals().get("workpath") or __import__("tempfile").mkdtemp(prefix="shack-vendor-")
SHACK = shack_vendor.unpack(ROOT, Path(_work) / "shack")
datas += shack_vendor.datas(SHACK)
datas += [(str(ROOT / "ohsradio" / n), "ohsradio") for n in ("pad-actions.json", "pad-layout.json")]
# libiio 0.26's DLLs into _internal\libiio, as data: see openhamshack-nb.spec for why.
datas += [(str(p), "libiio") for p in sorted((VENDOR / "libiio").glob("*.dll"))]
# No WSJT-X since 17/10/2026: see openhamshack-nb.spec.

# The same unmodified codec2/LPCNet DLLs as NB's bundle (FreeDV).
binaries = [(str(p), ".") for p in sorted((VENDOR / "codec2").glob("*.dll"))]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "windows" / "launch-ham.py")],
    pathex=[str(ROOT), str(VENDOR / "py"), str(SHACK)],
    binaries=binaries,
    datas=datas,
    # Imported lazily, inside the device factories, only when the operator
    # picks the device: named so the analysis cannot miss them. The
    # Hermes-Lite 2 needs nothing beyond Python's sockets. paramiko is
    # imported only when the operator runs the Pluto's AD9364 fix
    # (ohsradio/plutofix.py); its own hooks bring cryptography, bcrypt, nacl.
    # ohscore.ohsdigi: the FT8/FT4 encoder, as in openhamshack-nb.spec.
    hiddenimports=shack_vendor.hidden(SHACK) + ["iio", "pyaudio", "ohscore.devices.pluto", "ohscore.devices.hl2", "ohsradio.devices.sim",
                   "ohscore.devices.soapy", "paramiko", "ohscore.ohsdigi",
                   "ohscore.update", "cryptography.hazmat.primitives.asymmetric.ed25519", "hid"],
    # ohsnb is never imported by HAM; excluding it keeps NB's code out of
    # HAM's bundle should anything ever reach for it by accident.
    # PIL is no longer excluded (until 12/10/2026 it was, and the pad's keys
    # could never show a picture on Windows or macOS); "hid" is hidapi, the
    # pad's transport there, which shack_pad imports inside a function.
    excludes=["tkinter", "SoapySDR", "scipy", "matplotlib", "IPython", "ohsnb"],
    noarchive=False,
)
# Qt PDF out (Qt6Pdf.dll, the qpdf plugin): see bundle_prune.py and
# openhamshack-nb.spec.
a.binaries = without_qt_pdf(a.binaries)
a.datas = without_qt_pdf(a.datas)
# Python packages' licence texts into licences/, checked against
# THIRD-PARTY.txt: see openhamshack-nb.spec and bundle_licences.py.
a.datas = with_licences(a, "ham", ROOT / "packaging" / "windows" / "THIRD-PARTY.txt",
                        Path(sys.base_prefix) / "LICENSE.txt")
pyz = PYZ(a.pure)  # noqa: F821

common = dict(exclude_binaries=True, debug=False, strip=False, upx=False, icon=ICO)
gui = EXE(pyz, a.scripts, [], name="openhamshack-radio", console=False, **common)  # noqa: F821
cli = EXE(pyz, a.scripts, [], name="openhamshack-radio-console", console=True, **common)  # noqa: F821

coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name="openhamshack-radio")  # noqa: F821
