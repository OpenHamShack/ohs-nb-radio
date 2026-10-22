import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import shutil
import signal
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from ohscore.modes import decoder_shadow, ft8

FS = 12_000.0


def _feed_one_slot(dec, audio, variant, timeout=10.0):
    """Pad audio to exactly one slot, feed it in small blocks starting at a
    slot boundary (t=0), then feed one more block past the boundary so the
    decoder's own slot-end logic fires -- and wait (via an Event set from
    inside emit) for the worker thread's jt9 result rather than sleeping a
    fixed guess."""
    slot_n = int(round(ft8.SLOT_S[variant] * FS))
    padded = np.zeros(slot_n, dtype=np.float32)
    padded[:len(audio)] = audio[:slot_n]
    block = 1200
    t = 0.0
    for i in range(0, len(padded), block):
        dec.feed(padded[i:i + block], t=t)
        t += block / FS
    dec.feed(np.zeros(block, dtype=np.float32), t=t)
    return t


FT4_ENC = unittest.skipUnless(ft8.CAN_ENCODE["ft4"], "no FT4 encoder (neither ohsdigi nor ft4code)")


@unittest.skipUnless(ft8.CAN_ENCODE["ft8"], "wsjtx (jt9/ft8code) not installed")
class Ft8LoopbackTests(unittest.TestCase):
    def _decode(self, text, variant="ft8", offset=1500.0, noise_std=0.0, seed=1, timeout=10.0):
        audio = ft8.Encoder().render(text=text, variant=variant, offset=offset)
        if noise_std:
            rng = np.random.default_rng(seed)
            audio = audio + rng.normal(0, noise_std, len(audio)).astype(np.float32)
        done = threading.Event()
        events = []

        def on_event(ev):
            events.append(ev)
            done.set()

        dec = ft8.Decoder(on_event, variant=variant, offset=offset)
        _feed_one_slot(dec, audio, variant)
        done.wait(timeout)
        # Finished and closed before the next test: a pass still running
        # writes its slot summary into whichever test is capturing the log
        # by then (SlotLog's counts lines exactly).
        _settle(dec)
        dec.close()
        return events

    def test_clean_ft8_cq(self):
        events = self._decode("CQ GM4BRI IO86", variant="ft8")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["text"], "CQ GM4BRI IO86")
        self.assertEqual(events[0]["call"], "GM4BRI")
        self.assertEqual(events[0]["grid"], "IO86")
        self.assertEqual(events[0]["mode"], "ft8")

    def test_noisy_ft8_still_decodes(self):
        # FT8's whole point is decoding well below the noise floor; this is
        # a modest SNR by its standards, nowhere near where it gives up.
        events = self._decode("CQ GM4BRI IO86", variant="ft8", noise_std=0.6)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["text"], "CQ GM4BRI IO86")
        self.assertLess(events[0]["snr"], 10)  # confirms the noise was actually doing something

    @FT4_ENC
    def test_ft4_cq(self):
        events = self._decode("CQ GM4BRI IO86", variant="ft4")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["text"], "CQ GM4BRI IO86")
        self.assertEqual(events[0]["mode"], "ft4")

    def test_reply_with_report_parses_call_not_grid(self):
        events = self._decode("GM4BRI G0ABC R-05", variant="ft8")
        self.assertEqual(events[0]["call"], "G0ABC")
        self.assertNotIn("grid", events[0])

    def test_rr73_is_not_mistaken_for_a_grid(self):
        # RR73 has the same two-letters-two-digits shape as a locator; this
        # is exactly the collision _parse_standard has to not fall into.
        events = self._decode("GM4BRI G0ABC RR73", variant="ft8")
        self.assertEqual(events[0]["call"], "G0ABC")
        self.assertNotIn("grid", events[0])

    def test_different_audio_offset(self):
        events = self._decode("CQ GM4BRI IO86", variant="ft8", offset=2200.0)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["df"], 2200)

    def test_feed_never_blocks_the_caller(self):
        # The whole design point of the worker thread: feed() returns long
        # before jt9 could possibly have finished (it takes >1 s even on a
        # fast machine, per DESIGN.md's own description of it).
        import time
        audio = ft8.Encoder().render(text="CQ GM4BRI IO86", variant="ft8")
        dec = ft8.Decoder(lambda e: None, variant="ft8")
        t0 = time.monotonic()
        _feed_one_slot(dec, audio, "ft8")
        self.assertLess(time.monotonic() - t0, 1.0)
        _settle(dec)
        dec.close()


def _alone(which: str):
    """(context, Decoder keywords) for decoding with one decoder only:
    "jt9" with no ohsdigi, "ohsdigi" with jt9 made absent (as on a machine
    without WSJT-X) - so neither has a shadow and neither can fall back."""
    import contextlib
    if which == "jt9":
        return contextlib.nullcontext(), {"ohsdigi": None}
    return mock.patch.object(ft8, "_JT9", None), {}


HAVE_JT9 = unittest.skipUnless(ft8._JT9 and ft8.CAN_ENCODE["ft8"], "no jt9 (wsjtx not installed)")
HAVE_BOTH = unittest.skipUnless(ft8._OHSDIGI_DEC is not None and ft8._JT9,
                                "needs ohsdigi (tools/build-ohsdigi.sh --host --install) and jt9")


@HAVE_JT9
class Jt9CallsTests(unittest.TestCase):
    """jt9's a-priori passes look for the operator's call, not jt9's
    built-in K1ABC. The slot is "G4XYZ W9XYZ R-09" at -21 dB (ft8sim's
    2500 Hz convention), seed 7: too weak for jt9 to decode unaided, and
    decoded as an a2 (MyCall) decode when jt9 is told MyCall is G4XYZ -
    found by search, for ohsdigi's waveform and the fallback's alike.
    OhsdigiCallsTests runs the same with ohsdigi decoding."""

    MSG = "G4XYZ W9XYZ R-09"
    DECODER = "jt9"

    @staticmethod
    def slot(msg="G4XYZ W9XYZ R-09"):
        a = ft8.Encoder().render(text=msg, variant="ft8", offset=1500.0).astype(np.float64)
        a /= np.max(np.abs(a))
        rng = np.random.default_rng(7)
        wave = np.zeros(int(15 * FS))
        wave[6000:6000 + len(a)] += np.sqrt(2 * 2500 / 6000) * 10 ** (0.05 * -21) * a
        wave += rng.normal(0, 1, len(wave))
        return (wave / 300.0).astype(np.float32)

    def _decode(self, calls):
        events = []
        ctx, kw = _alone(self.DECODER)
        with ctx:
            dec = ft8.Decoder(events.append, variant="ft8", calls=calls, **kw)
            try:
                _feed_one_slot(dec, self.slot(self.MSG), "ft8")
                deadline = time.monotonic() + 20
                while dec._busy and time.monotonic() < deadline:   # the early pass and the final one
                    time.sleep(0.05)
            finally:
                dec.close()
        return [(e.get("text"), e.get("ap")) for e in events]

    def test_mycall_steers_the_a_priori_passes(self):
        self.assertEqual(self._decode(lambda: ("g4xyz", "")), [(self.MSG, "a2")])

    def test_no_call_means_no_mycall_ap_not_k1abc(self):
        self.assertEqual(self._decode(None), [])
        self.assertEqual(self._decode(lambda: ("", "")), [])

    def test_a_portable_call_reaches_jt9_whole(self):
        # Unquoted, jt9 would read "G4XYZ/P" as "G4XYZ" (Fortran
        # list-directed input stops at "/") and find this message to G4XYZ.
        self.assertEqual(self._decode(lambda: ("G4XYZ/P", "")), [])

    def test_a_failing_lookup_costs_ap_not_the_decode(self):
        def broken():
            raise KeyError("callsign")
        self.assertEqual(self._decode(broken), [])

    def test_argument_spelling(self):
        self.assertEqual(ft8._jt9_call("G4XYZ"), "'G4XYZ'")
        self.assertEqual(ft8._jt9_call("pj4/k1abc"), "'PJ4/K1ABC'")
        for nothing in ("", "  ", "G4 XYZ", "G4XYZ'", "ABCDEFGHIJKLM"):
            self.assertEqual(ft8._jt9_call(nothing), "b", nothing)
        self.assertEqual(ft8._calls_now(lambda: (" g4xyz ", "w9 xyz")), ("G4XYZ", ""))


@unittest.skipUnless(ft8._OHSDIGI_DEC is not None and ft8.CAN_ENCODE["ft8"], "ohsdigi not built")
class OhsdigiCallsTests(Jt9CallsTests):
    DECODER = "ohsdigi"


class Jt9OutputTests(unittest.TestCase):
    """jt9's own stdout lines, as WSJT-X 2.x prints them."""

    def parse(self, line):
        return ft8._parse_jt9_output(line, "ft8", 0.0)[0]

    def test_an_a_priori_decode_keeps_its_call(self):
        ev = self.parse("192845 -12  0.3 1500 ~  CQ G4XYZ IO91                          a1")
        self.assertEqual(ev["text"], "CQ G4XYZ IO91")
        self.assertEqual(ev["call"], "G4XYZ")
        self.assertEqual(ev["ap"], "a1")
        ev = self.parse("192845 -20  0.1  900 ~  M0ABC G4XYZ -15                        a7")
        self.assertEqual((ev["text"], ev["call"]), ("M0ABC G4XYZ -15", "G4XYZ"))

    def test_a_low_confidence_mark_is_not_part_of_the_message(self):
        ev = self.parse("192845 -22  0.2 1200 ~  CQ EA8ABC IL18                         ?")
        self.assertEqual((ev["text"], ev["call"]), ("CQ EA8ABC IL18", "EA8ABC"))
        self.assertTrue(ev["lowConfidence"])

    def test_a_low_confidence_a_priori_decode_keeps_neither_mark(self):
        # A real on-air decode (07/10/2026, ohsnb --analyse against Brian's
        # QO-100 recording) carried both marks, "?" then "a1": only the
        # trailing one ("a1") was being stripped, so the message kept a
        # "?" and a column of padding - wrong text, and a lookup/reply
        # that could never match the call it plainly contains.
        ev = self.parse("128256  14  0.8  619 ~  CQ RN3DDW KO85                      ? a1")
        self.assertEqual((ev["text"], ev["call"]), ("CQ RN3DDW KO85", "RN3DDW"))
        self.assertEqual(ev["ap"], "a1")
        self.assertTrue(ev["lowConfidence"])

    def test_a_plain_decode_is_untouched(self):
        ev = self.parse("192845  -5  0.1 1500 ~  CQ G4XYZ IO91")
        self.assertEqual(ev["text"], "CQ G4XYZ IO91")
        self.assertNotIn("ap", ev)
        self.assertNotIn("lowConfidence", ev)


class _Recorder(ft8.Decoder):
    """A decoder that records each decode it would start - where in the slot
    the audio stood, and what audio - instead of running jt9: the timing
    logic, tested on its own with the clock (feed's `t`) in our hands."""

    def __init__(self, *a, **kw):
        self.started = []
        super().__init__(*a, **kw)

    def _start(self, run, pcm, after):
        self.started.append((run.slot_t0, self._end / FS, "final" if after is not None or run.early else "early", pcm))
        th = threading.Thread(target=lambda: None)
        th.start()
        return th


@unittest.skipUnless(ft8.CAN_ENCODE["ft8"], "wsjtx (jt9/ft8code) not installed")
class SlotTimingTests(unittest.TestCase):
    """Decodes must be ready before the next slot begins, so an answer to a
    CQ can go in it (WSJT-X decodes FT8 at 11.8/13.5/14.7 s into the slot).
    The decoder used to decode only once the slot had ended."""

    T0 = 1_791_000_000.0      # a slot boundary for both modes (divisible by 15)

    def _feed(self, dec, audio, t0, upto_s, block=1200):
        n = int(round(upto_s * FS))
        for i in range(0, n, block):
            dec.feed(audio[i:min(i + block, n)], t=t0 + i / FS)

    def test_ft8_decode_starts_at_13_5_s_with_the_rest_zero(self):
        dec = _Recorder(lambda e: None, variant="ft8")
        audio = np.ones(int(15 * FS), np.float32)
        self._feed(dec, audio, self.T0, 13.4)
        self.assertEqual(dec.started, [])
        self._feed_from(dec, audio, self.T0, 13.4, 13.6)
        self.assertEqual(len(dec.started), 1)
        slot, at, kind, pcm = dec.started[0]
        self.assertEqual((slot, kind), (self.T0, "early"))
        self.assertAlmostEqual(at, 13.5, delta=0.11)
        self.assertEqual(len(pcm), int(15 * FS))                       # padded to the whole slot
        self.assertTrue(np.all(pcm[:int(13.5 * FS)] == 1.0))
        self.assertTrue(np.all(pcm[int(13.6 * FS):] == 0.0))
        self._feed_from(dec, audio, self.T0, 13.6, 15.1)
        self.assertEqual([k for _, _, k, _ in dec.started], ["early", "final"])

    def test_ft4_decode_starts_at_6_s(self):
        dec = _Recorder(lambda e: None, variant="ft4")
        audio = np.ones(int(7.5 * FS), np.float32)
        self._feed(dec, audio, self.T0, 5.9)
        self.assertEqual(dec.started, [])
        self._feed_from(dec, audio, self.T0, 5.9, 6.1)
        self.assertEqual([k for _, _, k, _ in dec.started], ["early"])

    def _feed_from(self, dec, audio, t0, from_s, to_s, block=1200):
        a, b = int(round(from_s * FS)), int(round(to_s * FS))
        for i in range(a, b, block):
            j = min(i + block, b)
            chunk = audio[i:j] if j <= len(audio) else np.zeros(j - i, np.float32)
            dec.feed(chunk, t=t0 + i / FS)

    def test_a_real_cq_decodes_before_the_slot_ends(self):
        sig = ft8.Encoder().render(text="CQ GM4BRI IO86", variant="ft8")
        audio = np.zeros(int(15 * FS), np.float32)
        audio[int(0.5 * FS):int(0.5 * FS) + len(sig)] = sig
        audio += np.random.default_rng(3).normal(0, 0.3, len(audio)).astype(np.float32)
        got = threading.Event()
        events = []
        dec = ft8.Decoder(lambda e: (events.append(e), got.set()), variant="ft8")
        self._feed(dec, audio, self.T0, 13.6)                 # and not a sample more
        self.assertTrue(got.wait(10.0), "no decode from 13.6 s of the slot")
        self.assertEqual(events[0]["text"], "CQ GM4BRI IO86")
        self.assertEqual(events[0]["slot"], self.T0)

    def test_audio_is_placed_by_its_time_not_appended(self):
        # The decoder made just after a slot boundary (the operator picked
        # FT8 0.4 s into the slot): the first sample it is given is 0.4 s
        # into the slot, and jt9 must see it there, or DT comes out -0.4.
        sig = ft8.Encoder().render(text="CQ GM4BRI IO86", variant="ft8")
        audio = np.zeros(int(15 * FS), np.float32)
        audio[int(0.5 * FS):int(0.5 * FS) + len(sig)] = sig
        got = threading.Event()
        events = []
        dec = ft8.Decoder(lambda e: (events.append(e), got.set()), variant="ft8")
        self._feed_from(dec, audio, self.T0, 0.4, 13.6)
        self.assertTrue(got.wait(10.0))
        self.assertLess(abs(events[0]["dt"]), 0.15)

    def test_the_final_pass_does_not_repeat_the_early_one(self):
        sig = ft8.Encoder().render(text="CQ GM4BRI IO86", variant="ft8")
        audio = np.zeros(int(16 * FS), np.float32)
        audio[int(0.5 * FS):int(0.5 * FS) + len(sig)] = sig
        events = []
        threads = []
        dec = ft8.Decoder(events.append, variant="ft8")
        orig = dec._start
        dec._start = lambda run, pcm, after: threads.append(orig(run, pcm, after)) or threads[-1]
        self._feed_from(dec, audio, self.T0, 0.0, 15.5)
        self.assertEqual(len(threads), 2)
        for th in threads:
            th.join(15.0)
        self.assertEqual([e["text"] for e in events], ["CQ GM4BRI IO86"])

    def test_a_late_starter_is_caught_by_the_final_pass(self):
        # A station 2.3 s late (DT +1.8, inside FT8's +-2.5 s search) is
        # still sending at 13.5 s. Whichever pass decodes it -- the early one
        # often manages with the end cut off, the final one has all of it --
        # it is reported, and reported once.
        sig = ft8.Encoder().render(text="CQ G0ABC IO91", variant="ft8")
        audio = np.zeros(int(16 * FS), np.float32)
        audio[int(2.3 * FS):int(2.3 * FS) + len(sig)] = sig
        events = []
        threads = []
        dec = ft8.Decoder(events.append, variant="ft8")
        orig = dec._start
        dec._start = lambda run, pcm, after: threads.append(orig(run, pcm, after)) or threads[-1]
        self._feed_from(dec, audio, self.T0, 0.0, 15.5)
        for th in threads:
            th.join(15.0)
        self.assertEqual([e["text"] for e in events], ["CQ G0ABC IO91"])


class TempFolderCase(unittest.TestCase):
    """The decoder's working directories go in the system temp folder; here
    that is a scratch folder of the test's own, so what is left behind can
    be counted without touching the real one."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(tempfile, "tempdir", str(self.tmp))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def ours(self):
        return sorted(d.name for d in self.tmp.iterdir() if d.name.startswith(ft8.TMP_PREFIX))

    def settled(self, dec, timeout=10.0):
        end = time.monotonic() + timeout
        while dec._busy and time.monotonic() < end:
            time.sleep(0.01)
        # _leave drops _busy to 0 and then removes the folder, both under
        # _dir_lock; reading _busy without it could see 0 while the rmtree
        # was still running (the NB 0.1.7 release run did), so wait for the
        # lock as well before anyone looks at the folder.
        with dec._dir_lock:
            return dec._busy == 0


@HAVE_JT9
class TempFolderTests(TempFolderCase):
    """Until 0.1.2 every decoder made an ohsnb-ft8-* folder when it was
    created or reset, and nothing ever removed one. jt9 decodes here (no
    ohsdigi): the folders are jt9's."""

    def decode_once(self, dec):
        done = threading.Event()
        dec.emit = lambda ev: done.set()
        _feed_one_slot(dec, ft8.Encoder().render(text="CQ GM4BRI IO86"), "ft8")
        self.assertTrue(done.wait(10))
        self.assertTrue(self.settled(dec))

    def test_a_decoder_that_never_decodes_leaves_nothing(self):
        dec = ft8.Decoder(lambda e: None, ohsdigi=None)
        dec.reset()
        dec.reset()
        self.assertEqual(self.ours(), [])

    def test_each_decode_leaves_only_the_fft_wisdom_and_close_removes_the_rest(self):
        dec = ft8.Decoder(lambda e: None, ohsdigi=None)
        self.decode_once(dec)
        dec.reset()                                    # the same slot again, as a fresh one
        self.decode_once(dec)
        dirs = self.ours()
        self.assertEqual(len(dirs), 1)                 # one folder for the decoder's life
        self.assertEqual(sorted(os.listdir(self.tmp / dirs[0])), ["jt9_wisdom.dat"])
        dec.close()
        self.assertEqual(self.ours(), [])
        dec.close()                                    # twice is harmless

    def test_closing_mid_decode_removes_the_folder_when_the_decode_ends(self):
        dec = ft8.Decoder(lambda e: None, ohsdigi=None)
        started, release = threading.Event(), threading.Event()
        real_run = ft8.subprocess.run

        def slow_jt9(*a, **kw):
            started.set()
            release.wait(10)
            return real_run(*a, **kw)
        # Rendered before the patch: without ohsdigi, the Encoder itself runs
        # ft8code through subprocess.run, and the stand-in for a slow jt9
        # would catch that call first (07/10, on a machine without ohsdigi).
        audio = ft8.Encoder().render(text="CQ GM4BRI IO86")
        with mock.patch.object(ft8.subprocess, "run", slow_jt9):
            _feed_one_slot(dec, audio, "ft8")
            self.assertTrue(started.wait(10))
            dec.close()
            self.assertEqual(len(self.ours()), 1)      # jt9 is still working in it
            release.set()
            self.assertTrue(self.settled(dec))
        self.assertEqual(self.ours(), [])


class StaleFolderSweep(TempFolderCase):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(ft8, "_swept", False)
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
        old_ft8 = self.folder("ohsnb-ft8-abc123", 2 * 86400)
        old_ft4 = self.folder("ohsnb-ft4-def456", 2 * 86400)
        recent = self.folder("ohsnb-ft8-recent", 3600)            # another program may be using it
        other = self.folder("ohsnb-shots-xyz", 2 * 86400)         # not a decoder's
        ft8._sweep_stale()
        self.assertFalse(old_ft8.exists())
        self.assertFalse(old_ft4.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(other.exists())
        again = self.folder("ohsnb-ft8-later", 2 * 86400)
        ft8._sweep_stale()                                       # once per process
        self.assertTrue(again.exists())


class Ft8AvailabilityTests(unittest.TestCase):
    def test_why_sentence_is_the_documented_one(self):
        # Reached only with neither ohsdigi nor an installed jt9. ohsdigi is
        # what every build carries (WSJT-X since 17/10/2026 none), so the
        # sentence is about ohsdigi first; an installed WSJT-X is the other way.
        from ohscore import host
        self.assertTrue(ft8.WHY_UNAVAILABLE.startswith("ohsdigi, OpenHamShack's FT8, FT4 and Q65 decoder, "
                                                       "did not load"), ft8.WHY_UNAVAILABLE)
        if host.WINDOWS:
            self.assertIn("the Windows installer carries it", ft8.WHY_UNAVAILABLE)
        elif host.MACOS:
            self.assertIn("the Mac app carries it", ft8.WHY_UNAVAILABLE)
        else:
            self.assertIn("install wsjtx for its jt9", ft8.WHY_UNAVAILABLE)

    def test_ft4_without_ft4code_or_ohsdigi_says_receive_only_rather_than_install_wsjtx(self):
        # WSJT-X for Windows ships jt9 and ft8code but no ft4code; with no
        # ohsdigi either, FT4 is receive-only.
        from unittest import mock
        with mock.patch.object(ft8, "_JT9", "jt9"), mock.patch.object(ft8, "_FT4CODE", None):
            with self.assertRaises(RuntimeError) as cm:
                ft8.Encoder(ohsdigi=None).render(text="CQ GM4BRI IO86", variant="ft4")
        self.assertEqual(str(cm.exception), ft8.WHY_NO_FT4_ENCODER)


class Ft8EncoderShapeTests(unittest.TestCase):
    @unittest.skipUnless(ft8.CAN_ENCODE["ft8"], "wsjtx not installed")
    def test_render_is_float32_mono_peak_limited(self):
        audio = ft8.Encoder().render(text="CQ GM4BRI IO86", variant="ft8")
        self.assertEqual(audio.dtype, np.float32)
        self.assertEqual(audio.ndim, 1)
        self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)

    @unittest.skipUnless(ft8.CAN_ENCODE["ft8"], "wsjtx not installed")
    def test_ft8_duration_matches_79_symbols(self):
        audio = ft8.Encoder().render(text="CQ GM4BRI IO86", variant="ft8")
        expected = 79 * 0.160
        self.assertAlmostEqual(len(audio) / FS, expected, delta=0.01)

    @FT4_ENC
    def test_ft4_duration_matches_105_symbols(self):
        audio = ft8.Encoder().render(text="CQ GM4BRI IO86", variant="ft4")
        expected = 105 * 0.048
        self.assertAlmostEqual(len(audio) / FS, expected, delta=0.01)


def _settle(dec, timeout=20.0):
    deadline = time.monotonic() + timeout
    while dec._busy and time.monotonic() < deadline:
        time.sleep(0.02)


def _slot(variant, signals, noise=0.0, seed=1):
    """One slot of audio: `signals` are (text, offset Hz, start s, gain)."""
    out = np.zeros(int(round(ft8.SLOT_S[variant] * FS)), np.float32)
    for text, off, start, gain in signals:
        a = ft8.Encoder().render(text=text, variant=variant, offset=off) * gain
        i = int(start * FS)
        n = min(len(a), len(out) - i)
        out[i:i + n] += a[:n]
    if noise:
        out += np.random.default_rng(seed).normal(0, noise, len(out)).astype(np.float32)
    return out


def _events(variant, audio, which, calls=None):
    """Every event one decoder alone emits for one slot, in a fixed order."""
    events = []
    ctx, kw = _alone(which)
    with ctx, mock.patch.dict(os.environ, {decoder_shadow.ENV: "0"}):
        dec = ft8.Decoder(events.append, variant=variant, calls=calls, **kw)
        try:
            _feed_one_slot(dec, audio, variant)
            _settle(dec)
        finally:
            dec.close()
    return sorted(events, key=lambda e: (e["text"], e["df"]))


@HAVE_BOTH
class OhsdigiMatchesJt9(unittest.TestCase):
    """ohsdigi is the decoder; what it emits must be what jt9's output made
    of the same slot, field for field - text, call, grid, SNR, DT,
    frequency, the AP and "?" marks - or the band activity, the country
    column and click-to-answer would change under the operator."""

    FIXTURES = [
        ("clean CQ", "ft8", [("CQ GM4BRI IO86", 1500.0, 0.5, 1.0)], 0.0, None),
        ("noisy CQ", "ft8", [("CQ GM4BRI IO86", 1500.0, 0.5, 1.0)], 0.6, None),
        ("reply with a report", "ft8", [("GM4BRI G0ABC R-05", 1500.0, 0.5, 1.0)], 0.0, None),
        ("RR73", "ft8", [("GM4BRI G0ABC RR73", 1500.0, 0.5, 1.0)], 0.0, None),
        ("another offset", "ft8", [("CQ GM4BRI IO86", 2200.0, 0.5, 1.0)], 0.0, None),
        ("late starter", "ft8", [("CQ G0ABC IO91", 1500.0, 2.3, 1.0)], 0.1, None),
        ("crowded", "ft8", [("CQ DL1ABC JO31", 900.0, 0.6, 0.2), ("CQ GM4BRI IO86", 1500.0, 0.5, 0.2),
                            ("G4XYZ EA4QRP IN80", 2100.0, 1.2, 0.1), ("EA4QRP G4XYZ R-12", 600.0, 0.3, 0.05)],
         0.05, None),
        ("to me, with a call", "ft8", [("G4XYZ EA4QRP IN80", 1500.0, 0.5, 0.3)], 0.2, ("G4XYZ", "EA4QRP")),
        ("FT4 CQ", "ft4", [("CQ GM4BRI IO86", 1500.0, 0.5, 1.0)], 0.0, None),
        ("FT4 crowded", "ft4", [("CQ DL1ABC JO31", 900.0, 0.5, 0.2), ("GM4BRI G0ABC RR73", 1700.0, 0.6, 0.2),
                                ("CQ G0ABC IO91", 2300.0, 0.4, 0.1)], 0.05, None),
    ]

    def test_the_same_events_as_jt9(self):
        for name, variant, signals, noise, calls in self.FIXTURES:
            if variant == "ft4" and not ft8.CAN_ENCODE["ft4"]:
                continue
            with self.subTest(name):
                audio = _slot(variant, signals, noise)
                c = (lambda calls=calls: calls) if calls else None
                jt9 = _events(variant, audio, "jt9", c)
                ours = _events(variant, audio, "ohsdigi", c)
                self.assertTrue(jt9, "the fixture must decode at all")
                self.assertEqual(ours, jt9)

    def test_a_priori_marks_match(self):
        # The weak slot only an a-priori pass decodes (Jt9CallsTests): the
        # "a2" must come through from ohsdigi as it does from jt9's output.
        audio = Jt9CallsTests.slot()
        jt9 = _events("ft8", audio, "jt9", lambda: ("G4XYZ", ""))
        ours = _events("ft8", audio, "ohsdigi", lambda: ("G4XYZ", ""))
        self.assertEqual([e.get("ap") for e in jt9], ["a2"])
        self.assertEqual(ours, jt9)

    def test_hashed_calls_are_named_as_jt9_names_them(self):
        # A message to or from a hashed call shows the call where jt9 knows
        # it (MyCall, the DX call) and "<...>" where it does not; ohsdigi
        # used to show "<...>" even for the operator's own call. See
        # ft8._jt9_hashes for why jt9 knows what it knows.
        msgs = ["<G4XYZ/P> W9XYZ -11", "W9XYZ <G4XYZ/P> R-11", "<PJ4/K1ABC> G4XYZ RR73", "G4XYZ <PJ4/K1ABC> 73",
                "<G4XYZ> PJ4/K1ABC RRR", "PJ4/K1ABC <G4XYZ> RRR", "PJ4/K1ABC <W9XYZ> RR73"]
        calls = [("G4XYZ/P", ""), ("G4XYZ", "PJ4/K1ABC"), ("PJ4/K1ABC", "W9XYZ"), ("G4XYZ", "W9XYZ"), ("", "")]
        dec = ft8.Decoder(lambda e: None, ohsdigi=None)
        try:
            for variant in ("ft8", "ft4"):
                for msg in msgs:
                    audio = _slot(variant, [(msg, 1500.0, 0.5, 0.3)])
                    ints = ft8._pcm16(audio)
                    dec.variant, dec.slot_s = variant, ft8.SLOT_S[variant]
                    for my, dx in calls:
                        with self.subTest(variant=variant, msg=msg, my=my, dx=dx):
                            want = [e["text"] for e in dec._jt9(audio, ints, 0.0, my, dx)]
                            got = [e["text"] for e in ft8._ohsdigi_decode(ft8._OHSDIGI_DEC, variant, ints, 0.0, my, dx)]
                            self.assertEqual(got, want)
        finally:
            dec.close()


class OhsdigiEvents(unittest.TestCase):
    """ohsdigi's decode dicts made into the events jt9's lines become."""

    def ev(self, **d):
        base = {"text": "CQ G4XYZ IO91", "snr": -12, "dt": 0.3, "freq": 1500.0, "ap": 0, "qual": 1.0}
        base.update(d)
        return ft8._ohsdigi_event(base, "ft8", 15.0)

    def test_fields(self):
        ev = self.ev()
        self.assertEqual(ev, {"mode": "ft8", "slot": 15.0, "snr": -12, "dt": 0.3, "df": 1500, "text": "CQ G4XYZ IO91",
                              "call": "G4XYZ", "grid": "IO91"})

    def test_rounded_as_jt9_prints_them(self):
        # f5.1 and nint: to the nearest, a half away from zero.
        for dt, want in ((0.25, 0.3), (-0.25, -0.3), (0.04, 0.0), (1.149999976158142, 1.1), (-1.05, -1.1)):
            self.assertEqual(self.ev(dt=dt)["dt"], want, dt)
        for f, want in ((1500.5, 1501), (1500.49, 1500), (612.7, 613)):
            self.assertEqual(self.ev(freq=f)["df"], want, f)

    def test_a_priori_and_low_confidence(self):
        ev = self.ev(ap=2, qual=0.5)
        self.assertEqual((ev["ap"], "lowConfidence" in ev), ("a2", False))
        ev = self.ev(ap=1, qual=0.1)
        self.assertEqual((ev["ap"], ev["lowConfidence"]), ("a1", True))
        # WSJT-X marks "?" only on a-priori decodes.
        ev = self.ev(ap=0, qual=0.1)
        self.assertNotIn("ap", ev)
        self.assertNotIn("lowConfidence", ev)


def _fake(decodes=(), raises=False):
    m = types.SimpleNamespace()

    def dec(pcm16, depth=1, mycall="", dxcall=""):
        dec.calls += 1
        if raises:
            raise RuntimeError("ohsdigi blew up")
        return [dict(d) for d in decodes]

    dec.calls = 0
    m.ft8_decode = m.ft4_decode = dec
    return m


class _DecoderCase(unittest.TestCase):
    MSG = "CQ GM4BRI IO86"

    def setUp(self):
        p = mock.patch.dict(os.environ, {decoder_shadow.ENV: "0"})
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(ft8, "_said", set())
        q.start()
        self.addCleanup(q.stop)

    def run_slots(self, n=1, **kw):
        """Decode `n` slots of the CQ; (events, statuses reported)."""
        events, statuses = [], []
        audio = _slot("ft8", [(self.MSG, 1500.0, 0.5, 1.0)])
        dec = ft8.Decoder(events.append, variant="ft8", on_decoder=statuses.append, **kw)
        try:
            for k in range(n):
                t0 = k * 15.0
                for i in range(0, len(audio), 1200):
                    dec.feed(audio[i:i + 1200], t=t0 + i / FS)
                dec.feed(np.zeros(1200, np.float32), t=t0 + 15.0)
                _settle(dec)
                if callable(getattr(self, "between", None)):
                    self.between(k)
        finally:
            dec.close()
        return events, statuses


@HAVE_JT9
class Fallback(_DecoderCase):
    def test_without_ohsdigi_jt9_decodes_and_says_so_once(self):
        with self.assertLogs("ohscore.modes.ft8", "INFO") as cm:
            events, statuses = self.run_slots(ohsdigi=None)
            ft8.Decoder(lambda e: None, ohsdigi=None).close()          # a second decoder: not said again
        self.assertEqual([e["text"] for e in events], [self.MSG])
        self.assertEqual(statuses, ["jt9"])
        self.assertEqual(len([line for line in cm.output if "no ohsdigi decoder" in line]), 1)

    def test_when_ohsdigi_raises_jt9_decodes_the_slot(self):
        fake = _fake(raises=True)
        with self.assertLogs("ohscore.modes.ft8", "WARNING") as cm:
            events, statuses = self.run_slots(n=2, ohsdigi=fake)
        self.assertEqual([e["text"] for e in events], [self.MSG, self.MSG])
        self.assertEqual(statuses, ["ohsdigi", "jt9 (ohsdigi failed)"])
        self.assertEqual(fake.ft8_decode.calls, 4)               # tried every pass, early and final
        self.assertEqual(len(cm.output), 1)                      # but said once, with the traceback
        self.assertIn("ohsdigi blew up", cm.output[0])

    def test_a_good_slot_after_a_failure_says_ohsdigi_again(self):
        fake = _fake(raises=True)
        decodes = [{"text": self.MSG, "snr": 10, "dt": 0.0, "freq": 1500.0, "ap": 0, "qual": 1.0}]

        def heal(k):
            fake.ft8_decode = fake.ft4_decode = _fake(decodes).ft8_decode
        self.between = heal
        with self.assertLogs("ohscore.modes.ft8", "WARNING"):
            events, statuses = self.run_slots(n=2, ohsdigi=fake)
        self.assertEqual(statuses, ["ohsdigi", "jt9 (ohsdigi failed)", "ohsdigi"])
        self.assertEqual(len(events), 2)


# The fixture is encoded with jt9 hidden, so only ohsdigi's encoder can make it.
NEEDS_OHSDIGI_ENC = unittest.skipUnless(ft8._OHSDIGI is not None, "ohsdigi not built: nothing else encodes the fixture with jt9 hidden")


@NEEDS_OHSDIGI_ENC
class FallbackWithoutJt9(_DecoderCase):
    def test_ohsdigi_failing_with_nothing_behind_it_is_reported(self):
        with mock.patch.object(ft8, "_JT9", None):
            events, statuses = self.run_slots(ohsdigi=_fake(raises=True))
        self.assertEqual(statuses, ["ohsdigi"])
        self.assertTrue(events)
        self.assertTrue(all("ohsdigi blew up" in e["error"] for e in events))

    def test_nothing_to_decode_with_decodes_nothing(self):
        with mock.patch.object(ft8, "_JT9", None):
            events, statuses = self.run_slots(ohsdigi=None)
        self.assertEqual((events, statuses), ([], [""]))


@HAVE_JT9
class ForceJt9(_DecoderCase):
    WRONG = [{"text": "CQ Z9ZZ AA00", "snr": 0, "dt": 0.0, "freq": 2500.0, "ap": 0, "qual": 1.0}]

    def test_jt9_decodes_when_asked(self):
        fake = _fake(self.WRONG)
        events, statuses = self.run_slots(ohsdigi=fake, decoder="jt9")
        self.assertEqual([e["text"] for e in events], [self.MSG])
        self.assertEqual(statuses, ["jt9"])
        self.assertEqual(fake.ft8_decode.calls, 0)               # and the shadow is off here

    def test_the_setting_applies_from_the_next_slot(self):
        choice = ["auto"]
        self.between = lambda k: choice.__setitem__(0, "jt9")
        events, statuses = self.run_slots(n=2, ohsdigi=_fake(self.WRONG), decoder=lambda: choice[0])
        self.assertEqual(statuses, ["ohsdigi", "jt9"])
        self.assertEqual([e["text"] for e in events], ["CQ Z9ZZ AA00", self.MSG])

    def test_an_unknown_value_is_automatic(self):
        _events, statuses = self.run_slots(ohsdigi=_fake(self.WRONG), decoder="jt10")
        self.assertEqual(statuses, ["ohsdigi"])

    @NEEDS_OHSDIGI_ENC
    def test_asking_for_jt9_where_there_is_none_still_decodes(self):
        with mock.patch.object(ft8, "_JT9", None):
            events, statuses = self.run_slots(ohsdigi=_fake(self.WRONG), decoder="jt9")
        self.assertEqual(statuses, ["ohsdigi"])
        self.assertEqual([e["text"] for e in events], ["CQ Z9ZZ AA00"])


class BrokenJt9(_DecoderCase):
    """An installed jt9 that fails - crashes, or exits with an error - is
    a failure, said in the log, not a slot that heard nothing. Until
    17/10/2026 its exit status and stderr were dropped: the Mac app's jt9
    aborted on every run and the shadow said "jt9 0" each slot, silently.
    jt9 here is a shell script standing in for one; ohsdigi a stand-in
    returning a fixed decode, so no real decoder runs and no jt9 need be
    installed."""

    DECODES = ({"text": "CQ G0ABC IO91", "snr": -5, "dt": 0.1, "freq": 1200.0},)

    def fake_jt9(self, body):
        d = tempfile.mkdtemp(prefix="ohsnb-test-jt9-")
        self.addCleanup(shutil.rmtree, d, True)
        path = Path(d) / "jt9"
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)
        p = mock.patch.object(ft8, "_JT9", str(path))
        p.start()
        self.addCleanup(p.stop)

    def slot(self, decoder="auto", shadow="0"):
        events, statuses = [], []
        with mock.patch.dict(os.environ, {decoder_shadow.ENV: shadow}):
            dec = ft8.Decoder(events.append, variant="ft8", ohsdigi=_fake(self.DECODES), decoder=decoder,
                              on_decoder=statuses.append)
            silence = np.zeros(int(15 * FS), np.float32)
            try:
                for i in range(0, len(silence), 1200):
                    dec.feed(silence[i:i + 1200], t=i / FS)
                dec.feed(np.zeros(1200, np.float32), t=15.0)
                _settle(dec)
            finally:
                dec.close()
        return events, statuses

    CRASH = 'echo "Fortran runtime error: out of bounds" >&2\nexit 2\n'

    def test_a_crashing_jt9_put_first_hands_the_slot_to_ohsdigi_and_says_why(self):
        self.fake_jt9(self.CRASH)
        with self.assertLogs("ohscore.modes.ft8", "WARNING") as cm:
            events, statuses = self.slot(decoder="jt9")
        self.assertEqual([e["text"] for e in events], ["CQ G0ABC IO91"])
        self.assertEqual(statuses, ["jt9", "ohsdigi (jt9 failed)"])
        warned = [m for m in cm.output if "jt9 failed to decode" in m]
        self.assertEqual(len(warned), 1, cm.output)                   # both passes failed, said once
        self.assertIn("exited with status 2: Fortran runtime error: out of bounds", warned[0])

    def test_a_shadow_jt9_that_crashes_is_counted_and_logged_not_read_as_silence(self):
        self.fake_jt9("kill -ABRT $$\n")
        decoder_shadow.reset()
        self.addCleanup(decoder_shadow.reset)
        with self.assertLogs("ohscore.modes.ohsdigi", "WARNING") as cm:
            events, _ = self.slot(shadow="1")
        self.assertEqual([e["text"] for e in events], ["CQ G0ABC IO91"])
        self.assertEqual(decoder_shadow.summary(), {"ft8: jt9 shadow failures": 2})
        self.assertEqual(len(cm.output), 1, cm.output)
        self.assertIn(f"was killed by signal {int(signal.SIGABRT)}: nothing on stderr", cm.output[0])

    def test_stderr_from_a_run_that_worked_is_said_once_and_its_decodes_kept(self):
        self.fake_jt9('echo "192845  -5  0.1 1500 ~  CQ G4XYZ IO91"\n'
                      'echo "Note: IEEE_UNDERFLOW_FLAG is signalling" >&2\n')
        with self.assertLogs("ohscore.modes.ft8", "WARNING") as cm:
            events, statuses = self.slot(decoder="jt9")
        self.assertEqual([e["text"] for e in events], ["CQ G4XYZ IO91"])
        self.assertEqual(statuses, ["jt9"])
        self.assertEqual(cm.output, ["WARNING:ohscore.modes.ft8:jt9 wrote to stderr on a run that succeeded: "
                                     "Note: IEEE_UNDERFLOW_FLAG is signalling"])


class SlotLog(_DecoderCase):
    """One log line per slot that decoded anything (how many, SNR, CQs,
    and every message to the operator), a line when nothing has decoded
    for a while, and each decode at DEBUG: a remote operator's log alone
    then says whether NB heard the band and whether anyone answered.
    ohsdigi is a stand-in returning fixed decodes, so no decoder runs."""

    DECODES = ({"text": "CQ G0ABC IO91", "snr": -5, "dt": 0.1, "freq": 1200.0},
               {"text": "GM4BRI G0ABC -12", "snr": 3, "dt": 0.2, "freq": 1500.0},
               {"text": "CQ DL1XYZ JO62", "snr": -18, "dt": -0.1, "freq": 2100.0})

    def slots(self, n, decodes):
        dec = ft8.Decoder(lambda e: None, variant="ft8", ohsdigi=_fake(decodes), calls=lambda: ("GM4BRI", ""))
        slot = np.zeros(int(15 * FS), np.float32)
        try:
            for k in range(n):
                for i in range(0, len(slot), 1200):
                    dec.feed(slot[i:i + 1200], t=k * 15.0 + i / FS)
                dec.feed(np.zeros(1200, np.float32), t=k * 15.0 + 15.0)
                _settle(dec)
        finally:
            dec.close()

    def test_a_slot_with_decodes_is_one_line(self):
        with self.assertLogs("ohscore.modes.ft8", "DEBUG") as cm:
            self.slots(1, self.DECODES)
        info = [m for m in cm.output if m.startswith("INFO")]
        self.assertEqual(info, ["INFO:ohscore.modes.ft8:FT8 slot 00:00:00: 3 decoded, SNR best +3 median -5 dB, "
                                "2 CQ, to GM4BRI: GM4BRI G0ABC -12"])
        # Each decode once at DEBUG, though both passes found it.
        self.assertEqual(sum("FT8 00:00:00 -18 -0.1 2100 CQ DL1XYZ JO62" in m for m in cm.output), 1)

    def test_nothing_decoded_is_said_after_four_slots_and_not_again_within_a_minute(self):
        with self.assertLogs("ohscore.modes.ft8", "DEBUG") as cm:
            self.slots(6, ())
        info = [m for m in cm.output if m.startswith("INFO")]
        self.assertEqual(len(info), 1, info)
        self.assertRegex(info[0], r"FT8: nothing decoded in the last 4 slots, the decoder running "
                                  r"\(slot audio -\d+\.\d dBFS rms, peak -\d+\.\d dBFS\)")
        self.assertEqual(sum("nothing decoded (slot audio" in m for m in cm.output), 5)


if __name__ == "__main__":
    unittest.main()
