"""Broadcast FM in stereo with RDS through Radio's engine (23/10/2026):
shack_sdr's wfm.Receiver in place of the mono demodulator (ohscore/dsp/wfm.py
StereoWfm), on the RSPdx-shaped simulator with shack_sdr's own FM stereo
and RDS test transmitter on the air (ohsradio/devices/simfm.py).

- **Stereo:** a station with its pilot is heard as two channels, 1 kHz
  left and 1.5 kHz right, at 48 kHz; `audio_channels()` (api/status
  audio.stereo) and the meter's `stereo` say so. Without a pilot it is
  mono, as the old demodulator was.
- **RDS** reaches the state as `rds`, the library's field names, null
  until a station's PI is heard.
- **Every retune starts again:** the old station's RDS is cleared at once
  and never shown against the new one; leaving wide FM clears it too.
- **De-emphasis:** the setting reaches the receiver.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from ohscore import sdr
from ohscore.dsp import wfm

from ham_helpers import close, pump
from listen_helpers import make_listener, peak_hz

ONE, TWO = 97_700_000.0, 99_100_000.0
RT = "Hello from the simulated station"
FIELDS = ["pi", "ps", "rt", "pty", "ptyName", "ta", "tp", "ct", "af", "stereo", "ts"]


def power_db(a, hz, rate=48_000.0):
    """The power within 20 Hz of `hz` in `a`, dB."""
    A = np.abs(np.fft.rfft(a * np.hanning(len(a)))) ** 2
    f = np.fft.rfftfreq(len(a), 1 / rate)
    return 10 * np.log10(A[np.abs(f - hz) < 20].sum() + 1e-30)


def on_air(*stations):
    from ohsradio.devices.simfm import FmBand
    return FmBand(list(stations))


def station(hz=ONE, pi=0xC201, ps="SIM ONE", stereo=True, rt=RT, pty=10, level_db=-35.0):
    from ohsradio.devices.simfm import FmStation
    return FmStation(hz, level_db, pi, ps, rt, pty, stereo, 1000.0, 1500.0 if stereo else 0.0)


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class StereoAndRds(unittest.TestCase):
    def radio(self, *stations, vfo=ONE):
        r, audio, dev = make_listener([], vfo=vfo, mode="wfm")
        dev.fm = on_air(*stations)
        self.addCleanup(close, r)
        r.start()
        return r, audio

    def rds(self, r, want=lambda d: d.get("rt"), seconds=30):
        pump(r, seconds, until=lambda: r.state().get("rds") and want(r.state()["rds"]))
        return r.state().get("rds")

    def test_a_stereo_station_is_heard_in_stereo_with_its_rds(self):
        # Strong enough for full stereo: the receiver blends towards mono
        # below 40 dB of stereo SNR (shack_sdr README), and at -35 dBFS in
        # the simulator's noise it sits at about 38.
        r, audio = self.radio(station(level_db=-15.0))
        self.assertIsInstance(r.wfmdemod, wfm.StereoWfm)
        d = self.rds(r)
        self.assertEqual(list(d), FIELDS)
        self.assertEqual((d["pi"], d["ps"], d["rt"], d["pty"], d["ptyName"], d["stereo"]),
                         ("C201", "SIM ONE ", RT, 10, "Pop music", True))
        self.assertIsInstance(d["ts"], float)
        self.assertEqual(r.audio_channels(), 2)
        self.assertEqual(r.wfmdemod.status()["blend"], 1.0)
        audio.chunks = []
        pump(r, 30, until=lambda: sum(len(c) for c in audio.chunks if c.ndim == 2) >= 48_000)
        lr = np.concatenate([c for c in audio.chunks if c.ndim == 2])[-48_000:]
        self.assertAlmostEqual(peak_hz(lr[:, 0]), 1000.0, delta=2.0)
        self.assertAlmostEqual(peak_hz(lr[:, 1]), 1500.0, delta=2.0)
        # Separated, not each channel carrying both tones: the other
        # channel's tone is far down in each (the loop's seam, once every
        # 3 s, is broadband and is why this is not a plain SNR).
        self.assertGreater(power_db(lr[:, 0], 1000.0) - power_db(lr[:, 0], 1500.0), 30.0)
        self.assertGreater(power_db(lr[:, 1], 1500.0) - power_db(lr[:, 1], 1000.0), 30.0)

    def test_the_meter_carries_the_stereo_flag(self):
        r, _audio = self.radio(station())
        meter = r.subscribe("meter", 400)
        self.rds(r)
        got = pump(r, 2, feeds=[meter])["meter"]
        self.assertTrue(got and all(m.get("stereo") is True for m in got[-5:]))

    def test_without_a_pilot_it_is_mono(self):
        r, audio = self.radio(station(stereo=False, ps="SIMNEWS"))
        d = self.rds(r)
        self.assertEqual((d["ps"], d["stereo"]), ("SIMNEWS ", False))
        self.assertEqual(r.audio_channels(), 1)
        audio.chunks = []
        pump(r, 2)
        self.assertTrue(audio.chunks and all(c.ndim == 1 for c in audio.chunks))
        self.assertAlmostEqual(peak_hz(np.concatenate(audio.chunks)[-48_000:]), 1000.0, delta=2.0)

    def test_no_rds_is_null(self):
        r, _audio = self.radio(station(pi=None))
        pump(r, 3, until=lambda: r.audio_channels() == 2)
        self.assertEqual(r.audio_channels(), 2)             # stereo, and still no RDS
        self.assertIsNone(r.state()["rds"])

    def test_a_retune_clears_rds_and_never_shows_the_last_station(self):
        r, _audio = self.radio(station(), station(TWO, pi=0xC5C1, ps="CLASSIC", rt="A quiet piece", pty=14))
        self.assertEqual(self.rds(r)["pi"], "C201")
        resets = []
        real = r.wfmdemod.reset
        r.wfmdemod.reset = lambda: (resets.append(1), real())[1]
        feed = r.subscribe("state", 4000)
        r.set(vfo=TWO)
        self.assertIsNone(r.state()["rds"])                 # at once, not a block later
        self.assertEqual(self.rds(r, want=lambda d: d.get("ps"))["pi"], "C5C1")
        seen = [c["changes"]["rds"] for c in pump(r, 0.2, feeds=[feed])["state"] if "rds" in c["changes"]]
        # Cleared first, then only the new station.
        self.assertIsNone(seen[0])
        self.assertTrue(all(d is None or d["pi"] == "C5C1" for d in seen), seen)
        self.assertEqual(len(resets), 1)
        # A small step is a retune too: the receiver starts again.
        r.set(vfo=TWO + 10_000.0)
        pump(r, 5, until=lambda: len(resets) == 2)
        self.assertEqual(len(resets), 2)

    def test_leaving_wide_fm_clears_it(self):
        r, _audio = self.radio(station())
        self.rds(r)
        r.set(mode="am")
        pump(r, 5, until=lambda: r.state()["rds"] is None)
        self.assertIsNone(r.state()["rds"])
        self.assertEqual(r.audio_channels(), 1)

    def test_the_deemphasis_setting_reaches_the_receiver(self):
        r, _audio = self.radio(station())
        told = []
        real = r.wfmdemod.rx.set_deemphasis
        r.wfmdemod.rx.set_deemphasis = lambda us: (told.append(us), real(us))[1]
        r.set(wfmDeemphasis=75.0)
        pump(r, 5, until=lambda: told)
        self.assertEqual(told, [75.0])
        self.assertEqual(r.wfmdemod.tau_us, 75.0)


class WithoutTheWheel(unittest.TestCase):
    def test_the_mono_demodulator_is_the_fallback(self):
        from unittest import mock
        with mock.patch.object(sdr, "load", return_value=None):
            d = wfm.make_demod(240_000.0, 50.0)
        self.assertIsInstance(d, wfm.WfmDemod)
        self.assertIsNone(d.rds())
        d.reset()                       # nothing to start again, but it answers


if __name__ == "__main__":
    unittest.main()
