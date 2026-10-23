"""ohsnb.analyse_digital.other_modes_report: FT4, Q65, JS8 and PSK31
decode counts beside the base report's own FT8. Behavioural throughout:
real encoded signals (ohscore.modes.ft8/q65/psk's own Encoder classes,
ohscore.devices.simsignals.analytic placing them in wideband IQ exactly as
tests/test_ohsnb_analyse.py's own Ft8JT9VsOhsdigi does for FT8) decoded by
the function under test and checked against what it reports - not a
string in its source.

JS8 has no encoder to build a fixture from (ohscore/modes/js8.py's own
module docstring); its slot is exercised through _decode_slotted directly
with a bare-bones fake Decoder instead, which still proves the
dummy-sample "flush the last slot" mechanism js8.py and q65.py share
(q65's own real end-to-end test below is the other, load-bearing half of
that proof)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import math
import time
import unittest
from unittest import mock

import numpy as np

from ohscore.devices import simsignals
from ohscore.dsp.bank import Geometry, Source, Synthesis
from ohscore.modes import ft8 as ft8mod
from ohscore.modes import js8 as js8mod
from ohscore.modes import psk as pskmod
from ohscore.modes import q65 as q65mod

from ohsnb import analyse_digital, bandplan

FS = 240_000.0     # wideband test rate, as tests/test_ohsnb_analyse.py's Ft8JT9VsOhsdigi uses
NOISE_STD = 0.01


def _embed(geo, audio_real, offset_hz, gain, noise_std, seed):
    """A mode's own rendered real audio (12 kHz), analytic (USB), placed
    `offset_hz` from DC in a noisy wideband complex stream - the same
    construction Ft8JT9VsOhsdigi uses."""
    one_sided = simsignals.analytic(audio_real)
    d = geo.decimation_for(12_000.0)
    src = Source(geo, d, freq=offset_hz, gain=gain)
    synth = Synthesis(geo)
    m = len(one_sided) // src.hop
    wide_sig = synth.render(m, [(src, one_sided[:m * src.hop])])
    rng = np.random.default_rng(seed)
    noise = (rng.standard_normal(len(wide_sig)) + 1j * rng.standard_normal(len(wide_sig))).astype(np.complex64)
    return (wide_sig + noise * np.float32(noise_std)).astype(np.complex64)


def _fixture(wide, dc_hz):
    view = np.stack([wide.real, wide.imag], axis=1).astype(np.float32)
    caps = [{"core:sample_start": 0, "core:frequency": dc_hz}]
    info = {"lnb_lo_hz": None, "nominal_dc_flat": None}
    return view, len(wide), caps, info


@unittest.skipUnless(ft8mod.CAN_ENCODE["ft4"], "no FT4 encoder (ohsdigi or ft4code)")
class Ft4RealDecode(unittest.TestCase):
    """A real FT4 message, at FT4's own QO-100 calling frequency (shared
    with FT8 - ohsnb.bandplan's "FT8" preset), decoded by
    other_modes_report's own channel-audio-plus-Decoder path."""

    OFFSET_HZ = 1700.0
    TEXT = "CQ GM4BRI IO86"

    def test_the_message_is_found_bucketed_and_dialled_right(self):
        geo = Geometry(FS)
        audio = ft8mod.Encoder().render(text=self.TEXT, variant="ft4", offset=self.OFFSET_HZ)
        wide = _embed(geo, audio, self.OFFSET_HZ, gain=0.01, noise_std=NOISE_STD, seed=1)
        dial = next(p["dl"] for p in bandplan.PRESETS if p["name"] == "FT8")
        dc_hz = dial - self.OFFSET_HZ
        view, n, caps, info = _fixture(wide, dc_hz)
        slot_s = ft8mod.SLOT_S["ft4"]
        start_utc = math.floor(time.time() / slot_s) * slot_s + 0.5
        r = analyse_digital.other_modes_report(view, 1.0, n, FS, caps, info, 0.0, [], start_utc,
                                               bucket_s=3600.0)
        ft4 = r["ft4"]
        self.assertTrue(ft4["available"])
        self.assertEqual(ft4["total"], 1)
        self.assertEqual(ft4["buckets"], [{"t0": 0.0, "decodes": 1}])
        self.assertEqual(len(ft4["dial_mhz_seen"]), 1)
        # dial_mhz_seen is where the decode actually was (dial + jt9's own
        # df), not the bare calling frequency: the message was placed
        # OFFSET_HZ above it on purpose, same as a real station's own tone.
        self.assertAlmostEqual(ft4["dial_mhz_seen"][0], (dial + self.OFFSET_HZ) / 1e6, delta=0.0005)


@unittest.skipUnless(q65mod.CAN_ENCODE, "no q65code to build a fixture")
class Q65RealDecode(unittest.TestCase):
    """Q65's Decoder has no explicit "flush the last slot" call (unlike
    FT8/FT4's); _decode_slotted instead feeds one dummy sample timestamped
    past the period's end. A real decode succeeding is the proof that
    mechanism actually flushes q65.py's own pending slot rather than
    silently losing it - the message is 51 of Q65-60A's 60 s period, so
    feed() never sees "the next slot" on its own."""

    OFFSET_HZ = 1500.0
    TEXT = "CQ GM4BRI IO86"

    def test_the_last_slot_is_flushed_and_decoded(self):
        geo = Geometry(FS)
        audio = q65mod.Encoder().render(text=self.TEXT, offset=self.OFFSET_HZ)
        wide = _embed(geo, audio, self.OFFSET_HZ, gain=0.01, noise_std=NOISE_STD, seed=2)
        dial = next(p["dl"] for p in bandplan.PRESETS if p["name"] == "Q65-60A")
        dc_hz = dial - self.OFFSET_HZ
        view, n, caps, info = _fixture(wide, dc_hz)
        start_utc = math.floor(time.time() / q65mod.PERIOD_S) * q65mod.PERIOD_S + 0.5
        r = analyse_digital.other_modes_report(view, 1.0, n, FS, caps, info, 0.0, [], start_utc,
                                               bucket_s=3600.0)
        q65 = r["q65"]
        self.assertTrue(q65["available"])
        self.assertEqual(q65["total"], 1)
        self.assertEqual(q65["buckets"], [{"t0": 0.0, "decodes": 1}])
        self.assertAlmostEqual(q65["dial_mhz_seen"][0], (dial + self.OFFSET_HZ) / 1e6, delta=0.0005)


@unittest.skipUnless(pskmod.FS, "psk module import failed")
class Psk31RealDecode(unittest.TestCase):
    """A real PSK31 message, placed in the "digimodes (2.7 kHz max)"
    segment, decoded by _psk_report's own find_carriers-then-Decoder path
    on *demodulated real audio* (the bug this module's own docstring
    explains: psk.Decoder does not take complex IQ)."""

    TEXT = "CQ CQ DE GM4BRI GM4BRI PSE K"
    CENTER_HZ = 1200.0

    def test_the_message_is_decoded_and_its_dial_is_in_the_right_segment(self):
        geo = Geometry(FS)
        audio = pskmod.Encoder().render(text=self.TEXT, variant="psk31", center=self.CENTER_HZ)
        seg_lo, seg_hi = next((lo, hi) for lo, hi, _label, classes, _maxbw in bandplan.SEGMENTS
                              if classes == {"digital", "cw"} and (hi - lo) > 10_000.0)
        centre = (seg_lo + seg_hi) / 2.0
        dc_hz = centre - self.CENTER_HZ
        wide = _embed(geo, audio, self.CENTER_HZ, gain=0.03, noise_std=0.002, seed=3)
        view, n, caps, info = _fixture(wide, dc_hz)
        r = analyse_digital.other_modes_report(view, 1.0, n, FS, caps, info, 0.0, [], 0.0,
                                               bucket_s=3600.0, psk_window_s=20.0)
        psk31 = r["psk31"]
        self.assertTrue(psk31["available"])
        self.assertGreater(psk31["total"], 0)
        self.assertTrue(all(seg_lo / 1e6 <= d <= seg_hi / 1e6 for d in psk31["dial_mhz_seen"]))


class NotAvailable(unittest.TestCase):
    def test_a_mode_with_no_decoder_installed_says_so_rather_than_fail(self):
        geo = Geometry(FS)
        n = int(5.0 * FS)
        rng = np.random.default_rng(4)
        wide = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64) * 0.01
        dc_hz = bandplan.BEACONS["middle"]["ref"]
        view, n, caps, info = _fixture(wide, dc_hz)
        with mock.patch.object(q65mod, "CAN_DECODE", False), mock.patch.object(js8mod, "CAN_DECODE", False), \
             mock.patch.object(ft8mod, "CAN_DECODE", False):
            r = analyse_digital.other_modes_report(view, 1.0, n, FS, caps, info, 0.0, [], 0.0, bucket_s=600.0)
        for mode in ("ft4", "q65", "js8"):
            self.assertFalse(r[mode]["available"])
            self.assertTrue(r[mode]["why"])
            self.assertEqual(r[mode]["buckets"], [])


class BucketingArithmetic(unittest.TestCase):
    """analyse_digital._bucket_slotted directly: slot time bucketed
    relative to the recording's own start, each decode's dial from the
    mode's own preset plus jt9's df, and a timeline covering the whole
    file even past the last real decode."""

    def test_events_land_in_the_right_bucket_with_the_right_dial(self):
        start_utc = 1_000_000.0
        events = [{"slot": start_utc + 5.0, "df": 120, "text": "A"},
                 {"slot": start_utc + 605.0, "df": -30, "text": "B"}]
        buckets, dials = analyse_digital._bucket_slotted(events, start_utc, dial_hz=10_489_540_000.0,
                                                          bucket_s=600.0, total_s=1800.0)
        self.assertEqual(buckets, [{"t0": 0.0, "decodes": 1}, {"t0": 600.0, "decodes": 1},
                                   {"t0": 1200.0, "decodes": 0}])
        self.assertAlmostEqual(dials[0], (10_489_540_000.0 + 120) / 1e6, places=6)
        self.assertAlmostEqual(dials[1], (10_489_540_000.0 - 30) / 1e6, places=6)

    def test_no_events_still_covers_the_whole_file(self):
        buckets, dials = analyse_digital._bucket_slotted([], 0.0, 10_489_540_000.0, 600.0, 1250.0)
        self.assertEqual(len(buckets), 3)
        self.assertEqual([b["decodes"] for b in buckets], [0, 0, 0])
        self.assertEqual(dials, [])


class FlushesTheLastPartialSlot(unittest.TestCase):
    """analyse_digital._decode_slotted's two flush strategies - JS8 has no
    encoder to build a real fixture from (see this file's own docstring),
    so its path is exercised here with a bare-bones fake Decoder that
    records how it was flushed."""

    class _Fake:
        def __init__(self, emit):
            self.emit = emit
            self._busy = 0
            self.fed: list[tuple[int, float]] = []
            self.closed = False
            self.explicit_closed = False

        def feed(self, audio, t):
            self.fed.append((len(audio), t))

        def _close(self):
            self.explicit_closed = True

        def close(self):
            self.closed = True

    def test_explicit_close_is_called_once_for_ft8_shaped_decoders(self):
        audio = np.zeros(12_000, dtype=np.float32)
        made = []

        def make(emit):
            d = self._Fake(emit)
            made.append(d)
            return d
        events = analyse_digital._decode_slotted(make, [audio], 0.0, period_s=15.0, explicit_close=True)
        self.assertEqual(events, [])
        self.assertTrue(made[0].explicit_closed)
        self.assertTrue(made[0].closed)

    def test_a_dummy_sample_past_the_period_flushes_q65_js8_shaped_decoders(self):
        audio = np.zeros(12_000, dtype=np.float32)
        made = []

        def make(emit):
            d = self._Fake(emit)
            made.append(d)
            return d
        analyse_digital._decode_slotted(make, [audio], 100.0, period_s=60.0, explicit_close=False)
        fake = made[0]
        self.assertFalse(fake.explicit_closed)
        # The real feed calls (one per second of audio) plus exactly one
        # more, timestamped a whole period past the last real sample.
        self.assertEqual(len(fake.fed), 2)
        last_len, last_t = fake.fed[-1]
        self.assertEqual(last_len, 1)
        self.assertAlmostEqual(last_t, 100.0 + 1.0 + 60.0, places=6)


if __name__ == "__main__":
    unittest.main()
