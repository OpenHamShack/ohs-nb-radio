"""A zero-IF receiver's DC spike (Brian, 23/10/2026): the RSPdx's own DC
offset and LO leakage stood as a carrier at the exact centre of every
capture, on the trace and down the waterfall.

- **The blocker** (ohscore/dsp/dcblock.py), on numbers: exactly the
  one-pole recurrence whatever the block size; a DC offset with a slowly
  wandering LO leak is taken down by more than 60 dB; a tone 1 kHz from
  the centre loses nothing measurable.
- **On a receiver** (the RSPdx-shaped simulator with a DC offset and LO
  leak added): the wide scope's line is gone and the feed says which bins
  were filled in (`dcBins`, also on api/events' JSON); the DC heard as a
  tone through the demodulator is gone while a carrier 1 kHz from the
  centre is heard as loud as before; `dcBlock` auto is on for zero-IF
  radios and off for the simulator, and off means off.
- **The DC keep-out**, for every mode Radio has, wide FM included: a
  dial tuned onto the centre moves the centre instead, so the passband
  never covers DC.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import math
import time
import unittest

import numpy as np

from ham_helpers import close, make_radio, pump
from listen_helpers import HEARD, ListeningSim, TapAudio

from ohscore.dsp.dcblock import DcBlocker
from ohscore.server.app import spectrum_item
from ohscore.span import DC_GUARD_HZ
from ohsradio import state
from ohsradio.radio import USABLE, Radio

FS = 2_400_000.0
DC = 0.02 + 0.012j            # -32 dBFS: an RSP's residue on a quiet band is about this


def reference(x, mu, m0):
    """The blocker one sample at a time."""
    out, m = np.empty(len(x), np.complex128), m0
    for i, v in enumerate(x):
        out[i] = v - m
        m = m + mu * (v - m)
    return out, m


def tone_at(y, hz, fs):
    """The complex amplitude of `hz` in `y` (a correlation over whole cycles)."""
    t = np.arange(len(y)) / fs
    return complex(np.mean(y * np.exp(-2j * np.pi * hz * t)))


class TheBlocker(unittest.TestCase):
    def test_any_block_size_is_the_one_pole_recurrence(self):
        rng = np.random.default_rng(1)
        x = (rng.standard_normal(5000) + 1j * rng.standard_normal(5000) + 0.3).astype(np.complex64)
        blk = DcBlocker(48_000.0, corner_hz=200.0)
        blk.chunk = 700                   # several chunks inside one block, as at low rates
        m0 = complex(np.mean(x[:1234], dtype=np.complex128))
        got = np.concatenate([blk(x[:1234]), blk(x[1234:1235]), blk(x[1235:4000]), blk(x[4000:])])
        # The first block seeds the estimate with its own mean; after that,
        # sample for sample what the loop gives.
        want, m = reference(x.astype(np.complex128), blk.mu, m0)
        np.testing.assert_allclose(got, want, rtol=0, atol=2e-5)
        self.assertLess(abs(blk.dc - m), 1e-6)            # single precision, scaled by mu

    def test_dc_and_a_wandering_lo_leak_go_and_a_tone_1_khz_off_stays(self):
        n = int(0.5 * FS)
        t = np.arange(n) / FS
        rng = np.random.default_rng(2)
        leak = DC * (1 + 0.05 * np.sin(2 * np.pi * 0.3 * t))          # drifting with temperature
        tone = 0.01 * np.exp(2j * np.pi * 1000.0 * t)
        noise = 1e-3 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
        x = (leak + tone + noise).astype(np.complex64)
        blk = DcBlocker(FS)
        y = np.concatenate([blk(x[a:a + 65_536]) for a in range(0, n, 65_536)])
        tail = slice(int(0.2 * FS), n)                 # after six time constants
        before, after = abs(np.mean(x[tail])), abs(np.mean(y[tail]))
        # The wander is let through at its frequency over the corner (0.3 /
        # 5 Hz: -24 dB of a 5 % wander, -26 dB): about 50 dB down in all.
        self.assertGreater(20 * math.log10(before / after), 45.0)
        a_in, a_out = tone_at(x[tail], 1000.0, FS), tone_at(y[tail], 1000.0, FS)
        self.assertAlmostEqual(20 * math.log10(abs(a_out) / abs(a_in)), 0.0, delta=0.01)
        self.assertLess(abs(math.degrees(np.angle(a_out / a_in))), 1.0)


class Carrier:
    """An unmodulated carrier at `hz`, `level_db` dBFS."""

    def __init__(self, hz, level_db=-40.0):
        self.hz, self.amp = float(hz), 10 ** (level_db / 20)

    def iq(self, t, rx_if):
        return (self.amp * np.exp(2j * np.pi * (self.hz - rx_if) * t)).astype(np.complex64)


class ZeroIfSim(ListeningSim):
    """The RSPdx-shaped simulator with what a zero-IF radio adds at its
    centre: a DC offset and an LO leak wandering slowly around it."""

    def _generate(self, m):
        y = super()._generate(m)
        t = (self.k - len(y) + np.arange(len(y))) / self.fs
        return (y + DC * (1 + 0.05 * np.sin(2 * np.pi * 0.3 * t))).astype(np.complex64)


def zero_if_radio(stations=(), **over):
    import tempfile
    tmp = tempfile.TemporaryDirectory()
    cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
           "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full", "vfo": 7_100_000.0, "mode": "usb",
           **over}
    audio = TapAudio()
    r = Radio(cfg, persist=False, data_dir=tmp.name, audio=audio, device=ZeroIfSim(dict(cfg), FS, stations))
    r._tmp = tmp
    return r, audio


class OnAZeroIfReceiver(unittest.TestCase):
    def wide_lines(self, r, n=6):
        """The last three of the next `n` wide scope lines."""
        feed = r.subscribe("wide", 64)
        lines, end = [], time.monotonic() + 20
        while len(lines) < n and time.monotonic() < end:
            r.heartbeat()
            lines += feed.drain()
            time.sleep(0.02)
        r.unsubscribe(feed)
        self.assertGreaterEqual(len(lines), n)
        return lines[-3:]

    def dc_bin(self, r, line):
        _t, start, bin_hz, db = line
        return int(round((r.centre - start) / bin_hz))

    def test_the_line_goes_and_the_feed_says_which_bins(self):
        r, _audio = zero_if_radio()
        self.addCleanup(close, r)
        r.start()
        pump(r, 5, until=lambda: r.dcblock is not None)
        self.assertIsNotNone(r.dcblock)                      # auto: an RSP is zero-IF
        for line in self.wide_lines(r):
            i = self.dc_bin(r, line)
            db = line[3]
            floor = float(np.median(db))
            self.assertLess(db[i] - floor, 10.0)                 # among the noise, not 30 dB over it
            self.assertEqual(line.dc_bins, (i - 2, i + 2))
            item = spectrum_item("wide", line)
            self.assertEqual(item["dcBins"], [i - 2, i + 2])
        # Off means off: the line is back, standing well clear of the noise,
        # and nothing is filled in.
        r.set(dcBlock="off")
        pump(r, 5, until=lambda: r.dcblock is None)
        self.assertIsNone(r.dcblock)
        for line in self.wide_lines(r):
            i = self.dc_bin(r, line)
            self.assertGreater(line[3][i] - float(np.median(line[3])), 30.0)
            self.assertIsNone(line.dc_bins)
            self.assertNotIn("dcBins", spectrum_item("wide", line))

    def heard(self, r, audio, seconds=1.0):
        pump(r, 5, until=r._rx_settled)
        audio.take()
        pump(r, 30, until=lambda: sum(len(c) for c in audio.chunks) >= int(seconds * HEARD) * 2)
        a = audio.take()[-int(seconds * HEARD):]
        spec = np.abs(np.fft.rfft(a * np.hanning(len(a)))) ** 2
        f = np.fft.rfftfreq(len(a), 1 / HEARD)

        def level(hz):
            return 10 * math.log10(spec[np.abs(f - hz) < 20].sum() + 1e-30)
        return level

    def test_the_dc_heard_as_a_tone_goes_and_a_carrier_1_khz_off_is_heard_as_before(self):
        centre = 7_150_000.0
        r, audio = zero_if_radio([Carrier(centre + 1000.0)], agc="off", rfGain=0.0)
        self.addCleanup(close, r)
        r.start()
        # The dial 1.5 kHz below the centre in USB, so DC is heard at
        # 1500 Hz and the carrier at 2500 Hz. The DC keep-out would never
        # let the dial there; the test pins the centre itself to hear what
        # the blocker does on its own.
        r.set(vfo=centre - 1500.0)
        r.pin_to(centre)
        pump(r, 5, until=lambda: r.centre == centre)
        r.set(dcBlock="off")
        off = self.heard(r, audio)
        r.set(dcBlock="on")
        on = self.heard(r, audio)
        self.assertGreater(off(1500.0) - on(1500.0), 30.0)      # the spike's tone is gone
        self.assertAlmostEqual(on(2500.0), off(2500.0), delta=0.5)

    def test_auto_is_on_for_zero_if_radios_and_off_for_the_simulator(self):
        r = make_radio()
        self.addCleanup(close, r)
        r.start()
        pump(r, 2, until=lambda: not r.reconf)
        self.assertIsNone(r.dcblock)
        r.set(dcBlock="on")
        pump(r, 2, until=lambda: r.dcblock is not None)
        self.assertIsNotNone(r.dcblock)
        for kind in ("pluto", "libresdr", "rtlsdr", "sdrplay", "soapy"):
            with self.subTest(kind=kind):
                self.assertIn(kind, state.REG.spec["device"]["choices"])
        self.assertEqual(state.REG.spec["dcBlock"]["default"], "auto")


class TheDcKeepOut(unittest.TestCase):
    """One rule for every mode: the dial's passband plus DC_GUARD_HZ stays
    clear of the receiver's centre, by moving the centre."""

    def test_every_mode_keeps_its_passband_off_dc(self):
        r, _audio = zero_if_radio(vfo=14_200_000.0)
        self.addCleanup(close, r)
        r.start()
        half = USABLE * FS / 2
        for mode in state.MODES:
            with self.subTest(mode=mode):
                vfo = 98_000_000.0 if mode == "wfm" else 14_200_000.0
                r.set(mode=mode, vfo=vfo)
                pump(r, 5, until=lambda: r.pending_centre is None)
                # Onto the centre, then just inside the keep-out.
                for target in (r.centre, r.centre + 1000.0):
                    r.set(vfo=target)
                    pump(r, 5, until=lambda: r.pending_centre is None)
                    st = r.state()
                    rx, c = st["rxDial"], r.centre
                    edge = r._dial_edge(st)
                    self.assertGreaterEqual(abs(rx - c), edge + DC_GUARD_HZ, (mode, rx, c))
                    self.assertLessEqual(abs(rx - c) + edge, half, (mode, rx, c))
                if mode == "wfm":
                    self.assertGreaterEqual(abs(r.state()["rxDial"] - r.centre), 90_000.0 + DC_GUARD_HZ)
                    self.assertEqual(r._dial_edge(r.state()), 100_000.0)


if __name__ == "__main__":
    unittest.main()
