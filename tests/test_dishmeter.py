"""Dish alignment (ohsnb/dishmeter.py, Radio.dish_open): against a running
Radio on the simulator and on a recording of it - it measures the middle
beacon and the transponder from the receive stream and follows a change,
holds the receive gain while open and gives it back, refuses transmit,
sounds a tone that rises with the beacon, and serves its phone page to
the local network only, and only while asked."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import ipaddress
import json
import socket
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from helpers import make_radio, run_sim, sim_cfg, wait_rx_lock
from ohscore.audio import NullAudio
from ohscore.engine import TxRefused
from ohsnb import dishmeter
from ohsnb.radio import Radio


class Heard(NullAudio):
    """What the speaker would have played."""

    def __init__(self):
        super().__init__(realtime=False)
        self.blocks = []

    def play(self, audio):
        super().play(audio)
        self.blocks.append(np.array(audio, np.float32))


def fade(radio, db):
    for s in radio.dev.stations:
        if "beacon" in s.name:
            s.amp *= 10 ** (db / 20)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def radio(self, audio=None, **over):
        if audio is not None:
            r = Radio(sim_cfg(**over), persist=False, data_dir=self.tmp.name, audio=audio)
        else:
            r = make_radio(self.tmp.name, **over)
        self.addCleanup(r.stop)
        self.addCleanup(r.dish_close)
        r.start()
        if r.state()["beaconMode"] == "auto":
            self.assertTrue(wait_rx_lock(r))
        else:
            run_sim(r, 0.5)
        return r

    def settle(self, r, seconds=1.5):
        run_sim(r, seconds)
        return r.state()


class Measures(Case):
    def test_the_beacon_and_the_transponder_from_the_receive_stream(self):
        r = self.radio()
        r.dish_open()
        s = self.settle(r)
        self.assertTrue(s["dishOpen"])
        # The meter takes its noise from beside the beacon, not within beacon
        # lock's filtered 4 kHz channel, and reads lower than beacon lock's
        # badge (dishmeter.py): 2-3 dB when the simulator's beacon was random
        # bits, ~5 dB since it sends text (08/10, ohsnb/devices/midbeacon.py)
        # - mostly spaces and fill, as DK0SB's is, whose steadier envelope
        # gives beacon lock's squared line ~3 dB more. The meter's own
        # reading did not move (26.5 dB either way).
        self.assertGreater(s["dishSnr"], 20.0)
        self.assertLess(abs(s["dishSnr"] - s["rxSnr"]), 6.5)
        # The simulator's transponder noise is 9 dB over the floor beside it.
        self.assertAlmostEqual(s["dishRise"], 9.0, delta=1.5)
        self.assertEqual(s["dishWhere"], "Where beacon lock has the middle beacon")
        self.assertEqual(s["dishBest"], max(s["dishBest"], s["dishSnr"]))

    def test_a_weaker_beacon_reads_lower_and_best_keeps_the_peak(self):
        r = self.radio()
        r.dish_open()
        strong = self.settle(r)["dishSnr"]
        fade(r, -10.0)                     # the dish moved off the satellite
        s = self.settle(r)
        self.assertAlmostEqual(s["dishSnr"], strong - 10.0, delta=2.0)
        self.assertAlmostEqual(s["dishBest"], strong, delta=1.0)
        r.dish_reset()
        s = self.settle(r, 0.6)
        self.assertAlmostEqual(s["dishBest"], s["dishSnr"], delta=1.0)

    def test_without_beacon_lock_it_looks_near_where_the_beacon_should_be(self):
        # A dish being moved has often lost the lock; the figure must still move.
        r = self.radio(beaconMode="hold", rxCorr=2_500.0 + 3_000.0)     # held 3 kHz wrong
        r.dish_open()
        s = self.settle(r)
        self.assertGreater(s["dishSnr"], 20.0)
        self.assertTrue(s["dishWhere"].endswith("kHz from where the beacon should be"), s["dishWhere"])
        off = float(s["dishWhere"].split(", ")[-1].split()[0])
        self.assertAlmostEqual(off, -3.0, delta=0.3)


class Gain(Case):
    def spy(self, r):
        calls = []
        orig = r.dev.set_rx_gain

        def rec(mode, db):
            calls.append((mode, float(db)))
            orig(mode, db)
        r.dev.set_rx_gain = rec
        return calls

    def test_the_agc_is_held_where_it_is_while_open_and_given_back(self):
        r = self.radio()
        calls = self.spy(r)
        r.dish_open()
        s = self.settle(r, 0.5)
        self.assertEqual(calls, [("manual", 40.0)])                 # where the simulator's "AGC" is
        self.assertIn("held at 40 dB (manual)", s["dishGain"])
        # The operator's own setting never changed: not in the state, not in the config.
        self.assertEqual(s["rxGainMode"], "slow_attack")
        self.assertEqual(r.cfg["rxGainMode"], "slow_attack")
        r.dish_close()
        self.settle(r, 0.3)
        self.assertEqual(calls[-1][0], "slow_attack")

    def test_the_hold_is_said_in_the_log_and_marked_in_a_recording(self):
        # Mac test 17/10/2026, finding 11: the hold was said in the dialog
        # alone, and changed the level of a recording running with no mark.
        import json
        from ohscore import sigmf
        r = self.radio()
        path = r.start_recording()
        run_sim(r, 0.5)
        with self.assertLogs(r.log.name, "INFO") as said:
            r.dish_open()
            s = self.settle(r, 0.5)
            self.assertEqual(s["dishHeldDb"], 40.0)
            self.assertIn("A recording is running", s["dishGain"])
            r.dish_close()
            s = self.settle(r, 0.5)
        self.assertIsNone(s["dishHeldDb"])
        lines = "\n".join(said.output)
        self.assertIn("receive gain held at 40 dB manual", lines)
        self.assertIn("marked in the recording", lines)
        self.assertIn("back to the AGC (slow_attack)", lines)
        r.stop_recording()
        deadline = time.monotonic() + 10
        while r.rec_closing and time.monotonic() < deadline:
            r.heartbeat()
            time.sleep(0.02)
        m = json.loads(sigmf.paths(path)[1].read_text())
        held = [a for a in m["annotations"] if a.get("openhamshack:key") == "dishHeldDb"]
        # Before, during and after: the held stretch is a segment of its own.
        self.assertEqual([a["openhamshack:value"] for a in held], [None, 40.0, None])
        for p in sigmf.paths(path):
            p.unlink()

    def test_a_manual_gain_is_left_as_it_is(self):
        r = self.radio(rxGainMode="manual", rxGain=30.0)
        calls = self.spy(r)
        r.dish_open()
        s = self.settle(r, 0.5)
        self.assertEqual(calls, [])
        self.assertIn("manual at 30 dB already", s["dishGain"])


class Transmit(Case):
    def test_refused_while_open_and_it_will_not_open_while_transmitting(self):
        r = self.radio(mode="cw", vfo=10_489_520_000.0)
        r.dish_open()
        with self.assertRaises(TxRefused) as e:
            r.ptt(True)
        self.assertIn("Dish alignment is open", str(e.exception))
        self.assertFalse(r.state()["keyed"])
        self.assertIn("Dish alignment is open", r.state()["txBlocked"])
        r.dish_close()
        self.assertEqual(r.state()["txBlocked"], "")
        r.ptt(True)
        try:
            self.assertTrue(r.state()["keyed"])
            with self.assertRaises(ValueError) as e:
                r.dish_open()
            self.assertIn("Transmitting", str(e.exception))
            self.assertFalse(r.state()["dishOpen"])
        finally:
            r.ptt(False)


class Tone(Case):
    def pitch(self, audio, since):
        x = np.concatenate(audio.blocks[since:])[-6000:]
        X = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        return float(np.argmax(X)) * 12_000.0 / len(x)

    def share_at(self, audio, since, hz, width=15.0):
        """The share of the audio's power within `width` Hz of `hz`: near
        1 for the meter's tone, small for receive audio."""
        x = np.concatenate(audio.blocks[since:])[-6000:]
        X = np.abs(np.fft.rfft(x * np.hanning(len(x)))) ** 2
        f = np.arange(len(X)) * 12_000.0 / len(x)
        return float(X[np.abs(f - hz) <= width].sum() / max(X.sum(), 1e-30))

    def test_the_tone_replaces_the_audio_and_rises_with_the_beacon(self):
        heard = Heard()
        r = self.radio(audio=heard)
        r.dish_open()
        r.set(dishTone=True)
        s = self.settle(r)
        n = len(heard.blocks)
        self.settle(r, 1.0)
        high = self.pitch(heard, n)
        self.assertAlmostEqual(high, dishmeter.tone_hz(s["dishSnr"]), delta=60.0)
        self.assertGreater(self.share_at(heard, n, high), 0.8)
        fade(r, -12.0)
        self.settle(r)
        n = len(heard.blocks)
        s = self.settle(r, 1.0)
        low = self.pitch(heard, n)
        self.assertAlmostEqual(low, dishmeter.tone_hz(s["dishSnr"]), delta=60.0)
        self.assertLess(low, high - 400.0)
        # Off again: the receive audio, not a tone. Judged by how much of
        # the power sits at the tone's pitch, not by where the loudest bin
        # is: the receive audio's own peak can land within a few hertz of
        # the old tone by chance (1 run in 4 did, 07/10).
        r.set(dishTone=False)
        self.settle(r, 0.5)
        n = len(heard.blocks)
        self.settle(r, 1.0)
        self.assertLess(self.share_at(heard, n, low), 0.5)


class PhonePage(Case):
    def get(self, url):
        with urllib.request.urlopen(url, timeout=3) as f:
            return f.read()

    def test_served_only_while_asked_and_only_while_open(self):
        port = free_port()
        r = self.radio(dishPort=port)
        url = f"http://127.0.0.1:{port}/"
        r.dish_open()
        self.settle(r, 0.5)
        with self.assertRaises(urllib.error.URLError):              # off by default
            self.get(url)
        r.set(dishPhone=True)
        s = self.settle(r)
        self.assertTrue(s["dishUrls"])
        self.assertTrue(all(u.startswith("http://") and u.endswith(f":{port}/") for u in s["dishUrls"].split(", ")))
        page = self.get(url).decode()
        self.assertIn("Middle beacon", page)
        self.assertIn("AudioContext", page)
        # Self-contained: nothing fetched from anywhere else.
        for ref in ("https://", "src=", "<link", "@import"):
            self.assertNotIn(ref, page)
        self.assertNotIn("http://", page)
        got = json.loads(self.get(url + "s"))
        self.assertTrue(got["open"])
        self.assertAlmostEqual(got["snr"], r.state()["dishSnr"], delta=1.0)
        self.assertEqual(got["tone"], dishmeter.tone_hz(got["snr"]))
        # Reset forgets the best and the next measurement starts it again
        # (Radio.dish_reset), and the simulator runs free on its own thread,
        # so "None straight after the POST" lost the race whenever a
        # measurement landed first (5 runs in 120 under load, 10/10). A peak
        # that can't come back tells the two apart: the beacon is faded
        # first, so a best still at the old peak is a reset that did not
        # happen, whatever lands in between.
        strong = r.state()["dishBest"]
        fade(r, -10.0)
        self.settle(r)
        self.assertAlmostEqual(r.state()["dishBest"], strong, delta=1.0)     # held through the fade
        urllib.request.urlopen(urllib.request.Request(url + "reset", data=b"", method="POST"), timeout=3).read()
        s = self.settle(r, 0.6)
        self.assertLess(s["dishBest"], strong - 5.0)
        self.assertAlmostEqual(s["dishBest"], s["dishSnr"], delta=1.0)
        r.dish_close()
        with self.assertRaises(urllib.error.URLError):              # stops with the tool
            self.get(url)
        self.assertFalse(r.state()["dishPhone"])                     # and is off when it opens again
        self.assertEqual(r.state()["dishUrls"], "")

    def test_a_port_in_use_is_said_and_nothing_is_served(self):
        with socket.socket() as busy:
            busy.bind(("0.0.0.0", 0))
            busy.listen(1)
            port = busy.getsockname()[1]
            r = self.radio(dishPort=port)
            r.dish_open()
            r.set(dishPhone=True)
            s = r.state()
            self.assertIn(f"Port {port} is in use", s["dishPhoneError"])
            self.assertFalse(s["dishPhone"])
            self.assertEqual(s["dishUrls"], "")

    def test_only_addresses_off_the_internet_are_answered(self):
        # The shared range (a tailnet's, a hotspot's) built rather than
        # written: packaging/source-scrub.txt keeps real-looking ones out.
        shared = str(ipaddress.IPv4Network((0x64400000, 10))[7])        # in 100.64/10
        for a in ("10.0.0.5", "172.16.3.4", "127.0.0.1", "169.254.1.1", shared,
                  "::1", "fe80::1", "fd00::5", "::ffff:10.1.2.3"):
            self.assertTrue(dishmeter.allowed_client(a), a)
        for a in ("8.8.8.8", "81.2.69.160", "2a00:1450:4009:81f::200e", "::ffff:8.8.8.8", "nonsense"):
            self.assertFalse(dishmeter.allowed_client(a), a)


class Playback(unittest.TestCase):
    def test_it_measures_a_recording_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = make_radio(tmp)
            rec.start()
            try:
                wait_rx_lock(rec)
                path = rec.start_recording()
                run_sim(rec, 3.0)
                rec.stop_recording()
                t0 = time.monotonic()
                while rec.rec_closing and time.monotonic() - t0 < 10:
                    rec.heartbeat()
                    time.sleep(0.02)
            finally:
                rec.stop()
            r = make_radio(tmp)
            try:
                r.start_playback(Path(path), realtime=False)
                r.dish_open()
                run_sim(r, 1e9, until=lambda: r.state()["playEnded"])
                s = r.state()
                self.assertGreater(s["dishBest"], 20.0)
                self.assertAlmostEqual(s["dishRise"], 9.0, delta=1.5)
                self.assertIn("recording", s["dishGain"])
            finally:
                r.dish_close()
                r.stop()


if __name__ == "__main__":
    unittest.main()
