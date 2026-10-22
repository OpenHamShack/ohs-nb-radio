"""The macOS specs (packaging/macos/<package>.spec): the .app each one
asks PyInstaller for - its name, bundle id, version and the Info.plist
keys without which macOS silences the microphone - and its licence texts,
which must agree with packaging/macos/THIRD-PARTY.txt both ways, as the
Windows bundle's do with its own (bundle_licences.py).

Run as tests/test_windows_bundle.py runs the Windows specs: executed as
PyInstaller would, with stand-ins for Analysis, PYZ, EXE, COLLECT and
BUNDLE, so they run on any system; tools/build-macos.sh runs them for
real on a Mac.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Functions and plain classes only: a TestCase imported here would run twice.
from test_windows_bundle import StandIns, toc

REPO_ROOT = Path(__file__).resolve().parent.parent
MACOS = REPO_ROOT / "packaging" / "macos"
PKG = {"nb": "openhamshack-nb", "ham": "openhamshack-radio"}
# The Python package each app's VERSION file and .qm catalog live under -
# ohsnb and ohsradio (not "ohsham": Radio's Python package kept its name
# from before the 17/10/2026 package rename; see docs/names.md).
PYDIR = {"nb": "ohsnb", "ham": "ohsradio"}
THIRD_PARTY = MACOS / "THIRD-PARTY.txt"
sys.path.insert(0, str(REPO_ROOT / "packaging" / "windows"))
import bundle_licences  # noqa: E402


class MacStandIns(StandIns):
    """StandIns, with the vendor folder build-macos.sh fills: every licence
    text the Mac's THIRD-PARTY.txt names that no stand-in wheel supplies."""

    def __init__(self, root: Path, app: str):
        super().__init__(root, app)
        self.icns = self.vendor / f"{PKG[app]}.icns"
        self.icns.write_bytes(b"icns")
        provided = {"python-LICENSE.txt"} | set(self.dist_licences())
        required, _ = bundle_licences.references(THIRD_PARTY.read_text(), app)
        for ref in required:
            if ref.endswith("*"):
                ref = ref[:-1] + "stand-in"
            if ref not in provided and not (self.vendor / "licences" / ref).exists():
                (self.vendor / "licences" / ref).write_text(f"{ref}\n")
        # StandIns filled the folder for the Windows THIRD-PARTY.txt too;
        # the Mac has no libusb, winpthreads or PlutoSDR drivers, so the
        # texts its list does not name go (build-macos.sh never fetches them).
        _, allowed = bundle_licences.references(THIRD_PARTY.read_text(), app)
        for f in (self.vendor / "licences").iterdir():
            if not any(f.name == a or (a.endswith("*") and f.name.startswith(a[:-1])) for a in allowed):
                f.unlink()


def run_spec(app: str, env_extra: dict | None = None) -> dict:
    captured = {}
    stand_ins = None

    class Analysis:
        def __init__(self, scripts, binaries=(), datas=(), **_kw):
            self.scripts = scripts
            self.pure = [(m, f"/site/{m}/__init__.py", "PYMODULE") for m in stand_ins.modules]
            self.binaries = list(binaries) + toc(["PyQt6/Qt6/lib/QtCore.framework/QtCore"])
            self.datas = [(Path(src).name if dest == "." else f"{dest}/{Path(src).name}", src, "DATA")
                          for src, dest in datas]

    def COLLECT(*args, **kw):
        captured["toc"] = [e for a in args if isinstance(a, list) for e in a]
        # The bundled VERSION file's text, read while its source still exists.
        captured["version_file"] = next((Path(src).read_text().strip() for name, src, _ in captured["toc"]
                                         if name == f"{PYDIR[app]}/VERSION"), None)

    def BUNDLE(coll, **kw):
        captured["bundle"] = kw

    with tempfile.TemporaryDirectory() as tmp:
        stand_ins = MacStandIns(Path(tmp), app)
        spec = MACOS / f"{PKG[app]}.spec"
        env = {"OHSMAC_VENDOR": str(stand_ins.vendor), "OHSMAC_ICNS": str(stand_ins.icns),
               "OHSMAC_PYLICENCE": str(stand_ins.python / "LICENSE.txt"), **(env_extra or {})}
        g = {"__file__": str(spec), "__name__": "__main__", "SPECPATH": str(MACOS), "Analysis": Analysis,
             "PYZ": lambda *a, **k: "pyz", "EXE": lambda *a, **k: "exe", "COLLECT": COLLECT, "BUNDLE": BUNDLE}
        saved_path = list(sys.path)
        try:
            sys.path[:] = [str(stand_ins.site)] + [p for p in saved_path
                                                    if not p.endswith(("site-packages", "dist-packages"))]
            with mock.patch.dict(os.environ, env):
                exec(compile(spec.read_text(), str(spec), "exec"), g)
        finally:
            sys.path[:] = saved_path
    return captured


class MacSpecs(unittest.TestCase):
    def test_each_app_is_its_own_app_with_a_microphone_reason(self) -> None:
        # Named and identified as OpenHamShack since 17/10/2026 (were
        # "OpenHamShack NB.app", com.openhamshack-nb).
        for app, name, bid in (("nb", "OpenHamShack QO-100 NB", "com.openhamshack.qo100nb"),
                               ("ham", "OpenHamShack Radio", "com.openhamshack.radio")):
            b = run_spec(app)["bundle"]
            version = (REPO_ROOT / PYDIR[app] / "VERSION").read_text().strip()
            self.assertEqual(b["name"], f"{name}.app")
            self.assertEqual(b["bundle_identifier"], bid)
            plist = b["info_plist"]
            self.assertEqual((plist["CFBundleShortVersionString"], plist["CFBundleVersion"]), (version, version))
            # Without it macOS hands the program silence for a microphone.
            self.assertIn("microphone", plist["NSMicrophoneUsageDescription"])
            self.assertTrue(b["icon"].endswith(f"{PKG[app]}.icns"))

    def test_the_plist_asks_for_local_network_access_or_lan_radios_are_silently_unreachable(self) -> None:
        # Found live, 07/10/2026: without NSLocalNetworkUsageDescription,
        # macOS 15+ refuses the socket to a LAN radio with no prompt at all
        # (errno 65, "No route to host") rather than asking the operator
        # once, as it does for the microphone. NSBonjourServices must carry
        # libiio's own mDNS service type, "_iio._tcp" (checked in the libiio
        # 0.26 source build-macos.sh builds from: dns_sd_bonjour.c, dns_sd.c,
        # dns_sd_windows.c all agree), or its discovery is silently blocked
        # the same way the direct connection was.
        for app in ("nb", "ham"):
            plist = run_spec(app)["bundle"]["info_plist"]
            self.assertIn("local network", plist["NSLocalNetworkUsageDescription"].lower())
            self.assertIn("_iio._tcp", plist["NSBonjourServices"])

    def test_a_preview_carries_its_label_in_about_but_not_in_info_plist(self) -> None:
        # build-macos.sh --preview writes the build's own VERSION file; the
        # repository's ohsnb/VERSION and ohsradio/VERSION are left as they are.
        for app in ("nb", "ham"):
            release = (REPO_ROOT / PYDIR[app] / "VERSION").read_text().strip()
            with tempfile.TemporaryDirectory() as tmp:
                f = Path(tmp) / "VERSION"
                f.write_text(f"{release}+mac-preview.1\n")
                got = run_spec(app, {"OHSMAC_VERSION_FILE": str(f)})
            self.assertEqual(got["version_file"], f"{release}+mac-preview.1")
            plist = got["bundle"]["info_plist"]
            # macOS takes these as numbers only.
            self.assertEqual((plist["CFBundleShortVersionString"], plist["CFBundleVersion"]), (release, release))
            self.assertEqual(run_spec(app)["version_file"], release)

    def test_licences_and_the_macs_third_party_txt_agree(self) -> None:
        for app in ("nb", "ham"):
            got = run_spec(app)["toc"]
            self.assertEqual(bundle_licences.disagreements(THIRD_PARTY.read_text(), app, got), [], app)
            names = {e[0] for e in got}
            self.assertIn("THIRD-PARTY.txt", names)
            self.assertIn("licences/python-LICENSE.txt", names)
            self.assertEqual("licences/paramiko-LICENSE" in names, app == "ham")


    def test_each_app_carries_the_shared_string_catalog_and_its_own(self) -> None:
        # ohscore/i18n loads them from beside each package; without them the
        # window still opens, but English plurals show their "(s)" source.
        for app, other in (("nb", "ham"), ("ham", "nb")):
            names = {e[0] for e in run_spec(app)["toc"]}
            self.assertIn("ohscore/i18n/ohscore_en.qm", names)
            self.assertIn(f"{PYDIR[app]}/i18n/{PYDIR[app]}_en.qm", names)
            self.assertNotIn(f"{PYDIR[other]}/i18n/{PYDIR[other]}_en.qm", names)


if __name__ == "__main__":
    unittest.main()
