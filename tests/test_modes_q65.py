import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""Q65-60A, loopback - in the style of test_modes_ft8.py, scoped to what
ohscore/modes/q65.py does: one decode pass a period, no averaging. The
loopback runs through whatever decodes here (ohsdigi first, jt9 as the
fallback); the jt9 program path has its own tests (ohsdigi=None), which
skip where WSJT-X is not installed. That ohsdigi decodes as jt9 does is
rust/ohsdigi/tests/q65_golden.rs's to prove."""
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from ohscore.modes import q65

FS = q65.FS


def _feed_one_period(dec, audio, timeout=10.0):
    slot_n = int(round(q65.PERIOD_S * FS))
    padded = np.zeros(slot_n, dtype=np.float32)
    padded[:len(audio)] = audio[:slot_n]
    block = 1200
    t = 0.0
    for i in range(0, len(padded), block):
        dec.feed(padded[i:i + block], t=t)
        t += block / FS
    dec.feed(np.zeros(block, dtype=np.float32), t=t)
    return t


@unittest.skipUnless(q65.CAN_ENCODE, "neither ohsdigi nor wsjtx (jt9/q65code) here")
class Q65LoopbackTests(unittest.TestCase):
    def _decode(self, text, offset=1500.0, noise_std=0.0, seed=1, timeout=20.0):
        audio = q65.Encoder().render(text=text, offset=offset)
        if noise_std:
            rng = np.random.default_rng(seed)
            audio = audio + rng.normal(0, noise_std, len(audio)).astype(np.float32)
        done = threading.Event()
        events = []

        def on_event(ev):
            events.append(ev)
            done.set()

        dec = q65.Decoder(on_event)
        _feed_one_period(dec, audio)
        done.wait(timeout)
        dec.close()
        return events

    def test_clean_cq(self):
        events = self._decode("CQ GM4BRI IO86")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["text"], "CQ GM4BRI IO86")
        self.assertEqual(events[0]["call"], "GM4BRI")
        self.assertEqual(events[0]["grid"], "IO86")
        self.assertEqual(events[0]["mode"], "q65")
        self.assertEqual(events[0]["ap"], "q0")           # no MyCall/DxCall given

    def test_a_reply_parses_call_not_grid(self):
        events = self._decode("GM4BRI G0ABC R-05")
        self.assertEqual(events[0]["call"], "G0ABC")
        self.assertNotIn("grid", events[0])

    def test_feed_never_blocks_the_caller(self):
        audio = q65.Encoder().render(text="CQ GM4BRI IO86")
        dec = q65.Decoder(lambda e: None)
        t0 = time.monotonic()
        _feed_one_period(dec, audio)
        self.assertLess(time.monotonic() - t0, 1.0)
        dec.close()


@unittest.skipUnless(q65.CAN_ENCODE, "neither ohsdigi nor wsjtx (jt9/q65code) here")
class Q65CallsTests(unittest.TestCase):
    """jt9's a-priori passes need the operator's call, exactly as FT8's do
    (ft8.py's _jt9_call/_calls_now, reused here). Demonstrating the AP
    *benefit* the way test_modes_ft8.py's Jt9CallsTests does needs a slot
    weakened to within Q65-60A's narrow no-AP-vs-AP margin (-27.6 vs
    -30.2 dB, the Quick-Start Guide's table): experimentally, this signal
    decoded at every noise level tried up to the point it failed outright
    for both, with no std that only AP rescued - Q65's deeper AP gain is
    demonstrated over several averaged periods (the guide's own worked
    example needed three), which this first cut does not implement. So
    this checks the wiring - the right call reaches jt9 - rather than the
    decode margin."""

    def test_mycall_and_dxcall_reach_jt9(self):
        calls = lambda: ("g4xyz", "w9xyz")  # noqa: E731
        with mock.patch.object(q65.subprocess, "run") as run:
            run.return_value.stdout = ""
            with mock.patch.object(q65, "_JT9", "/usr/bin/jt9"):
                dec = q65.Decoder(lambda e: None, calls=calls, ohsdigi=None)
                dec._decode_slot(0.0, np.zeros(int(q65.PERIOD_S * FS), np.float32))
                dec.close()
        args = run.call_args[0][0]
        self.assertIn("'G4XYZ'", args)
        self.assertIn("'W9XYZ'", args)
        self.assertEqual(args[args.index("-c") + 1], "'G4XYZ'")
        self.assertEqual(args[args.index("-x") + 1], "'W9XYZ'")

    def test_no_call_is_still_a_plain_decode(self):
        # Unlike FT8's K1ABC/W9XYZ-hunting default, a clean signal with no
        # AP help at all still decodes here - this message just is not
        # K1ABC's, so there is no false-decode risk to guard against.
        audio = q65.Encoder().render(text="G4XYZ W9XYZ R-09")
        events = []
        dec = q65.Decoder(events.append, calls=None)
        _feed_one_period(dec, audio)
        deadline = time.monotonic() + 20
        while dec._busy and time.monotonic() < deadline:
            time.sleep(0.05)
        dec.close()
        self.assertEqual([(e.get("text"), e.get("ap")) for e in events], [("G4XYZ W9XYZ R-09", "q0")])


class Jt9OutputTests(unittest.TestCase):
    """jt9 -3's own stdout lines, as measured against q65sim/q65code-built
    WAVs (wsjtx 2.7.0): a non-clock leading field, SNR, DT, df, then the
    sync marker ":" and the text, ending in a "q#" (optionally "q##") flag
    - not FT8/FT4's "~"/"+"-marked, "a#"/"?"-flagged lines."""

    def parse(self, line):
        return q65._parse_jt9_output(line, 0.0)[0]

    def test_a_q0_decode_keeps_its_text(self):
        ev = self.parse("0000 -25  0.1 1200 :  CQ G4XYZ IO91                         q0 ")
        self.assertEqual(ev["text"], "CQ G4XYZ IO91")
        self.assertEqual(ev["call"], "G4XYZ")
        self.assertEqual(ev["ap"], "q0")
        self.assertNotIn("averaged", ev)

    def test_an_averaged_decode_reports_how_many_periods(self):
        ev = self.parse("022900 -20 0.4 1010 :  K1JT K9AN R-16                       q22")
        self.assertEqual(ev["text"], "K1JT K9AN R-16")
        self.assertEqual(ev["ap"], "q2")
        self.assertEqual(ev["averaged"], 2)

    def test_the_leading_field_need_not_be_six_digits(self):
        # jt9 -3 does not print a reliable hhmmss the way -8/-5 do (measured:
        # "0000" from a filename with no embedded clock, "****" from one it
        # could not parse); this module never reads that field either way.
        ev = self.parse("**** 45 -1.0 1500 :  K1ABC W9XYZ EN37                      q3 ")
        self.assertEqual(ev["text"], "K1ABC W9XYZ EN37")


class TempFolderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(tempfile, "tempdir", str(self.tmp))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def ours(self):
        return sorted(d.name for d in self.tmp.iterdir() if d.name.startswith(q65.TMP_PREFIX))

    def settled(self, dec, timeout=10.0):
        end = time.monotonic() + timeout
        while dec._busy and time.monotonic() < end:
            time.sleep(0.01)
        with dec._dir_lock:
            return dec._busy == 0


@unittest.skipUnless(q65._JT9 and q65._Q65CODE, "wsjtx (jt9/q65code) not installed")
class TempFolderTests(TempFolderCase):
    """As ft8.py's: jt9 gets one working directory for the decoder's life,
    emptied but for jt9's FFT wisdom between decodes, removed by close()."""

    def decode_once(self, dec):
        done = threading.Event()
        dec.emit = lambda ev: done.set()
        _feed_one_period(dec, q65.Encoder(ohsdigi=None).render(text="CQ GM4BRI IO86"))
        self.assertTrue(done.wait(20))
        self.assertTrue(self.settled(dec))

    def test_a_decoder_that_never_decodes_leaves_nothing(self):
        dec = q65.Decoder(lambda e: None, ohsdigi=None)
        dec.reset()
        dec.reset()
        self.assertEqual(self.ours(), [])

    def test_each_decode_leaves_only_the_fft_wisdom_and_close_removes_the_rest(self):
        dec = q65.Decoder(lambda e: None, ohsdigi=None)
        self.decode_once(dec)
        dec.reset()
        self.decode_once(dec)
        dirs = self.ours()
        self.assertEqual(len(dirs), 1)
        self.assertEqual(sorted(os.listdir(self.tmp / dirs[0])), ["jt9_wisdom.dat"])
        dec.close()
        self.assertEqual(self.ours(), [])
        dec.close()


class StaleFolderSweep(TempFolderCase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(q65, "_swept", False)
        p.start()
        self.addCleanup(p.stop)

    def folder(self, name, age_s):
        d = self.tmp / name
        d.mkdir()
        (d / "timer.out").write_text("x")
        t = time.time() - age_s
        os.utime(d, (t, t))
        return d

    def test_folders_left_by_earlier_runs_are_removed_after_a_day_and_nothing_else(self):
        old = self.folder(f"{q65.TMP_PREFIX}abc123", 2 * 86400)
        recent = self.folder(f"{q65.TMP_PREFIX}recent", 3600)
        other = self.folder("ohsnb-ft8-xyz", 2 * 86400)
        q65._sweep_stale()
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(other.exists())


class Q65EncoderShapeTests(unittest.TestCase):
    @unittest.skipUnless(q65.CAN_ENCODE, "neither ohsdigi nor wsjtx here")
    def test_render_is_float32_mono_peak_limited(self):
        audio = q65.Encoder().render(text="CQ GM4BRI IO86")
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(audio.ndim, 1)
        self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)

    @unittest.skipUnless(q65.CAN_ENCODE, "neither ohsdigi nor wsjtx here")
    def test_duration_matches_85_symbols_at_0_6s(self):
        audio = q65.Encoder().render(text="CQ GM4BRI IO86")
        expected = 85 * 0.6
        self.assertAlmostEqual(len(audio) / FS, expected, delta=0.01)

    def test_a_channel_symbol_count_mismatch_is_caught(self):
        # q65code's own output format is the only thing standing between a
        # change in some future WSJT-X and a silently wrong waveform; this
        # is what that check looks like failing.
        with mock.patch.object(q65.subprocess, "run") as run:
            run.return_value.stdout = "Channel symbols (85 total)\n0 1 2\n"
            with self.assertRaises(ValueError):
                q65._channel_symbols("CQ GM4BRI IO86")


@unittest.skipUnless(q65._OHSDIGI_Q65 is not None, "ohsdigi without Q65 (tools/build-ohsdigi.sh --host --install)")
class OhsdigiTests(TempFolderCase):
    def test_the_waveform_is_wsjtxs_unshaped_fsk_not_the_fallback_tones(self):
        a = q65.Encoder().render(text="CQ GM4BRI IO86", offset=1200.0)
        b = q65.Encoder(ohsdigi=None).render(text="CQ GM4BRI IO86", offset=1200.0) \
            if (q65._JT9 and q65._Q65CODE) else None
        # 85 symbols of 7200 samples, the fade at the very end.
        self.assertEqual(len(a), 85 * 7200)
        self.assertLess(abs(float(a[-1])), 0.1 * float(np.max(np.abs(a))))
        if b is not None:
            self.assertEqual(len(a), len(b))

    def test_a_period_decodes_without_a_temporary_folder(self):
        events = []
        dec = q65.Decoder(events.append, calls=lambda: ("GM4BRI", "G0ABC"))
        audio = np.zeros(int(q65.PERIOD_S * FS), np.float32)
        sig = q65.Encoder().render(text="GM4BRI G0ABC R-05")
        start = int(q65.START_S * FS)
        audio[start:start + len(sig)] = 0.3 * sig
        _feed_one_period(dec, audio)
        end = time.monotonic() + 20
        while dec._busy and time.monotonic() < end:
            time.sleep(0.01)
        dec.close()
        # With DxCall G0ABC known the list decode finds it first: q3.
        self.assertEqual([(e["text"], e["ap"], e["dt"]) for e in events], [("GM4BRI G0ABC R-05", "q3", 0.1)])
        self.assertEqual(self.ours(), [])

    def test_a_raising_ohsdigi_hands_the_period_to_jt9(self):
        class Broken:
            def q65_decode(self, *a, **k):
                raise RuntimeError("ohsdigi bug")

            def q65_encode_audio(self, *a, **k):
                raise RuntimeError("ohsdigi bug")

        with mock.patch.object(q65, "_JT9", "/usr/bin/jt9"), mock.patch.object(q65.subprocess, "run") as run:
            run.return_value.stdout = run.return_value.stderr = ""
            run.return_value.returncode = 0
            dec = q65.Decoder(lambda e: None, ohsdigi=Broken())
            dec._decode_slot(0.0, np.zeros(int(q65.PERIOD_S * FS), np.float32))
            dec.close()
        self.assertEqual(run.call_args[0][0][:2], ["/usr/bin/jt9", "-3"])


class Q65ModeRegistryTests(unittest.TestCase):
    def test_listed_whether_or_not_wsjtx_is_installed(self):
        from ohscore.modes import MODES
        self.assertIn("q65", MODES)
        info = MODES["q65"]
        self.assertEqual(info.available, q65.CAN_ENCODE)
        if not q65.CAN_ENCODE:
            self.assertEqual(info.why, q65.WHY_UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
