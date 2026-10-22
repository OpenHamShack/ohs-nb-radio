"""The first-run Welcome of both apps (docs/ui-overhaul-2026-10.md section
5.8): Skip on every step saves nothing but "seen", NB asks the licence
class beside the callsign, and what the Welcome records is all the
transmit guard needs - and no more. Driven as an operator would, on Qt's
offscreen platform against real engines on the simulator; a simulator
that claims to radiate stands in for the Pluto (nothing here keys)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QDialog
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

from helpers import RadiatingSim

from test_ui_window import WindowCase


def radiating():
    """A simulator that says it radiates, as the Pluto it stands for does:
    the licence gate judges by the device the engine holds."""
    from ohsnb.devices.sim import SimDevice

    class Radiating(RadiatingSim, SimDevice):
        pass
    return Radiating


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class Welcome(WindowCase):
    def probe(self, app, **over):
        """The Welcome as a first run opens it (ohsnb/ui/__init__.py run):
        on a Bridge of its own before the window, fresh prefs, no class."""
        from ohscore.ui.bridge import Bridge
        from ohscore.ui.prefs import Prefs
        self.n = getattr(self, "n", 0) + 1                    # a fresh ui.json for each first run
        ui = os.path.join(self.tmp, f"ui-{self.n}.json")
        if app == "nb":
            from helpers import make_radio
            from ohsnb.ui.face import Qo100Face as Face
            from ohsnb.ui.welcome import Welcome as W
            radio = make_radio(self.tmp, callsign="", licenceClass="", **over)
        else:
            from ham_helpers import make_radio
            from ohsradio.ui.face import HamFace as Face
            from ohsradio.ui.welcome import Welcome as W
            radio = make_radio(callsign="", licenceClass="", **over)
            self.addCleanup(radio._tmp.cleanup)
        self.addCleanup(radio.stop)
        bridge = Bridge(radio, face=Face())
        self.addCleanup(bridge.stop)
        prefs = Prefs(ui)
        self.assertFalse(prefs["welcomed"])
        self.assertFalse(prefs["licenceAck"])
        w = W(bridge, prefs)
        w.show()
        self.app.processEvents()
        return w, radio, prefs

    def pluto_window(self):
        """A first run's window on a Pluto: its `device` setting says
        "pluto" (so Welcome's radio step shows it chosen, and leaving it
        restarts nothing), the engine holds a radiating simulator."""
        from helpers import sim_cfg
        from ohscore.audio import NullAudio
        from ohscore.ui.prefs import Prefs
        from ohsnb.radio import Radio
        from ohsnb.ui import build
        cfg = sim_cfg(device="pluto", callsign="", licenceClass="", mode="usb", vfo=10_489_700_000.0)
        radio = Radio(cfg, persist=False, data_dir=self.tmp, audio=NullAudio(realtime=False),
                      device=radiating()(dict(cfg, device="sim")))
        self.n = getattr(self, "n", 0) + 1                    # a fresh ui.json for each first run
        prefs = Prefs(os.path.join(self.tmp, f"ui-pluto-{self.n}.json"))
        win, bridge = build(radio, prefs)
        win.resize(1600, 960)
        win.show()
        self.wins.append((win, bridge))
        return win, bridge, radio

    def test_skip_on_every_step_saves_nothing_but_seen(self):
        from ohscore.ui.prefs import Prefs
        for app in ("nb", "ham"):
            for step in range(3):
                with self.subTest(app=app, step=step):
                    w, radio, prefs = self.probe(app)
                    before = radio.state()
                    # The operator has filled in all of it, then thinks better of it.
                    w.call.setText("GM4BRI")
                    w.loc.setText("IO75RL")
                    w.cls.set_value("full")
                    w.ack.setChecked(True)
                    w._pick_device("pluto")
                    w.go(step)
                    self.assertTrue(w.skip_btn.isVisible())
                    QTest.mouseClick(w.skip_btn, Qt.MouseButton.LeftButton)
                    self.app.processEvents()
                    self.assertFalse(w.isVisible())
                    self.assertEqual(w.result(), QDialog.DialogCode.Rejected)   # the window applies nothing
                    self.assertFalse(w.restart_needed)
                    # Seen, and saved as seen: the next start goes straight to the window.
                    self.assertTrue(prefs["welcomed"])
                    self.assertTrue(Prefs(prefs.path)["welcomed"])
                    self.assertFalse(prefs["licenceAck"])
                    self.assertFalse(Prefs(prefs.path)["licenceAck"])
                    after = radio.state()
                    for k in ("device", "plutoUri", "callsign", "locator", "licenceClass"):
                        self.assertEqual(after.get(k), before.get(k), k)
                    self.assertEqual(after["device"], "sim")

    def test_skip_leaves_an_earlier_acknowledgement_alone(self):
        # Welcome… from the menu, for a station that ticked the box long
        # ago: Skip is "close", not "untick".
        w, _radio, prefs = self.probe("nb")
        prefs["licenceAck"] = True
        w.ack.setChecked(False)
        w.skip()
        self.assertTrue(prefs["licenceAck"])

    def test_nb_asks_the_class_of_the_callsigns_country_on_the_first_step(self):
        from ohscore.ui.welcome import NO_CALL_YET
        w, radio, _prefs = self.probe("nb")
        w.go(0)
        page = w.stack.widget(0)
        self.assertTrue(page.isAncestorOf(w.cls))
        self.assertEqual(w.cls_why.text(), NO_CALL_YET)
        self.assertFalse(w.cls.isVisible())
        w.call.setText("GM4BRI")
        self.assertTrue(w.cls.isVisible())
        self.assertEqual([v for v, _ in w.cls.options], ["foundation", "intermediate", "full"])
        self.assertEqual(w.cls.value, "")                     # none chosen for the operator
        self.assertFalse(w.cls_why.isVisible())
        # A country with no licence written: no classes, and NB's own
        # sentence - it is not checked, rather than Radio's "will not transmit".
        w.call.setText("ZS1ABC")
        self.assertFalse(w.cls.isVisible())
        self.assertIn("No licence for South Africa", w.cls_why.text())
        self.assertIn("not checked", w.cls_why.text())
        self.assertNotIn("will not transmit", w.cls_why.text())
        # A German call gets Germany's classes, not the UK's.
        w.call.setText("DL1ABC")
        self.assertNotIn("foundation", [v for v, _ in w.cls.options])
        self.assertTrue(w.cls.options)

    def test_nb_records_the_class_with_the_callsign(self):
        w, radio, prefs = self.probe("nb")
        w.call.setText("gm4bri")
        w.loc.setText("IO75RL")
        w.cls.set_value("intermediate")
        for _ in range(3):
            w._next()
        self.assertEqual(w.result(), QDialog.DialogCode.Accepted)
        st = radio.state()
        self.assertEqual((st["callsign"], st["locator"], st["licenceClass"]), ("GM4BRI", "IO75RL", "intermediate"))
        self.assertTrue(prefs["welcomed"])
        self.assertFalse(prefs["licenceAck"])                 # recorded, not granted: nobody ticked the box

    def test_nb_may_tick_the_box_without_a_class(self):
        # NB's box does not name a class (Radio's does, test_ham_ui), so
        # ticking it with none is allowed; the reminder then stands.
        w, radio, prefs = self.probe("nb")
        w.call.setText("GM4BRI")
        w.go(1)
        w.ack.setChecked(True)
        w.go(2)
        w._next()
        self.assertEqual(w.result(), QDialog.DialogCode.Accepted)
        self.assertTrue(prefs["licenceAck"])
        self.assertEqual(radio.state()["licenceClass"], "")

    def test_a_refused_class_is_said_on_the_step_that_asks_it(self):
        from unittest import mock
        w, radio, prefs = self.probe("nb")
        w.call.setText("GM4BRI")
        w.cls.set_value("full")
        w.go(2)
        real = radio.set

        def refuse(*a, **kw):
            if "licenceClass" in kw:
                raise ValueError("Licence class refused for this test")
            return real(*a, **kw)
        with mock.patch.object(radio, "set", side_effect=refuse):
            w._next()
        self.assertEqual(w.stack.currentIndex(), 0)
        self.assertTrue(w.cls_msg.isVisible())
        self.assertIn("refused for this test", w.cls_msg.text())
        self.assertFalse(prefs["welcomed"])
        w.go(2)
        w._next()
        self.assertEqual(radio.state()["licenceClass"], "full")
        self.assertFalse(w.cls_msg.isVisible())

    def test_a_class_and_the_box_on_a_pluto_give_transmit(self):
        # The whole of setting up, end to end: a station whose radio is a
        # Pluto, with nothing set, completes the Welcome with its class and
        # the box ticked, and the transmit classifier says "ok" - no
        # standing "no licence class" reminder, no lock. The same station
        # skipping it is "setup": Skip grants nothing.
        from ohscore.ui import txstate
        for finish in (True, False):
            with self.subTest(finish=finish):
                win, bridge, radio = self.pluto_window()
                self.run_for(radio, 0.3)
                self.assertEqual(txstate.of_bridge(bridge).kind, txstate.SETUP)
                w = win.welcome_dialog()
                w.show()
                self.assertEqual(w.device, "pluto")
                w.call.setText("GM4BRI")
                w.loc.setText("IO75RL")
                w.cls.set_value("full")
                w.go(1)
                w.ack.setChecked(True)
                w.go(2)
                if finish:
                    w._next()
                else:
                    w.skip()
                if w.result() == QDialog.DialogCode.Accepted:        # as BaseWindow.open_welcome does
                    win.apply_prefs(w.restart_needed)
                self.assertFalse(w.restart_needed)                # still the Pluto it was
                self.run_for(radio, 0.3)
                bridge.st.update(radio.state())
                got = txstate.of_bridge(bridge)
                if finish:
                    self.assertEqual(got, txstate.TxState(txstate.OK))
                    self.assertNotEqual((radio.state().get("txWarning") or {}).get("key"), "licence")
                else:
                    self.assertEqual(got.kind, txstate.SETUP)
                    self.assertEqual(radio.state()["licenceClass"], "")
                self.assertFalse(radio.state()["keyed"])


    def test_each_apps_own_sentences_come_from_the_catalogs(self):
        # The apps keep what differs (rules, the class question, the radios)
        # as class attributes; until 18/10/2026 they were shown as written,
        # so a translated Welcome had translated titles over English steps.
        # The pseudo-locale makes every catalogued string visibly different.
        import importlib.util
        import tempfile
        from pathlib import Path
        from PyQt6.QtWidgets import QLabel
        from ohscore import i18n
        repo = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("i18n_tool", repo / "tools" / "i18n.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        p = tool.pseudo_text
        d = tempfile.mkdtemp(dir=self.tmp)
        tool.write_pseudo(Path(d))
        self.addCleanup(i18n.install, locale="en", catalogs=i18n.app_catalogs(repo / "ohsnb"))
        for app, pkg in (("nb", "ohsnb"), ("ham", "ohsradio")):
            with self.subTest(app=app):
                i18n.install(locale="en-XA", catalogs=[(Path(d), "ohscore"), (Path(d), pkg)])
                w, radio, prefs = self.probe(app)
                labels = [lab.text() for lab in w.findChildren(QLabel)]
                self.assertIn(p(type(w).TAGLINE), labels)
                self.assertIn(p(type(w).RULES), labels)
                self.assertEqual(w.cls_cap.text(), p(type(w).CLASS_CAP))
                self.assertEqual(w.choices["sim"].title, p(type(w).DEVICES[0][2]))
                # Translated as a template, then the country filled in.
                w.go(type(w).CLASS_PAGE)
                w.call.setText("ZS1ABC")
                self.assertEqual(w.cls_why.text(), p(type(w).NO_LICENCE_YET).format(country="South Africa"))
                w.reject()

if __name__ == "__main__":
    unittest.main()
