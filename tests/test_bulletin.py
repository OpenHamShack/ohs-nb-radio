"""Multimedia-beacon bulletins made fit to read (ohsnb/bulletin.py) and shown
in the Beacon view's reader (ohsnb/ui/mmbview.py BulletinView).

The two HTML bulletins in tests/data/bulletins are real, as NB on the Mac
mini received them on 17/10/2026: AMSAT News Service ANS-249 (its first
paragraphs: Word's <o:p>, <span style> with font-family &quot;Georgia&quot;,
<br> lists, "~B:5:249~" before it) and the QO-100 DX Club's news. Until
then the reader showed all of it as text, tags, entities and header."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtWidgets import QApplication  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from ohsnb import bulletin

DATA = Path(__file__).resolve().parent / "data" / "bulletins"
ANS = (DATA / "ANS-249.blt").read_text("utf-8")
DXCLUB = (DATA / "qo100dxclub.blt").read_text("utf-8")
PLAIN = ("OPENHAMSHACK NB SIMULATOR - SAMPLE BULLETIN 2\nSimulated content, not from AMSAT-DL.\n\n"
         "Band plan reminder: CW 10489.505-540, <500 Hz digimodes 540-580 & more\n")
# What a bulletin must never get to do: fetch, run, or reach a local file.
HOSTILE = ("~B:7:300~\n<p onclick=\"steal()\" style=\"color:red\">Hi<img src=\"http://tracker.example/x.png\">"
           "<script>alert(1)</script><style>p{display:none}</style>"
           "<link rel=\"stylesheet\" href=\"http://evil.example/s.css\">"
           "<a href=\"javascript:alert(2)\">js</a> <a href=\"file:///etc/passwd\">file</a>"
           "<iframe src=\"http://evil.example/\"></iframe> <a href=\"https://amsat.org\" target=\"_blank\">ok</a></p>")


class Parse(unittest.TestCase):
    def test_ans_249_reads_as_html_with_its_title_and_without_office_junk(self):
        b = bulletin.parse(ANS, "ANS-249.blt")
        self.assertEqual(b.title, "Bulletin 5 – ANS-249")
        self.assertTrue(b.is_html)
        self.assertNotIn("~B:", b.body)
        for junk in ("<o:p", "</o:p", "style=", "font-family", "Georgia", "class=", "MsoNormal"):
            self.assertNotIn(junk, b.body)
        self.assertIn("<h3>AMSAT NEWS SERVICE ANS-249</h3>", b.body)
        self.assertIn('<a href="https://www.amsat.org">', b.body)
        self.assertIn("<br>", b.body)

    def test_a_header_with_a_title_names_itself(self):
        b = bulletin.parse(DXCLUB, "qo100dxclub.blt")
        self.assertEqual(b.title, "QO-100 DX Club News")
        self.assertTrue(b.is_html)
        self.assertIn('<a href="https://qo100dx.club/news/791">Platinum Award</a>', b.body)
        self.assertNotIn("target=", b.body)
        self.assertEqual(bulletin.title_of(DXCLUB, "qo100dxclub.blt"), b.title)
        # Under its title its own h1s step down a level.
        self.assertTrue(bulletin.under_title(b.body).startswith("<h2><b><a href="), b.body[:40])
        self.assertNotIn("<h1", bulletin.under_title(b.body))

    def test_plain_text_is_left_exactly_as_it_was(self):
        b = bulletin.parse(PLAIN, "amsat_2.blt")
        self.assertEqual((b.title, b.body, b.is_html), ("", PLAIN, False))
        # A header on plain text is a title; the text after it is untouched.
        b = bulletin.parse("~B:3:12~\n" + PLAIN, "news-12.txt")
        self.assertEqual((b.title, b.body, b.is_html), ("Bulletin 3 – news-12", PLAIN, False))
        b = bulletin.parse("~B:3:12~\n" + PLAIN)
        self.assertEqual(b.title, "Bulletin 3 – 12")

    def test_nothing_that_fetches_runs_or_points_off_the_web_survives(self):
        b = bulletin.parse(HOSTILE, "x.blt")
        self.assertTrue(b.is_html)
        for bad in ("onclick", "steal", "<img", "tracker", "<script", "alert", "<style", "display:none", "<link",
                    "evil.example", "javascript:", "file:", "<iframe", "color:red"):
            self.assertNotIn(bad, b.body)
        self.assertIn('<a href="https://amsat.org">ok</a>', b.body)
        self.assertIn("Hi", b.body)


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Reader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def view(self):
        from ohsnb.ui.mmbview import BulletinView
        v = BulletinView()
        v.resize(700, 500)
        self.addCleanup(v.close)
        return v

    def test_ans_249_is_drawn_as_text_not_tags(self):
        v = self.view()
        v.show_bulletin(ANS, "ANS-249.blt")
        text = v.toPlainText()
        self.assertTrue(text.startswith("Bulletin 5 – ANS-249\nAMSAT NEWS SERVICE ANS-249"), text[:80])
        self.assertIn("Updated VUCC & DXCC Satellite Standings", text)     # &amp; decoded
        for raw in ("<", "&quot;", "&amp;", "~B:"):
            self.assertNotIn(raw, text)
        # The <br> list is a list of lines, not one run-on paragraph.
        self.assertIn("Approaches\n* ARISS Announces", text.replace(" ", "\n"))

    def test_plain_bulletins_are_shown_as_they_were(self):
        v = self.view()
        v.show_bulletin(PLAIN, "amsat_2.blt")
        self.assertEqual(v.toPlainText(), PLAIN.rstrip("\n") + ("\n" if PLAIN.endswith("\n") else ""))
        from ohscore.ui import theme
        self.assertEqual(v.font().family(), theme.font(13, mono=True).family())

    def test_no_resource_is_ever_loaded(self):
        # Past the cleaning too: the view itself refuses whatever is asked.
        v = self.view()
        v.setHtml('<p>x<img src="file:///etc/hostname"><img src="http://tracker.example/p.png"></p>')
        v.grab()
        self.assertTrue(any(u.endswith("/etc/hostname") for u in v.refused), v.refused)
        self.assertIn("http://tracker.example/p.png", v.refused)

    def test_a_link_opens_in_the_systems_browser_only_when_clicked(self):
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        v = self.view()
        v.show_bulletin(DXCLUB, "qo100dxclub.blt")
        with mock.patch.object(QDesktopServices, "openUrl") as opened:
            self.app.processEvents()
            self.assertFalse(opened.called)               # showing it opens nothing
            v.anchorClicked.emit(QUrl("https://qo100dx.club/news/791"))
            v.anchorClicked.emit(QUrl("file:///etc/passwd"))
        self.assertEqual([c.args[0].toString() for c in opened.call_args_list], ["https://qo100dx.club/news/791"])
        self.assertIn("Platinum Award", v.toPlainText())        # the view stayed on the bulletin


if __name__ == "__main__":
    unittest.main()
