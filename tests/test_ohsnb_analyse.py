"""ohsnb --analyse (ohsnb/analyse.py): a report on a SigMF recording, built
without a developer, from a plain read of the samples.

Behavioural, not textual: each test makes a real recording - the beacon
ones through Engine.start_recording on the simulator (exactly what a
tester's recording looks like, with a known LNB error and, in the second
test, a known linear drift substituted for the simulator's own sinusoidal
one so the expected Hz/min is exact), the FT8 one a small SigMF pair built
by hand from ohscore.modes.ft8.Encoder's real waveform (ohsdigi's, falling
back to WSJT-X's ft8code where ohsdigi is not built) placed in a quiet
wideband stream - and then calls analyse() and checks the numbers it
reports, not any string in its source."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import math
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from helpers import make_radio, run_sim
from ohscore import sigmf
from ohscore.devices import simsignals
from ohscore.dsp.bank import Geometry, Source, Synthesis
from ohscore.modes import ft8
from ohscore.modes.ft8 import SLOT_S, Encoder
from ohsnb import analyse


def _wait_saved(radio, timeout=15.0):
    """Until the stopped recording's writer thread is done (ohscore/sigmf.py
    Recorder) and the supervisor has noticed - the same wait test_recording.py
    uses, inlined so this file does not import another test module."""
    deadline = time.monotonic() + timeout
    while radio.rec_closing and time.monotonic() < deadline:
        radio.heartbeat()
        time.sleep(0.02)


class BeaconOffsetAndDrift(unittest.TestCase):
    """The middle beacon's offset and drift, as ohsnb.dsp.lock.BeaconTracker
    measures them when analyse() feeds it the file - the same class and the
    same numbers production beacon lock would reach live."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_known_constant_offset(self):
        # simDriftHz=0: the LNB error the simulator gives is exact and
        # unmoving, so beacon lock's final rxCorr must land on it and
        # report (near) zero drift and wobble.
        r = make_radio(self.dir, simRxErrorHz=23_000.0, simDriftHz=0.0, simSignals=False)
        r.start()
        try:
            path = r.start_recording()
            run_sim(r, 40.0)
            self.assertEqual(r.stop_recording(), path)
            _wait_saved(r)
        finally:
            r.stop()
        report = analyse.analyse(path, self.dir / "out-offset")
        self.assertTrue(report["qo100"])
        mid = report["beacons"]["middle"]
        self.assertTrue(mid["heard"])
        self.assertGreater(mid["median_snr_db"], 10.0)
        lnb = report["beacons"]["lnb"]
        self.assertAlmostEqual(lnb["rx_corr_hz"], 23_000.0, delta=5.0)
        self.assertLess(abs(lnb["drift_hz_per_min"]), 10.0)
        self.assertLess(lnb["wobble_hz_rms"], 5.0)
        # Both beacons either side of the middle one are real signals here
        # too (simSignals only turns off the random station population).
        self.assertTrue(report["beacons"]["lower"]["heard"])
        self.assertTrue(report["beacons"]["upper"]["heard"])
        self.assertTrue((self.dir / "out-offset" / "report.txt").exists())
        self.assertLess((self.dir / "out-offset" / "report.txt").stat().st_size, 2200)
        json.loads((self.dir / "out-offset" / "report.json").read_text())   # must parse

    def test_known_linear_drift(self):
        # The simulator's own drift is a smooth wander with a random phase
        # (ohsnb/devices/sim.py SimDevice.rx_err) - good for proving lock
        # holds through drift, but not a fixed number to check a report
        # against. Substituting a plain ramp after the device is open (nothing
        # reads rx_err before the first block) gives an exact expected
        # Hz/min with everything else - the real beacon signal, the real
        # recorder, the real tracker - unchanged.
        rate_hz_s = 4.0
        r = make_radio(self.dir, simRxErrorHz=20_000.0, simDriftHz=0.0, simSignals=False)
        r.start()
        r.dev.rx_err = lambda t: 20_000.0 + rate_hz_s * t
        try:
            path = r.start_recording()
            run_sim(r, 50.0)
            r.stop_recording()
            _wait_saved(r)
        finally:
            r.stop()
        report = analyse.analyse(path, self.dir / "out-drift")
        lnb = report["beacons"]["lnb"]
        self.assertIsNotNone(lnb["drift_hz_per_min"])
        expected = rate_hz_s * 60.0
        self.assertAlmostEqual(lnb["drift_hz_per_min"], expected, delta=expected * 0.3)
        # A steady ramp has no short-term jitter of its own; what is left is
        # the tracker's own measurement noise, small next to the drift.
        self.assertLess(lnb["wobble_hz_rms"], 10.0)


class AdHocMetaShape(unittest.TestCase):
    """The flat-field recording shape (ohsnb/analyse.py's module docstring;
    ohscore.devices.filedev.FileDevice._segments plays the same two shapes
    back through the real receiver, by the same rule) must reconstruct the
    *nominal* downlink at DC, not the corrected one, from a capture's own
    `core:frequency` and `openhamshack:lnb_lo_hz` - not from the flat
    `openhamshack:centre_downlink_nominal_hz` field, which is RX_CENTRE_DL, the
    *corrected* downlink.

    Found 07/10/2026 by playback and live beacon lock disagreeing with
    this module by ~25 kHz on Brian's real recordings: reading the flat
    field as the nominal figure seeded the tracker's rxCorr on top of a
    dc that already had the correction baked in, so it searched 25 kHz
    from where the beacon actually was. Checked directly against
    `_capture_dc` (what filedev.py's own `_segments` computes for the
    same two shapes) rather than through a simulated recording: the
    beacon tracker's own search can themselves lock onto a wrong
    candidate on a short, population-free (simSignals=False) recording
    regardless of this fix, which tests elsewhere already exercise
    end to end (test_known_constant_offset, test_known_linear_drift) -
    this one isolates the frequency arithmetic from that search
    behaviour entirely."""

    def test_reconstructs_the_standard_recorders_own_figure(self):
        # Built from one of Brian's real recordings (07/10/2026): the
        # per-capture core:frequency the ad hoc script wrote (the SDR's
        # raw tuned frequency, after the LNB) and its flat
        # openhamshack:lnb_lo_hz, versus what ohscore.sigmf.Recorder's own
        # core:frequency convention would have given for the same dish
        # setup - the number this module's beacon/FT8/SSB work all key
        # off, so the two shapes must agree on it exactly.
        raw_hw_if = 739_771_429.1
        lnb_lo = 9_750_000_000.0
        lnb_error = 24_929.1
        standard_nominal_at_dc = raw_hw_if + lnb_lo   # what ohscore.sigmf.Recorder would write
        adhoc_info = {
            "nominal_dc_flat": standard_nominal_at_dc - lnb_error,   # RX_CENTRE_DL: the *corrected* figure
            "lnb_lo_hz": lnb_lo,
        }
        adhoc_cap = {"core:frequency": raw_hw_if}
        self.assertAlmostEqual(analyse._capture_dc(adhoc_cap, adhoc_info), standard_nominal_at_dc, places=3)

    def test_falls_back_to_the_flat_field_with_no_per_capture_frequency(self):
        # Belt and braces: a capture that says nothing at all about where
        # it was tuned still gets *something* (the flat field, uncorrected
        # as it is) rather than this module silently treating the whole
        # recording as unplaceable.
        info = {"nominal_dc_flat": 10_489_746_500.0, "lnb_lo_hz": 9_750_000_000.0}
        self.assertEqual(analyse._capture_dc({}, info), 10_489_746_500.0)

    def test_the_standard_shape_is_untouched_by_an_lnb_lo_it_never_writes(self):
        # ohscore.sigmf.Recorder's own core:frequency already *is* the
        # nominal downlink at DC; a stray openhamshack:lnb_lo_hz (which it
        # never writes, but nothing stops some other tool adding one)
        # must not get added on top of it a second time.
        info = {"nominal_dc_flat": None, "lnb_lo_hz": None}
        cap = {"core:frequency": 10_489_746_500.0}
        self.assertEqual(analyse._capture_dc(cap, info), 10_489_746_500.0)


def _locked_hist(rate_hz_s: float, seconds: float, start_hz: float = 0.0) -> list[dict]:
    """A synthetic beacon-tracker history: `seconds` of "locked" reports at
    BeaconTracker.UPDATE spacing, rxCorr ramping at a known, exact rate -
    the same shape test_known_linear_drift substitutes for the simulator's
    own wander, but built directly (no recording, no engine) since what is
    under test here is only the bucketing arithmetic over an already-built
    history, not the tracker that makes one."""
    from ohsnb.dsp.lock import BeaconTracker
    n = int(seconds / BeaconTracker.UPDATE)
    return [{"t": i * BeaconTracker.UPDATE, "state": "locked",
            "rxCorr": start_hz + rate_hz_s * i * BeaconTracker.UPDATE} for i in range(n)]


class LnbEvening(unittest.TestCase):
    """analyse._lnb_evening: the whole-file drift fit (_beacon_summary's),
    done again inside each bucket_s window, plus whether BeaconTracker's
    own +-50 kHz search and its 0.5 s/60 Hz tracking hysteresis have room
    to spare against what was actually measured."""

    def test_a_steady_drift_reads_the_same_in_every_bucket(self):
        hist = _locked_hist(rate_hz_s=4.0, seconds=1800.0)       # 3 buckets of 10 minutes
        ev = analyse._lnb_evening(hist, bucket_s=600.0)
        self.assertEqual(len(ev["buckets"]), 3)
        for b in ev["buckets"]:
            self.assertAlmostEqual(b["drift_hz_per_min"], 240.0, delta=0.5)   # 4 Hz/s * 60
        self.assertAlmostEqual(ev["excursion_hz"], 4.0 * 1800.0, delta=5.0)
        self.assertAlmostEqual(ev["max_abs_drift_hz_per_min"], 240.0, delta=0.5)
        # 4 Hz/s is a real LNB's whole day (HANDOVER: real ones measured
        # 120-145 Hz/min - 2-2.4 Hz/s); comfortably under both limits.
        self.assertTrue(ev["search_adequate"])
        self.assertTrue(ev["rate_adequate"])

    def test_a_fast_drift_is_flagged_on_both_counts(self):
        # 200 Hz/s: per 0.5 s update that is 100 Hz, well past
        # BeaconTracker.MAX_TRACK_ERR (60 Hz, the "an update this size is an
        # outlier" threshold) even with the 30% margin this function
        # judges by; over 1200 s the excursion alone (240 kHz) is also well
        # past the default +-50 kHz search.
        hist = _locked_hist(rate_hz_s=200.0, seconds=1200.0)
        ev = analyse._lnb_evening(hist, bucket_s=600.0)
        self.assertFalse(ev["rate_adequate"])
        self.assertFalse(ev["search_adequate"])
        self.assertIn("50 kHz", ev["search_why"])

    def test_too_few_locked_points_reports_no_drift_not_a_bad_fit(self):
        # 8 points inside one bucket: under the 10-point floor, so the
        # bucket's own drift is None rather than a line fit through noise.
        from ohsnb.dsp.lock import BeaconTracker
        hist = [{"t": i * BeaconTracker.UPDATE, "state": "locked", "rxCorr": 100.0} for i in range(8)]
        ev = analyse._lnb_evening(hist, bucket_s=600.0)
        self.assertEqual(len(ev["buckets"]), 1)
        self.assertIsNone(ev["buckets"][0]["drift_hz_per_min"])
        self.assertIsNone(ev["max_abs_drift_hz_per_min"])
        self.assertIsNone(ev["rate_adequate"])

    def test_never_locked_says_so_rather_than_crash(self):
        ev = analyse._lnb_evening([{"t": 1.0, "state": "searching", "rxCorr": None}])
        self.assertEqual(ev["buckets"], [])
        self.assertIsNone(ev["search_adequate"])


class LockedWobble(unittest.TestCase):
    """analyse._locked_wobble (and, through it, beacons.lnb.wobble_hz_rms):
    short-term jitter around a *local* trend, fit fresh inside each short
    window - not the residual of one straight line over the whole file,
    which a real multi-hour recording's drift rate changing partway
    through (still locally linear, just not globally so - exactly what a
    real LNB's own warming does over hours) inflates hugely. Found on
    Brian's 3-hour 07/10/2026 recording: a single whole-file fit read
    141.9 Hz rms where every short stretch of it read 5-6 Hz."""

    def _bent_hist(self, rate1, rate2, seconds, jitter_hz, seed=1):
        from ohsnb.dsp.lock import BeaconTracker
        rng = np.random.default_rng(seed)
        n = int(seconds / BeaconTracker.UPDATE)
        half = n // 2
        out = []
        corr = 0.0
        for i in range(n):
            t = i * BeaconTracker.UPDATE
            rate = rate1 if i < half else rate2
            corr += rate * BeaconTracker.UPDATE
            out.append({"t": t, "state": "locked", "rxCorr": corr + jitter_hz * rng.standard_normal()})
        return out

    def test_a_steady_drift_s_wobble_is_just_the_jitter(self):
        hist = self._bent_hist(rate1=4.0, rate2=4.0, seconds=1200.0, jitter_hz=2.0)
        w = analyse._locked_wobble(hist)
        self.assertLess(w, 6.0)

    def test_a_drift_that_reverses_still_reads_only_the_jitter(self):
        # The naive whole-file fit (what _beacon_summary used to report)
        # is wildly inflated by the reversal; the windowed one is not.
        hist = self._bent_hist(rate1=10.0, rate2=-10.0, seconds=1200.0, jitter_hz=2.0)
        t = np.array([e["t"] for e in hist])
        c = np.array([e["rxCorr"] for e in hist])
        slope, intercept = np.polyfit(t - t[0], c, 1)
        naive = float(np.sqrt(np.mean((c - (slope * (t - t[0]) + intercept)) ** 2)))
        windowed = analyse._locked_wobble(hist)
        self.assertGreater(naive, 30.0)
        self.assertLess(windowed, 6.0)

    def test_too_few_locked_samples_is_none_not_a_crash(self):
        self.assertIsNone(analyse._locked_wobble([{"t": 0.0, "state": "locked", "rxCorr": 0.0}]))


def _both_decoders() -> bool:
    return ft8._OHSDIGI_DEC is not None and bool(ft8._JT9)


# Both decoders or nothing: without the ohsdigi extension (a development tree
# that has not run tools/build-ohsdigi.sh) there is no second column to compare.
@unittest.skipUnless(_both_decoders() and ft8.CAN_ENCODE["ft8"], "ohsdigi extension not built, or no jt9")
class Ft8JT9VsOhsdigi(unittest.TestCase):
    """The FT8 table: jt9 and ohsdigi given the same slot, from a signal
    encoded by ohscore.modes.ft8.Encoder (WSJT-X's own waveform, ohsdigi's
    port of it or, where that is not built, ft8code) at a held SNR - both
    must decode it and agree."""

    FS = 240_000.0        # small enough for a fast test, large enough that
                          # the beacon tracker's own channel geometry (not
                          # exercised here) would still be the real design's
    FT8_OFFSET_HZ = 2_000.0   # the signal's place in the test file, from DC
    GAIN = 0.001          # -> about -5 dB SNR as jt9/ohsdigi report it (checked below)
    NOISE_STD = 0.01
    TEXT = "CQ GM4BRI IO86"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_recording(self) -> Path:
        geo = Geometry(self.FS)
        audio = Encoder().render(text=self.TEXT, variant="ft8", offset=1500.0)
        one_sided = simsignals.analytic(audio)        # USB-sided baseband, as a real FT8 transmitter sends
        d = geo.decimation_for(12_000.0)
        src = Source(geo, d, freq=self.FT8_OFFSET_HZ, gain=self.GAIN)
        synth = Synthesis(geo)
        m = len(one_sided) // src.hop
        wide_sig = synth.render(m, [(src, one_sided[:m * src.hop])])
        rng = np.random.default_rng(4)
        noise = (rng.standard_normal(len(wide_sig)) + 1j * rng.standard_normal(len(wide_sig))).astype(np.complex64)
        wide = (wide_sig + noise * np.float32(self.NOISE_STD)).astype(np.complex64)

        dc_hz = analyse.FT8_DIAL_DL - self.FT8_OFFSET_HZ
        base = self.dir / "ft8-fixture"
        data_bytes, clipped = sigmf.to_ci16(wide)
        self.assertEqual(clipped, 0, "the fixture must not clip, or the known SNR is not what was asked for")
        (self.dir / "ft8-fixture.sigmf-data").write_bytes(data_bytes)
        # An FT8 transmission starts 0.5 s into its 15 s slot (ohscore.modes.ft8
        # EARLY_S/SLOT_S); a recording start time with no such alignment (a
        # bare time.time()) puts the encoded burst at a random point in
        # whichever slot it lands in, sometimes straddling 13.5 s and
        # triggering both of jt9's early and final decode passes on a
        # signal that is not where either expects it - flaky and, once,
        # outright undecodable. Aligning the fixture is what a real
        # operator's transmission already does; it is not a licence to
        # skip the two-pass logic, which the other tests still exercise
        # against whatever real IQ gives them.
        slot_s = SLOT_S["ft8"]
        start_utc = math.floor(time.time() / slot_s) * slot_s + 0.5
        meta = {
            "global": {"core:datatype": "ci16_le", "core:sample_rate": self.FS, "core:version": sigmf.SIGMF_VERSION,
                      "core:num_channels": 1, "core:extensions": [dict(sigmf.EXT)],
                      "openhamshack:app": "OpenHamShack NB", "openhamshack:version": "0.0.0-test",
                      "core:description": "test fixture: one encoded FT8 slot in white noise"},
            "captures": [{"core:sample_start": 0, "core:frequency": dc_hz, "core:datetime": sigmf.iso_utc(start_utc)}],
            "annotations": [],
        }
        (self.dir / "ft8-fixture.sigmf-meta").write_text(json.dumps(meta), encoding="utf-8")
        return base

    def test_both_decoders_find_the_same_message(self):
        base = self._make_recording()
        report = analyse.analyse(base, self.dir / "out-ft8")
        f8 = report["ft8"]
        if f8 is None:
            self.skipTest("jt9 is not installed on this machine")
        self.assertEqual(f8["jt9_total"], 1)
        self.assertEqual(f8["ohsdigi_total"], 1)
        self.assertEqual(f8["both"], 1)
        self.assertEqual(f8["jt9_only_total"], 0)
        self.assertEqual(f8["ohsdigi_only_total"], 0)
        self.assertEqual(len(f8["slots"]), 1)
        slot = f8["slots"][0]
        self.assertEqual(slot["jt9"], 1)
        self.assertEqual(slot["ohsdigi"], 1)
        # Both decoders' SNR, in a sane band around what the fixture was built for.
        self.assertAlmostEqual(f8["jt9_snr"]["median"], -5.0, delta=8.0)
        self.assertAlmostEqual(f8["ohsdigi_snr"]["median"], -5.0, delta=8.0)


class AdHocScale(unittest.TestCase):
    """A capture whose device is not full-scale at its container width -
    the Pluto ad hoc recordings of 07/10/2026: ci16, but +-2048, not
    +-32768 - must be read at its own scale, not the datatype's default.
    ohscore.devices.filedev.FileDevice already does this for playback
    (`openhamshack:scale`); analyse.py's own level stats did not, and so read
    every dBFS figure 24 dB (32768/2048) too quiet - a real +4.5 dBFS,
    3743-clipped-sample recording reported +-24 dB headroom and zero
    clipping (found running the extended analysis on Brian's 3-hour
    07/10/2026 recording)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, i, q, scale):
        base = self.dir / "adhoc-scale"
        raw = np.empty(2 * len(i), dtype="<i2")
        raw[0::2], raw[1::2] = i.astype(np.int16), q.astype(np.int16)
        (self.dir / "adhoc-scale.sigmf-data").write_bytes(raw.tobytes())
        meta = {
            "global": {"core:datatype": "ci16_le", "core:sample_rate": 48_000.0, "core:version": sigmf.SIGMF_VERSION,
                      "core:num_channels": 1, "core:recorder": "ohscore.devices.pluto.PlutoDevice",
                      "openhamshack:scale": scale,
                      "core:description": "an ad hoc Pluto capture, +-2048 full scale"},
            "captures": [{"core:sample_start": 0, "core:frequency": 7_100_000.0,
                         "core:datetime": sigmf.iso_utc(time.time())}],
            "annotations": [],
        }
        (self.dir / "adhoc-scale.sigmf-meta").write_text(json.dumps(meta), encoding="utf-8")
        return base

    def test_the_level_stats_are_read_at_the_recording_s_own_full_scale(self):
        n = 4800
        t = np.arange(n) / 48_000.0
        amp = 2000.0     # near the device's own +-2048 full scale, not +-32768
        i = amp * np.cos(2 * np.pi * 1000.0 * t)
        q = amp * np.sin(2 * np.pi * 1000.0 * t)
        base = self._write(i, q, 2048.0)
        report = analyse.analyse(base, self.dir / "out-scale")
        # Read at +-2048 this is close to 0 dBFS; at the datatype's own
        # default (+-32768) it would be ~24 dB quieter (about -23.8 dBFS).
        self.assertGreater(report["levels"]["peak_dbfs"], -2.0)

    def test_clipping_is_counted_against_the_same_overridden_scale(self):
        n = 4800
        i = np.full(n, 2048, dtype=np.int16)    # every sample at the device's own full scale
        q = np.zeros(n, dtype=np.int16)
        base = self._write(i, q, 2048.0)
        report = analyse.analyse(base, self.dir / "out-scale-clip")
        # At the datatype's own +-32768 default these samples are 6 % of
        # full scale and nothing would be counted as clipped.
        self.assertGreater(report["levels"]["clipped_pct"], 90.0)

    def test_with_no_override_the_datatype_s_own_default_scale_still_applies(self):
        n = 4800
        i = np.full(n, 2048, dtype=np.int16)
        q = np.zeros(n, dtype=np.int16)
        base = self.dir / "no-override"
        raw = np.empty(2 * n, dtype="<i2")
        raw[0::2], raw[1::2] = i, q
        (self.dir / "no-override.sigmf-data").write_bytes(raw.tobytes())
        meta = {
            "global": {"core:datatype": "ci16_le", "core:sample_rate": 48_000.0, "core:version": sigmf.SIGMF_VERSION,
                      "core:num_channels": 1, "core:description": "a plain ci16 recording, full scale +-32768"},
            "captures": [{"core:sample_start": 0, "core:frequency": 7_100_000.0,
                         "core:datetime": sigmf.iso_utc(time.time())}],
            "annotations": [],
        }
        (self.dir / "no-override.sigmf-meta").write_text(json.dumps(meta), encoding="utf-8")
        report = analyse.analyse(base, self.dir / "out-no-override")
        self.assertLess(report["levels"]["clipped_pct"], 1.0)
        self.assertLess(report["levels"]["peak_dbfs"], -20.0)


class ExtendedSections(unittest.TestCase):
    """--extended wires in all five slow sections (ohsnb.analyse_mmb/_power/
    _ssb/_digital/_census) without disturbing the base report: each
    arrives as its own key under report["ext"], computed or not exactly as
    its own flag says, and the whole thing runs end to end (including
    matplotlib's PNGs, where installed) on a real, if short and quiet,
    recording rather than only on each module's own synthetic fixtures."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_section_runs_and_reports_its_own_shape(self):
        r = make_radio(self.dir, simRxErrorHz=5_000.0, simDriftHz=0.0, simSignals=False, sampleRate=600_000)
        r.start()
        try:
            path = r.start_recording()
            run_sim(r, 30.0)
            self.assertEqual(r.stop_recording(), path)
            _wait_saved(r)
        finally:
            r.stop()
        report = analyse.analyse(path, self.dir / "out-extended", extended=True)
        ext = report["ext"]
        for key in ("mmb", "overpower", "ssb_scale", "other_modes", "census"):
            self.assertIn(key, ext, f"{key} missing from an --extended report")
        self.assertIn("available", ext["mmb"])
        self.assertIn("events", ext["overpower"])
        self.assertIn("attempts", ext["ssb_scale"])
        for mode in ("ft4", "q65", "js8", "psk31"):
            self.assertIn(mode, ext["other_modes"])
        self.assertEqual(len(ext["census"]["counts"]), len(ext["census"]["segments"]))
        text = (self.dir / "out-extended" / "report.txt").read_text()
        self.assertIn("Band census", text)
        json.loads((self.dir / "out-extended" / "report.json").read_text())   # must still parse

    def test_with_no_flags_the_ext_key_is_empty_and_the_base_report_is_unchanged(self):
        r = make_radio(self.dir, simRxErrorHz=5_000.0, simDriftHz=0.0, simSignals=False, sampleRate=600_000)
        r.start()
        try:
            path = r.start_recording()
            run_sim(r, 15.0)
            r.stop_recording()
            _wait_saved(r)
        finally:
            r.stop()
        report = analyse.analyse(path, self.dir / "out-plain")
        self.assertEqual(report["ext"], {})
        text = (self.dir / "out-plain" / "report.txt").read_text()
        for marker in ("Multimedia beacon", "Over-power events", "SSB at scale", "Band census"):
            self.assertNotIn(marker, text)


@unittest.skipUnless(ft8.CAN_ENCODE["ft8"], "wsjtx (jt9/ft8code) not installed")
class Ft8WithoutOhsdigi(Ft8JT9VsOhsdigi):
    """The same fixture on a machine without ohsdigi: jt9's decode must
    still be counted. Until 07/10 the table was built only from the
    comparison hook, which never runs without ohsdigi, so such a machine
    reported jt9 0 on a busy evening's recording."""

    __unittest_skip__ = False

    def test_both_decoders_find_the_same_message(self):
        self.skipTest("needs ohsdigi; covered by Ft8JT9VsOhsdigi")

    def test_jt9_alone_is_still_counted(self):
        # jt9 is this test's subject, so it is a real prerequisite; ohsdigi
        # is not, and is taken away below whether or not this host has it.
        # The skip used to come after the analysis, keyed on report["ft8"]
        # being None - true only when neither decoder exists, so a host
        # with ohsdigi and no WSJT-X ran the test and failed it with
        # jt9_total 0, a fact about the host rather than the code.
        if not ft8._JT9:
            self.skipTest("jt9 is not installed on this machine")
        from unittest import mock
        base = self._make_recording()
        with mock.patch.object(ft8, "_OHSDIGI_DEC", None):
            report = analyse.analyse(base, self.dir / "out-jt9")
        f8 = report["ft8"]
        self.assertIsNotNone(f8)
        self.assertEqual(f8["jt9_total"], 1)
        self.assertFalse(f8["ohsdigi_built"])
        self.assertEqual(f8["ohsdigi_total"], 0)
        text = (self.dir / "out-jt9" / "report.txt").read_text()
        self.assertIn("ohsdigi not built here", text)


class NotQo100(unittest.TestCase):
    """A recording nowhere near the QO-100 downlink: the beacon/FT8/SSB
    sections are skipped with a reason, not reported as empty or wrong."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_skips_qo100_specific_sections(self):
        fs = 48_000.0
        rng = np.random.default_rng(1)
        n = int(2.0 * fs)
        wide = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64) * 0.01
        base = self.dir / "hf-fixture"
        data_bytes, _clipped = sigmf.to_ci16(wide)
        (self.dir / "hf-fixture.sigmf-data").write_bytes(data_bytes)
        meta = {
            "global": {"core:datatype": "ci16_le", "core:sample_rate": fs, "core:version": sigmf.SIGMF_VERSION,
                      "core:num_channels": 1, "core:extensions": [dict(sigmf.EXT)],
                      "core:description": "an HF recording, nothing to do with QO-100"},
            "captures": [{"core:sample_start": 0, "core:frequency": 7_100_000.0,
                         "core:datetime": sigmf.iso_utc(time.time())}],
            "annotations": [],
        }
        (self.dir / "hf-fixture.sigmf-meta").write_text(json.dumps(meta), encoding="utf-8")
        report = analyse.analyse(base, self.dir / "out-hf")
        self.assertFalse(report["qo100"])
        self.assertIn("QO-100", report["qo100_why"])
        self.assertEqual(report["beacons"], {})
        self.assertIsNone(report["ft8"])
        self.assertEqual(report["ssb"], [])
        text = (self.dir / "out-hf" / "report.txt").read_text()
        self.assertIn("Not analysed as QO-100", text)


# Run in a fresh child process (test_core_isolation.py's own pattern) so the
# measurement is this one analyse() call's own peak RSS, not whatever earlier
# tests in a shared process happened to allocate first.
_MEMORY_CHILD = r"""
import json, os, re, sys, tempfile, threading, time
sys.path.insert(0, sys.argv[1])
sys.path.insert(0, os.path.join(sys.argv[1], "tests"))
import scratch_home  # noqa: F401
import numpy as np
from pathlib import Path
from ohscore import sigmf
from ohsnb import analyse, bandplan

# What is bounded here is *anonymous* memory (RssAnon, /proc/self/status) -
# this process's own heap, never the kernel's page cache for the recording
# itself. Reading a large file sequentially fills the page cache as it
# goes, same as any file-processing tool (cp, grep -r, ffmpeg); that is
# reclaimable on demand and is not what leaked. What OOM-killed a laptop
# running this section over a real three-hour file (07/10/2026) was a
# whole-file 12 kHz channel-audio array held per mode/segment (real,
# unreclaimable heap) and - separately, found chasing that one down - an
# unbounded number of concurrent jt9/q65code/js8 subprocesses once this
# module reads a file faster than they can keep up (each one anonymous
# memory of its own, not counted in *this* process's figure but every bit
# as real on the machine running it); both are fixed, in ohsnb.analyse
# (_ft8_stream_decode, MAX_CONCURRENT_DECODES/_wait_for_room) and
# ohsnb.analyse_digital (_channel_audio_chunks, _decode_slotted).
def _rss_anon_kb():
    for line in open("/proc/self/status"):
        if line.startswith("RssAnon:"):
            return int(re.search(r"(\d+)", line).group(1))
    return 0

peak = {"kb": 0}
stop = threading.Event()

def _sample():
    while not stop.is_set():
        peak["kb"] = max(peak["kb"], _rss_anon_kb())
        time.sleep(0.05)

sampler = threading.Thread(target=_sample, daemon=True)
sampler.start()

fs = 240_000.0
n = int(300.0 * fs)        # 5 minutes: long enough that one whole-file 12 kHz
                           # channel-audio array (the OOM's own cause) would
                           # be ~14 MB; several of those are what to catch.
tmp = sys.argv[2]          # the parent's TemporaryDirectory: it removes the 288 MB file
base = Path(tmp) / "long"
# Written a chunk at a time, never as one whole-file array: building the
# fixture must not itself be what this test measures.
rng = np.random.default_rng(1)
step = int(5.0 * fs)
with open(Path(tmp) / "long.sigmf-data", "wb") as f:
    for a in range(0, n, step):
        b = min(a + step, n)
        chunk = (rng.standard_normal(b - a) + 1j * rng.standard_normal(b - a)).astype(np.complex64) * 0.01
        data_bytes, _clipped = sigmf.to_ci16(chunk)
        f.write(data_bytes)
dc0 = (bandplan.DL_LO + bandplan.DL_HI) / 2.0
meta = {
    "global": {"core:datatype": "ci16_le", "core:sample_rate": fs, "core:version": sigmf.SIGMF_VERSION,
              "core:num_channels": 1, "core:extensions": [dict(sigmf.EXT)],
              "openhamshack:app": "OpenHamShack NB", "openhamshack:version": "0.0.0-test",
              "core:description": "a long, quiet recording for the memory-bound test"},
    "captures": [{"core:sample_start": 0, "core:frequency": dc0, "core:datetime": sigmf.iso_utc(time.time())}],
    "annotations": [],
}
(Path(tmp) / "long.sigmf-meta").write_text(json.dumps(meta), encoding="utf-8")
report = analyse.analyse(base, Path(tmp) / "out", extended=True)
stop.set()
sampler.join(timeout=2)
print(json.dumps({"peak_anon_kb": peak["kb"], "qo100": report["qo100"]}))
"""


class BoundedMemory(unittest.TestCase):
    """Peak *anonymous* memory (RssAnon - this process's own heap, never
    the kernel's reclaimable page cache for the recording itself: see
    _MEMORY_CHILD's own comment) during an --extended run must not grow
    with the recording's length. What OOM-killed a laptop running this
    section over a real three-hour file (07/10/2026) was a whole-file
    12 kHz channel-audio array held per mode/segment (ohsnb.analyse's own
    FT8 section, and ohsnb.analyse_digital's FT4/Q65/JS8/PSK31 ones, each
    built one such array before this fix) rather than streamed, and -
    found chasing that down, a second and larger way to the same place -
    no limit on how many of those modes' own jt9/q65code/js8 subprocesses
    could be outstanding at once when this module reads a file faster
    than they can keep up. A 5-minute recording already makes the first
    mistake's own cost (tens of MB per array, several arrays) the
    dominant thing in a fresh process's own anonymous memory, so a
    regression shows up here long before a real multi-hour file is
    needed to find it; the second would show instead as this process
    itself staying small while the *machine* runs low (RssAnon, by
    design, only ever reports this process's own heap)."""

    # Measured directly (this test's own numbers, 60 s and 300 s recordings
    # run side by side): anonymous memory here sits at 330-375 MB more or
    # less flat with duration - numpy/matplotlib/the jt9-subprocess
    # machinery's own fixed overhead, not something that grows with the
    # file. 600 MB is comfortably above that baseline and still well
    # below what even one reintroduced whole-file array would add.
    MAX_ANON_MB = 600

    def test_extended_analysis_of_a_long_quiet_recording_stays_bounded(self):
        repo_root = str(Path(__file__).resolve().parent.parent)
        # The child writes a 288 MB recording; it used to make its own
        # mkdtemp() and never remove it, and /tmp is RAM (tmpfs) on the dev
        # VM - 13 runs had 3.6 GB of it held on 17/10/2026.
        with tempfile.TemporaryDirectory() as tmp:
            res = subprocess.run([sys.executable, "-c", _MEMORY_CHILD, repo_root, tmp],
                                 capture_output=True, text=True, timeout=600)
        self.assertEqual(res.returncode, 0, f"stdout:\n{res.stdout}\nstderr:\n{res.stderr}")
        out = json.loads(res.stdout.strip().splitlines()[-1])
        self.assertTrue(out["qo100"])     # the QO-100-tagged metadata took, so every section really ran
        peak_mb = out["peak_anon_kb"] / 1024.0
        self.assertLess(peak_mb, self.MAX_ANON_MB,
                        f"peak anonymous memory {peak_mb:.0f} MB for a 5-minute recording - "
                        f"something is holding a whole-file array again")


if __name__ == "__main__":
    unittest.main()
