# -*- mode: python -*-
# PyInstaller spec for the Windows build. Run by tools/build-windows.ps1,
# which sets OHSNB_VENDOR (the folder it fetched libcodec2, the libiio
# bindings and libiio's DLLs into) and OHSNB_ICO (the icon it rendered with tools/make-ico.py).
#
# onedir, not onefile: a onefile .exe unpacks itself into %TEMP% on every
# start - seconds of delay for Qt's size, and a fresh unsigned DLL tree for
# antivirus to scan each time - and the installer has to lay files down
# anyway, so there is nothing for onefile to save.
#
# Two executables share one folder: openhamshack-nb.exe is the windowed program
# the Start menu runs (no console behind it); openhamshack-nb-console.exe is the
# same program with a console, for --headless and for reading what the
# engine prints when something goes wrong. A windowed .exe has no stdout at
# all, so without the second one --headless would run silently.
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
    (str(ROOT / "ohsnb" / "VERSION"), "ohsnb"),       # read by the welcome screen
    (str(ROOT / "packaging" / "openhamshack-nb.svg"), "."),
    (ICO, "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "packaging" / "windows" / "THIRD-PARTY.txt"), "."),
    # The noise reduction's gain tables (WDSP's), loaded beside nr.py.
    (str(ROOT / "ohscore" / "dsp" / "nr_tables.npz"), "ohscore/dsp"),
    # The simulator's multimedia beacon sends this picture (ohsnb/devices/mmbeacon.py).
    (str(ROOT / "ohsnb" / "devices" / "mmb-testcard.jpg"), "ohsnb/devices"),
    # AD1C's cty.dat for the FT8 Country column, beside dxcc.py where it
    # looks (ohscore/data, pinned in cty-source.txt there), with its notice;
    # build-windows.ps1 copies the notice into licences/ as well.
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
datas += [(str(p), f"{pkg}/i18n") for pkg in ("ohscore", "ohsnb")
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
datas += [(str(ROOT / "ohsnb" / n), "ohsnb") for n in ("pad-actions.json", "pad-layout.json")]
# libiio 0.26's DLLs (libiio, libxml2, libusb-1.0, libserialport), unmodified
# from ADI's 0.26 Windows release, into _internal\libiio, where
# ohscore.host.bundled_libiio() points the bindings. A folder of their own so
# nothing else can pick up the bundle's libusb or libxml2 by accident. Given
# as data, not as binaries, on purpose: PyInstaller's binary analysis would
# go looking for libiio.dll's imports itself and may take them from wherever
# it finds them - System32 on a build machine that has ADI's installer -
# or hoist them to the bundle root. As data, the four files from one ADI
# release land side by side exactly as fetched.
datas += [(str(p), "libiio") for p in sorted((VENDOR / "libiio").glob("*.dll"))]
# No WSJT-X (17/10/2026). From 0.1.4 its jt9.exe, ft8code.exe and their
# DLLs went in here as wsjtx\bin, ohsdigi's fallback and shadow; ohsdigi now
# decodes and encodes every slot mode, and a WSJT-X the operator installs
# is still found (ohscore/host.py find_tool), so the installer no longer
# carries ~30 MB of someone else's programs to back it up.

# libcodec2.dll and the liblpcnetfreedv.dll it links against, unmodified
# from FreeDV-GUI's Windows release; ohscore.host.find_library looks for them
# at the bundle's root.
binaries = [(str(p), ".") for p in sorted((VENDOR / "codec2").glob("*.dll"))]

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "windows" / "launch.py")],
    # VENDOR/py holds ADI's pure-Python iio.py (libiio 0.26's bindings); the
    # libiio.dll it loads is the one in _internal\libiio (above).
    pathex=[str(ROOT), str(VENDOR / "py"), str(SHACK)],
    binaries=binaries,
    datas=datas,
    # Imported lazily, inside functions, only when the operator picks the
    # device: name them so the analysis cannot miss them.
    # ohscore.ohsdigi is the FT8/FT4 encoder (rust/ohsdigi), ohsdigi.pyd in
    # ohscore\ (build-windows.ps1 puts it there); ft8.py imports it by name
    # at run time, which the analysis cannot follow. ohscore.update and
    # cryptography's Ed25519 check the update feed's signature; imported
    # inside a function, so named here too - a bundle without them would
    # show it only by never offering an update (build-windows.ps1's smoke
    # test looks for the self-test line at start-up).
    hiddenimports=shack_vendor.hidden(SHACK) + ["iio", "pyaudio", "ohscore.devices.pluto", "ohsnb.devices.sim", "ohscore.devices.soapy",
                   "serial", "serial.tools.list_ports", "ohscore.rig.civ", "ohscore.rig.rigctl", "ohscore.ohsdigi",
                   "ohscore.update", "cryptography.hazmat.primitives.asymmetric.ed25519", "hid"],
    # PIL is no longer excluded (until 12/10/2026 it was, and the pad's keys
    # could never show a picture on Windows or macOS); "hid" is hidapi, the
    # pad's transport there, which shack_pad imports inside a function.
    excludes=["tkinter", "SoapySDR", "scipy", "matplotlib", "IPython"],
    noarchive=False,
)
# Qt PDF out, from 0.1.4: the QtGui hook collects the qpdf image-format
# plugin and with it Qt6Pdf.dll, which neither program uses, and Qt PDF is
# built from Qt WebEngine - carrying it meant hosting the 580 MB
# qtwebengine source beside the installer. By name, after Analysis,
# because no module exclude reaches a plugin; bundle_prune.py has the
# rest, and build-windows.ps1 fails a build where either DLL is back.
a.binaries = without_qt_pdf(a.binaries)
a.datas = without_qt_pdf(a.datas)
# The licence texts of the Python packages actually collected, and of
# Python and PyInstaller, into licences/ beside the C libraries' (which
# build-windows.ps1 fetched); then licences/ must match THIRD-PARTY.txt
# both ways, or the build stops. bundle_licences.py says why and how.
a.datas = with_licences(a, "nb", ROOT / "packaging" / "windows" / "THIRD-PARTY.txt",
                        Path(sys.base_prefix) / "LICENSE.txt")
pyz = PYZ(a.pure)  # noqa: F821

common = dict(exclude_binaries=True, debug=False, strip=False, upx=False, icon=ICO)
gui = EXE(pyz, a.scripts, [], name="openhamshack-nb", console=False, **common)  # noqa: F821
cli = EXE(pyz, a.scripts, [], name="openhamshack-nb-console", console=True, **common)  # noqa: F821

coll = COLLECT(gui, cli, a.binaries, a.datas, strip=False, upx=False, name="openhamshack-nb")  # noqa: F821
