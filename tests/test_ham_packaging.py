"""OpenHamShack HAM's .deb: build it with tools/build-deb.sh ham and check what
it does - its own package and its own copy of the core, a launcher that
runs from wherever dpkg puts it, and no path shared with OpenHamShack NB's
.deb, so the two install side by side. Drives dpkg-deb and the installed
launcher; reads none of this repo's source text."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

if shutil.which("dpkg-deb") is None:
    raise unittest.SkipTest("dpkg-deb not installed: the .deb is built and checked on Debian")

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILD_SCRIPT = REPO_ROOT / "tools" / "build-deb.sh"
VERSION = (REPO_ROOT / "ohsradio" / "VERSION").read_text().strip()


def build(tmpdir, *args):
    subprocess.run([str(BUILD_SCRIPT), *args], cwd=tmpdir, check=True, capture_output=True, text=True)
    app = args[0] if args and args[0] in ("nb", "ham") else "nb"
    name = "openhamshack-radio" if app == "ham" else "openhamshack-nb"
    version = args[1] if len(args) > 1 else ((REPO_ROOT / ("ohsradio" if app == "ham" else "ohsnb") / "VERSION")
                                            .read_text().strip())
    deb = Path(tmpdir) / f"{name}_{version}_all.deb"
    assert deb.is_file(), deb
    return deb


def field(deb, name):
    return subprocess.run(["dpkg-deb", "-f", str(deb), name], check=True, capture_output=True, text=True).stdout.strip()


def contents(deb):
    out = subprocess.run(["dpkg-deb", "-c", str(deb)], check=True, capture_output=True, text=True).stdout
    return [line.split()[-1] for line in out.splitlines()]


class HamDeb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.deb = build(cls.tmp.name, "ham")
        cls.listing = contents(cls.deb)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_identity_and_version(self):
        self.assertEqual(field(self.deb, "Package"), "openhamshack-radio")
        self.assertEqual(field(self.deb, "Version"), VERSION)
        self.assertEqual(field(self.deb, "Architecture"), "all")
        self.assertIn("amateur", field(self.deb, "Description"))

    def test_depends_on_paramiko_for_the_pluto_fix_and_nb_does_not(self):
        self.assertIn("python3-paramiko", field(self.deb, "Depends"))
        with tempfile.TemporaryDirectory() as d:
            self.assertNotIn("paramiko", field(build(d, "nb"), "Depends"))

    def test_recommends_librtlsdr_for_the_rtl_sdr_and_nb_does_not(self):
        self.assertIn("librtlsdr0", field(self.deb, "Recommends").split(", "))
        with tempfile.TemporaryDirectory() as d:
            self.assertNotIn("librtlsdr0", field(build(d, "nb"), "Recommends"))

    def test_explicit_version(self):
        with tempfile.TemporaryDirectory() as d:
            deb = build(d, "ham", "9.8.7")
            self.assertEqual(field(deb, "Version"), "9.8.7")

    def test_ships_the_app_its_core_and_desktop_files(self):
        for p in ("./usr/bin/openhamshack-radio", "./usr/lib/openhamshack-radio/ohsradio/radio.py",
                  "./usr/lib/openhamshack-radio/ohsradio/__main__.py", "./usr/lib/openhamshack-radio/ohsradio/VERSION",
                  "./usr/lib/openhamshack-radio/ohscore/__init__.py", "./usr/lib/openhamshack-radio/ohscore/dsp/fm.py",
                  "./usr/share/applications/openhamshack-radio.desktop",
                  "./usr/share/icons/hicolor/scalable/apps/openhamshack-radio.svg",
                  "./usr/share/metainfo/openhamshack-radio.metainfo.xml", "./usr/share/man/man1/openhamshack-radio.1.gz",
                  "./usr/share/doc/openhamshack-radio/copyright"):
            self.assertIn(p, self.listing)

    def test_carries_nothing_of_nb(self):
        self.assertFalse(any("/ohsnb/" in p or p.endswith("/ohsnb") for p in self.listing))
        self.assertFalse(any("openhamshack-nb" in p for p in self.listing))
        self.assertFalse(any("__pycache__" in p or p.endswith((".pyc", ".pyo")) for p in self.listing))

    def test_no_path_in_common_with_nb_so_both_install(self):
        with tempfile.TemporaryDirectory() as d:
            nb = set(p for p in contents(build(d, "nb")) if not p.endswith("/"))
        ham = set(p for p in self.listing if not p.endswith("/"))
        self.assertEqual(nb & ham, set())


class HamExtracted(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.deb = build(cls.tmp.name, "ham")
        cls.root = Path(cls.tmp.name) / "root"
        subprocess.run(["dpkg-deb", "-x", str(cls.deb), str(cls.root)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def _env(self):
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        env["OHS_RADIO_CONF"] = str(Path(self.tmp.name) / "conf.json")
        env["OHS_RADIO_DATA"] = str(Path(self.tmp.name) / "data")
        return env

    def test_headless_runs_on_the_sim_and_never_keys(self):
        with tempfile.TemporaryDirectory() as cwd:
            res = subprocess.run([str(self.root / "usr" / "bin" / "openhamshack-radio"), "--headless", "--no-audio",
                                  "--seconds", "2", "--band", "20m"], cwd=cwd, env=self._env(),
                                 capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("20m", res.stdout)
        self.assertIn("stopped;", res.stdout)
        # Headless has no PTT source; the status lines never say it keyed.
        self.assertNotIn("ON AIR", res.stdout)
        self.assertNotIn("Transmit", res.stdout)

    def test_installed_app_uses_its_own_core(self):
        libdir = self.root / "usr" / "lib" / "openhamshack-radio"
        env = self._env()
        env["PYTHONPATH"] = str(libdir)
        with tempfile.TemporaryDirectory() as cwd:
            res = subprocess.run([sys.executable, "-c",
                                  "import ohsradio.__main__, ohscore; print(ohsradio.__file__); print(ohscore.__file__)"],
                                 cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        for line in res.stdout.split():
            self.assertTrue(Path(line).resolve().is_relative_to(libdir.resolve()), line)

    def test_installed_copy_reads_its_own_cty_dat_with_no_wsjtx(self):
        # As NB's (test_packaging.py): HAM's private ohscore carries it too.
        libdir = self.root / "usr" / "lib" / "openhamshack-radio"
        env = self._env()
        env["PYTHONPATH"] = str(libdir)
        with tempfile.TemporaryDirectory() as cwd:
            res = subprocess.run([sys.executable, "-c",
                                  "from ohscore import dxcc, host; host.wsjtx_cty_files = lambda: []; "
                                  "print(dxcc.BUNDLED); print(dxcc.load(None).lookup('OR4TN').name)"],
                                 cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        path, name = res.stdout.strip().splitlines()
        self.assertTrue(Path(path).resolve().is_relative_to(libdir.resolve()), path)
        self.assertEqual(name, "Antarctica")

    def test_window_icon_found_from_the_installed_tree(self):
        libdir = self.root / "usr" / "lib" / "openhamshack-radio"
        env = self._env()
        env["PYTHONPATH"] = str(libdir)
        with tempfile.TemporaryDirectory() as cwd:
            res = subprocess.run([sys.executable, "-c", "from ohsradio.ui.appicon import svg_path; print(svg_path())"],
                                 cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(Path(res.stdout.strip()).resolve().is_relative_to(self.root.resolve()), res.stdout)


if __name__ == "__main__":
    unittest.main()
