"""When the FT8 panel's overs go out, against a clock the test turns.

Ray (QO-100 FT8, IC-9700, 16/10/2026): "I'm having to wait 27 seconds
before I can reply if I have just finished a QSO and click on another
station." Their slot is decoded 13.5 s in, so its lines appear about a
second before our slot starts, and the click on one lands early in our
slot - ours because they transmit in the other parity. The panel only
ever queued for the *next* slot, which is theirs, so the call waited for
the one after: the rest of this slot and the whole of theirs. If the
sequencer had an RR73 repeat for the old QSO queued in this slot, it went
out first, too.

The same rule held up every auto-sequenced reply: the over for our slot
was queued 2.5 s into theirs, before their answer was decoded at 13.5 s,
so the stale message went out and the answer waited a cycle.

The panel runs here against a stand-in engine that keeps the engine's
timing rule (ohscore.engine.slot_start) and its queue - keyed from send()
until the over ends, on the air from its start - on the test's clock, so
each case says when the radio would key, in seconds after the click."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import math
import os
import shutil
import tempfile
import time as _time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    from PyQt6.QtCore import QObject  # noqa: F401
    HAVE_QT = True
except ImportError:  # pragma: no cover
    HAVE_QT = False

import numpy as np

from ohscore import engine
from ohscore.engine import AUDIO_RATE, slot_start, slot_truncate
from ohscore.ft8seq import plan_over

T0 = 1_760_000_000.0 - (1_760_000_000.0 % 30.0)      # an even FT8 slot boundary
OVER = 12.64                                          # an FT8 transmission's length


class Clock:
    """Stands in for the panel module's `time`: time() is the test's;
    the formatting functions are the real ones."""

    def __init__(self, t):
        self.t = t

    def time(self):
        return self.t

    strftime = staticmethod(_time.strftime)
    gmtime = staticmethod(_time.gmtime)


class FakeRadio:
    """The engine as the panel sees it: send() queues an over for
    slot_start(), halt() drops it, and nothing can be queued again until
    the last one has ended (tx_idle)."""

    def __init__(self, clock, st):
        self.clock, self.st = clock, st
        self.sent = []           # (text, period, queued at, keys at, aligned to or None)
        self.halts = []
        self.logged = []
        self.data_dir = None

    def log_entries(self):
        return []

    def log_qso(self, call, **fields):
        self.logged.append(call)

    def send(self, mode, **msg):
        if self.st["keyed"]:
            raise ValueError("Already transmitting")
        now = self.clock.time()
        align = slot_truncate(now, mode, msg.get("period")) if msg.get("late_start") else None
        at = now if align is not None else slot_start(now, mode, msg.get("period"))
        self.sent.append((msg["text"], msg.get("period"), now, at, align))
        self.st.update(keyed=True, txOnAir=False)

    def halt(self):
        self.halts.append(self.clock.time())
        self.st.update(keyed=False, txOnAir=False)

    def tx_idle(self):
        return not self.st["keyed"]

    def advance(self):
        """The queue at the clock's time: on the air from its start, done
        (unkeyed) after its length."""
        if self.st["keyed"] and self.sent:
            at, align = self.sent[-1][3], self.sent[-1][4]
            end = (align if align is not None else at) + OVER      # a late start's tail ends on time
            now = self.clock.time()
            self.st["txOnAir"] = at <= now < end
            if now >= end:
                self.st["keyed"] = False


class FakeBridge:
    def __init__(self, clock):
        self.st = {"callsign": "GM4BRI", "locator": "IO75rl", "mode": "ft8", "keyed": False, "txOnAir": False,
                   "dxCall": ""}
        self.radio = FakeRadio(clock, self.st)
        self.face = mock.Mock()
        self.face.on_air = lambda st: bool(st.get("txOnAir"))
        self.said = []

    def say(self, text, level="warn"):
        self.said.append(text)

    def set(self, quiet=False, **changes):
        self.st.update(changes)
        return True

    def send(self, mode, /, **msg):
        try:
            self.radio.send(mode, **msg)
        except ValueError as e:
            self.say(str(e))
            return False
        return True

    def halt(self):
        self.radio.halt()

    def licence_locked(self):
        # Halt TX asks (ohscore/ui/txstate.py of_bridge) whether this run may
        # transmit: the simulated QSO may.
        return False


class PlanOver(unittest.TestCase):
    """The rule on its own: which slot an over is queued for, given the time."""

    def test_a_click_early_in_our_own_slot_goes_in_that_slot(self):
        # Odd is ours (the station clicked was heard in the even slot just
        # ended); 1.2 s into the odd slot.
        now = T0 + 15 + 1.2
        k = plan_over(now, 15.0, 1, None, True, 1.6)
        self.assertEqual(k, (T0 + 15) // 15)
        # ...and the engine starts it at once, late by 0.7 s (DT +0.7).
        self.assertEqual(slot_start(now, "ft8", "odd"), now)

    def test_too_late_in_our_slot_waits_for_the_next_of_ours(self):
        now = T0 + 15 + 3.0
        self.assertIsNone(plan_over(now, 15.0, 1, None, True, 1.6))
        # From the other station's slot, a fresh choice is queued at once
        # for ours, without waiting for decodes it does not depend on.
        self.assertEqual(plan_over(T0 + 30 + 0.1, 15.0, 1, None, True, 1.6), (T0 + 45) // 15)

    def test_a_repeat_never_late_starts_and_waits_for_the_decodes(self):
        self.assertIsNone(plan_over(T0 + 15 + 1.0, 15.0, 1, None, False, 1.6))
        self.assertIsNone(plan_over(T0 + 30 + 1.0, 15.0, 1, None, False, 1.6))     # decodes not in yet
        self.assertEqual(plan_over(T0 + 30 + 2.6, 15.0, 1, None, False, 1.6), (T0 + 45) // 15)
        self.assertIsNone(plan_over(T0 + 30 + 2.6, 15.0, 1, (T0 + 45) // 15, False, 1.6))   # already queued
        self.assertIsNone(plan_over(T0 + 30 + 14.5, 15.0, 1, None, False, 1.6))    # no time left to render


@unittest.skipUnless(HAVE_QT, "PyQt6 is not installed")
class ReplyAfterAQso(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from helpers import qt_app
        cls.app = qt_app()

    def setUp(self):
        from ohscore.ui.panels import ft8
        self.clock = Clock(T0)
        p = mock.patch.object(ft8, "time", self.clock)
        p.start()
        self.addCleanup(p.stop)
        self.bridge = FakeBridge(self.clock)
        self.radio = self.bridge.radio
        from ohscore.ui.prefs import Prefs
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        prefs = Prefs(os.path.join(tmp, "ui.json"))        # the window's defaults
        self.panel = ft8.Ft8Panel(self.bridge, prefs)
        self.addCleanup(self.panel.deleteLater)

    def run_to(self, t):
        """Turn the clock to `t` in 50 ms frames, as the window's tick does."""
        while self.clock.t < t:
            self.clock.t = min(t, self.clock.t + 0.05)
            self.radio.advance()
            self.panel.tick(0.05)

    def decode(self, slot_t0, text, call, snr=-10, df=1200):
        """A decode from the slot starting at slot_t0, arriving now."""
        self.panel.on_event({"mode": "ft8", "slot": slot_t0, "text": text, "call": call, "snr": snr, "dt": 0.1,
                             "df": df})

    def click_last(self):
        self.panel._row_clicked(self.panel.table.rowCount() - 1, 5)

    def test_a_cq_heard_in_the_slot_just_ended_is_answered_in_this_one(self):
        # A QSO has just ended (TX off, nothing queued). DL1ABC called CQ in
        # the even slot T0+30; the operator double-clicks its line 1 s into
        # the odd slot T0+45.
        self.run_to(T0 + 45 + 1.0)
        self.decode(T0 + 30, "CQ DL1ABC JO31", "DL1ABC")
        click = self.clock.t
        self.click_last()
        self.run_to(T0 + 45 + 3.0)
        self.assertEqual(len(self.radio.sent), 1)
        text, period, _queued, keys, _align = self.radio.sent[0]
        self.assertEqual((text, period), ("DL1ABC GM4BRI IO75", "odd"))
        self.assertLess(keys - click, 1.0)       # was 29.5 s: the odd slot after next

    def click_at(self, into):
        """DL1ABC's CQ from the even slot T0+30, double-clicked `into` s into
        the odd slot T0+45 (ours); the panel runs on 3 s. The over sent."""
        self.run_to(T0 + 45 + into)
        self.decode(T0 + 30, "CQ DL1ABC JO31", "DL1ABC")
        self.click_last()
        self.run_to(T0 + 45 + into + 3.0)
        return self.radio.sent

    def test_a_click_1_s_in_shifts_the_whole_message(self):
        sent = self.click_at(1.0)
        self.assertEqual(len(sent), 1)
        _text, period, queued, keys, align = sent[0]
        self.assertEqual((period, keys, align), ("odd", queued, None))     # at once, all of it (DT +0.5)

    def test_clicks_4_and_5_9_s_in_start_at_once_aligned_to_the_slot(self):
        for into in (4.0, 5.9):
            with self.subTest(into=into):
                self.setUp()
                sent = self.click_at(into)
                self.assertEqual(len(sent), 1)
                _text, period, queued, keys, align = sent[0]
                self.assertEqual(period, "odd")
                self.assertAlmostEqual(keys, T0 + 45 + into, delta=0.06)   # at once...
                self.assertEqual(align, T0 + 45 + 0.5)                     # ...as if it had started on time

    def test_a_click_6_5_s_in_goes_in_our_next_slot(self):
        self.run_to(T0 + 45 + 6.5)
        self.decode(T0 + 30, "CQ DL1ABC JO31", "DL1ABC")
        self.click_last()
        self.run_to(T0 + 75 + 1.0)
        self.assertEqual(len(self.radio.sent), 1)
        self.assertEqual(self.radio.sent[0][3], T0 + 75 + 0.5)
        self.assertIsNone(self.radio.sent[0][4])

    def test_a_new_station_abandons_the_old_qsos_rr73_repeat(self):
        # The old QSO with EA4QRP: we sent RR73 in odd slot T0+15 and their
        # 73 was not heard, so the sequencer repeats RR73, queued 2.5 s into
        # their slot (T0+30) for ours at T0+45.
        self.panel.seq.answer("EA4QRP", "IN80")
        self.panel.seq.rcvd, self.panel.seq.next = "-09", 4
        self.panel.period.set_value("1")
        self.panel.set_tx_enabled(True)
        self.run_to(T0 + 30 + 3.0)
        self.assertEqual(self.radio.sent[-1][:2], ("EA4QRP GM4BRI RR73", "odd"))
        self.assertTrue(self.bridge.st["keyed"])
        # 1 s into our slot, the RR73 already on the air, the operator
        # double-clicks a new CQ from the even slot.
        self.run_to(T0 + 45 + 1.0)
        self.assertTrue(self.bridge.st["txOnAir"])
        self.decode(T0 + 30, "CQ DL1ABC JO31", "DL1ABC")
        click = self.clock.t
        self.click_last()
        self.run_to(T0 + 45 + 5.0)
        self.assertEqual(len(self.radio.halts), 1)              # the RR73 cut short...
        self.assertEqual(self.radio.sent[-1][:2], ("DL1ABC GM4BRI IO75", "odd"))
        self.assertLess(self.radio.sent[-1][3] - click, 1.0)    # ...and the call in its place

    def test_a_queued_repeat_not_yet_on_the_air_is_dropped_at_the_click(self):
        self.panel.seq.answer("EA4QRP", "IN80")
        self.panel.seq.rcvd, self.panel.seq.next = "-09", 4
        self.panel.period.set_value("0")          # ours even this time
        self.panel.set_tx_enabled(True)
        self.run_to(T0 + 15 + 7.0)                 # RR73 queued for T0+30
        self.assertTrue(self.bridge.st["keyed"])
        self.assertFalse(self.bridge.st["txOnAir"])
        # A station heard in the even slot T0 (so ours would be odd): the
        # click comes 7 s into the odd slot T0+15, too late for it.
        self.decode(T0, "CQ DL1ABC JO31", "DL1ABC")
        self.click_last()
        self.assertEqual(len(self.radio.halts), 1)              # RR73 for the old QSO dropped at once
        self.run_to(T0 + 45 + 1.0)
        self.assertEqual([s[:2] for s in self.radio.sent[1:]], [("DL1ABC GM4BRI IO75", "odd")])
        self.assertEqual(self.radio.sent[-1][3], T0 + 45 + 0.5)

    def test_the_operators_choice_already_queued_is_not_cut_and_resent(self):
        self.panel.seq.answer("DL1ABC", "JO31")
        self.panel.period.set_value("1")
        self.clock.t = T0 + 16.0                   # after our odd slot T0+15 could still take it
        self.panel.set_tx_enabled(True)
        self.run_to(T0 + 30 + 3.0)                 # Tx1 queued for T0+45
        self.run_to(T0 + 45 + 0.8)
        self.panel.choose(1)                       # the same Tx1, picked again
        self.run_to(T0 + 45 + 3.0)
        self.assertEqual(self.radio.halts, [])
        self.assertEqual(len(self.radio.sent), 1)

    def test_their_answer_replaces_the_stale_over_before_it_goes_out(self):
        # We called DL1ABC (Tx1) in odd slot T0+15; they answer with a report
        # in even slot T0+30. Our over for T0+45 is queued 2.5 s into T0+30,
        # still Tx1; their report is decoded 13.8 s in.
        self.panel.seq.answer("DL1ABC", "JO31")
        self.panel.period.set_value("1")
        self.clock.t = T0 + 16.0
        self.panel.set_tx_enabled(True)
        self.run_to(T0 + 30 + 13.8)
        self.assertEqual(self.radio.sent[-1][:2], ("DL1ABC GM4BRI IO75", "odd"))
        self.decode(T0 + 30, "GM4BRI DL1ABC -12", "DL1ABC", snr=-8)
        self.run_to(T0 + 45 + 3.0)
        self.assertEqual(len(self.radio.halts), 1)               # dropped before key-up
        self.assertEqual(self.radio.sent[-1][:2], ("DL1ABC GM4BRI R-08", "odd"))
        self.assertEqual(self.radio.sent[-1][3], T0 + 45 + 0.5)  # in the very next slot, on time

    def test_a_late_decode_does_not_cut_an_over_already_on_the_air(self):
        self.panel.seq.answer("DL1ABC", "JO31")
        self.panel.period.set_value("1")
        self.clock.t = T0 + 16.0
        self.panel.set_tx_enabled(True)
        self.run_to(T0 + 45 + 1.0)                 # Tx1 on the air
        self.assertTrue(self.bridge.st["txOnAir"])
        self.decode(T0 + 30, "GM4BRI DL1ABC -12", "DL1ABC")     # a slow decoder's answer
        self.run_to(T0 + 45 + 3.0)
        self.assertEqual(self.radio.halts, [])
        self.run_to(T0 + 75 + 1.0)                 # the reply goes in our next slot
        self.assertEqual(self.radio.sent[-1][0], "DL1ABC GM4BRI R-10")

    def test_their_73_drops_our_queued_rr73_repeat(self):
        self.panel.seq.answer("EA4QRP", "IN80")
        self.panel.seq.rcvd, self.panel.seq.next = "-09", 4
        self.panel.seq.sent_rr73 = True
        self.panel.period.set_value("1")
        self.clock.t = T0 + 16.0
        self.panel.set_tx_enabled(True)
        self.run_to(T0 + 30 + 13.8)                # RR73 repeat queued for T0+45
        self.assertTrue(self.bridge.st["keyed"])
        self.decode(T0 + 30, "GM4BRI EA4QRP 73", "EA4QRP")
        self.assertEqual(self.radio.logged, ["EA4QRP"])
        self.assertFalse(self.panel.tx_enabled)    # logged, done
        self.assertEqual(len(self.radio.halts), 1)
        self.run_to(T0 + 75 + 1.0)
        self.assertEqual(len(self.radio.sent), 1)  # nothing more went out


class ShiftedClock:
    """The engine module's `time` with the wall clock moved by `off`
    seconds: the slot arithmetic sees the time the test wants, everything
    else (monotonic, sleep) is real."""

    def __init__(self, off):
        self.off = off

    def time(self):
        return _time.time() + self.off

    def __getattr__(self, name):
        return getattr(_time, name)


class EngineLateStart(unittest.TestCase):
    """What the engine puts on the air for a late start, on the simulator:
    the tail of the rendered waveform, from where a punctual over would be
    by the time the audio starts. The rendered over is a 1500 Hz tone under
    a rising envelope, so each sample is distinct and the tail can be told
    from the whole."""

    def setUp(self):
        from helpers import make_radio
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        r = self.radio = make_radio(self.tmp, mode="ft8", vfo=10_489_540_000.0, callsign="GM4BRI",
                                    licenceClass="full")
        n = int(OVER * AUDIO_RATE)
        i = np.arange(n)
        self.audio = ((0.1 + 0.8 * i / n) * np.sin(2 * np.pi * 1500 * i / AUDIO_RATE)).astype(np.float32)
        r._render = lambda mode, msg: self.audio.copy()
        self.blocks = []                     # (engine wall time, 12 kHz block) as each is modulated
        self.reqs = []
        real_chain = r._tx_chain
        blocks = self.blocks

        class Recording:
            def __init__(self, mod):
                self.mod = mod

            def __call__(self, a):
                blocks.append((engine.time.time(), np.array(a, copy=True)))
                return self.mod(a)

            def __getattr__(self, name):
                return getattr(self.mod, name)

        def chain(req):
            self.reqs.append(req)
            mod, src = real_chain(req)
            return Recording(mod), src
        r._tx_chain = chain
        r.start()
        self.addCleanup(r.stop)

    def send_at(self, into, late_start=True):
        """send() as if `into` s into an odd (our) FT8 slot."""
        now = _time.time()
        target = math.floor(now / 30) * 30 + 15 + 30 + into
        p = mock.patch.object(engine, "time", ShiftedClock(target - now))
        p.start()
        self.addCleanup(p.stop)
        self.radio.send("ft8", text="DL1ABC GM4BRI IO75", freq=1500.0, period="odd", late_start=late_start)
        return math.floor(target / 15) * 15

    def wait_over(self, timeout=30.0):
        t0 = _time.monotonic()
        while not self.radio.tx_idle() and _time.monotonic() - t0 < timeout:
            self.radio.heartbeat()
            _time.sleep(0.02)
        self.assertFalse(self.radio.state()["keyed"])

    def test_4_and_5_9_s_in_send_the_tail_aligned_to_the_slot(self):
        for into in (4.0, 5.9):
            with self.subTest(into=into):
                self.blocks.clear()
                slot = self.send_at(into)
                self.wait_over()
                req = self.reqs[-1]
                self.assertEqual(req["align_t0"], slot + 0.5)
                skip = int(round(req["skipped_s"] * AUDIO_RATE))
                t_first, first = self.blocks[0]
                # The first block on the air is the waveform from `skip`...
                np.testing.assert_array_equal(first, self.audio[skip:skip + len(first)])
                # ...and `skip` is where a punctual over (audio from 0.5 s
                # into the slot) had got to when this audio began.
                self.assertAlmostEqual(skip / AUDIO_RATE, t_first - (slot + 0.5), delta=0.1)
                self.assertGreater(skip / AUDIO_RATE, into - 0.5 - 0.05)
                # Nothing after the waveform's end: the tail, then silence.
                sent = np.concatenate([b for _t, b in self.blocks])
                np.testing.assert_array_equal(sent[:len(self.audio) - skip], self.audio[skip:])
                self.assertFalse(np.any(sent[len(self.audio) - skip:]))

    def test_without_late_start_or_past_the_limit_it_waits_for_the_next_slot(self):
        for into, late in ((4.0, False), (6.5, True)):
            with self.subTest(into=into, late_start=late):
                slot = self.send_at(into, late)
                req = self.reqs[-1] if self.reqs else None
                self.assertEqual(self.radio.state()["txStartAt"], slot + 30.5)
                self.radio.halt()
                self.wait_over()
                self.assertNotIn("align_t0", req or {})


if __name__ == "__main__":
    unittest.main()
