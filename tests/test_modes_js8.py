import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""JS8 Normal: ohsdigi first, js8 as the fallback (ohscore/modes/js8.py).

- Ohsdigi*Tests: a period made with ohsdigi's own JS8 encoder decodes through
  Decoder.feed to the text JS8Call would show, without temporary folders;
  a raising ohsdigi hands the period to js8, or reports it when there is no
  js8. (That ohsdigi's decodes and encodes are JS8Call's own is
  rust/ohsdigi/tests/js8_golden.rs's to prove.)

For the js8 program path, in test_modes_q65.py's style:

- Jt9OutputTests: js8's own stdout line shape, measured directly against
  js8call 2.2.0+ds-5+b1's own regression WAVs (`media/tests/*.wav`, its own
  `test` script) rather than assumed - see those crafted lines below and
  the module docstring for the two Fortran `format` strings they come from.
- the temp-folder/stale-sweep tests, adapted to feed silence rather than a
  real signal (no encoder to make one): js8 still runs, still reports zero
  decodes, still leaves jt9_wisdom.dat behind, exactly the behaviour those
  tests check.
- Js8CallsTests: -c/-x reach js8 exactly as they reach jt9 for FT8/Q65
  (ft8.py's _jt9_call/_calls_now, reused as-is).
"""
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from ohscore.modes import ft8, js8

FS = js8.FS


def _silence(seconds: float) -> np.ndarray:
    return np.zeros(int(round(seconds * FS)), dtype=np.float32)


def _feed_one_period(dec, audio, t0=0.0):
    slot_n = int(round(js8.PERIOD_S * FS))
    padded = np.zeros(slot_n, dtype=np.float32)
    padded[:min(len(audio), slot_n)] = audio[:slot_n]
    block = 1200
    t = t0
    for i in range(0, len(padded), block):
        dec.feed(padded[i:i + block], t=t)
        t += block / FS
    dec.feed(np.zeros(block, dtype=np.float32), t=t)
    return t


class Jt9OutputTests(unittest.TestCase):
    """js8 -8's own stdout lines (module docstring): a non-clock leading
    field (always six digits here, unlike Q65's jt9 -3 - js8's nutc is
    always an integer variable, never the "****" Q65 sometimes prints), SNR,
    DT, df, the submode letter, then the message token - usually a packed
    frame, sometimes a plain standard message, and only sometimes an "aN"
    a-priori flag (no Q65-style averaging digit, no FT8-style "?" - see the
    module docstring for where a low-confidence decode's mark actually
    lands instead)."""

    def parse(self, line):
        return js8._parse_jt9_output(line, 0.0)[0]

    def test_a_packed_frame_is_kept_as_its_raw_token(self):
        # Exactly what A_2_6.wav (js8call's own test WAV) decodes to at
        # depth 3 - not invented. No call/grid: _parse_standard correctly
        # does not mistake a packed token for a standard message.
        ev = self.parse("000000  11  0.1  500 A  SIUT18l+CDqE         3   ")
        self.assertEqual(ev["text"], "SIUT18l+CDqE         3")
        self.assertEqual(ev["mode"], "js8")
        self.assertEqual(ev["snr"], 11)
        self.assertEqual(ev["dt"], 0.1)
        self.assertEqual(ev["df"], 500)
        self.assertNotIn("ap", ev)
        self.assertNotIn("call", ev)

    def test_a_standard_cq_message_parses_as_text_and_call_grid(self):
        # js8's own Fortran decoder (lib/decoder.f90) leaves a "CQ ..."
        # message as plain text, unlike a directed/compound/heartbeat
        # frame (module docstring) - _parse_standard (ft8.py, reused)
        # recognises it exactly as it does FT8's own CQ shape.
        ev = self.parse("000000 -14  0.1  500 A  CQ G4XYZ IO91              a2 ")
        self.assertEqual(ev["text"], "CQ G4XYZ IO91")
        self.assertEqual(ev["call"], "G4XYZ")
        self.assertEqual(ev["grid"], "IO91")
        self.assertEqual(ev["ap"], "a2")

    def test_negative_frequency_offset_df_is_still_an_integer_field(self):
        # df is unsigned in js8's own format (i5, module docstring) - this
        # just guards the regex accepts the field width js8 actually prints.
        ev = self.parse("000000   0  0.2 1997 A  SJff78l+CDqP         3   ")
        self.assertEqual(ev["df"], 1997)

    @unittest.skipUnless(js8._OHSDIGI_JS8 is not None, "ohsdigi without JS8")
    def test_with_ohsdigi_a_js8_frame_reads_as_js8call_shows_it(self):
        # The A_2_6.wav line above, read by JS8Call's own message layer
        # (checked against it in rust/ohsdigi/tests/js8_golden.rs).
        ev = js8._parse_jt9_output("000000  11  0.1  500 A  SIUT18l+CDqE         3   ", 0.0,
                                   js8._OHSDIGI_JS8)[0]
        self.assertEqual(ev["text"], "KB1CTC: AC9BA HEARTBEAT SNR -17")
        self.assertEqual((ev["frame"], ev["i3bit"], ev["kind"]), ("SIUT18l+CDqE", 3, "directed"))
        self.assertEqual((ev["call"], ev["to"]), ("KB1CTC", "AC9BA"))
        self.assertTrue(ev["first"] and ev["last"])
        self.assertEqual((ev["snr"], ev["df"]), (11, 500))

    def test_unparseable_lines_are_silently_skipped(self):
        # <DecodeStarted>/<DecodeDebug>/<DecodeFinished> and the " EOF on
        # input file ..." line js8 also prints (module docstring) - none of
        # this module's business.
        self.assertEqual(js8._parse_jt9_output(
            "<DecodeStarted>   0   0\n <DecodeDebug> mode A decode started\n"
            " EOF on input file x.wav\n<DecodeFinished>   0\n", 0.0), [])


class Js8CallsTests(unittest.TestCase):
    """jt9-family a-priori passes need the operator's call, reused from
    ft8.py exactly as q65.py reuses it (same _jt9_call/_calls_now)."""

    def test_mycall_and_dxcall_reach_js8(self):
        calls = lambda: ("g4xyz", "w9xyz")  # noqa: E731
        # js8 runs through ft8.run_decoder_tool, as jt9 does.
        with mock.patch.object(ft8.subprocess, "run") as run:
            run.return_value.stdout = run.return_value.stderr = ""
            run.return_value.returncode = 0
            dec = js8.Decoder(lambda e: None, calls=calls, ohsdigi=None)
            dec._decode_slot(0.0, np.zeros(int(js8.PERIOD_S * FS), np.float32))
            dec.close()
        args = run.call_args[0][0]
        self.assertIn("'G4XYZ'", args)
        self.assertIn("'W9XYZ'", args)
        self.assertEqual(args[args.index("-c") + 1], "'G4XYZ'")
        self.assertEqual(args[args.index("-x") + 1], "'W9XYZ'")
        self.assertIn("-8", args)
        self.assertEqual(args[args.index("-b") + 1], "A")


class Js8EncoderTests(unittest.TestCase):
    def test_without_ohsdigi_render_refuses_with_its_sentence(self):
        # Sending switched on 17/10/2026 (tests/test_js8_send.py); js8,
        # JS8Call's program, cannot send, so without ohsdigi it refuses.
        with self.assertRaises(ValueError) as ctx:
            js8.Encoder(ohsdigi=None).render(text="CQ GM4BRI IO86", callsign="GM4BRI")
        self.assertEqual(str(ctx.exception), js8.WHY_NO_ENCODER)


class Js8ModeRegistryTests(unittest.TestCase):
    def test_listed_whether_or_not_js8call_is_installed(self):
        from ohscore.modes import MODES
        self.assertIn("js8", MODES)
        info = MODES["js8"]
        self.assertEqual(info.available, js8.CAN_DECODE)
        if not js8.CAN_DECODE:
            self.assertEqual(info.why, js8.WHY_UNAVAILABLE)
        # The encoder is wired in whether or not ohsdigi is, so a send
        # without it reaches js8.WHY_NO_ENCODER rather than a blank refusal.
        self.assertIsNotNone(info.make_encoder)


class TempFolderCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = mock.patch.object(tempfile, "tempdir", str(self.tmp))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def ours(self):
        return sorted(d.name for d in self.tmp.iterdir() if d.name.startswith(js8.TMP_PREFIX))

    def settled(self, dec, timeout=10.0):
        end = time.monotonic() + timeout
        while dec._busy and time.monotonic() < end:
            time.sleep(0.01)
        with dec._dir_lock:
            return dec._busy == 0


@unittest.skipUnless(js8._JS8, "js8call (js8) not installed")
class TempFolderTests(TempFolderCase):
    """As q65.py's/ft8.py's: one working directory for the decoder's life,
    emptied but for jt9's FFT wisdom between decodes, removed by close().
    Fed silence (no encoder to make a real signal, module docstring): js8
    still runs to completion and still writes jt9_wisdom.dat - the
    behaviour these tests check does not need an actual decode."""

    def decode_once(self, dec):
        _feed_one_period(dec, _silence(js8.PERIOD_S))
        self.assertTrue(self.settled(dec, timeout=20.0))

    def test_a_decoder_that_never_decodes_leaves_nothing(self):
        dec = js8.Decoder(lambda e: None, ohsdigi=None)
        dec.reset()
        dec.reset()
        self.assertEqual(self.ours(), [])

    def test_each_decode_leaves_only_the_fft_wisdom_and_close_removes_the_rest(self):
        dec = js8.Decoder(lambda e: None, ohsdigi=None)
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
        p = mock.patch.object(js8, "_swept", False)
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
        old = self.folder(f"{js8.TMP_PREFIX}abc123", 2 * 86400)
        recent = self.folder(f"{js8.TMP_PREFIX}recent", 3600)
        other = self.folder("ohsnb-q65-xyz", 2 * 86400)
        js8._sweep_stale()
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(other.exists())


@unittest.skipUnless(js8._JS8, "js8call (js8) not installed")
class Js8DecoderWiringTests(unittest.TestCase):
    """Feeding silence (module docstring: no encoder exists to make a real
    JS8 signal) still exercises the real js8 binary end to end - it is the
    plumbing (feed() never blocking, the subprocess call, the worker
    thread) being checked here, not a decode."""

    def test_feed_never_blocks_the_caller(self):
        dec = js8.Decoder(lambda e: None, ohsdigi=None)
        t0 = time.monotonic()
        _feed_one_period(dec, _silence(js8.PERIOD_S))
        self.assertLess(time.monotonic() - t0, 1.0)
        dec.close()

    def test_a_quiet_period_reports_no_decodes(self):
        events = []
        dec = js8.Decoder(events.append, ohsdigi=None)
        _feed_one_period(dec, _silence(js8.PERIOD_S))
        deadline = time.monotonic() + 20
        while dec._busy and time.monotonic() < deadline:
            time.sleep(0.05)
        dec.close()
        self.assertEqual(events, [])


def _js8_period(text="HB IO75", seed=3):
    """One Normal period: `text`'s first frame sent on time at 1300 Hz in
    noise, float32 full scale, as the receiver hands audio to feed()."""
    lb = js8._OHSDIGI_JS8
    frame, i3bit = lb.js8_frames(text, "GM4BRI", "IO75")[0]
    sig = np.frombuffer(lb.js8_encode_audio(frame, i3bit, "normal", 1300.0), np.float32)
    x = np.random.default_rng(seed).normal(0.0, 0.02, int(js8.PERIOD_S * FS)).astype(np.float32)
    x[6000:6000 + len(sig)] += 0.1 * sig
    return x


def _settle(dec, timeout=20.0):
    end = time.monotonic() + timeout
    while dec._busy and time.monotonic() < end:
        time.sleep(0.01)


@unittest.skipUnless(js8._OHSDIGI_JS8 is not None, "ohsdigi without JS8 (tools/build-ohsdigi.sh --host --install)")
class OhsdigiDecodeTests(TempFolderCase):
    def test_a_period_decodes_to_what_js8call_shows(self):
        events = []
        dec = js8.Decoder(events.append)
        _feed_one_period(dec, _js8_period(), t0=1_800_000_000.0)
        _settle(dec)
        dec.close()
        self.assertEqual(len(events), 1, events)
        ev = events[0]
        self.assertEqual(ev["mode"], "js8")
        self.assertEqual(ev["slot"], 1_800_000_000.0)
        self.assertEqual(ev["text"], "GM4BRI: @HB HEARTBEAT IO75")
        self.assertEqual((ev["kind"], ev["call"], ev["grid"]), ("heartbeat", "GM4BRI", "IO75"))
        self.assertEqual(ev["df"], 1300)
        self.assertEqual(ev["dt"], 0.0)
        # ohsdigi needs no WAV file and no folder to put one in.
        self.assertEqual(self.ours(), [])

    def test_a_group_is_not_reported_as_the_sender(self):
        events = []
        dec = js8.Decoder(events.append)
        _feed_one_period(dec, _js8_period("@ALLCALL CQ CQ CQ IO75"))
        _settle(dec)
        dec.close()
        self.assertEqual([e["text"] for e in events], ["GM4BRI: @ALLCALL CQ CQ CQ IO75"])
        self.assertEqual(events[0]["call"], "GM4BRI")
        events.clear()
        # A directed frame to a group: the sender is the station, the
        # group is `to`, never `call`.
        dec = js8.Decoder(events.append)
        _feed_one_period(dec, _js8_period("@ALLCALL SNR?"))
        _settle(dec)
        dec.close()
        self.assertEqual((events[0]["call"], events[0]["to"]), ("GM4BRI", "@ALLCALL"))


@unittest.skipUnless(js8._OHSDIGI_JS8 is not None, "ohsdigi without JS8")
class OhsdigiFallbackTests(unittest.TestCase):
    class Broken:
        def js8_decode(self, *a, **k):
            raise RuntimeError("ohsdigi bug")

        def js8_unpack(self, *a, **k):
            raise RuntimeError("ohsdigi bug")

    def test_a_raising_ohsdigi_hands_the_period_to_js8(self):
        with mock.patch.object(js8, "_JS8", "/usr/bin/js8"), mock.patch.object(ft8.subprocess, "run") as run:
            run.return_value.stdout = run.return_value.stderr = ""
            run.return_value.returncode = 0
            dec = js8.Decoder(lambda e: None, ohsdigi=self.Broken())
            dec._decode_slot(0.0, np.zeros(int(js8.PERIOD_S * FS), np.float32))
            dec.close()
        self.assertEqual(run.call_args[0][0][0], "/usr/bin/js8")

    def test_without_js8_the_failure_is_reported(self):
        events = []
        with mock.patch.object(js8, "_JS8", None):
            dec = js8.Decoder(events.append, ohsdigi=self.Broken())
            dec._decode_slot(0.0, np.zeros(int(js8.PERIOD_S * FS), np.float32))
            dec.close()
        self.assertEqual(events, [{"mode": "js8", "slot": 0.0, "error": "ohsdigi bug"}])


if __name__ == "__main__":
    unittest.main()
