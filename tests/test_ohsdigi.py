import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""ohsdigi, the Rust FT8/FT4 encoder, as the program uses it: the module
that is actually installed (ohscore/ohsdigi.*), held to WSJT-X 2.7.0 through
the same corpus the Rust tests read; its audio decoded by jt9; its
waveform against WSJT-X's own ft8sim; and the fallback to ft8code/ft4code
when it is absent. Running the corpus here rather than only under cargo
is what proves a given binary - a cross-built .pyd on Windows, the arm64
.so - and not just the source."""
import gzip
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from ohscore.modes import ft8

REPO = Path(__file__).resolve().parents[1]
CORPUS = REPO / "rust" / "ohsdigi" / "testdata" / "wsjtx-2.7.0-ft8-ft4.tsv.gz"
FS = 12_000.0

ohsdigi = ft8._OHSDIGI
HAVE = unittest.skipUnless(ohsdigi is not None, f"ohsdigi not built ({ft8.OHSDIGI_WHY_NOT}); tools/build-ohsdigi.sh --host --install")


def _corpus():
    """The rows of the WSJT-X corpus: (message, ft8 fields, ft4 fields),
    each fields tuple (status, i3.n3, sent, bits, tones)."""
    with gzip.open(CORPUS, "rt", encoding="latin-1", newline="\n") as f:
        lines = f.read().split("\n")
    assert lines[0].startswith("#") and lines[1].startswith("message\t")
    for line in lines[2:]:
        if line:
            f = line.split("\t")
            yield f[0], tuple(f[1:6]), tuple(f[6:11])


def _type(e):
    return f"{e.i3}." if e.i3 >= 1 else f"{e.i3}.{e.n3}"


@HAVE
class CorpusTests(unittest.TestCase):
    def test_identical_to_wsjtx_for_every_message_it_defines(self):
        n = same = undefined = 0
        diffs = []
        for msg, *modes in _corpus():
            n += 1
            for mode, (status, typ, sent, bits, tones) in zip(("ft8", "ft4"), modes):
                try:
                    e = ohsdigi.encode(mode, msg)
                except ohsdigi.BadMessage as exc:
                    if "whatever was in memory" in str(exc):
                        undefined += 1
                    elif status in ("bad", "crash"):
                        same += 1
                    else:
                        diffs.append(f"{mode} {msg!r}: refused ({exc}), WSJT-X {status}")
                    continue
                if e.undefined_in_wsjtx and mode == "ft4":
                    undefined += 1
                    continue
                got = (_type(e), e.sent, e.bits, "".join(str(t) for t in e.tones))
                if status == "ok" and got == (typ, sent, bits, tones):
                    same += 1
                else:
                    diffs.append(f"{mode} {msg!r}: WSJT-X {status} {(typ, sent, bits, tones)}, ohsdigi {got}")
        self.assertEqual(diffs[:20], [])
        self.assertGreater(n, 5000)
        self.assertEqual(same + undefined, 2 * n)
        self.assertLess(undefined, n // 10)

    def test_bad_message_is_a_value_error_that_says_so(self):
        with self.assertRaises(ValueError) as cm:
            ohsdigi.encode("ft8", "K1ABC W9XYZ +999")
        self.assertIn("bad message", str(cm.exception))

    def test_pack_unpack_round_trip_with_shared_hashes(self):
        # A decoder keeps one table for a session: a call heard in full is
        # later shown by name where only its hash arrives.
        h = ohsdigi.CallHashes()
        bits, i3, n3 = ohsdigi.pack77("<PJ4/K1ABC> W9XYZ -11", h)
        self.assertEqual((i3, n3), (1, 0))
        self.assertEqual(ohsdigi.unpack77(bits, True, h), ("<PJ4/K1ABC> W9XYZ -11", True))
        self.assertEqual(ohsdigi.unpack77(bits, True), ("<...> W9XYZ -11", True))


def _jt9_decode(audio, variant, offset=1500.0):
    """Decode one slot of `audio` through the program's own jt9 path."""
    done = threading.Event()
    events = []

    def on_event(ev):
        events.append(ev)
        done.set()

    dec = ft8.Decoder(on_event, variant=variant, offset=offset)
    slot_n = int(round(ft8.SLOT_S[variant] * FS))
    padded = np.zeros(slot_n, dtype=np.float32)
    start = int(0.5 * FS)
    padded[start:start + len(audio)] = audio[:slot_n - start]
    t = 0.0
    for i in range(0, slot_n, 1200):
        dec.feed(padded[i:i + 1200], t=t)
        t += 1200 / FS
    dec.feed(np.zeros(1200, dtype=np.float32), t=t)
    done.wait(15)
    dec.close()
    return [e.get("text") for e in events if "text" in e]


MESSAGES = ["CQ GM4BRI IO86", "G4XYZ GM4BRI R-12", "TNX BOB 73 GL", "K1ABC W9XYZ 6A WI",
            "TU; W9XYZ K1ABC R 579 MA", "CQ PJ4/K1ABC", "123456789ABCDEF012"]


@HAVE
@unittest.skipUnless(ft8._JT9, "no jt9")
class Jt9DecodesOhsdigiTests(unittest.TestCase):
    """What ohsdigi sends, WSJT-X's own decoder reads back as the text ohsdigi
    said would be received: the end-to-end check that no corpus can make."""

    def _round_trip(self, variant):
        for msg in MESSAGES:
            with self.subTest(msg=msg):
                e = ohsdigi.encode(variant, msg)
                audio = ft8.Encoder(ohsdigi=ohsdigi).render(text=msg, variant=variant, offset=1200.0)
                self.assertEqual(_jt9_decode(audio, variant, 1200.0), [e.sent])

    def test_ft8(self):
        self._round_trip("ft8")

    def test_ft4(self):
        self._round_trip("ft4")


@HAVE
class WaveformTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("ft8sim"), "no ft8sim (WSJT-X)")
    def test_ft8_waveform_is_wsjtx_own(self):
        # ft8sim with SNR above 90 writes gen_ft8wave's signal alone, 0.5 s
        # into a 15 s WAV, scaled to 32766.9 at its peak. It looks the sine
        # up in a 65536-entry table where the transmitter computes it, so
        # the two agree to within that table's rounding, not exactly.
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["ft8sim", "CQ K1ABC FN42", "1500", "0.0", "0", "0", "1", "99"],
                           cwd=d, capture_output=True, check=True)
            wav = np.fromfile(Path(d) / "000000_000001.wav", dtype="<i2", offset=44).astype(float)
        ours = np.frombuffer(ohsdigi.encode("ft8", "CQ K1ABC FN42").waveform(1500.0), dtype="<f4").astype(float)
        ours *= 32766.9 / np.abs(ours).max()
        ref = wav[6000:6000 + len(ours)]
        self.assertEqual(len(ours), 79 * 1920)
        self.assertLess(np.abs(ref - ours).max(), 5.0)       # of 32767
        self.assertEqual(np.abs(wav[:6000]).max(), 0)

    def test_ft4_has_its_ramp_symbols(self):
        w = np.frombuffer(ohsdigi.encode("ft4", "CQ K1ABC FN42").waveform(1500.0), dtype="<f4")
        self.assertEqual(len(w), 105 * 576)
        self.assertLess(abs(w[0]), 1e-6)
        self.assertLess(np.abs(w[:100]).max(), np.abs(w[576:676]).max())


HAVE_JS8 = unittest.skipUnless(ohsdigi is not None and hasattr(ohsdigi, "js8_decode"),
                               "ohsdigi without JS8 (tools/build-ohsdigi.sh --host --install)")


def _js8_period(frames, submode="normal", freq=1500.0, level=0.05, seed=7):
    """One period holding `frames` (frame, i3bit, offset Hz) sent on time,
    in noise of 0.1 rms, as float32 full scale."""
    info = ohsdigi.JS8_SUBMODES[submode]
    n = int(info["period"] * FS)
    x = np.random.default_rng(seed).normal(0.0, 0.1, n).astype(np.float32)
    start = int(round(info["start"] * FS))
    for frame, i3bit, f in frames:
        a = np.frombuffer(ohsdigi.js8_encode_audio(frame, i3bit, submode, f), "<f4")
        x[start:start + len(a)] += level * a[:n - start]
    return x


@HAVE_JS8
class Js8Tests(unittest.TestCase):
    """The JS8 calls end to end through the module as ohscore loads it: text
    to frames to audio, and back to the text JS8Call would show. That each
    stage is JS8Call's own is rust/ohsdigi/tests/js8_golden.rs's to prove."""

    def test_every_speed_round_trips_a_message(self):
        for submode in ohsdigi.JS8_SUBMODES:
            with self.subTest(submode=submode):
                frames = ohsdigi.js8_frames("J1Y SNR -05", "GM4BRI", "IO75", submode=submode)
                self.assertEqual(len(frames), 1)
                (frame, i3bit), = frames
                got = ohsdigi.js8_decode(_js8_period([(frame, i3bit, 1200.0)], submode), submode)
                self.assertEqual([(d["frame"], d["i3bit"]) for d in got], [(frame, i3bit)])
                d = got[0]
                self.assertEqual((d["text"], d["kind"], d["from"], d["to"]),
                                 ("GM4BRI: J1Y SNR -05 ", "directed", "GM4BRI", "J1Y"))
                self.assertTrue(d["first"] and d["last"])
                # The decoder measures frequency to its own bins: finer
                # than a tenth of a tone at every speed.
                spacing = ohsdigi.JS8_SUBMODES[submode]["tone_spacing"]
                self.assertAlmostEqual(d["freq"], 1200.0, delta=0.1 * spacing)
                self.assertAlmostEqual(d["dt"], 0.0, delta=0.1)

    def test_a_long_message_is_a_run_of_frames_read_back_in_order(self):
        text = "J1Y HELLO FROM SCOTLAND ON QO-100"
        frames = ohsdigi.js8_frames(text, "GM4BRI", "IO75")
        self.assertGreater(len(frames), 2)
        self.assertTrue(frames[0][1] & ohsdigi.JS8_FRAME_FIRST and frames[-1][1] & ohsdigi.JS8_FRAME_LAST)
        shown = "".join(ohsdigi.js8_unpack(f, b)["text"] for f, b in frames)
        self.assertEqual(shown, "GM4BRI: J1Y  HELLO FROM SCOTLAND ON QO-100")

    def test_frames_refuse_what_js8_cannot_send(self):
        with self.assertRaises(ValueError):
            ohsdigi.js8_frames("lower case", "GM4BRI")
        with self.assertRaises(ValueError):
            ohsdigi.js8_tones("SHORT", 0)
        with self.assertRaises(ValueError):
            ohsdigi.js8_decode(np.zeros(10, np.float32), "wide")


HAVE_Q65 = unittest.skipUnless(ohsdigi is not None and hasattr(ohsdigi, "q65_decode"),
                               "ohsdigi without Q65 (tools/build-ohsdigi.sh --host --install)")


@HAVE_Q65
class Q65Tests(unittest.TestCase):
    """The Q65 calls end to end through the module as ohscore loads it.
    That they are WSJT-X's own is rust/ohsdigi/tests/q65_golden.rs's to
    prove; this proves the binding carries every period and submode."""

    def test_every_period_and_submode_round_trips(self):
        for period, sub in ((15, "A"), (30, "B"), (60, "A"), (60, "C"), (120, "D"), (300, "E")):
            with self.subTest(period=period, submode=sub):
                info = ohsdigi.Q65_PERIODS[period]
                sent, tones = ohsdigi.q65_encode("GM4BRI G4XYZ R-12")
                self.assertEqual((sent, len(tones)), ("GM4BRI G4XYZ R-12", 85))
                a = np.frombuffer(ohsdigi.q65_encode_audio("GM4BRI G4XYZ R-12", period, sub, 1000.0), "<f4")
                self.assertEqual(len(a), 85 * info["nsps"])
                x = np.random.default_rng(period).normal(0.0, 0.05, period * 12000).astype(np.float32)
                start = int(info["start"] * FS)
                x[start:start + len(a)] += 0.05 * a[:len(x) - start]
                got = ohsdigi.q65_decode(x, period, sub, freq_qso=1000.0, mycall="GM4BRI", dxcall="G4XYZ")
                self.assertEqual([d["text"] for d in got], ["GM4BRI G4XYZ R-12"])
                d = got[0]
                self.assertEqual((d["period"], d["submode"]), (period, sub))
                self.assertEqual(d["ap"], 3)                  # the list decode, with DxCall known
                self.assertAlmostEqual(d["freq"], 1000.0, delta=2.0)
                self.assertAlmostEqual(d["dt"], 0.0, delta=0.15)

    def test_refusals(self):
        with self.assertRaises(ValueError):
            ohsdigi.q65_decode(np.zeros(100, np.float32), 45)
        with self.assertRaises(ValueError):
            ohsdigi.q65_decode(np.zeros(100, np.float32), 60, "F")
        with self.assertRaises(ohsdigi.BadMessage):
            ohsdigi.q65_encode("K1ABC W9XYZ +999")


class FallbackTests(unittest.TestCase):
    def test_absent_module_means_fallback_not_failure(self):
        # A build without ohsdigi (an architecture we ship no binary for):
        # importing ohscore.ohsdigi fails, and the loader says so instead of
        # raising.
        with mock.patch.dict(sys.modules, {"ohscore.ohsdigi": None}):
            mod, why = ft8._load_ohsdigi()
        self.assertIsNone(mod)
        self.assertTrue(why)

    def test_a_module_for_another_wsjtx_is_not_used(self):
        fake = mock.Mock(WSJTX_VERSION="3.0.1")
        with mock.patch.dict(sys.modules, {"ohscore.ohsdigi": fake}):
            mod, why = ft8._load_ohsdigi()
        self.assertIsNone(mod)
        self.assertIn("3.0.1", why)

    @unittest.skipUnless(ft8._JT9 and ft8._FT8CODE and ft8._FT4CODE, "needs jt9, ft8code and ft4code")
    def test_fallback_encodes_and_jt9_decodes_both_modes(self):
        for variant in ("ft8", "ft4"):
            with self.subTest(variant=variant):
                audio = ft8.Encoder(ohsdigi=None).render(text="CQ GM4BRI IO86", variant=variant)
                self.assertEqual(_jt9_decode(audio, variant), ["CQ GM4BRI IO86"])

    def test_fallback_waveform_is_wsjtxs_as_ohsdigi_makes_it(self):
        # ohsdigi's waveform is WSJT-X's (checked against ft8sim above), so
        # the fallback is held to it sample by sample: same framing, pulse,
        # carrier phase and ramps. The tolerance is the drift single
        # precision leaves in WSJT-X's (and ohsdigi's) phase over a whole
        # transmission, worst at a high audio offset (~0.013 at 2700 Hz);
        # the old Gaussian, four times too wide, was out by the full
        # amplitude within a symbol or two.
        if ohsdigi is None:
            self.skipTest("ohsdigi not built")
        for variant in ("ft8", "ft4"):
            for msg in ("CQ GM4BRI IO86", "G4XYZ EA4QRP R-12"):
                for f0 in (300.0, 1500.0, 2700.0):
                    with self.subTest(variant=variant, msg=msg, f0=f0):
                        e = ohsdigi.encode(variant, msg)
                        tones = "".join(str(t) for t in e.tones)
                        if variant == "ft4":
                            tones = f"0{tones}0"       # as ft4code prints them, ramp symbols included
                        want = np.frombuffer(e.waveform(f0, FS), dtype="<f4").astype(np.float64)
                        got = ft8._gfsk_audio(tones, variant, f0)
                        self.assertEqual(len(got), len(want))
                        err = np.abs(got - want)
                        self.assertLess(err.max(), 0.02)
                        self.assertLess(np.sqrt(np.mean(err ** 2)), 0.008)

    @unittest.skipUnless(ft8._FT8CODE and ft8._FT4CODE, "needs ft8code and ft4code")
    def test_fallback_tones_as_ft8code_and_ft4code_give_them(self):
        # The fallback's input is the codec's printed symbols; for FT4 that
        # is 105 with the ramp symbols, which _gfsk_audio strips.
        if ohsdigi is None:
            self.skipTest("ohsdigi not built")
        for variant, codec in (("ft8", ft8._FT8CODE), ("ft4", ft8._FT4CODE)):
            with self.subTest(variant=variant):
                printed = ft8._channel_symbols(codec, "CQ GM4BRI IO86")
                inner = printed[1:-1] if variant == "ft4" else printed
                self.assertEqual(inner, "".join(str(t) for t in ohsdigi.encode(variant, "CQ GM4BRI IO86").tones))

    @unittest.skipUnless(ft8._FT8CODE, "needs ft8code")
    def test_fallback_refuses_a_bad_message_as_ohsdigi_does(self):
        with self.assertRaises(ValueError) as cm:
            ft8.Encoder(ohsdigi=None).render(text="K1ABC W9XYZ +999", variant="ft8")
        self.assertIn("bad message", str(cm.exception))

    def test_without_ft4code_ohsdigi_still_sends_ft4(self):
        # The Windows case: WSJT-X there has no ft4code. With ohsdigi, FT4 is
        # not receive-only.
        if ohsdigi is None:
            self.skipTest("ohsdigi not built")
        with mock.patch.object(ft8, "_FT4CODE", None):
            audio = ft8.Encoder().render(text="CQ GM4BRI IO86", variant="ft4")
        self.assertEqual(len(audio), 105 * 576)


if __name__ == "__main__":
    unittest.main()
