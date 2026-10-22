# -*- mode: python -*-
# PyInstaller spec for the macOS build, "OpenHamShack QO-100 NB.app". Run by
# tools/build-macos.sh on an Apple Silicon Mac, which sets OHSMAC_VENDOR (the
# folder it built and fetched the third-party parts into), OHSMAC_ICNS (the
# icon it rendered with tools/make-ico.py) and OHSMAC_PYLICENCE (Python's own
# LICENSE.txt). Read packaging/windows/openhamshack-nb.spec first: this is its
# twin, and only what differs is explained here.
#
# What is NOT in here, on purpose: libiio and libad9361, and libcodec2.
# build-macos.sh puts those into the finished .app afterwards
# (Contents/Frameworks/libiio, /libcodec2.dylib), then signs the whole
# bundle once: given as data a Mach-O would land in Contents/Resources,
# where code must not live in a signed bundle. libiio is kept in a folder
# of its own for the same reason as on Windows - laid out exactly as built
# - and so the one place that rewrites install names and signs is the
# script, where it can be read. (WSJT-X's jt9, ft8code and q65code went in
# the same way until 17/10/2026, when they were dropped: ohsdigi decodes and
# encodes, and tools/build-macos.sh says why.)
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(SPECPATH).parent / "windows"))  # noqa: F821 - bundle_prune, bundle_licences
from bundle_prune import without_qt_pdf             # noqa: E402
from bundle_licences import with_licences           # noqa: E402

ROOT = Path(SPECPATH).resolve().parents[1]          # noqa: F821 - SPECPATH is PyInstaller's
VENDOR = Path(os.environ["OHSMAC_VENDOR"])
ICNS = os.environ["OHSMAC_ICNS"]
# A labelled build - the macOS preview, "0.1.9+mac-preview.1" - is given its
# own VERSION file by build-macos.sh --preview (OHSMAC_VERSION_FILE), so About
# and the update check say what it is while ohsnb/VERSION keeps naming the
# release for every other platform. Info.plist takes the release part only:
# CFBundleVersion and CFBundleShortVersionString are numbers to macOS.
VERSION_FILE = Path(os.environ.get("OHSMAC_VERSION_FILE") or ROOT / "ohsnb" / "VERSION")
VERSION = VERSION_FILE.read_text().strip()
RELEASE = VERSION.partition("+")[0]

datas = [
    (str(VERSION_FILE), "ohsnb"),
    (str(ROOT / "packaging" / "openhamshack-nb.svg"), "."),
    (str(ROOT / "LICENSE"), "."),
    (str(ROOT / "packaging" / "macos" / "THIRD-PARTY.txt"), "."),
    (str(ROOT / "ohscore" / "dsp" / "nr_tables.npz"), "ohscore/dsp"),
    (str(ROOT / "ohsnb" / "devices" / "mmb-testcard.jpg"), "ohsnb/devices"),
    # AD1C's cty.dat and its notice, beside dxcc.py (see the Windows spec).
    # As data PyInstaller puts them in Contents/Resources and links them
    # into Contents/Frameworks/ohscore/data, where a signed bundle wants data.
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

a = Analysis(  # noqa: F821
    # The Windows launcher: the same `python -m ohsnb` main(), nothing
    # Windows about it.
    [str(ROOT / "packaging" / "windows" / "launch.py")],
    # VENDOR/py: libiio 0.26's own iio.py, from the source it was built from.
    pathex=[str(ROOT), str(VENDOR / "py"), str(SHACK)],
    datas=datas,
    hiddenimports=shack_vendor.hidden(SHACK) + ["iio", "pyaudio", "ohscore.devices.pluto", "ohsnb.devices.sim", "ohscore.devices.soapy",
                   "serial", "serial.tools.list_ports", "ohscore.rig.civ", "ohscore.rig.rigctl", "ohscore.ohsdigi",
                   "ohscore.update", "cryptography.hazmat.primitives.asymmetric.ed25519", "hid"],
    # setuptools is in the build venv only to build PyAudio's sdist (the
    # Windows venv has none); left in, its hooks pull itself and
    # `packaging` into the bundle, which the program never imports.
    # PIL is no longer excluded (until 12/10/2026 it was, and the pad's keys
    # could never show a picture on Windows or macOS); "hid" is hidapi, the
    # pad's transport there, which shack_pad imports inside a function.
    excludes=["tkinter", "SoapySDR", "scipy", "matplotlib", "IPython",
              "setuptools", "pkg_resources", "_distutils_hack"],
    noarchive=False,
)
a.binaries = without_qt_pdf(a.binaries)
a.datas = without_qt_pdf(a.datas)
a.datas = with_licences(a, "nb", ROOT / "packaging" / "macos" / "THIRD-PARTY.txt",
                        Path(os.environ["OHSMAC_PYLICENCE"]))
pyz = PYZ(a.pure)  # noqa: F821

# One executable: on a Mac a windowed program run from Terminal still has
# its stdout, so --headless needs no console twin as on Windows.
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="openhamshack-nb", console=False,  # noqa: F821
          debug=False, strip=False, upx=False, argv_emulation=False, target_arch="arm64",
          codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="openhamshack-nb")  # noqa: F821
app = BUNDLE(  # noqa: F821
    coll,
    name="OpenHamShack QO-100 NB.app",
    icon=ICNS,
    bundle_identifier="com.openhamshack.qo100nb",
    version=RELEASE,
    info_plist={
        # The bundle was "OpenHamShack NB.app", id com.openhamshack-nb, until
        # 17/10/2026, when Brian had everything renamed. A new name means
        # an update dragged into Applications lands beside the old app
        # instead of over it (ohscore/update.py, kind "dmg"): the old copy
        # stays until the operator bins it, and ohscore/rename.py says so in
        # the log. Its settings are this one's by then (rename.py moves
        # the folders), and a new bundle id only means macOS asks for the
        # microphone again, as it already does for every ad-hoc build.
        "CFBundleDisplayName": "OpenHamShack QO-100 NB",
        "CFBundleShortVersionString": RELEASE,
        "CFBundleVersion": RELEASE,
        # Without it macOS gives the program silence for a microphone, with
        # no prompt and no error: transmit audio would be zeros.
        "NSMicrophoneUsageDescription": "OpenHamShack QO-100 NB sends your microphone as the transmitted audio "
                                        "(SSB, FM) and listens to it for the audio level meter.",
        # Without it macOS 15+ (Local Network privacy) silently refuses the
        # socket to a Pluto or LibreSDR on the LAN - no prompt, no error, and
        # libiio's connect fails with "No route to host" - rather than
        # asking the operator once, as it does for the microphone above
        # (found 07/10/2026; ohscore/host.py's local_network_hint names this
        # in the error). NSBonjourServices lets libiio's own mDNS discovery
        # (dns_sd_bonjour.c, compiled in for Apple by default) through the
        # same privacy boundary: libiio 0.26 advertises and browses
        # "_iio._tcp" (checked in its source, packaging/macos/ build area).
        # NB has no Hermes-Lite 2 support (that is HAM's; docs/macos.md), so
        # its sentence names only what it actually opens.
        "NSLocalNetworkUsageDescription": "OpenHamShack QO-100 NB connects to your Pluto or LibreSDR on your local "
                                          "network.",
        "NSBonjourServices": ["_iio._tcp"],
        "NSHighResolutionCapable": True,
        # NumPy 2.5's arm64 wheels need macOS 14; build-macos.sh fails the
        # build if any binary in the bundle needs later than this.
        "LSMinimumSystemVersion": "14.0",
        "LSApplicationCategoryType": "public.app-category.utilities",
        "NSHumanReadableCopyright": "GPL-3.0-or-later. Third-party parts: THIRD-PARTY.txt in Contents/Resources.",
    },
)
