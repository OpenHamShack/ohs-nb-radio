"""FT8/FT4 slots with too little audio to decode are said in the log, with
why (ohscore/modes/ft8.py Decoder._skip). On 17/10/2026 a Windows PC got 37 %
of the Pluto's stream over a Tailscale relay; every slot was skipped for
want of audio and nothing was logged, even with -v. The decoder here is
fed by time, as the engine feeds it, with stretches missing; a stand-in
for ohsdigi makes it a decoder on a machine without one, and no decode is
ever started (what a decode does is test_modes_ft8's business)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import threading
import types
import unittest
from unittest import mock

import numpy as np

from ohscore.modes import ft8

FS = 12_000
T0 = 1_791_000_000.0          # a slot boundary for both modes
STAND_IN = types.SimpleNamespace(ft8_decode=lambda *a, **k: [], ft4_decode=lambda *a, **k: [])


class Quiet(ft8.Decoder):
    """Counts the decodes it would start instead of starting them."""

    def __init__(self, *a, **kw):
        self.started = []
        super().__init__(lambda e: None, *a, ohsdigi=STAND_IN, **kw)

    def _start(self, run, pcm, after):
        self.started.append(run.slot_t0)
        th = threading.Thread(target=lambda: None)
        th.start()
        return th


def feed(dec, start_s, end_s, keep=1.0, block=900):
    """Audio from start_s to end_s after T0, with only the first `keep` of
    every second arriving - a stream short of samples."""
    a = int(start_s * FS)
    while a < int(end_s * FS):
        if (a % FS) < keep * FS:
            dec.feed(np.zeros(block, np.float32), T0 + a / FS)
        a += block


class Skips(unittest.TestCase):
    def logs(self, dec, *spans, keep=1.0):
        with self.assertLogs("ohscore.modes.ft8", "DEBUG") as said:
            for a, b in spans:
                feed(dec, a, b, keep)
        return [r for r in said.records if "not decoded" in r.getMessage()]

    def test_a_short_stream_is_said_at_info_once_a_minute_with_a_count(self):
        dec = Quiet(variant="ft8")
        clock = [1000.0]
        with mock.patch.object(ft8.time, "monotonic", lambda: clock[0]):
            # A slot is judged when the next begins. The first is whole in
            # time but 37 % present: said at INFO, with the share.
            recs = self.logs(dec, (0, 16.0), keep=0.37)
            self.assertEqual([r.levelname for r in recs], ["INFO"])
            self.assertRegex(recs[0].getMessage(), r"only 3[78] % of its audio arrived")   # 900-sample blocks
            self.assertIn("losing samples", recs[0].getMessage())
            # The next three slots, within the minute: DEBUG only.
            clock[0] += 45.0
            recs = self.logs(dec, (16.0, 61.0), keep=0.37)
            self.assertEqual([r.levelname for r in recs], ["DEBUG"] * 3)
            # A minute on: INFO again, with how many were skipped meanwhile.
            clock[0] += 20.0
            recs = self.logs(dec, (61.0, 76.0), keep=0.37)
            self.assertEqual([r.levelname for r in recs], ["INFO"])
            self.assertIn("4 slots skipped so in the last 65 s", recs[0].getMessage())
        self.assertEqual(dec.started, [])

    def test_joining_part_way_through_is_expected_and_only_debug(self):
        dec = Quiet(variant="ft8")
        recs = self.logs(dec, (10.0, 31.0))       # joins 10 s into a slot, then a whole one
        self.assertEqual([(r.levelname, "joined part-way" in r.getMessage()) for r in recs], [("DEBUG", True)])
        self.assertIn(T0 + 15.0, dec.started)       # the whole slot is decoded

    def test_a_whole_stream_skips_nothing(self):
        dec = Quiet(variant="ft4")
        with self.assertNoLogs("ohscore.modes.ft8", "INFO"):
            feed(dec, 0.0, 30.0)
        self.assertEqual(sorted(set(dec.started)), [T0 + 7.5 * i for i in range(4)])


if __name__ == "__main__":
    unittest.main()
