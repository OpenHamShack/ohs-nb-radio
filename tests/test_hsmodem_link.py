import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
"""HSmodem between two OpenHamShack NB engines through the simulated transponder,
and the transmit guards on an HSmodem transmission.

Two Radios, two simulators, one transponder (SimDevice.attach_peer): what
A sends comes down at B through the round trip, A's uplink error and B's
LNB error, at A's level relative to the beacon, in the simulator's
transponder noise. A sends a picture and a text file with radio.send(), as
the panel does; B receives them with the hsmodem decoder its mode runs,
and the files must arrive byte for byte. Each run prints the decode
quality B saw and its margin over the speed's cliff (the Es/N0 below which
frames start to go, rust/ohsdigi/examples/hsspeeds).

Nothing here opens a radio: both devices are simulators."""
import os
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from helpers import run_sim, sim_cfg, wait_rx_lock
from ohscore.audio import NullAudio
from ohscore.engine import TxRefused
from ohscore.modes import hsmodem as hs
from ohsnb import bandplan
from ohsnb.devices.sim import SimDevice
from ohsnb.radio import Radio

CARD = Path(__file__).resolve().parents[1] / "ohsnb" / "devices" / "mmb-testcard.jpg"
DIGI = 10_489_620_000.0          # the 2.7 kHz digimode segment
# Es/N0 (dB) at which every frame still decodes, per speed (hsspeeds, 07/10).
CLIFF = {1200: 8.0, 2400: 7.0, 3000: 11.0, 4000: 10.0, 4410: 10.0, 4800: 9.0, 5500: 12.0, 6000: 13.0,
         6600: 13.0, 7200: 13.0}


@unittest.skipUnless(hs.AVAILABLE, hs.WHY_NOT or "ohsdigi")
class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.radios = []

    def tearDown(self):
        for r in self.radios:
            r.stop()

    def radio(self, name, **over):
        cfg = sim_cfg(mode="hsmodem", vfo=DIGI, **over)
        d = os.path.join(self.tmp, name)
        os.makedirs(d, exist_ok=True)
        r = Radio(cfg, persist=False, data_dir=Path(d), audio=NullAudio(realtime=False),
                  device=SimDevice(dict(cfg)))
        self.radios.append(r)
        return r


class TwoStations(Base):
    def link(self, speed: int, tx_gain: float):
        # A 25 Hz uplink error (TX lock finds it while A sends) and LNBs
        # that disagree by kilohertz (beacon lock takes that out at both).
        a = self.radio("a", callsign="G4AAA", locator="IO91wm", hsSpeed=speed, txGain=tx_gain,
                       simUlErrorHz=25.0, simSeed=7)
        b = self.radio("b", callsign="G4BBB", hsSpeed=speed, simRxErrorHz=-1700.0, simSeed=8)
        a._inj_device.attach_peer(b._inj_device)
        ev = b.subscribe("events", 8000)
        a.start()
        b.start()
        self.assertTrue(wait_rx_lock(a) and wait_rx_lock(b))
        run_sim(b, 2.0)
        return a, b, ev

    def send_and_wait(self, a, b, ev, kind: str, **msg) -> list[dict]:
        a.send("hsmodem", **msg)
        got = []
        t0 = time.monotonic()
        while time.monotonic() - t0 < 240:
            a.heartbeat()
            got += run_sim(b, 1.0, [ev])["events"]
            if not a.state()["keyed"] and any(e.get("kind") == kind for e in got):
                break
        got += run_sim(b, 1.0, [ev])["events"]
        return got

    def check(self, speed: int, tx_gain: float):
        a, b, ev = self.link(speed, tx_gain)
        img = CARD.read_bytes()
        got = self.send_and_wait(a, b, ev, "image", name="station.jpg", data=img)
        pics = [e for e in got if e.get("kind") == "image"]
        self.assertEqual(len(pics), 1, [e.get("kind") for e in got if e.get("kind") != "file_progress"])
        self.assertEqual(Path(pics[0]["path"]).read_bytes(), img)
        self.assertEqual(Path(pics[0]["path"]).parent, b.hsmodem_dir())
        self.assertIn(("G4AAA", "IO91wm"), {(e["call"], e["loc"]) for e in got if e.get("kind") == "station"})
        text = "Notes from G4AAA\n" + "".join(f"line {i}: the quick brown fox\n" for i in range(40))
        got2 = self.send_and_wait(a, b, ev, "bulletin", name="notes.txt", data=text.encode())
        txt = [e for e in got2 if e.get("kind") == "bulletin"]
        self.assertEqual([e["text"] for e in txt], [text])
        self.assertEqual((b.hsmodem_dir() / "notes.txt").read_text(), text)
        # TX lock worked on the HSmodem signal as on any other (uplink 25 Hz high).
        self.assertLess(abs(a.state()["txCorr"] + 25.0), 5.0, a.state()["txCorr"])
        mer = [e["mer"] for e in got + got2 if e.get("kind") == "stats" and e["sync"] and e["ok"]]
        m = float(np.median(mer))
        print(f"\nHSmodem {speed} bit/s NB to NB, A {tx_gain:g} dB ({a.state().get('vsBeacon')} dB vs beacon): "
              f"MER {m:.1f} dB, margin {m - CLIFF[speed]:.1f} dB over the {CLIFF[speed]:g} dB cliff")
        self.assertGreater(m - CLIFF[speed], 1.0)

    def test_default_speed_picture_and_text(self):
        # 7 dB under the beacon: inside the level guard's 6 dB margin.
        self.check(hs.DEFAULT_SPEED, -27.0)

    def test_bpsk_2400_picture_and_text(self):
        self.check(2400, -27.0)


class Guards(Base):
    def keyed_radio(self, **over):
        over.setdefault("callsign", "G4AAA")
        r = self.radio("g", **over)
        r.start()
        self.assertTrue(wait_rx_lock(r))
        return r

    def test_no_callsign_no_transmission(self):
        r = self.keyed_radio(callsign="")
        with self.assertRaisesRegex(TxRefused, "callsign"):
            r.send("hsmodem", text="hello")
        self.assertFalse(r.state()["keyed"])

    def test_band_plan_refuses_the_narrow_and_the_ssb_segments(self):
        r = self.keyed_radio()
        r.set(vfo=10_489_560_000.0)
        # Idle, the TX button says so already, by the speed's own width.
        run_sim(r, 0.3)
        self.assertIn(f"{bandplan.HSMODEM_WIDTH[4410]:.0f} Hz wide", r.state()["txBlocked"])
        with self.assertRaisesRegex(TxRefused, "500 Hz at most"):
            r.send("hsmodem", text="hello")
        r.set(vfo=10_489_700_000.0)
        with self.assertRaisesRegex(TxRefused, "not allowed in the SSB only segment"):
            r.send("hsmodem", text="hello")
        r.set(vfo=DIGI)
        r.send("hsmodem", text="hello")
        self.assertTrue(r.state()["keyed"])
        r.halt()

    def test_longer_than_the_time_out_is_refused_before_key_up(self):
        r = self.keyed_radio(hsSpeed=1200)
        r.set(authorise=True, txTimeoutSec=30.0)
        with self.assertRaisesRegex(TxRefused, "longer than the transmit time-out"):
            r.send("hsmodem", name="station.jpg", data=CARD.read_bytes())
        self.assertFalse(r.state()["keyed"])

    def test_level_guard_trims_an_hsmodem_transmission(self):
        # About level with the beacon, as TX lock measures it: the guard
        # (limit, 6 dB margin) trims the gain while the file goes out.
        r = self.keyed_radio(txGain=-14.0, levelMode="limit")
        r.send("hsmodem", name="station.jpg", data=CARD.read_bytes())
        run_sim(r, 15.0, until=lambda: r.state()["txGain"] < -18.0)
        self.assertLess(r.state()["txGain"], -18.0, r.state().get("vsBeacon"))
        r.halt()

    def test_every_speed_fits_and_the_table_is_what_is_sent(self):
        # What send() measures (Engine._occupied: 99.5 % of the power) of a
        # rendered picture at each speed: inside 2.7 kHz, and what the band
        # plan was told within 60 Hz, never under it.
        self.assertEqual(bandplan.HSMODEM_SPEEDS, tuple(sorted(hs.SPEEDS)))
        r = self.radio("w", callsign="G4AAA")
        img = CARD.read_bytes()[:3000]
        for bps in hs.SPEEDS:
            a = hs.Encoder().render(name="x.jpg", data=img, speed=bps, callsign="G4AAA")
            lo, hi = r._occupied("hsmodem", 0.0, a)
            self.assertLessEqual(hi - lo, bandplan.HSMODEM_WIDTH[bps], bps)
            self.assertGreater(hi - lo, bandplan.HSMODEM_WIDTH[bps] - 60.0, bps)
            self.assertLessEqual(bandplan.HSMODEM_WIDTH[bps], bandplan.MAX_BW)


if __name__ == "__main__":
    unittest.main()
