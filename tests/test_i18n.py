"""Translation scaffolding (docs/I18N.md): the string check passes with its
baseline and fails on a new literal, the committed catalogs are what their
.ts compile to, each app's window speaks whatever catalogs are installed
(the shared ohscore one and its own, shown with the pseudo-locale), English
plurals come out right, an unknown locale falls back to English, and
frequencies format as the shared vectors say."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QCoreApplication
    HAVE_QT = True
except ImportError:  # pragma: no cover - the check and the catalogs are still tested
    HAVE_QT = False

REPO = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("i18n_tool", REPO / "tools" / "i18n.py")
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

NB = "OpenHamShack QO-100 NB"
HAM = "OpenHamShack Radio"


def run_tool(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(root / "tools" / "i18n.py"), *args],
                          capture_output=True, text=True, timeout=300)


class StringCheck(unittest.TestCase):
    def test_this_repo_passes_with_its_baseline(self):
        r = run_tool(REPO, "check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # The count M3 drives to zero, in every suite run's output.
        summary = r.stdout.strip().splitlines()[-1]
        self.assertIn("baseline", summary)
        sys.stderr.write(f"\n{summary}\n")

    def test_a_new_literal_fails_and_a_converted_one_must_leave_the_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            shutil.copytree(REPO / "tools", root / "tools", ignore=shutil.ignore_patterns("__pycache__"))
            (root / ".git").mkdir()     # the check finds the repo root by it
            (root / "app").mkdir()
            ui = root / "app" / "ui.py"
            ui.write_text('class W:\n    def f(self):\n        self.b.setText("Old label")\n')

            r = run_tool(root, "check")
            self.assertEqual(r.returncode, 1, r.stdout)
            self.assertIn('"Old label"', r.stdout)

            self.assertEqual(run_tool(root, "baseline", "--add-new").returncode, 0)
            r = run_tool(root, "check")
            self.assertEqual(r.returncode, 0, r.stdout)
            self.assertIn("baseline 1 literal(s)", r.stdout)

            # A new literal beside the baselined one fails, and the baseline
            # command will not quietly take it in.
            ui.write_text(ui.read_text() + '        self.b.setToolTip("New tip")\n')
            r = run_tool(root, "check")
            self.assertEqual(r.returncode, 1)
            self.assertIn('"New tip"', r.stdout)
            self.assertNotIn('"Old label"', r.stdout)
            self.assertEqual(run_tool(root, "baseline").returncode, 1)
            self.assertNotIn("New tip", (root / "i18n-pending.txt").read_text())

            # Converting the old literal leaves a stale line, which fails
            # until the baseline command removes it.
            ui.write_text('class W:\n    def f(self):\n        self.b.setText(self.tr("Old label"))\n')
            r = run_tool(root, "check")
            self.assertEqual(r.returncode, 1)
            self.assertIn("matched nothing", r.stdout)
            run_tool(root, "baseline")
            self.assertNotIn("Old label", (root / "i18n-pending.txt").read_text())


class Catalogs(unittest.TestCase):
    def test_each_committed_qm_is_its_ts_compiled(self):
        self.assertEqual([c["ts"] for c in tool.CATALOGS],
                         ["ohscore/i18n/ohscore_en.ts", "ohsnb/i18n/ohsnb_en.ts", "ohsradio/i18n/ohsradio_en.ts"])
        for c in tool.CATALOGS:
            ts = REPO / c["ts"]
            self.assertEqual(ts.with_suffix(".qm").read_bytes(), tool.qm_for(ts),
                             f"{ts.name} changed without tools/i18n.py compile")

    def test_each_gettext_template_is_current(self):
        r = run_tool(REPO, "pot", "--check")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_templates_hold_each_gettext_call_and_go_stale_when_a_sentence_changes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            shutil.copytree(REPO / "tools", root / "tools", ignore=shutil.ignore_patterns("__pycache__"))
            for pkg in ("ohscore", "ohsnb", "ohsradio"):
                (root / pkg).mkdir()
            src = root / "ohsnb" / "radio.py"
            src.write_text("from ohsnb.i18n import _, ngettext, pgettext\n"
                           "def f(n, x):\n"
                           "    a = _(\"The dish is {state}\").format(state=x)\n"
                           "    b = ngettext(\"%(n)d spot\", \"%(n)d spots\", n)\n"
                           "    c = pgettext(\"mode\", \"Lock\")\n"
                           "    d = _(x)\n")
            self.assertEqual(run_tool(root, "pot").returncode, 0)
            pot = (root / "ohsnb" / "i18n" / "ohsnb.pot").read_text()
            self.assertIn('msgid "The dish is {state}"\nmsgstr ""', pot)
            self.assertIn('msgid "%(n)d spot"\nmsgid_plural "%(n)d spots"\nmsgstr[0] ""\nmsgstr[1] ""', pot)
            self.assertIn('msgctxt "mode"\nmsgid "Lock"', pot)
            self.assertIn("#: ohsnb/radio.py:3", pot)
            # One domain per package: Radio's template has none of NB's sentences.
            self.assertNotIn("The dish", (root / "ohsradio" / "i18n" / "ohsradio.pot").read_text())
            self.assertEqual(run_tool(root, "pot", "--check").returncode, 0)
            src.write_text(src.read_text().replace("The dish is", "The dish was"))
            r = run_tool(root, "pot", "--check")
            self.assertEqual(r.returncode, 1)
            self.assertIn("ohsnb/i18n/ohsnb.pot is out of date", r.stdout)

    def test_english_plural_forms_follow_the_convention(self):
        self.assertEqual(tool.plural_forms("%n QSO(s)"), ["%n QSO", "%n QSOs"])
        self.assertIsNone(tool.plural_forms("%n entry or entries"))

    def test_pseudo_text_keeps_placeholders_and_grows(self):
        p = tool.pseudo_text("%n signal(s) near {freq}")
        self.assertIn("%n", p)
        self.assertIn("{freq}", p)
        self.assertTrue(p.startswith("[") and p.endswith("]"))
        self.assertGreater(len(p), len("%n signal(s) near {freq}") * 1.3)

    def test_pseudo_text_leaves_rich_text_markup_working(self):
        src = "<span style='color:#3ddc84'>&#9632;</span> CQ &nbsp; &File"
        p = tool.pseudo_text(src)
        self.assertIn("<span style='color:#3ddc84'>&#9632;</span>", p)
        self.assertIn("&nbsp;", p)
        self.assertIn("&Fîlé", p)                   # a shortcut marker is not an entity
        self.assertNotIn("CQ", p.replace("ÇQ", ""))   # the words themselves are still changed


class Locale(unittest.TestCase):
    def test_candidates_go_from_specific_to_language(self):
        from ohscore import i18n
        self.assertEqual(i18n.candidates("pt-BR.UTF-8"), ["pt_BR", "pt"])
        self.assertEqual(i18n.candidates("C"), [])

    def test_a_language_any_catalog_has_is_chosen_and_one_none_has_falls_back_to_english(self):
        from ohscore import i18n
        with tempfile.TemporaryDirectory() as d:
            core, app = Path(d) / "core", Path(d) / "app"
            core.mkdir()
            app.mkdir()
            # Only the app's own catalog has German: still German, so a
            # half-translated app shows what it has.
            (app / "ohsnb_de.qm").write_bytes(b"")
            cats = [(core, "ohscore"), (app, "ohsnb")]
            self.assertEqual(i18n.choose(["fr_FR", "de_AT"], cats), "de")
            self.assertEqual(i18n.choose(["fr_FR", "xx"], cats), "en")

    def test_each_app_names_the_shared_catalog_and_its_own(self):
        from ohscore import i18n
        self.assertEqual(i18n.app_catalogs(REPO / "ohsradio"),
                         [(REPO / "ohscore" / "i18n", "ohscore"), (REPO / "ohsradio" / "i18n", "ohsradio")])


class Frequencies(unittest.TestCase):
    """The shared vectors (ohs-libs spec/vectors/i18n/format.json)."""

    @unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
    def test_frequency_vectors(self):
        from ohscore.i18n import fmt
        cases = json.loads((REPO / "tests" / "data" / "i18n-format.json").read_text())["frequency"]
        for c in cases:
            with self.subTest(c):
                if "error" in c:
                    with self.assertRaises(fmt.FormatError) as cm:
                        fmt.frequency(c["hz"], c["unit"], c["decimals"], c["locale"])
                    self.assertEqual(cm.exception.code, c["error"])
                else:
                    self.assertEqual(fmt.frequency(c["hz"], c["unit"], c["decimals"], c["locale"]), c["text"])


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Windows(unittest.TestCase):
    """Both apps' main windows on the simulator, built as the UI tests
    build them, in whatever language is installed."""

    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["OHS_NB_UI_CONF"] = os.path.join(self.tmp, "nb-ui.json")
        os.environ["OHS_RADIO_UI_CONF"] = os.path.join(self.tmp, "ham-ui.json")
        self.errors = []
        self._hook = sys.excepthook
        sys.excepthook = lambda t, v, tb: self.errors.append((t, v, tb))

    def tearDown(self):
        from ohsnb.ui import make_app
        self.app.processEvents()
        sys.excepthook = self._hook
        shutil.rmtree(self.tmp, ignore_errors=True)
        # Back to what every other UI test expects: NB's catalogs, in the
        # desktop's language.
        make_app(["test"])
        if self.errors:
            import traceback
            self.fail("exceptions in Qt slots:\n" + "".join("".join(traceback.format_exception(*e))
                                                            for e in self.errors))

    def nb_window(self):
        from ohscore.ui.prefs import Prefs
        from helpers import make_radio
        from ohsnb import config
        from ohsnb.ui import build
        return self._show(build, make_radio(self.tmp), Prefs(config.CONFIG))

    def ham_window(self):
        from ohscore.ui.prefs import Prefs
        from ham_helpers import make_radio
        from ohsradio import config
        from ohsradio.ui import build
        return self._show(build, make_radio(), Prefs(config.CONFIG))

    def _show(self, build, radio, prefs):
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.addCleanup(bridge.stop)
        self.addCleanup(win.close)
        self.app.processEvents()
        return win

    @staticmethod
    def menus(win) -> dict:
        """{menu title: [item texts]}, as the menu bar shows them."""
        return {m.text(): [a.text() for a in m.menu().actions() if not a.isSeparator()]
                for m in win.menuBar().actions()}

    def test_english_plurals_come_from_the_english_catalogs(self):
        from ohscore import i18n
        from ohsradio.ui import make_app as ham_app
        from ohsnb.ui import make_app as nb_app
        tr = QCoreApplication.translate
        nb_app(["test"])
        self.assertEqual(tr("LogView", "%n QSO(s)", "", 1), "1 QSO")       # ohscore's catalog
        self.assertEqual(tr("LogView", "%n QSO(s)", "", 3), "3 QSOs")
        self.assertEqual(tr("SkimView", "%n signal(s)", "", 7), "7 signals")   # NB's own
        self.assertEqual(i18n.install(locale="en_GB", catalogs=i18n.app_catalogs(REPO / "ohsradio")), "en")
        self.assertEqual(tr("LogView", "%n QSO(s)", "", 1), "1 QSO")
        # Each app's make_app() puts its own catalog in front, replacing the
        # other's: the suite builds both apps' windows in one process.
        ham_app(["test"])
        self.assertEqual(tr("SkimView", "%n signal(s)", "", 7), "7 signal(s)")
        self.assertEqual(tr("LogView", "%n QSO(s)", "", 2), "2 QSOs")

    def test_each_window_speaks_the_installed_catalogs(self):
        from ohscore import i18n
        from ohsnb.ui.welcome import About
        p = tool.pseudo_text
        with tempfile.TemporaryDirectory() as d:
            tool.write_pseudo(Path(d))
            self.assertEqual(i18n.install(locale="en-XA", catalogs=[(Path(d), "ohscore"), (Path(d), "ohsnb")]), "en_XA")
            win = self.nb_window()
            about = About(win)
            self.addCleanup(about.close)
            self.assertEqual(i18n.install(locale="en-XA", catalogs=[(Path(d), "ohscore"), (Path(d), "ohsradio")]), "en_XA")
            ham = self.ham_window()
        # NB: its own title, badge and Radio menu item from ohsnb's catalog,
        # the shared menus and About box from ohscore's.
        self.assertEqual(win.windowTitle(), p(NB))
        menus = self.menus(win)
        self.assertIn(p("&File"), menus)
        self.assertIn(p("Dish alignment…"), menus[p("&Radio")])
        self.assertIn(p("About {app}").format(app=NB), menus[p("&Help")])
        self.assertEqual(win.rx_badge.title, p("RX · beacon"))
        self.assertEqual(about.windowTitle(), p("About {app}").format(app=NB))
        # Radio: the same shared menus, with its own item added to Help by
        # reference (found by its title it would be lost once translated).
        self.assertEqual(ham.windowTitle(), p(HAM))
        menus = self.menus(ham)
        self.assertIn(p("Check radio…"), menus[p("&Help")])
        self.assertIn(p("Second display"), menus[p("&View")])

    def test_an_unknown_locale_gets_the_english_windows(self):
        from ohscore import i18n
        self.assertEqual(i18n.install(locale="xx_YY", catalogs=i18n.app_catalogs(REPO / "ohsnb")), "en")
        win = self.nb_window()
        self.assertEqual(win.windowTitle(), NB)
        self.assertIn("Dish alignment…", self.menus(win)["&Radio"])
        self.assertEqual(i18n.install(locale="xx_YY", catalogs=i18n.app_catalogs(REPO / "ohsradio")), "en")
        ham = self.ham_window()
        self.assertEqual(ham.windowTitle(), HAM)
        self.assertIn("Check radio…", self.menus(ham)["&Help"])

    def test_frequencies_reach_each_window_through_the_formatter(self):
        from ohscore import i18n
        self.assertEqual(i18n.install(locale="de", catalogs=i18n.app_catalogs(REPO / "ohsradio")), "en")
        ham = self.ham_window()
        ham.bridge.st["band"] = "20m"
        # German has the decimal comma: kHz on HF, MHz from 30 MHz up.
        self.assertEqual(ham.bandbar._dial_tip("ft8"), "This band's FT8 dial, 14074,0\u00a0kHz")
        ham.bridge.st["band"] = "2m"
        self.assertEqual(ham.bandbar._dial_tip("ft8"), "This band's FT8 dial, 144,174\u00a0MHz")
        # NB's transmit card shows the IC-9700's dial the same way.
        self.assertEqual(i18n.install(locale="de", catalogs=i18n.app_catalogs(REPO / "ohsnb")), "en")
        win = self.nb_window()
        card = win.txcard
        card._sync_rig({"rigLink": "ok", "rigFreq": 1_296_200_000.0, "rigMode": "usb", "rigKeyed": False})
        self.assertEqual(card.rig.text(), "IC-9700  1296,200000\u00a0MHz  USB  RX")


if __name__ == "__main__":
    unittest.main()
