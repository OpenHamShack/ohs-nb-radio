"""DMR in Radio (docs/SERVER-API.md "DMR"): the band simulator's repeater on
439.6125 MHz (ohsradio/devices/simdmr.py, shack_sdr's DMR test transmitter
playing its showcase) decoded by a `dmr` session cut from the engine's own
bank, faster than real time - both slots' calls with their IDs, talker
aliases, the encrypted call and the SMS, the slots' summary in the
session's meta, `needs_codec:mbelib` worded while a call goes unheard -
and `listen`: the session's sound in place of the demodulator's on the
speaker, one session at a time, refused for a decoder that makes none.

mbelib is never part of this repository: the one test that wants real
voice reads SHACK_TEST_MBELIB (a developer's own build) and skips without
it, and the others skip if this machine happens to have one installed."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import os
import tempfile
import unittest

import numpy as np

from ham_helpers import close, pump
from listen_helpers import TapAudio

from ohscore import sdr
from ohscore.decoders import Refused, mbelib_sentence
from ohsradio.devices import simdmr
from ohsradio.radio import Radio

DMR_HZ = simdmr.FREQ


def has_dmr() -> bool:
    m = sdr.load()
    return m is not None and any(e["id"] == "dmr" for e in m.catalogue())


def make(**over):
    tmp = tempfile.TemporaryDirectory()
    cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
           "callsign": "GM4BRI", "licenceClass": "full", "vfo": DMR_HZ, "mode": "fm"}
    cfg.update(over)
    audio = TapAudio()
    r = Radio(cfg, persist=False, data_dir=tmp.name, audio=audio)
    r._tmp = tmp
    return r, audio


def frames(items, sid, kind):
    return [i["fields"] for i in items if i.get("session") == sid and i.get("type") == "frame"
            and i.get("frame") == kind]


@unittest.skipUnless(has_dmr(), "no shack_sdr with DMR for this machine")
class TheSimulatedRepeater(unittest.TestCase):
    def setUp(self):
        self.r, self.audio = make()
        self.feed = self.r.subscribe("decoders", 20_000)
        self.r.start()
        self.addCleanup(close, self.r)
        if any(c["id"] == "mbelib" and c["state"] == "found" for c in self.r.decoders.codecs()):
            self.skipTest("this machine has mbelib installed; these tests are about its absence")

    def test_both_slots_calls_aliases_encryption_and_a_message(self):
        sess = self.r.decoders.start("dmr", DMR_HZ)
        sid = sess["id"]
        self.assertEqual((sess["decoder"], sess["panel"], sess["listening"]), ("dmr", "slots", False))
        got = pump(self.r, 90, feeds=[self.feed],
                   until=lambda: len([r for r in self.r.decoders.session(sid)["results"]
                                      if r.get("frame") in ("call_end", "sms")]) >= 4)["decoders"]
        ends = {(f["slot"], f["src"]): f for f in frames(got, sid, "call_end")}
        self.assertTrue({(1, 9_990_001), (2, 9_990_002), (2, 9_990_003)} <= set(ends), ends)
        tg, secret = ends[1, 9_990_001], ends[2, 9_990_003]
        self.assertEqual((tg["dst"], tg["callType"], tg["alias"], tg["cc"]), (99, "group", "MX0TST Test", 1))
        self.assertEqual(ends[2, 9_990_002]["callType"], "private")
        self.assertTrue(secret["encrypted"])
        (sms, *_) = frames(got, sid, "sms")
        self.assertEqual((sms["slot"], sms["text"]), (1, "Hello from the DMR simulator"))
        # The slots' summary, each keeping its last call when idle.
        view = self.r.decoders.session(sid)
        meta = view["meta"]
        self.assertEqual((meta["mode"], meta["cc"]), ("bs", 1))
        self.assertEqual([s["slot"] for s in meta["slots"]], [1, 2])
        self.assertTrue(all(s["src"] is not None and s["lastHeard"] for s in meta["slots"]), meta)
        # A call went unheard for want of mbelib, and the session said so in words.
        whys = [i for i in got if i.get("session") == sid and i.get("type") == "state"]
        self.assertTrue(any(i.get("why") == "needs_codec:mbelib" for i in whys), whys)

    def test_the_unheard_call_is_worded(self):
        self.assertIn("mbelib", mbelib_sentence())
        sess = self.r.decoders.start("dmr", DMR_HZ)
        pump(self.r, 90, until=lambda: self.r.decoders.session(sess["id"])["why"] == "needs_codec:mbelib")
        view = self.r.decoders.session(sess["id"])
        self.assertEqual((view["why"], view["whyText"]), ("needs_codec:mbelib", mbelib_sentence()))

    def test_listening_puts_the_session_on_the_speaker_in_place_of_the_radio(self):
        sess = self.r.decoders.start("dmr", DMR_HZ)
        sid = sess["id"]
        # The dial is on the repeater in FM: its 4FSK is a loud buzz.
        pump(self.r, 30, until=lambda: sum(len(c) for c in self.audio.chunks) > 4 * Radio.OUT_RATE)
        heard = self.audio.take()
        self.assertGreater(float(np.sqrt(np.mean(heard[-Radio.OUT_RATE:] ** 2))), 1e-3)
        view = self.r.decoders.listen(sid, True)
        self.assertTrue(view["listening"])
        self.assertEqual(self.r.decoders.status()["listening"], sid)
        # The session has no voice to give (no mbelib): after DRY_S the
        # speaker gets its silence, not the demodulator's buzz.
        self.audio.take()
        pump(self.r, 30, until=lambda: sum(len(c) for c in self.audio.chunks) > 3 * Radio.OUT_RATE)
        after = self.audio.take()[Radio.OUT_RATE:]
        self.assertGreater(len(after), Radio.OUT_RATE)
        self.assertEqual(float(np.max(np.abs(after))), 0.0)
        # Off again: the radio is heard.
        self.assertFalse(self.r.decoders.listen(sid, False)["listening"])
        pump(self.r, 30, until=lambda: sum(len(c) for c in self.audio.chunks) > 2 * Radio.OUT_RATE)
        self.assertGreater(float(np.sqrt(np.mean(self.audio.take() ** 2))), 1e-3)

    def test_listen_is_one_session_at_a_time_and_only_for_sound(self):
        dmr = self.r.decoders.start("dmr", DMR_HZ)
        rtty = self.r.decoders.start("rtty", DMR_HZ + 100_000)
        with self.assertRaises(Refused) as e:
            self.r.decoders.listen(rtty["id"], True)
        self.assertEqual(e.exception.code, "no_audio")
        with self.assertRaises(Refused) as e:
            self.r.decoders.listen("ds_none", True)
        self.assertEqual(e.exception.code, "unknown_session")
        self.r.decoders.listen(dmr["id"], True)
        # Stopping it gives the radio back.
        self.r.decoders.stop(dmr["id"])
        self.assertIsNone(self.r.decoders.status()["listening"])
        self.assertIsNone(self.r.decoders.listened())


@unittest.skipUnless(has_dmr() and os.environ.get("SHACK_TEST_MBELIB"),
                     "set SHACK_TEST_MBELIB to a developer's own libmbe.so.1 (never in the repository) to run this")
class WithMbelib(unittest.TestCase):
    def test_a_listened_session_plays_the_calls_voice(self):
        os.environ["SHACK_CODEC_MBELIB"] = os.environ["SHACK_TEST_MBELIB"]
        self.addCleanup(os.environ.pop, "SHACK_CODEC_MBELIB", None)
        r, audio = make(mode="usb", vfo=DMR_HZ + 200_000)   # the dial off the repeater, in silence
        r.start()
        self.addCleanup(close, r)
        self.assertTrue(any(c["id"] == "mbelib" and c["state"] == "found" for c in r.decoders.codecs(rescan=True)))
        sess = r.decoders.start("dmr", DMR_HZ)
        r.decoders.listen(sess["id"], True)
        pump(r, 60, until=lambda: sum(len(c) for c in audio.chunks) > 8 * Radio.OUT_RATE)
        a = audio.take()
        self.assertGreater(float(np.sqrt(np.mean(a ** 2))), 1e-4)
        self.assertNotEqual(r.decoders.session(sess["id"])["why"], "needs_codec:mbelib")
