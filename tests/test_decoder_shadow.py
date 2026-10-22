import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""The second FT8/FT4 decoder beside the first (ohscore/modes/decoder_shadow.py).

Since 07/10/2026 ohsdigi decodes and jt9 is the shadow; with "ft8Decoder"
set to jt9, the other way round. What matters here: the shadow never
emits, never delays or breaks the decodes the operator sees, is given
exactly the samples and calls the first decoder had, and a disagreement
is logged and counted for the diagnostics report.

Most of it runs against a stand-in for ohsdigi, so it needs only jt9; the
last class runs the real extension (`tools/build-ohsdigi.sh --host
--install` first).
"""
import logging
import os
import threading
import time
import types
import unittest
from unittest import mock

import numpy as np

from ohscore import diag
from ohscore.modes import ft8, decoder_shadow

FS = 12_000.0


def _fake(decodes, raises=False):
    """A stand-in ohsdigi: decodes are ohsdigi's own dicts (freq, ap, qual)."""
    m = types.SimpleNamespace()

    def dec(pcm16, depth=1, mycall="", dxcall=""):
        dec.calls.append((len(pcm16), depth, mycall, dxcall))
        if raises:
            raise RuntimeError("boom")
        return [dict(d) for d in decodes]

    dec.calls = []
    m.ft8_decode = dec
    m.ft4_decode = dec
    return m


def _d(text, freq=1500.0, dt=0.0, snr=-5, ap=0, qual=1.0):
    return {"text": text, "freq": freq, "dt": dt, "snr": snr, "ap": ap, "qual": qual}


class Enabled(unittest.TestCase):
    def test_on_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(decoder_shadow.ENV, None)
            self.assertTrue(decoder_shadow.enabled())

    def test_values(self):
        for v, want in (("yes", True), ("1", True), ("", True), ("0", False), ("off", False), ("no", False)):
            with mock.patch.dict(os.environ, {decoder_shadow.ENV: v}):
                self.assertEqual(decoder_shadow.enabled(), want, v)


class Pairing(unittest.TestCase):
    def test_pairs_by_frequency_and_dt(self):
        a = [{"text": "CQ K1ABC FN42", "df": 1234, "dt": 0.1},
             {"text": "K1ABC W9XYZ EN37", "df": 600, "dt": -0.3}]
        b = [{"text": "CQ K1ABC FN42", "df": 1234, "dt": 0.1},
             {"text": "K1ABC W9XYZ EN37", "df": 2000, "dt": 0.0}]
        pairs, only_a, only_b = decoder_shadow.pair(a, b)
        self.assertEqual([(p[0]["df"], p[1]["text"]) for p in pairs], [(1234, "CQ K1ABC FN42")])
        self.assertEqual([e["df"] for e in only_a], [600])
        self.assertEqual([o["df"] for o in only_b], [2000])

    def test_ohsdigis_own_dicts_pair_too(self):
        # ohsnb.analyse's older captures held ohsdigi's raw dicts ("freq").
        pairs, _, _ = decoder_shadow.pair([{"text": "A", "df": 1000, "dt": 0.0}],
                                          [{"text": "A", "freq": 1000.4, "dt": 0.05}])
        self.assertEqual(len(pairs), 1)

    def test_same_place_different_text_does_not_pair(self):
        pairs, only_a, only_b = decoder_shadow.pair([{"text": "A", "df": 1000, "dt": 0.0}],
                                                    [{"text": "B", "df": 1000, "dt": 0.0}])
        self.assertEqual((len(pairs), len(only_a), len(only_b)), (0, 1, 1))

    def test_one_partner_each(self):
        a = [{"text": "A", "df": 1000, "dt": 0.0}, {"text": "A", "df": 1001, "dt": 0.0}]
        pairs, only_a, only_b = decoder_shadow.pair(a, [{"text": "A", "df": 1000, "dt": 0.0}])
        self.assertEqual((len(pairs), len(only_a), only_b), (1, 1, []))

    def test_dt_too_far(self):
        pairs, only_a, only_b = decoder_shadow.pair([{"text": "A", "df": 1000, "dt": 0.0}],
                                                    [{"text": "A", "df": 1000, "dt": 0.3}])
        self.assertEqual((len(pairs), len(only_a), len(only_b)), (0, 1, 1))


class Record(unittest.TestCase):
    def setUp(self):
        decoder_shadow.reset()
        self.addCleanup(decoder_shadow.reset)

    def test_a_disagreement_is_one_info_line_naming_both_sides(self):
        with self.assertLogs("ohscore.modes.ohsdigi", logging.INFO) as cm:
            res = decoder_shadow.record("ft8", 0.0, "ohsdigi", [{"text": "CQ Y", "df": 1500, "dt": 0.0}], 0.05,
                                        "jt9", [{"text": "CQ X", "df": 900, "dt": 0.0}], 0.2)
        self.assertEqual((res["ohsdigi"], res["jt9"], res["both"]), (1, 1, 0))
        self.assertEqual(len(cm.output), 1)
        self.assertIn("ohsdigi only: CQ Y", cm.output[0])
        self.assertIn("jt9 only: CQ X", cm.output[0])

    def test_agreement_is_not_logged_at_info(self):
        ev = [{"text": "CQ X", "df": 900, "dt": 0.0}]
        with self.assertLogs("ohscore.modes.ohsdigi", logging.DEBUG) as cm:
            decoder_shadow.record("ft8", 0.0, "ohsdigi", ev, 0.05, "jt9", ev, 0.2)
        self.assertEqual([r.levelno for r in cm.records], [logging.DEBUG])

    def test_counts_reach_the_diagnostics_report(self):
        ev = [{"text": "CQ X", "df": 900, "dt": 0.0}]
        decoder_shadow.record("ft8", 0.0, "ohsdigi", ev, 0.05, "jt9", ev, 0.2)
        with self.assertLogs("ohscore.modes.ohsdigi", logging.INFO):
            decoder_shadow.record("ft8", 15.0, "ohsdigi", ev, 0.07, "jt9", [], 0.3)
            decoder_shadow.failed("ft8", "jt9", RuntimeError("no jt9"))
        report = diag.build_report({"app": "Test"}, {})
        self.assertIn("== ft8/ft4 decoder comparison ==", report)
        self.assertIn("ft8: ohsdigi, jt9 shadowing: 2 passes; decodes ohsdigi 2, jt9 1, both 1, ohsdigi only 1, "
                      "jt9 only 0; passes that disagreed 1", report)
        self.assertIn("ohsdigi 0.060 s mean, 0.070 s worst", report)
        self.assertIn("ohsdigi only: CQ X @900 Hz +0.0 s", report)
        self.assertIn("ft8: jt9 shadow failures: 1", report)

    def test_no_section_before_anything_was_compared(self):
        self.assertNotIn("decoder comparison", diag.build_report({"app": "Test"}, {}))

    def test_a_shadow_failure_is_logged_in_full_once(self):
        with self.assertLogs("ohscore.modes.ohsdigi", logging.WARNING) as cm:
            for _ in range(3):
                decoder_shadow.failed("ft8", "jt9", RuntimeError("boom"))
        self.assertEqual(len(cm.output), 1)
        self.assertEqual(decoder_shadow.summary(), {"ft8: jt9 shadow failures": 3})


def _feed_one_slot(dec, audio):
    slot_n = int(round(15 * FS))
    padded = np.zeros(slot_n, dtype=np.float32)
    padded[:len(audio)] = audio[:slot_n]
    t = 0.0
    for i in range(0, slot_n, 1200):
        dec.feed(padded[i:i + 1200], t=t)
        t += 1200 / FS
    dec.feed(np.zeros(1200, dtype=np.float32), t=t)


def _settle(dec, timeout=20.0):
    deadline = time.monotonic() + timeout
    while dec._busy and time.monotonic() < deadline:
        time.sleep(0.01)


@unittest.skipUnless(ft8._JT9 and ft8.CAN_ENCODE["ft8"], "no jt9")
class InTheDecoder(unittest.TestCase):
    """The shadow beside a real jt9, with a stand-in ohsdigi either side of
    it: the first decoder's events are what is emitted, the shadow's never
    are, and the shadow sees what the first decoder saw."""

    MSG = "CQ GM4BRI IO86"

    def setUp(self):
        decoder_shadow.reset()
        self.addCleanup(decoder_shadow.reset)
        self.recorded = []
        real = decoder_shadow.record

        def spy(*a):
            self.recorded.append(a)
            return real(*a)
        p = mock.patch.object(decoder_shadow, "record", side_effect=spy)
        p.start()
        self.addCleanup(p.stop)
        e = mock.patch.dict(os.environ, {decoder_shadow.ENV: "1"})
        e.start()
        self.addCleanup(e.stop)

    def _run(self, fake, choice="auto", calls=None):
        audio = ft8.Encoder().render(text=self.MSG, variant="ft8", offset=1500.0)
        events = []
        dec = ft8.Decoder(events.append, variant="ft8", calls=calls, decoder=choice, ohsdigi=fake)
        try:
            _feed_one_slot(dec, audio)
            _settle(dec)
        finally:
            dec.close()
        return events

    def test_ohsdigi_decodes_and_jt9_checks_it(self):
        # The slot starts with the signal, so jt9 says DT -0.5.
        fake = _fake([_d(self.MSG, freq=1500.2, dt=-0.46), _d("CQ Z9ZZ AA00", freq=2500.0)])
        with self.assertLogs("ohscore.modes.ohsdigi", logging.INFO) as cm:
            events = self._run(fake)
        # Emitted: ohsdigi's two, each once over both passes. jt9's, never.
        self.assertEqual(sorted(e["text"] for e in events), ["CQ GM4BRI IO86", "CQ Z9ZZ AA00"])
        self.assertTrue(self.recorded)
        variant, _slot, primary, p_events, _ps, shadow, s_events, _ss = self.recorded[0]
        self.assertEqual((variant, primary, shadow), ("ft8", "ohsdigi", "jt9"))
        self.assertEqual([e["text"] for e in s_events], [self.MSG])
        # The made-up decode is jt9's disagreement, and the log says so.
        self.assertTrue(any("ohsdigi only: CQ Z9ZZ AA00" in line for line in cm.output), cm.output)
        self.assertNotIn("jt9 only", " ".join(cm.output))

    def test_jt9_first_and_ohsdigi_the_shadow(self):
        fake = _fake([])
        events = self._run(fake, choice="jt9")
        self.assertEqual([e["text"] for e in events], [self.MSG])
        self.assertEqual({(r[2], r[5]) for r in self.recorded}, {("jt9", "ohsdigi")})
        self.assertTrue(fake.ft8_decode.calls)
        self.assertEqual({c[0] for c in fake.ft8_decode.calls}, {2 * 15 * 12000})   # the whole slot, int16

    def test_both_get_the_same_calls(self):
        # The two must do the same a-priori work, or the comparison
        # measures the calls rather than the decoders.
        fake = _fake([])
        self._run(fake, choice="jt9", calls=lambda: ("g4xyz", "PJ4/K1ABC"))
        self.assertEqual({c[2:] for c in fake.ft8_decode.calls}, {("G4XYZ", "PJ4/K1ABC")})

    def test_a_broken_shadow_does_not_touch_the_decodes(self):
        fake = _fake([], raises=True)
        with self.assertLogs("ohscore.modes.ohsdigi", logging.WARNING):
            events = self._run(fake, choice="jt9")
        self.assertEqual([e["text"] for e in events], [self.MSG])
        self.assertEqual(decoder_shadow.summary(), {"ft8: ohsdigi shadow failures": 2})

    def test_off_when_asked(self):
        with mock.patch.dict(os.environ, {decoder_shadow.ENV: "0"}):
            events = self._run(_fake([_d(self.MSG)]))
        self.assertEqual([e["text"] for e in events], [self.MSG])
        self.assertEqual(self.recorded, [])

    def test_the_slot_is_not_busy_until_the_shadow_decode_has_finished(self):
        # ohsnb.analyse (07/10/2026) polls Decoder._busy to know when a
        # slot's work - the decode's and the shadow's - is done, so it can
        # hand back every slot's comparison rather than racing it. The
        # shadow runs on its own thread (so the slot's final pass need not
        # wait for it), counted in _busy from before its pass ends.
        #
        # A single "did it run" flag would not catch a gap: a slot gets
        # two passes, so counting starts against finishes (both passes
        # share this stand-in) is what tells "nothing is still running"
        # from "something ran once".
        lock = threading.Lock()
        started = finished = 0

        def slow_decode(pcm16, depth=1, mycall="", dxcall=""):
            nonlocal started, finished
            with lock:
                started += 1
            time.sleep(0.2)
            with lock:
                finished += 1
            return []

        fake = types.SimpleNamespace(ft8_decode=slow_decode, ft4_decode=slow_decode)
        audio = ft8.Encoder().render(text=self.MSG, variant="ft8", offset=1500.0)
        dec = ft8.Decoder(lambda ev: None, variant="ft8", decoder="jt9", ohsdigi=fake)
        try:
            _feed_one_slot(dec, audio)
            _settle(dec)
            with lock:
                self.assertGreater(started, 0)
                self.assertEqual(finished, started, "a shadow decode was still running when _busy hit 0")
        finally:
            dec.close()


@unittest.skipUnless(ft8._OHSDIGI_DEC is not None and ft8._JT9 and ft8.CAN_ENCODE["ft8"],
                     "ohsdigi extension not built, or no jt9")
class RealExtension(unittest.TestCase):
    """Needs ohscore/ohsdigi.abi3.so with the decoder:
    tools/build-ohsdigi.sh --host --install."""

    def test_agrees_with_jt9_on_a_clean_slot(self):
        rng = np.random.default_rng(3)
        slot = np.zeros(int(15 * FS), np.float32)
        for text, off in (("CQ GM4BRI IO86", 1500.0), ("CQ DL1ABC JO31", 900.0), ("G4XYZ EA4QRP IN80", 2100.0)):
            a = ft8.Encoder().render(text=text, variant="ft8", offset=off) * 0.2
            slot[6000:6000 + len(a)] += a
        slot += rng.normal(0, 0.05, len(slot)).astype(np.float32)
        decoder_shadow.reset()
        self.addCleanup(decoder_shadow.reset)
        recorded = []
        with mock.patch.dict(os.environ, {decoder_shadow.ENV: "1"}), \
                mock.patch.object(decoder_shadow, "record", side_effect=lambda *a: recorded.append(a)):
            dec = ft8.Decoder(lambda ev: None, variant="ft8")
            try:
                _feed_one_slot(dec, slot)
                _settle(dec)
            finally:
                dec.close()
        self.assertTrue(recorded)
        for _v, _s, primary, p_events, _ps, shadow, s_events, _ss in recorded:
            self.assertEqual((primary, shadow), ("ohsdigi", "jt9"))
            pairs, only_p, only_s = decoder_shadow.pair(p_events, s_events)
            self.assertEqual((len(pairs), only_p, only_s), (3, [], []))


if __name__ == "__main__":
    unittest.main()
