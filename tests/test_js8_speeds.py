"""JS8's five speeds (Brian, 17/10/2026): all decoded at once, as JS8Call
does, and sent at the one the operator picks, each on its own period.

The speeds' timings are one table (ohscore/modegroups.py JS8_SPEEDS), held
here to ohsdigi's, which is JS8Call's. Keying is only the simulator's."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

import numpy as np

from helpers import make_radio, noise_audio, run_sim
from ohscore import engine
from ohscore.engine import SLOT_LEAD, SLOT_SEC, js8_slot_key
from ohscore.modegroups import JS8_SPEEDS
from ohscore.modes import js8

LB = js8._OHSDIGI_JS8
FS = 12_000
# A minute holds a whole number of periods of every speed (4, 6, 10, 15, 30 s).
MINUTE = 60.0
T0 = 1_700_000_040.0          # a whole minute (UTC)

# One frame per speed, each on its own offset.
OFFSETS = {"slow": 600.0, "normal": 1000.0, "fast": 1400.0, "turbo": 1900.0, "ultra": 2500.0}
CALLS = {"slow": "G4XYZ", "normal": "DL1ABC", "fast": "F5KLM", "turbo": "OH8ZZ", "ultra": "SV1QO"}


def minute_of_frames(level=0.05, seed=4):
    """60 s of noise with one CQ at each speed, each starting where its
    speed starts a frame, in that speed's first period of the minute."""
    x = np.random.default_rng(seed).standard_normal(int(MINUTE * FS)).astype(np.float32) * 0.05
    for speed, off in OFFSETS.items():
        frame, i3 = js8.frames("CQ CQ CQ", CALLS[speed], speed=speed)[0]
        a = np.frombuffer(LB.js8_encode_audio(frame, i3, speed, off), "<f4")
        s = int(round(JS8_SPEEDS[speed].start * FS))
        x[s:s + len(a)] += a * level
    return x


@unittest.skipUnless(js8.CAN_ENCODE, "ohsdigi with JS8 is not built here")
class Table(unittest.TestCase):
    def test_the_speeds_are_ohsdigis(self):
        self.assertEqual(set(JS8_SPEEDS), set(LB.JS8_SUBMODES))
        for name, sp in JS8_SPEEDS.items():
            ref = LB.JS8_SUBMODES[name]
            self.assertEqual(sp.letter, ref["letter"], name)
            self.assertEqual(sp.period, ref["period"], name)
            self.assertAlmostEqual(sp.start, ref["start"], places=5)
            self.assertAlmostEqual(sp.duration, ref["duration"], places=5)
            self.assertEqual(sp.spacing, ref["tone_spacing"], name)
            # A frame started as late as allowed still ends in its period.
            self.assertLess(sp.start + sp.late + sp.duration, sp.period, name)
            # The engine times each speed from the same table.
            key = js8_slot_key(name)
            self.assertEqual((SLOT_SEC[key], SLOT_LEAD[key]), (sp.period, sp.start))


@unittest.skipUnless(js8.CAN_ENCODE, "ohsdigi with JS8 is not built here")
class AllSpeeds(unittest.TestCase):
    def decode(self, audio, t0=T0, chunk=0.1):
        got = []
        dec = js8.AllSpeedsDecoder(got.append)
        n = int(chunk * FS)
        for i in range(0, len(audio), n):
            dec.feed(audio[i:i + n], t0 + i / FS)
        # The minute's last periods decode as the next minute's audio opens
        # them; a second of quiet closes every speed's period.
        dec.feed(np.zeros(FS, np.float32), t0 + len(audio) / FS)
        end = time.monotonic() + 15
        while time.monotonic() < end and len({e.get("speed") for e in got if e.get("text")}) < len(OFFSETS):
            time.sleep(0.05)
        time.sleep(0.5)
        dec.close()
        return [e for e in got if e.get("text")]

    def test_each_speed_decodes_its_own_frame_once(self):
        got = self.decode(minute_of_frames())
        by = {}
        for e in got:
            by.setdefault(e["speed"], []).append(e)
        for speed, off in OFFSETS.items():
            evs = by.get(speed, [])
            self.assertEqual(len(evs), 1, (speed, [(e["text"], e["df"]) for e in evs]))
            e = evs[0]
            self.assertEqual(e["call"], CALLS[speed])
            self.assertLess(abs(e["df"] - off), 3 + JS8_SPEEDS[speed].spacing)
            # Its own period: the first of the minute at its speed.
            self.assertEqual(e["slot"], T0)
        # Nothing reported twice, at one speed or across two.
        keys = [(e["frame"], round(e["df"] / 10)) for e in got]
        self.assertEqual(len(keys), len(set(keys)))

    def test_a_frame_two_passes_both_report_is_reported_once(self):
        got = []
        dec = js8.AllSpeedsDecoder(got.append, speeds=())
        ev = {"mode": "js8", "slot": T0, "frame": "238ubAXqP++u", "i3bit": 3, "df": 1200, "text": "x"}
        dec._emit(dict(ev, speed="normal"))
        dec._emit(dict(ev, speed="fast", slot=T0 + 10.0, df=1203))
        self.assertEqual(len(got), 1)
        # The same frame again a minute later is a new transmission.
        dec._emit(dict(ev, slot=T0 + 60.0))
        self.assertEqual(len(got), 2)


@unittest.skipUnless(js8.CAN_ENCODE, "ohsdigi with JS8 is not built here")
class SendAtEachSpeed(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.r = make_radio(self.tmp, audio_source=noise_audio(), mode="js8", vfo=10_489_548_000.0,
                            callsign="GM4BRI", locator="IO75RL")
        self.r.start()
        run_sim(self.r, 0.2)

    def tearDown(self):
        self.r.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_the_waveform_is_ohsdigis_at_each_speed(self):
        enc = js8.Encoder()
        for speed in JS8_SPEEDS:
            frame, i3 = js8.frames("CQ CQ CQ", "GM4BRI", speed=speed)[0]
            got = enc.render(text="CQ CQ CQ", offset=1500.0, callsign="GM4BRI", speed=speed)
            ref = np.frombuffer(LB.js8_encode_audio(frame, i3, speed, 1500.0), "<f4")
            self.assertEqual(len(got), len(ref), speed)
            self.assertAlmostEqual(len(got) / FS, JS8_SPEEDS[speed].duration, delta=0.01)
            self.assertLess(float(np.max(np.abs(got - ref / np.max(np.abs(ref)) * 0.95))), 1e-6, speed)

    def test_each_speed_keys_on_its_own_period_boundary(self):
        # The engine keys at once when a send lands within SLOT_LATE after a
        # period's nominal start (so a reply decoded late still goes out in
        # the next slot), and rendering the over takes real time. On the wall
        # clock this test therefore failed whenever load put the send a few
        # tens of ms past a boundary (start_at = that instant, not the
        # boundary): a race in the test, not in the engine. So the caller's
        # clock is pinned, to just before a boundary, for the send alone;
        # other threads keep the real one.
        real_time, caller = time.time, threading.get_ident()
        for speed, sp in JS8_SPEEDS.items():
            pinned = (int(real_time() / sp.period) + 1) * sp.period + sp.start - 0.3
            with mock.patch.object(engine.time, "time",
                                   lambda: pinned if threading.get_ident() == caller else real_time()):
                self.r.send("js8", text="CQ CQ CQ", part=0, speed=speed)
            st = self.r.state()
            self.assertTrue(st["keyed"], speed)
            k = (float(st["txStartAt"]) - sp.start) / sp.period
            self.assertAlmostEqual(k, round(k), places=5, msg=speed)
            self.r.halt()
            # Unkeyed and the transmit thread gone, before the next speed's.
            run_sim(self.r, 5.0, until=lambda: not self.r.state()["keyed"]
                    and not (self.r.tx_thread and self.r.tx_thread.is_alive()))
            self.assertFalse(self.r.state()["keyed"], speed)

    def test_an_unknown_speed_is_refused(self):
        with self.assertRaises(ValueError):
            self.r.send("js8", text="CQ CQ CQ", part=0, speed="warp")
        self.assertFalse(self.r.state()["keyed"])


if __name__ == "__main__":
    unittest.main()
