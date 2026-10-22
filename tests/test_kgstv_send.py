import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""Sending a KG-STV picture through NB's transmit path (Engine.send with
an OVER_MODES mode), on the simulated transponder with the Pluto's path:
the over keys from whatever mode the rail is in, is judged as KG-STV (its
own band-plan class and measured width), goes out whole, comes back round
the transponder into NB's own background KG-STV receiver - so the picture
it decodes is our own, sent through every stage a real one goes through -
and unkeys at the end. Halt stops it part way; the time-out refuses one
that would be cut off; the narrow digimode segment refuses it.

The IC-9700's side (CAT PTT) is in test_extrig_catptt.py's harness: see
CatKgStv at the bottom of this file."""
import shutil
import tempfile
import time
import unittest

import numpy as np

from helpers import make_radio, run_sim, wait_rx_lock
from ohscore.engine import TxRefused
from ohscore.modes import kgstv
from ohsnb import kgstvrx

from test_extrig_catptt import OFF, ON, Cat, wait_for
from test_kgstv import card

LINE = "GM4BRI IO75RL"


def picture():
    """The test card, sent at the fastest quality to keep the over short."""
    return card()


class Recorder:
    """The engine's SSB modulator, recording the 12 kHz audio it is given:
    what the over actually sent, block by block."""

    def __init__(self, mod):
        self.mod = mod
        self.blocks: list[np.ndarray] = []

    def __call__(self, a):
        self.blocks.append(np.array(a, np.float32))
        return self.mod(a)

    def __getattr__(self, k):
        return getattr(self.mod, k)

    def audio(self):
        return np.concatenate(self.blocks) if self.blocks else np.zeros(0, np.float32)


class OnThePluto(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def radio(self, **over):
        cfg = dict(simSeed=11, simRxErrorHz=1800.0, simUlErrorHz=0.0, txGain=-30.0, simRefGainDb=-20.0,
                   mode="usb", vfo=kgstvrx.DIAL, callsign="GM4BRI", locator="IO75RL", licenceClass="full",
                   mmbDecode=False, midTextDecode=False)
        cfg.update(over)
        r = make_radio(self.tmp, **cfg)
        r.start()
        self.addCleanup(r.stop)
        # The simulator's own KG-STV station sends on the same frequency
        # every ~90 s; off the band, so what comes back is ours alone.
        r.dev.stations = [s for s in r.dev.stations if s.name != "KG-STV"]
        self.rec = Recorder(r.mod)
        chain = r._tx_chain
        r._tx_chain = lambda req: (self.rec, chain(req)[1])
        self.assertTrue(wait_rx_lock(r))
        return r

    def test_a_picture_goes_out_whole_and_comes_back_round_the_transponder(self):
        r = self.radio()
        feed = r.subscribe("kgstv", 4096)
        tx = kgstv.Transmission(picture(), LINE, 15)
        keyed_at = []

        r.send("kgstv", picture=picture(), scale=15)
        st = r.state()
        # Keyed as a send() over, from USB: the over is KG-STV's.
        self.assertTrue(st["keyed"])
        self.assertEqual(st["mode"], "usb")
        seen = []

        def until():
            seen.extend(feed.drain())
            s = r.state()
            if s["keyed"] and s["txOnAir"] and not keyed_at:
                keyed_at.append(r.rx_samples / r.geo.fs)
            return not s["keyed"] and any(e["kind"] == "done" for e in seen)
        run_sim(r, tx.seconds + 40.0, until=until, timeout=600)
        seen.extend(feed.drain())
        self.assertFalse(r.state()["keyed"])
        # Everything the encoder made went to the modulator, and nothing
        # else: the over's audio, its length to the block.
        sent = self.rec.audio()
        want = tx.audio()
        self.assertGreaterEqual(len(sent), len(want))
        self.assertLess(len(sent) - len(want), 2400)                     # the last block's padding
        self.assertTrue(np.allclose(sent[:len(want)], want, atol=1e-5))
        # Its spectrum: centred on KG-STV's 1500 Hz between its tones,
        # nearly all of it within them, nothing much outside 0.7-2.3 kHz.
        P = np.abs(np.fft.rfft(sent)) ** 2
        f = np.fft.rfftfreq(len(sent), 1 / 12000.0)
        self.assertAlmostEqual(float((P * f).sum() / P.sum()), 1500.0, delta=30.0)
        self.assertGreater(P[(f > 900) & (f < 2100)].sum() / P.sum(), 0.9)
        self.assertGreater(P[(f > 700) & (f < 2300)].sum() / P.sum(), 0.99)
        # And round the transponder into NB's own receiver: the picture as
        # sent, every block, under our callsign line.
        done = [e for e in seen if e["kind"] == "done"]
        self.assertEqual(len(done), 1, [e["kind"] for e in seen][-5:])
        self.assertEqual((done[0]["call"], done[0]["why"], done[0]["blocks"]), (LINE, "end", 300))
        preview = tx.preview()
        for e in [e for e in seen if e["kind"] == "block"][::20]:
            got = np.frombuffer(e["rgb"], np.uint8).reshape(16, 16, 3)
            self.assertTrue(np.array_equal(got, preview[e["y"] * 16:(e["y"] + 1) * 16,
                                                       e["x"] * 16:(e["x"] + 1) * 16]), (e["x"], e["y"]))

    def test_halt_mid_picture_unkeys_at_once(self):
        r = self.radio()
        tx = kgstv.Transmission(picture(), LINE, 15)
        stops = []
        stop = r.dev.tx_stop
        r.dev.tx_stop = lambda: (stops.append(r.rx_samples / r.geo.fs), stop())
        r.send("kgstv", picture=picture(), scale=15)
        run_sim(r, 10.0)
        self.assertTrue(r.state()["keyed"])
        t = r.rx_samples / r.geo.fs
        r.halt()
        self.assertFalse(r.state()["keyed"])
        run_sim(r, 1.0, until=lambda: bool(stops))
        self.assertTrue(stops)
        self.assertLess(stops[0] - t, 0.5)
        # Part of the picture went, not all of it.
        sent = len(self.rec.audio()) / 12000.0
        self.assertLess(sent, tx.seconds / 2)
        self.assertGreater(tx.blocks_sent(sent), 0)

    def test_a_mode_change_ends_it(self):
        r = self.radio()
        r.send("kgstv", picture=picture(), scale=15)
        run_sim(r, 3.0)
        self.assertTrue(r.state()["keyed"])
        r.set(mode="lsb")
        self.assertFalse(r.state()["keyed"])

    def test_retuning_mid_picture_is_judged_as_kgstv(self):
        # The re-check a dial move makes judges the over as KG-STV, not as
        # the rail's USB: moving 5 kHz up stays in the digimode segment
        # and the picture goes on; into the SSB segment it is unkeyed.
        r = self.radio()
        r.send("kgstv", picture=picture(), scale=15)
        run_sim(r, 2.0)
        r.set(vfo=kgstvrx.DIAL + 5_000.0)
        run_sim(r, 1.0)
        self.assertTrue(r.state()["keyed"])
        r.set(vfo=10_489_700_000.0)
        self.assertFalse(r.state()["keyed"])

    def test_the_narrow_digimode_segment_refuses_it(self):
        r = self.radio(vfo=10_489_560_000.0)
        with self.assertRaises(TxRefused) as cm:
            r.send("kgstv", picture=picture(), scale=15)
        self.assertIn("500", str(cm.exception))
        self.assertFalse(r.state()["keyed"])
        self.assertEqual(self.rec.blocks, [])

    def test_a_picture_longer_than_the_time_out_is_refused_before_key_up(self):
        r = self.radio(txTimeoutSec=60.0)
        secs = kgstv.Transmission(picture(), LINE, 15).seconds
        self.assertGreater(secs, 60.0)
        with self.assertRaises(TxRefused) as cm:
            r.send("kgstv", picture=picture(), scale=15)
        self.assertIn(f"{secs:.0f} s", str(cm.exception))
        self.assertIn("time-out", str(cm.exception))
        self.assertFalse(r.state()["keyed"])
        self.assertEqual(self.rec.blocks, [])
        # The operator's limit decides, not a longer one for KG-STV: with it
        # raised past the over, the same picture goes.
        r.set(authorise=True, txTimeoutSec=float(np.ceil(secs)) + 10.0)
        r.send("kgstv", picture=picture(), scale=15)
        self.assertTrue(r.state()["keyed"])
        r.halt()

    def test_no_callsign_no_picture(self):
        r = self.radio(callsign="")
        with self.assertRaises(TxRefused) as cm:
            r.send("kgstv", picture=picture())
        self.assertIn("callsign", str(cm.exception))
        self.assertFalse(r.state()["keyed"])

    def test_the_callsign_line_is_the_stations_own(self):
        # A caller cannot put another call on the picture.
        r = self.radio()
        audio = r._render("kgstv", {"picture": picture(), "callsign": "G0XXX", "locator": "AA00", "scale": 15})
        calls = []
        dec = kgstv.Decoder(lambda e: calls.append(e["call"]) if e["state"] == "call" else None)
        dec.feed(audio)
        self.assertEqual(calls, [LINE])

    def test_other_modes_still_need_the_rail_in_them(self):
        r = self.radio()
        with self.assertRaises(ValueError) as cm:
            r.send("psk31", text="TEST")
        self.assertIn("Switch to psk31", str(cm.exception))


class CatKgStv(Cat):
    """KG-STV through the IC-9700 by CAT PTT, exactly as the other digital
    sends: keyed only with rigCatPtt on, audio to its sound device. The
    picture is sent from USB on the rail - the 9700 still goes to USB-D
    for it - and from the KG-STV frequency, which the emulator's 23 cm
    upconverter plan reaches."""

    cfg_over = {"vfo": kgstvrx.DIAL, "locator": "IO75RL"}

    def test_a_picture_keys_sends_whole_and_unkeys(self):
        self.audio.realtime = False      # the sound device takes the over as fast as it comes
        self.assertTrue(self.settled())
        self.assertTrue(wait_for(lambda: self.r.ext.link.mod_input is not None))
        tx = kgstv.Transmission(picture(), LINE, 15)
        self.r.send("kgstv", picture=picture(), scale=15)
        self.assertTrue(wait_for(lambda: not self.st()["keyed"] and not self.rig_tx(), timeout=60))
        self.assertEqual(self.ptt(), [ON, OFF])
        out = self.sink()
        self.assertEqual(out.device, "IC-9700 USB Audio CODEC")
        got = out.samples()
        want = tx.audio() * np.float32(10 ** (self.st()["rigTxAudioDb"] / 20))
        self.assertGreaterEqual(len(got), len(want))
        self.assertTrue(np.allclose(got[:len(want)], want, atol=1e-5))
        # The radio in USB-D for it, though NB's rail is in USB.
        self.assertTrue(self.civ.data)
        self.assertEqual(self.st()["mode"], "usb")

    def test_halt_mid_picture(self):
        self.assertTrue(self.settled())
        self.assertTrue(wait_for(lambda: self.r.ext.link.mod_input is not None))
        self.r.send("kgstv", picture=picture(), scale=15)
        self.assertTrue(self.on_air())
        time.sleep(1.0)
        t = time.monotonic()
        self.r.halt()
        self.assertTrue(wait_for(lambda: not self.rig_tx(), timeout=2))
        self.assertLess(self.civ.tx_log[-1][0] - t, 0.5)
        self.assertEqual(self.ptt(), [ON, OFF])
        self.assertLess(len(self.sink().samples()), 4 * 12000)


class CatKgStvOff(Cat):
    cfg_over = {"vfo": kgstvrx.DIAL, "rigCatPtt": False}

    def test_with_cat_ptt_off_the_picture_is_refused_and_nothing_keys(self):
        self.assertTrue(wait_for(lambda: self.st()["rigLink"] == "ok"))
        with self.assertRaises(TxRefused) as cm:
            self.r.send("kgstv", picture=picture(), scale=15)
        self.assertIn("key it on the radio", str(cm.exception))
        self.assertEqual(self.ptt(), [])
        self.assertEqual(self.audio.tx_outs, [])
        self.assertFalse(self.st()["keyed"])


if __name__ == "__main__":
    unittest.main()
