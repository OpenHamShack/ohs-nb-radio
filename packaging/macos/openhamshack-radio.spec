# -*- mode: python -*-
# PyInstaller spec for OpenHamShack Radio's macOS build, "OpenHamShack Radio.app": the
# twin of openhamshack-nb.spec beside it (read that first), as
# packaging/windows/openhamshack-radio.spec is of NB's there. Only the package,
# its data files, the hidden imports and the bundle's names differ.
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH).parent / "windows"))  # noqa: F821
from bundle_prune import without_qt_pdf             # noqa: E402
from bundle_licences import with_licences           # noqa: E402

ROOT = Path(SPECPATH).resolve().parents[1]          # noqa: F821
VENDOR = Path(os.environ["OHSMAC_VENDOR"])
ICNS = os.environ["OHSMAC_ICNS"]
# A labelled build's own VERSION file: see openhamshack-nb.spec.
VERSION_FILE = Path(os.environ.get("OHSMAC_VERSION_FILE") or ROOT / "ohsradio" / "VERSION")
VERSION = VERSION_FILE.read_text().strip()
RELEASE = VERSION.partition("+")[0]

datas = [
    (str(VERSION_FILE), "ohsradio"),
    (str(ROOT / "packaging" / "openhamshack-radio.svg"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "packaging" / "macos" / "THIRD-PARTY.txt"), "."),
    (str(ROOT / "ohscore" / "dsp" / "nr_tables.npz"), "ohscore/dsp"),
    # AD1C's cty.dat and its notice: see openhamshack-nb.spec beside this one.
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

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "windows" / "launch-ham.py")],
    pathex=[str(ROOT), str(VENDOR / "py"), str(SHACK)],
    datas=datas,
    # As on Windows; the HL2 needs only sockets, paramiko only the AD9364 fix.
    # SoapySDR is not in the first Mac build (docs/macos.md).
    hiddenimports=shack_vendor.hidden(SHACK) + ["iio", "pyaudio", "ohscore.devices.pluto", "ohscore.devices.hl2", "ohsradio.devices.sim",
                   "ohscore.devices.soapy", "paramiko", "ohscore.ohsdigi", "serial", "serial.tools.list_ports",
                   "ohscore.update", "cryptography.hazmat.primitives.asymmetric.ed25519", "hid"],
    # setuptools: build-only, as openhamshack-nb.spec says.
    # PIL is no longer excluded (until 12/10/2026 it was, and the pad's keys
    # could never show a picture on Windows or macOS); "hid" is hidapi, the
    # pad's transport there, which shack_pad imports inside a function.
    excludes=["tkinter", "SoapySDR", "scipy", "matplotlib", "IPython", "ohsnb",
              "setuptools", "pkg_resources", "_distutils_hack"],
    noarchive=False,
)
a.binaries = without_qt_pdf(a.binaries)
a.datas = without_qt_pdf(a.datas)
a.datas = with_licences(a, "ham", ROOT / "packaging" / "macos" / "THIRD-PARTY.txt",
                        Path(os.environ["OHSMAC_PYLICENCE"]))
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="openhamshack-radio", console=False,  # noqa: F821
          debug=False, strip=False, upx=False, argv_emulation=False, target_arch="arm64",
          codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="openhamshack-radio")  # noqa: F821
app = BUNDLE(  # noqa: F821
    coll,
    name="OpenHamShack Radio.app",
    icon=ICNS,
    bundle_identifier="com.openhamshack.radio",
    version=RELEASE,
    info_plist={
        # The bundle was "OpenHamShack HAM.app", id com.openhamshack-ham, until
        # 17/10/2026, when Brian had everything renamed. A new name means
        # an update dragged into Applications lands beside the old app
        # instead of over it (ohscore/update.py, kind "dmg"): the old copy
        # stays until the operator bins it, and ohscore/rename.py says so in
        # the log. Its settings are this one's by then (rename.py moves
        # the folders), and a new bundle id only means macOS asks for the
        # microphone again, as it already does for every ad-hoc build.
        "CFBundleDisplayName": "OpenHamShack Radio",
        "CFBundleShortVersionString": RELEASE,
        "CFBundleVersion": RELEASE,
        "NSMicrophoneUsageDescription": "OpenHamShack Radio sends your microphone as the transmitted audio "
                                        "(SSB, FM) and listens to it for the audio level meter.",
        # Local Network privacy (macOS 15+): see openhamshack-nb.spec for why both
        # keys are here. HAM also opens a Hermes-Lite 2 (ohscore/devices/hl2.py),
        # found over UDP broadcast on port 1024/1025, not mDNS - that needs
        # only the Local Network permission below, no Bonjour service type of
        # its own, because it never asks libiio or dns_sd to browse for one.
        "NSLocalNetworkUsageDescription": "OpenHamShack Radio connects to your Pluto, LibreSDR or Hermes-Lite 2 "
                                          "on your local network.",
        "NSBonjourServices": ["_iio._tcp"],
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "14.0",
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHumanReadableCopyright": "GPL-3.0-or-later. Third-party parts: THIRD-PARTY.txt in Contents/Resources.",
    },
)
