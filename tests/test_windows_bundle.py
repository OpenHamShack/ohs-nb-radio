"""What the Windows bundles leave out - Qt PDF (Qt6Pdf.dll and the qpdf
image-format plugin), from 0.1.4 on - and the licence texts they must
carry: every Python package's, beside the C libraries', matching
THIRD-PARTY.txt.

PyInstaller is not installed here, so each spec is executed as PyInstaller
executes it - as Python with SPECPATH and Analysis/PYZ/EXE/COLLECT in its
globals - with stand-ins for those four. The stand-in Analysis hands back
the kind of TOC the QtGui hook produces on Windows, Qt PDF included; the
test then looks at what the spec actually passes to COLLECT, which is what
lands in the installer. The filter itself (packaging/windows/bundle_prune.py)
is also run directly on the names that must go and the ones that must stay.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
WINDOWS = REPO_ROOT / "packaging" / "windows"
PKG = {"nb": "openhamshack-nb", "ham": "openhamshack-radio"}
# The Python package each app's .qm catalog lives under - ohsnb and
# ohsradio (not "ohsham": Radio's Python package kept its name from
# before the 17/10/2026 package rename; see docs/names.md).
PYDIR = {"nb": "ohsnb", "ham": "ohsradio"}

sys.path.insert(0, str(WINDOWS))
import bundle_licences  # noqa: E402
import bundle_prune  # noqa: E402

THIRD_PARTY = WINDOWS / "THIRD-PARTY.txt"

# Destination names as PyInstaller 6 writes them on Windows (backslashes).
QT_PDF = [
    r"PyQt6\Qt6\bin\Qt6Pdf.dll",
    r"PyQt6\Qt6\bin\Qt6PdfQuick.dll",
    r"PyQt6\Qt6\bin\Qt6PdfWidgets.dll",
    r"PyQt6\Qt6\plugins\imageformats\qpdf.dll",
    r"PyQt6\QtPdf.pyd",
    r"PyQt6\QtPdfWidgets.pyd",
]
NEEDED = [
    r"PyQt6\Qt6\bin\Qt6Core.dll",
    r"PyQt6\Qt6\bin\Qt6Gui.dll",
    r"PyQt6\Qt6\bin\Qt6Widgets.dll",
    r"PyQt6\Qt6\bin\Qt6Network.dll",
    r"PyQt6\Qt6\bin\Qt6Svg.dll",
    r"PyQt6\Qt6\plugins\imageformats\qsvg.dll",
    r"PyQt6\Qt6\plugins\imageformats\qico.dll",
    r"PyQt6\Qt6\plugins\imageformats\qjpeg.dll",
    r"PyQt6\Qt6\plugins\imageformats\qgif.dll",
    r"PyQt6\Qt6\plugins\iconengines\qsvgicon.dll",
    r"PyQt6\Qt6\plugins\platforms\qwindows.dll",
    r"PyQt6\QtGui.pyd",
    r"PyQt6\QtSvg.pyd",
    r"libiio\libiio.dll",
    r"wsjtx\bin\Qt5Core.dll",
    "libcodec2.dll",
]


def toc(names, typecode="BINARY"):
    return [(n, "C:\\src\\" + n, typecode) for n in names]


class Filter(unittest.TestCase):
    def test_takes_out_every_part_of_qt_pdf(self) -> None:
        for name in QT_PDF:
            self.assertTrue(bundle_prune.is_qt_pdf(name), name)
            self.assertTrue(bundle_prune.is_qt_pdf(name.replace("\\", "/")), name)

    def test_keeps_everything_the_programs_use(self) -> None:
        kept = bundle_prune.without_qt_pdf(toc(NEEDED + QT_PDF))
        self.assertEqual([e[0] for e in kept], NEEDED)

    def test_the_mac_build_loses_qt_pdf_under_its_mac_names_too(self) -> None:
        # As PyInstaller 6 collected them for the Mac build (07/10/2026).
        mac_pdf = ["PyQt6/Qt6/lib/QtPdf.framework/Versions/A/QtPdf", "PyQt6/Qt6/lib/QtPdf.framework/QtPdf",
                   "PyQt6/Qt6/plugins/imageformats/libqpdf.dylib", "PyQt6/QtPdf.abi3.so"]
        mac_needed = ["PyQt6/Qt6/lib/QtGui.framework/Versions/A/QtGui", "PyQt6/Qt6/plugins/imageformats/libqsvg.dylib",
                      "PyQt6/Qt6/plugins/imageformats/libqicns.dylib", "PyQt6/QtGui.abi3.so", "libcodec2.dylib"]
        link = ("QtPdf", "PyQt6/Qt6/lib/QtPdf.framework/Versions/A/QtPdf", "SYMLINK")   # the root link to it
        keep_link = ("QtGui", "PyQt6/Qt6/lib/QtGui.framework/Versions/A/QtGui", "SYMLINK")
        kept = bundle_prune.without_qt_pdf(toc(mac_needed + mac_pdf) + [link, keep_link])
        self.assertEqual([e[0] for e in kept], mac_needed + ["QtGui"])


class StandIns:
    """What a spec reads, made up in a scratch folder: the vendor folder
    build-windows.ps1 fills, installed distributions as pip lays them out
    (a .dist-info with METADATA and RECORD), and a Python home with its
    LICENSE.txt. Every licence text THIRD-PARTY.txt names is supplied -
    by a stand-in distribution where the real wheel carries it, in the
    vendor folder otherwise - so a test takes one away to see the build
    stop."""

    # (name, version, top-level modules, licence files in .dist-info) as
    # the real wheels have them on the Windows build machine; pySerial's has none, as 3.5's.
    NB_DISTS = [("numpy", "2.5.3", ["numpy"], ["licenses/LICENSE.txt", "licenses/numpy/ma/LICENSE"]),
                ("PyQt6", "6.11.0", ["PyQt6"], ["licenses/LICENSE"]),
                ("PyQt6-Qt6", "6.11.2", ["PyQt6/Qt6"], ["LICENSE"]),
                ("PyQt6_sip", "13.13.0", ["PyQt6/sip"], ["licenses/LICENSE"]),
                ("PyAudio", "0.2.14", ["pyaudio"], ["LICENSE.txt"]),
                ("pyserial", "3.5", ["serial"], []),
                ("pyinstaller", "6.22.3", ["PyInstaller"], ["licenses/COPYING.txt"]),
                # Both apps from 07/10/2026: the update feed's signature check.
                ("cryptography", "50.0.2", ["cryptography"],
                 ["licenses/LICENSE", "licenses/LICENSE.APACHE", "licenses/LICENSE.BSD"]),
                ("cffi", "2.1.1", ["_cffi_backend.pyd"], ["licenses/LICENSE"]),
                # Both apps from 12/10/2026: the controller pad's HID transport and key pictures.
                ("hidapi", "0.15.0", ["hid.pyd"], ["licenses/LICENSE.txt", "licenses/LICENSE-bsd.txt",
                                                   "licenses/LICENSE-gpl3.txt", "licenses/LICENSE-orig.txt"]),
                ("pillow", "12.3.0", ["PIL"], ["licenses/LICENSE"])]
    HAM_DISTS = [("paramiko", "3.5.1", ["paramiko"], ["LICENSE"]),
                 ("bcrypt", "5.0.0", ["bcrypt"], ["LICENSE"]),
                 ("PyNaCl", "1.6.2", ["nacl"], ["licenses/LICENSE", "licenses/licenses/LICENSE.libsodium.txt"])]
    # Installed but never bundled: a build tool, and cffi's build-time
    # parser (THIRD-PARTY.txt once listed it; the HAM build said otherwise).
    NOT_BUNDLED = [("altgraph", "0.17.5", ["altgraph"], ["LICENSE"]),
                   ("pycparser", "3.0", ["pycparser"], ["licenses/LICENSE"])]

    def __init__(self, root: Path, app: str):
        self.root = root
        self.app = app
        self.vendor = root / "vendor"
        for sub in ("licences", "libiio", "wsjtx/bin", "wsjtx/share/wsjtx", "codec2", "py"):
            (self.vendor / sub).mkdir(parents=True)
        self.ico = self.vendor / f"{PKG[app]}.ico"
        self.ico.write_bytes(b"\0")
        self.python = root / "python"
        self.python.mkdir()
        (self.python / "LICENSE.txt").write_text("PSF licence\n")
        self.site = root / "site"
        self.site.mkdir()
        self.modules = []
        dists = self.NB_DISTS + (self.HAM_DISTS if app == "ham" else []) + self.NOT_BUNDLED
        for name, version, tops, licences in dists:
            self.add_dist(name, version, tops, licences, bundled=(name, version, tops, licences) not in self.NOT_BUNDLED)
        # Everything else THIRD-PARTY.txt names comes from build-windows.ps1.
        provided = {"python-LICENSE.txt"} | {d for d in self.dist_licences()}
        required, _allowed = bundle_licences.references(THIRD_PARTY.read_text(), app)
        for ref in required:
            if not ref.endswith("*") and ref not in provided:
                (self.vendor / "licences" / ref).write_text(f"{ref}\n")

    def add_dist(self, name, version, tops, licences, bundled=True) -> None:
        info = f"{name.replace('-', '_')}-{version}.dist-info"
        files = []
        for top in tops:
            rel = top if top.endswith(".pyd") else f"{top}/__init__.py"
            files.append(rel)
            if bundled:
                self.modules.append(top.split("/")[0].removesuffix(".pyd"))
        files += [f"{info}/{lic}" for lic in licences] + [f"{info}/METADATA", f"{info}/RECORD"]
        for rel in files:
            (self.site / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.site / rel).write_text(f"{name} {rel}\n")
        (self.site / info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
        (self.site / info / "RECORD").write_text("".join(f"{rel},,\n" for rel in files))

    def dist_licences(self):
        for name, _v, _tops, licences in self.NB_DISTS + (self.HAM_DISTS if self.app == "ham" else []):
            for lic in licences:
                parts = lic.split("/")
                if parts[0] == "licenses" and len(parts) > 1:
                    parts = parts[1:]
                yield f"{name}-{'-'.join(parts)}"


class Specs(unittest.TestCase):
    """Each app's spec, run with stand-in PyInstaller classes."""

    def run_spec(self, app: str, prepare=None) -> dict:
        """Execute the spec as PyInstaller would; `prepare(stand_ins)` may
        change what it will find first."""
        captured = {}
        stand_ins = None

        class Analysis:
            def __init__(self, scripts, binaries=(), datas=(), **_kw):
                self.scripts = scripts
                # What PyInstaller's analysis would find imported: the
                # stand-in packages' modules, and the standard library.
                self.pure = [(m, f"C:\\site\\{m}\\__init__.py", "PYMODULE") for m in stand_ins.modules] + [
                    ("json", "C:\\python\\Lib\\json\\__init__.py", "PYMODULE")]
                # And the shared OpenHamShack libraries the spec unpacks and
                # names (packaging/shack_vendor.py), found as PyInstaller
                # finds them: their folder on the path, their dist-info in it.
                for p in _kw.get("pathex", []):
                    if Path(p, "shack_bandplan").is_dir():
                        sys.path.insert(0, p)
                self.pure += [(m, f"C:\\shack\\{m}.py", "PYMODULE") for m in _kw.get("hiddenimports", [])
                              if m.startswith("shack_")]
                # The spec's own binaries and datas, plus what the hooks add.
                self.binaries = list(binaries) + toc(NEEDED + QT_PDF)
                self.datas = [(Path(src).name if dest == "." else f"{dest}\\{Path(src).name}", src, "DATA")
                              for src, dest in datas] + toc(
                    [r"PyQt6\Qt6\translations\qtbase_en.qm", r"PyQt6\Qt6\plugins\imageformats\qpdf.dll"], "DATA")

        def COLLECT(*args, **kw):
            captured["toc"] = [e for a in args if isinstance(a, list) for e in a]
            captured["name"] = kw.get("name")

        with tempfile.TemporaryDirectory() as tmp:
            stand_ins = StandIns(Path(tmp), app)
            if prepare:
                prepare(stand_ins)
            spec = WINDOWS / f"{PKG[app]}.spec"
            env = {"OHSNB_VENDOR": str(stand_ins.vendor), "OHSNB_ICO": str(stand_ins.ico)}
            g = {"__file__": str(spec), "__name__": "__main__", "SPECPATH": str(WINDOWS),
                 "Analysis": Analysis, "PYZ": lambda *a, **k: "pyz", "EXE": lambda *a, **k: "exe",
                 "COLLECT": COLLECT}
            saved_path = list(sys.path)
            try:
                # Only the stand-in packages are "installed": the real ones
                # on this machine (Debian's numpy, PyQt6) must not be seen.
                sys.path[:] = [str(stand_ins.site)] + [p for p in saved_path
                                                        if not p.endswith(("site-packages", "dist-packages"))]
                with mock.patch.dict(os.environ, env), mock.patch.object(sys, "base_prefix", str(stand_ins.python)):
                    exec(compile(spec.read_text(), str(spec), "exec"), g)
            finally:
                sys.path[:] = saved_path
        return captured

    def check(self, app: str) -> None:
        got = self.run_spec(app)
        self.assertEqual(got["name"], PKG[app])
        names = [e[0] for e in got["toc"]]
        for name in QT_PDF:
            self.assertNotIn(name, names)
        for name in NEEDED:
            self.assertIn(name, names)
        self.assertIn(r"PyQt6\Qt6\translations\qtbase_en.qm", names)
        self.assertIn("THIRD-PARTY.txt", names)            # the spec's own data still goes in

    def test_nb_bundle_has_no_qt_pdf(self) -> None:
        self.check("nb")

    def test_ham_bundle_has_no_qt_pdf(self) -> None:
        self.check("ham")

    def test_each_bundle_carries_the_shared_string_catalog_and_its_own(self) -> None:
        # ohscore/i18n loads them from beside each package; without them the
        # window still opens, but English plurals show their "(s)" source.
        for app, other in (("nb", "ham"), ("ham", "nb")):
            names = {e[0] for e in self.run_spec(app)["toc"]}
            self.assertIn("ohscore/i18n\\ohscore_en.qm", names)
            self.assertIn(f"{PYDIR[app]}/i18n\\{PYDIR[app]}_en.qm", names)
            self.assertNotIn(f"{PYDIR[other]}/i18n\\{PYDIR[other]}_en.qm", names)


def licences_in(toc) -> set[str]:
    return {e[0].replace("\\", "/").split("/", 1)[1] for e in toc if e[0].replace("\\", "/").startswith("licences/")}


class Licences(Specs):
    """The packages' licence texts reach licences/, and the build stops
    when licences/ and THIRD-PARTY.txt disagree (bundle_licences.py)."""

    def test_nb_bundles_the_licence_of_every_python_package_it_carries(self) -> None:
        got = licences_in(self.run_spec("nb")["toc"])
        for name in ["python-LICENSE.txt", "pyinstaller-COPYING.txt", "numpy-LICENSE.txt", "numpy-numpy-ma-LICENSE",
                     "PyQt6-LICENSE", "PyQt6-Qt6-LICENSE", "PyQt6_sip-LICENSE", "PyAudio-LICENSE.txt",
                     "pyserial-LICENSE.txt", "cryptography-LICENSE", "cryptography-LICENSE.APACHE",
                     "cryptography-LICENSE.BSD", "cffi-LICENSE", "hidapi-LICENSE.txt", "hidapi-LICENSE-gpl3.txt",
                     "pillow-LICENSE"]:
            self.assertIn(name, got)
        # Installed for HAM or for the build, but not in NB's bundle.
        self.assertFalse({n for n in got if n.startswith(("paramiko-", "bcrypt-", "PyNaCl-", "altgraph-"))})

    def test_ham_bundles_paramiko_and_what_it_needs_too(self) -> None:
        got = licences_in(self.run_spec("ham")["toc"])
        for name in ["paramiko-LICENSE", "cryptography-LICENSE", "cryptography-LICENSE.APACHE",
                     "cryptography-LICENSE.BSD", "bcrypt-LICENSE", "PyNaCl-LICENSE",
                     "PyNaCl-licenses-LICENSE.libsodium.txt", "cffi-LICENSE",
                     "numpy-LICENSE.txt", "PyQt6-LICENSE"]:
            self.assertIn(name, got)
        self.assertNotIn("altgraph-LICENSE", got)
        self.assertNotIn("pycparser-LICENSE", got)

    def test_every_third_party_entry_has_its_licence_in_the_bundle(self) -> None:
        for app in ("nb", "ham"):
            toc = self.run_spec(app)["toc"]
            self.assertEqual(bundle_licences.disagreements(THIRD_PARTY.read_text(), app, toc), [], app)
            required, _ = bundle_licences.references(THIRD_PARTY.read_text(), app)
            shipped = licences_in(toc)
            for ref in required:
                self.assertTrue(any(s == ref or (ref.endswith("*") and s.startswith(ref[:-1])) for s in shipped),
                                f"{app}: licences/{ref}")

    def test_a_licence_named_in_third_party_but_missing_stops_the_build(self) -> None:
        def drop(s): (s.vendor / "licences" / "libusb-COPYING").unlink()
        with self.assertRaises(bundle_licences.LicenceError) as e:
            self.run_spec("nb", drop)
        self.assertIn("licences/libusb-COPYING, which is not in the bundle", str(e.exception))

    def test_a_package_without_an_entry_stops_the_build(self) -> None:
        def newdep(s): s.add_dist("shinything", "1.0", ["shinything"], ["licenses/LICENSE"])
        with self.assertRaises(bundle_licences.LicenceError) as e:
            self.run_spec("nb", newdep)
        self.assertIn("licences/shinything-LICENSE is in the bundle but THIRD-PARTY.txt does not name it",
                      str(e.exception))

    def test_a_package_with_no_licence_text_anywhere_stops_the_build(self) -> None:
        def drop(s): (s.vendor / "licences" / "pyserial-LICENSE.txt").unlink()
        with self.assertRaises(bundle_licences.LicenceError) as e:
            self.run_spec("nb", drop)
        self.assertIn("no licence text for pyserial 3.5", str(e.exception))

    def test_the_shared_libraries_are_bundled_under_the_apps_own_licence(self) -> None:
        # shack-bandplan, -client and -pad are the same author's GPL-3.0
        # code as the program; their wheels carry no licence file and the
        # program's LICENSE covers them, so the check must not demand one.
        for app in ("nb", "ham"):
            got = self.run_spec(app)
            dests = [d for d, _s, kind in got["toc"] if kind == "DATA"]
            self.assertTrue(any(d.replace("\\", "/").startswith("shack_bandplan/") for d in dests), app)
            self.assertFalse(any("licences" in d and "shack" in d for d in dests), app)

    def test_a_ham_only_entry_is_not_required_of_nb(self) -> None:
        required, allowed = bundle_licences.references(THIRD_PARTY.read_text(), "nb")
        self.assertNotIn("paramiko-LICENSE", required)
        self.assertIn("paramiko-LICENSE", allowed)
        required, _ = bundle_licences.references(THIRD_PARTY.read_text(), "ham")
        self.assertIn("paramiko-LICENSE", required)


if __name__ == "__main__":
    unittest.main()
