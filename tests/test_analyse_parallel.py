"""ohsnb.analyse_parallel: --jobs N must give the report a single pass gives.

Behavioural, not textual: a synthetic QO-100 recording with something for
every section - FT8 in every slot, either side of where a slice is cut; an
over-power carrier that starts in one slice and ends in the next - is
analysed in one process and again in four worker processes with slices
short enough to fall inside it, and the two reports compared whole. Below
that, the two pieces the exactness rests on are tested directly: a
slice's channel audio is the same, sample for sample, as a whole-file
pass's (the filter bank, LO phase and demodulator AGC rebuilt or warmed
up, ohsnb.analyse._audio_blocks), and PSK31's per-window decode, sliced by
windows, gives the same windows (its 10-minute window is too long for a
test recording to be cut at through analyse() itself)."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import math
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from ohscore import sigmf
from ohscore.devices import simsignals
from ohscore.dsp.bank import Geometry, Source, Synthesis
from ohscore.modes import ft8
from ohsnb import analyse, analyse_digital, analyse_parallel, bandplan

FS = 240_000.0
DURATION_S = 90.0
# Centred so the FT8 dial (10489.540) and the middle beacon (10489.750)
# are both inside +-120 kHz of DC at this small sample rate.
DC0 = 10_489_645_000.0
SLICE_S = 30.0             # analyse(slice_s=...): cuts near 30 s and 60 s
HOT_T = (20.0, 45.0)       # the over-power carrier: on across the 30 s cut
HOT_HZ = DC0 + 50_000.0    # clear of every beacon's exclusion zone
MESSAGES = ["CQ GM4BRI IO86", "CQ G4ABC IO91", "CQ M0XYZ JO01", "CQ 2E0AAA IO83",
            "CQ G0BBB IO92", "CQ M7CCC IO70"]


def _ft8_baseband(geo: Geometry, text: str, offset_hz: float, gain: float) -> np.ndarray:
    """One FT8 transmission as wideband IQ (USB-sided, at offset_hz from
    DC), from ohscore.modes.ft8.Encoder's real waveform - the same
    construction as test_ohsnb_analyse.Ft8JT9VsOhsdigi's fixture."""
    audio = ft8.Encoder().render(text=text, variant="ft8", offset=1500.0)
    one_sided = simsignals.analytic(audio)
    src = Source(geo, geo.decimation_for(12_000.0), freq=offset_hz, gain=gain)
    m = len(one_sided) // src.hop
    return Synthesis(geo).render(m, [(src, one_sided[:m * src.hop])])


def _write_recording(folder: Path, with_ft8: bool) -> tuple[Path, float]:
    n = int(DURATION_S * FS)
    t = np.arange(n) / FS
    rng = np.random.default_rng(7)
    x = (0.01 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))).astype(np.complex64)
    mid = bandplan.BEACONS["middle"]["ref"]
    x += (0.05 * np.exp(2j * np.pi * (mid - DC0) * t)).astype(np.complex64)
    on = (t >= HOT_T[0]) & (t < HOT_T[1])
    x[on] += (0.4 * np.exp(2j * np.pi * (HOT_HZ - DC0) * t[on])).astype(np.complex64)
    # An FT8 transmission starts 0.5 s into its slot: the recording starts
    # 0.5 s into one, so every 15 s of file time is a slot's own start.
    start_utc = math.floor(time.time() / 15.0) * 15.0 + 0.5
    if with_ft8:
        geo = Geometry(FS)
        for j, text in enumerate(MESSAGES):
            burst = _ft8_baseband(geo, text, analyse.FT8_DIAL_DL - DC0, 0.002)
            a = int(j * 15.0 * FS)
            b = min(n, a + len(burst))
            x[a:b] += burst[:b - a]
    data, clipped = sigmf.to_ci16(x)
    assert clipped == 0
    (folder / "par.sigmf-data").write_bytes(data)
    meta = {
        "global": {"core:datatype": "ci16_le", "core:sample_rate": FS, "core:version": sigmf.SIGMF_VERSION,
                  "core:num_channels": 1, "core:extensions": [dict(sigmf.EXT)],
                  "openhamshack:app": "OpenHamShack NB", "openhamshack:version": "0.0.0-test",
                  "core:description": "test fixture: FT8 every slot, an over-power carrier across a slice cut"},
        "captures": [{"core:sample_start": 0, "core:frequency": DC0, "core:datetime": sigmf.iso_utc(start_utc)}],
        "annotations": [],
    }
    (folder / "par.sigmf-meta").write_text(json.dumps(meta), encoding="utf-8")
    return folder / "par", start_utc


def _comparable(report: dict) -> dict:
    """The report as report.json holds it (tuples become lists etc.)."""
    return json.loads(json.dumps(report, default=str))


class SameReportEitherWay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.dir = Path(cls.tmp.name)
        cls.with_ft8 = bool(ft8.CAN_ENCODE["ft8"] and ft8.CAN_DECODE)
        cls.base, cls.start_utc = _write_recording(cls.dir, cls.with_ft8)
        lines: list[str] = []
        cls.one = analyse.analyse(cls.base, cls.dir / "one", extended=True, jobs=1)
        cls.four = analyse.analyse(cls.base, cls.dir / "four", extended=True, jobs=4, slice_s=SLICE_S,
                                   progress=lines.append)
        cls.progress = lines

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_slices_really_were_cut(self):
        # Without this, two equal reports could just mean nothing was split.
        done = [ln for ln in self.progress if ": done in" in ln]
        for section in ("levels", "wide spectrum", "over-power lines", "census"):
            self.assertIn(f"{section} 3/3: done in", " ".join(done), section)
        if self.with_ft8:
            self.assertIn("FT8 3/3: done in", " ".join(done))

    def test_every_section_reports_the_same(self):
        one, four = _comparable(self.one), _comparable(self.four)
        for key in one:
            if key == "ext":
                continue
            self.assertEqual(one[key], four[key], key)
        self.assertEqual(sorted(one["ext"]), sorted(four["ext"]))
        for key in one["ext"]:
            self.assertEqual(one["ext"][key], four["ext"][key], key)

    def test_the_report_files_are_identical(self):
        for name in ("report.txt", "report.json"):
            self.assertEqual((self.dir / "one" / name).read_text(), (self.dir / "four" / name).read_text(), name)

    def test_an_event_across_a_slice_boundary_is_one_event(self):
        evs = self.four["ext"]["overpower"]["events"]
        hot = [e for e in evs if e["freq_lo_hz"] - 500 <= HOT_HZ <= e["freq_hi_hz"] + 500]
        self.assertEqual(len(hot), 1, evs)
        self.assertLess(hot[0]["t_start_s"], SLICE_S)
        self.assertGreater(hot[0]["t_end_s"], SLICE_S)
        self.assertGreater(hot[0]["duration_s"], HOT_T[1] - HOT_T[0] - 5.0)

    def test_ft8_either_side_of_a_slot_cut_is_decoded_once(self):
        if not self.with_ft8:
            self.skipTest("no FT8 encoder/decoder here (wsjtx or ohsdigi)")
        f8 = self.four["ft8"]
        decoded = f8["jt9_total"] + f8["ohsdigi_total"] - f8["both"]
        self.assertGreaterEqual(decoded, len(MESSAGES) - 1)       # the last slot may run off the end
        slots = [s["slot_utc"] for s in f8["slots"]]
        self.assertEqual(len(slots), len(set(slots)), "a slot reported by two slices")


class SliceAudioIsExact(unittest.TestCase):
    """The channel audio a slice produces after its warm-up is the
    whole-file pass's, bit for bit - not close: decoders quantise it, and
    'close' is how an occasional decode would come and go."""

    def test_sliced_audio_matches_the_whole_pass(self):
        n = int(100.0 * FS)
        rng = np.random.default_rng(3)
        t = np.arange(n) / FS
        x = 0.01 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))
        # A loud burst well before the slice and a quiet stretch inside the
        # warm-up: the AGC must forget the burst for the two to agree.
        env = np.where((t > 10) & (t < 14), 30.0, 1.0) * np.where((t > 45) & (t < 60), 0.05, 1.0)
        x = (x * env + 0.02 * np.exp(2j * np.pi * -40_000.0 * t)).astype(np.complex64)
        view = np.stack([x.real, x.imag], axis=1).astype(np.float32)
        caps = [{"core:sample_start": 0, "core:frequency": 0.0}]
        grid, contiguous = analyse._chunk_grid(caps, {"lnb_lo_hz": None, "nominal_dc_flat": None}, n, FS)
        self.assertTrue(contiguous)
        # A frequency that moves every block, as beacon lock moves the real
        # one, so the LO phase replay has a history to get right.
        freq = lambda a, b, dc: -40_000.0 + 3.7 * (b / FS)            # noqa: E731
        whole = {k: a.copy() for k, a in analyse._audio_blocks(view, 1.0, FS, grid, freq)}
        lo = 70
        sliced = {k: a for k, a in analyse._audio_blocks(view, 1.0, FS, grid, freq, k_lo=lo, k_hi=len(grid),
                                                          k_warm=lo - analyse.WARM_CHUNKS)}
        self.assertEqual(sorted(sliced), [k for k in sorted(whole) if k >= lo])
        for k in sliced:
            np.testing.assert_array_equal(sliced[k], whole[k], err_msg=f"block {k}")
        # And the timestamps line up: the audio a pass from 0 had produced
        # before block `lo` is what a slice starts counting from.
        fed = sum(len(whole[k]) for k in whole if k < lo)
        self.assertEqual(analyse._audio_fed_before(FS, grid[lo][0]), fed)


class PskWindowsSliceExactly(unittest.TestCase):
    def test_windows_from_slices_are_the_whole_pass_s_windows(self):
        n = int(80.0 * FS)
        rng = np.random.default_rng(5)
        x = (0.01 * (rng.standard_normal(n) + 1j * rng.standard_normal(n))).astype(np.complex64)
        view = np.stack([x.real, x.imag], axis=1).astype(np.float32)
        lo_seg, hi_seg = analyse_digital._PSK_SEGMENTS[0]
        dc0 = (lo_seg + hi_seg) / 2.0
        caps = [{"core:sample_start": 0, "core:frequency": dc0}]
        info = {"lnb_lo_hz": None, "nominal_dc_flat": None}
        window_s = 15.0
        whole = analyse_digital._psk_segment(view, 1.0, n, FS, caps, info, 0.0, [], 0, window_s)
        grid, _ = analyse._chunk_grid(caps, info, n, FS)
        parts = analyse_parallel._psk_parts(grid, FS, window_s, 3)
        self.assertEqual(len(parts), 3)
        sliced = [w for p in parts for w in
                  analyse_digital._psk_segment(view, 1.0, n, FS, caps, info, 0.0, [], 0, window_s, p)]
        self.assertEqual(sliced, whole)
        self.assertEqual(len(whole), int(80.0 // window_s))


class DefaultJobs(unittest.TestCase):
    def test_never_less_than_one_and_capped_by_memory(self):
        from unittest import mock
        self.assertGreaterEqual(analyse_parallel.default_jobs(), 1)
        with mock.patch.object(analyse_parallel, "_available_memory", return_value=2 * 2**30), \
                mock.patch("os.cpu_count", return_value=16):
            self.assertEqual(analyse_parallel.default_jobs(), 1)
        with mock.patch.object(analyse_parallel, "_available_memory", return_value=5 * 2**30), \
                mock.patch("os.cpu_count", return_value=16):
            self.assertEqual(analyse_parallel.default_jobs(),
                             (5 * 2**30 - analyse_parallel.PARENT_RESERVE) // analyse_parallel.WORKER_BUDGET)
        with mock.patch.object(analyse_parallel, "_available_memory", return_value=64 * 2**30), \
                mock.patch("os.cpu_count", return_value=4):
            self.assertEqual(analyse_parallel.default_jobs(), 3)


if __name__ == "__main__":
    unittest.main()
