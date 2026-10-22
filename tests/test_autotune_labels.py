"""tools/autotune_labels.py: a labelled auto-tune corpus from leaked
carriers - behavioural, on a synthetic recording with three stations in
an SSB segment, each a different reason a label must or must not be made:

- a voice whose transmitter leaks its carrier (a steady line under the
  voice): labelled, at the carrier's own frequency;
- the same kind of voice with a clean, fully suppressed carrier: nothing
  to label from, so no label (and no line invented from its harmonics);
- a CW carrier with no voice above it: a steady line, but not a voice's;
- a leaky voice with a second line as strong 250 Hz under its carrier:
  two candidates for the carrier, which the label cannot choose between.
- a voice heard for 5 s of the 20 over a line that stands all 20: a
  carrier leaks only while its transmitter is keyed, so the line is not
  that voice's;
- a voice with a steady tone in its own lowest audio, ~50 Hz under where
  the voice reads as starting: no USB transmit filter passes audio that
  near its carrier, so the line is the bottom of the voice, not its
  carrier - refused as "voice too near the line".

The leaked carriers are weak (~12 dB over the noise in the averaged
spectrum, as most real ones on 07/10 are), wander +-3 Hz and carry phase
noise. The first version of the tool refused exactly such a carrier as
"contested" by noise (its rival test compared the line with the loudest
noise bin near it) and labelled nothing here. Its other real-recording
fault - a 4 Hz notch too narrow for a wandering carrier, bridged into a
voice that starts within 150 Hz of it - is not reproduced: the
simulator's voice starts 300 Hz up.

Then `score` on what `build` wrote: the label is the carrier, so the
scorer's answer for it is measured against the truth, and trying the
other MIN_EDGE_GAP values leaves auto-tune's own as it found it."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import contextlib
import importlib.util
import io
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from ohscore import sigmf
from ohscore.devices import simsignals as sg
from ohscore.dsp import autotune
from ohscore.dsp.bank import Geometry, Source, Synthesis

from ohsnb import bandplan

_spec = importlib.util.spec_from_file_location(
    "autotune_labels", Path(__file__).resolve().parent.parent / "tools" / "autotune_labels.py")
labels = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(labels)

FS = 240_000.0
SECONDS = 20.0
TOTAL_S = 22.0          # one whole window, with room for the bank's tail
# Voice level: ~20 dB over the noise, as most QO-100 SSB is. Much louder
# (gain 0.015 here) and the band-while-talking spectrum's skirts reach
# the carrier, so its lower edge reads under the line and the label tool
# refuses it - a strong station is lost, never mislabelled.
GAIN = 0.004
LEAK = 0.01             # a weak leaked carrier
WOBBLE_HZ = 3.0         # its frequency wanders this much (+-) over ~7 s
PHASE_NOISE = 0.03      # rad per 12 kHz sample, random walk: ~1.7 Hz Lorentzian


def _write(folder: Path) -> tuple[Path, dict]:
    geo = Geometry(FS)
    d = geo.decimation_for(12_000.0)
    seg_lo, seg_hi = next((lo, hi) for lo, hi, _l, classes, _m in bandplan.SEGMENTS if classes == {"ssb"})
    dc0 = (seg_lo + seg_hi) / 2.0 - 20_000.0
    carriers = {"leaky": dc0 + 10_000.3, "clean": dc0 + 20_000.0, "cw": dc0 + 30_000.0,
                "contested": dc0 + 40_000.0, "lingering": dc0 + 50_000.0,
                "hugging": dc0 + 60_000.0}
    n12 = int(TOTAL_S * 12_000.0)
    t = np.arange(n12) / 12_000.0
    # USB: a carrier is audio at 0 Hz; a wandering one, at 0 Hz +- WOBBLE_HZ.
    # And phase noise, as a real oscillator has: a random walk of phase, a
    # Lorentzian line ~1 Hz wide whose skirts reach well past the wander.
    walk = np.cumsum(np.random.default_rng(4).normal(0.0, PHASE_NOISE, n12))
    wobble = LEAK * np.exp(1j * (2 * np.pi * np.cumsum(WOBBLE_HZ * np.sin(2 * np.pi * t / 7.0)) / 12_000.0 + walk))
    srcs = []
    for k, (name, f) in enumerate(carriers.items()):
        if name == "cw":
            audio = np.full(n12, 0.3, np.complex128)
        else:
            audio = sg.voice(np.random.default_rng(10 + k), TOTAL_S)[:n12].astype(np.complex128)
            if name == "leaky":
                audio += wobble
            elif name == "contested":
                audio += 3 * LEAK + 3 * LEAK * np.exp(-2j * np.pi * 250.0 * t)
            elif name == "hugging":
                # The voice's band reads from ~250 Hz (see gap_hz below), so
                # a line at 200 Hz is ~50 Hz under it.
                audio += 3 * LEAK * np.exp(2j * np.pi * 200.0 * t)
            elif name == "lingering":
                audio[(t < 6.0) | (t >= 11.0)] = 0.0
                audio += 3 * LEAK
        src = Source(geo, d, freq=f - dc0, gain=GAIN)
        m = len(audio) // src.hop
        srcs.append((src, audio[:m * src.hop].astype(np.complex64)))
    wide = Synthesis(geo).render(m, srcs)
    rng = np.random.default_rng(3)
    x = wide + 0.002 * (rng.standard_normal(len(wide)) + 1j * rng.standard_normal(len(wide)))
    data, clipped = sigmf.to_ci16((4.0 * x).astype(np.complex64))
    assert clipped == 0
    (folder / "syn.sigmf-data").write_bytes(data)
    meta = {"global": {"core:datatype": "ci16_le", "core:sample_rate": FS, "core:version": sigmf.SIGMF_VERSION},
            "captures": [{"core:sample_start": 0, "core:frequency": dc0,
                          "core:datetime": sigmf.iso_utc(time.time())}],
            "annotations": []}
    (folder / "syn.sigmf-meta").write_text(json.dumps(meta), encoding="utf-8")
    # Hz from the recording's DC, as the index records them (no LNB error).
    return folder / "syn.sigmf-data", {k: v - dc0 for k, v in carriers.items()}


class LeakedCarrierLabels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        data, cls.carriers = _write(root)
        cls.data = data
        cls.out2 = root / "no-rule"
        cls.out2.mkdir()
        cls.out = root / "corpus"
        args = SimpleNamespace(outdir=str(cls.out), recordings=[str(data)], jobs=1, seconds=SECONDS,
                               lnb={}, names={"syn.sigmf-data": "syn"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            labels.build(args)
        cls.summary = json.loads(buf.getvalue().strip().splitlines()[-1])
        cls.rows = json.loads((cls.out / "index.json").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_only_the_leaky_station_is_labelled_at_its_carrier(self):
        self.assertEqual(len(self.rows), 1, self.rows)
        r = self.rows[0]
        # The 20 s average's peak: a wandering carrier's is wherever it
        # dwells - a turning point, here - so the label is good to the
        # wander (the scorer takes the 4 s track at the capture instead).
        self.assertAlmostEqual(r["truth"], self.carriers["leaky"], delta=WOBBLE_HZ + 0.5)
        # The voice starts above the carrier (300 Hz in the simulator's
        # audio, read a little lower from the band while talking).
        self.assertGreater(r["gap_hz"], 150.0)
        self.assertLess(r["gap_hz"], 320.0)
        self.assertEqual(self.summary["labelled"], 1)
        self.assertGreaterEqual(self.summary["no voice above"], 1)      # the CW carrier
        # The contested station: each of its two lines is the other's rival.
        self.assertEqual(self.summary["rival line"], 2)
        self.assertEqual(self.summary["line outlives the voice"], 1)
        self.assertEqual(self.summary["voice too near the line"], 1)

    def test_a_line_hugging_the_voice_would_be_a_label_without_the_rule(self):
        # What the rule removes is a label the rest of the tests accept: a
        # rule that refused it for some other reason would prove nothing.
        old = labels.LABEL_GAP_HZ
        labels.LABEL_GAP_HZ = 0.0
        try:
            rows, tally = labels._window((str(self.data), "syn", 0, SECONDS, None, str(self.out2)))
        finally:
            labels.LABEL_GAP_HZ = old
        near = [r for r in rows if abs(r["truth"] - (self.carriers["hugging"] + 200.0)) < 5.0]
        self.assertEqual(len(near), 1, rows)
        self.assertLess(near[0]["gap_hz"], labels.LABEL_GAP_HZ)

    def test_the_capture_is_the_receive_channel_at_four_dials(self):
        r = self.rows[0]
        z = np.load(self.out / (r["key"] + ".npz"))
        self.assertEqual(sorted(z.files), sorted(r["dials"]))
        for k in z.files:
            self.assertEqual(z[k].dtype, np.complex64)
            self.assertEqual(len(z[k]), int(SECONDS * labels.RATE))
        # Auto-tune itself, on the busiest 4 s at the voice's mid dial,
        # finds this voice's carrier: the capture really is that station.
        y = z["mid"][int(r["busy_s"] * labels.RATE):][:int(autotune.CAPTURE_SECONDS * labels.RATE)]
        t = autotune.auto_tune(y, "usb")
        self.assertTrue(t.ok, t.why)
        self.assertAlmostEqual(r["dials"]["mid"] + t.offset, r["truth"], delta=30.0)

    def test_scoring_tries_each_gap_and_leaves_auto_tunes_own(self):
        before = getattr(autotune, "MIN_EDGE_GAP", None)
        if before is None:
            self.skipTest("this auto-tune has no MIN_EDGE_GAP")
        res = labels._score_one((self.rows[0], str(self.out), [None, 100.0, 125.0], ("busy4", "whole")))
        self.assertEqual(autotune.MIN_EDGE_GAP, before)
        self.assertEqual({r["gap"] for r in res}, {None, 100.0, 125.0})
        self.assertEqual(len(res), 3 * 4 * 2)            # gaps x dials x (busy 4 s, whole)
        mid = [r for r in res if r["gap"] is None and r["dial"] == "mid" and r["span"] == "busy4"][0]
        self.assertTrue(mid["ok"], mid["why"])
        self.assertLess(abs(mid["err"]), 30.0)


if __name__ == "__main__":
    unittest.main()
