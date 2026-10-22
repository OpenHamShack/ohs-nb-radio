"""The cty.dat ohscore carries (ohscore/data), so the FT8 Country column works
on a machine with no WSJT-X - which, since ohsdigi decodes, FT8 itself no
longer needs."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from ohscore import diag, dxcc, host
from ohsradio import config as ham_config
from ohsnb import config as nb_config

REPO_ROOT = Path(__file__).resolve().parent.parent
APPS = (("NB", nb_config), ("HAM", ham_config))


class NoWsjtx(unittest.TestCase):
    """A fresh home (scratch_home) on a machine where WSJT-X installed
    nothing: every place it might have put a cty.dat is missing. This
    development machine has Debian's wsjtx, so that has to be hidden."""

    def setUp(self):
        dxcc._cache.clear()
        self.addCleanup(dxcc._cache.clear)
        p = mock.patch.object(host, "wsjtx_cty_files", return_value=[Path("/nonexistent/wsjtx/cty.dat")])
        p.start()
        self.addCleanup(p.stop)

    def _data_dir(self, cfg) -> Path:
        d = Path(cfg.data_dir())
        d.mkdir(parents=True, exist_ok=True)
        own = d / "cty.dat"
        if own.exists():
            own.unlink()
        self.addCleanup(lambda: own.unlink(missing_ok=True))
        return d

    def test_a_known_call_resolves_from_the_bundled_file(self):
        for app, cfg in APPS:
            with self.subTest(app):
                dxcc._cache.clear()
                countries = dxcc.load(self._data_dir(cfg))
                # Calls only Big CTY's exact-call list gets right (two of
                # its README's own checks): by prefix alone OR4TN would be
                # Belgium and MR6TMS England.
                self.assertEqual(countries.lookup("OR4TN").name, "Antarctica")
                self.assertEqual(countries.lookup("MR6TMS").name, "Scotland")
                self.assertEqual(countries.lookup("EA8/G4ABC").name, "Canary Islands")
                self.assertEqual(diag._cty(cfg.data_dir()), str(dxcc.BUNDLED))

    def test_a_cty_dat_in_the_data_folder_still_wins(self):
        for app, cfg in APPS:
            with self.subTest(app):
                dxcc._cache.clear()
                data = self._data_dir(cfg)
                (data / "cty.dat").write_text("Somewhere Newer: 14: 27: EU: 0.0: 0.0: 0.0: OR:\n    OR,=OR4TN;\n",
                                              encoding="latin-1")
                self.assertEqual(dxcc.load(data).lookup("OR4TN").name, "Somewhere Newer")
                self.assertEqual(diag._cty(data), str(data / "cty.dat"))

    def test_the_bundled_file_also_beats_an_installed_wsjtx(self):
        # Ours is refreshed each release; ohscore/dxcc.py says why it does
        # not try to tell which of the two is newer.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            theirs = Path(d) / "cty.dat"
            theirs.write_text("WSJT-X's Older: 14: 27: EU: 0.0: 0.0: 0.0: OR:\n    OR,=OR4TN;\n", encoding="latin-1")
            for app, cfg in APPS:
                with self.subTest(app), mock.patch.object(host, "wsjtx_cty_files", return_value=[theirs]):
                    dxcc._cache.clear()
                    self.assertEqual(dxcc.load(self._data_dir(cfg)).lookup("OR4TN").name, "Antarctica")


class Pinned(unittest.TestCase):
    def test_the_vendored_files_are_the_pinned_edition_unmodified(self):
        # What tools/cty-refresh.py --check compares, run as a release
        # would: AD1C's bytes, CRLF and all (.gitattributes keeps git off
        # them), matching the sha256 in ohscore/data/cty-source.txt.
        res = subprocess.run([sys.executable, str(REPO_ROOT / "tools" / "cty-refresh.py"), "--check"],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_the_check_notices_a_changed_file(self):
        import importlib.util
        import tempfile
        spec = importlib.util.spec_from_file_location("cty_refresh", REPO_ROOT / "tools" / "cty-refresh.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for name in tool.MEMBERS:
                (d / name).write_bytes((tool.DATA / name).read_bytes())
            self.assertEqual(tool.check(d), [])
            # The commonest way it goes wrong: line ends turned into LF.
            (d / "cty.dat").write_bytes((d / "cty.dat").read_bytes().replace(b"\r\n", b"\n"))
            wrong = tool.check(d)
            self.assertEqual(len(wrong), 1)
            self.assertIn("cty.dat", wrong[0])


if __name__ == "__main__":
    unittest.main()
