"""PSK and SSTV through Radio's engine (RADIO-SDR-PLAN §8.5 M2): shack_sdr's
Rust decoders as the mode's decoder and as sessions on frequencies of
their own, on the band simulator faster than real time, with Radio's
receive audio at 48 kHz (Engine.OUT_RATE) - the decoders are still fed the
engine's 12 kHz audio or a 12 kHz channel of its bank.

The air is the simulator with its own stations off and ours put on it
(HamSim.add_station): PSK sent by psk.py's encoder, and SSTV pictures sent
by shack_sdr's test transmitter, so what is heard is known exactly.

- **PSK as the mode:** the mode's own station and the extra channels
  pskChannels names, each character an `events` item in the shape the
  window and Remote read, with its `channel`; a channel added live.
- **PSK as a session:** one session, several channels (`channels`
  offsets from its frequency), each result's offsetHz on its station.
- **SSTV as the mode:** start, every row as it arrives (line counting
  from 1), done with the picture's `file`; the PNG in the data folder.
- **SSTV as a session:** `image` results with base64 rows and no path,
  and the picture in Decoders.files() and file().
- **The files cap:** the oldest pictures the host made beyond
  decoderFilesKeep go; pictures from before the host named them stay.

What the server makes of these (api/decoders/files) is test_server_decoders;
the same signals through an RSP's 2.4 MS/s path are test_ham_dab_rsp."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import base64
import os
import time
import unittest

import numpy as np

from ham_helpers import close, make_radio, pump

from ohscore import sdr
from ohscore.devices import simsignals as sg
from ohscore.modes import psk

PARKED = "no shack_sdr here, or the Rust PSK decoder switched off (ohscore/sdr.py PSK_ON_SHACK_SDR)"
RUST_PSK = sdr.available() and sdr.PSK_ON_SHACK_SDR

DIAL = 14_101_000.0            # USB; the simulator's own stations are off (simSignals False)
# dBFS: a good signal, among the simulator's own (-68 to -52). Much
# stronger (-42) and the receiver's AGC, lifting the noise by up to 40 dB
# in each gap between overs, has an idle PSK channel print a few
# characters of noise as it does; that is the AGC's doing, not a station's.
LEVEL = -58.0


def psk_air(text, centre, variant="psk31", gap_s=2.0):
    """`text` sent by psk.py's encoder at `centre` audio Hz, then `gap_s` of
    silence, as the complex baseband the simulator puts on a USB dial."""
    audio = psk.Encoder().render(text=text, variant=variant, center=centre)
    audio = np.concatenate([np.zeros(int(1.0 * 12_000), np.float32), audio,
                            np.zeros(int(gap_s * 12_000), np.float32)])
    return sg.analytic(audio)


def sstv_air(mode="robot36"):
    """One picture from shack_sdr's SSTV test transmitter, then quiet for as
    long again, so a looped template sends it once a cycle."""
    from shack_sdr import sstv
    audio, sent = sstv.testsig(mode, rate=12_000.0, lead_s=1.0, tail_s=2.0)
    audio = np.concatenate([audio, np.zeros(len(audio), np.float32)])
    return sg.analytic(audio), sent


def by_channel(events, mode="psk31"):
    out = {}
    for ev in events:
        if ev.get("mode") == mode and ev.get("text"):
            out[ev["channel"]] = out.get(ev["channel"], "") + ev["text"]
    return out


def radio(**over):
    cfg = {"simSignals": False, "vfo": DIAL, "mode": "usb", "simSeed": 3}
    cfg.update(over)
    return make_radio(**cfg)


@unittest.skipUnless(RUST_PSK, PARKED)
class PskAsTheMode(unittest.TestCase):
    def setUp(self):
        self.r = radio(mode="psk31")
        self.addCleanup(close, self.r)
        self.events = self.r.subscribe("events", 20000)
        self.r.start()
        self.assertEqual(self.r.OUT_RATE, 48_000)

    def test_the_modes_own_station_and_the_extra_channels_copy(self):
        self.r.dev.add_station("own", DIAL, psk_air("CQ CQ DE G4AAA G4AAA K ", 1000.0), LEVEL)
        self.r.dev.add_station("second", DIAL, psk_air("QRZ DE M0BBB M0BBB ", 1630.0), LEVEL)
        self.r.dev.add_station("third", DIAL, psk_air("TEST DE 2E0CCC 2E0CCC ", 2240.0), LEVEL)
        self.r.set(pskChannels=[1630.0, 2240.0])
        got = []

        def heard():
            got.extend(self.events.drain())
            ch = by_channel(got)
            return all(t in ch.get(c, "") for c, t in ((1000.0, "G4AAA G4AAA K"), (1630.0, "M0BBB M0BBB"),
                                                       (2240.0, "2E0CCC 2E0CCC")))
        pump(self.r, 90, until=heard)
        ch = by_channel(got)
        self.assertIn("CQ CQ DE G4AAA G4AAA K", ch.get(1000.0, ""), ch)
        self.assertIn("QRZ DE M0BBB M0BBB", ch.get(1630.0, ""), ch)
        self.assertIn("TEST DE 2E0CCC 2E0CCC", ch.get(2240.0, ""), ch)
        # The shape the window, Remote and Enable TX's replies read.
        ev = next(e for e in got if e.get("mode") == "psk31" and e.get("channel") == 1630.0)
        self.assertEqual(set(ev) >= {"mode", "text", "center", "df", "snr", "channel"}, True)
        self.assertAlmostEqual(ev["center"], 1630.0, delta=2.0)
        # The mode's decoder is the session "vfo", its channels in its params
        # (offsets from the audio centre it reports) and its meta.
        vfo = self.r.decoders.session("vfo")
        self.assertEqual((vfo["decoder"], vfo["panel"], vfo["params"]["baud"]), ("psk", "text", 31.25))
        centre = vfo["audioCentreHz"]
        self.assertEqual(sorted(centre + float(c) for c in vfo["params"]["channels"].split(",")),
                         [1000.0, 1630.0, 2240.0])
        self.assertEqual(len(vfo["meta"]["channels"]), 3)

    def test_a_channel_added_while_the_mode_runs(self):
        self.r.dev.add_station("late", DIAL, psk_air("LATE STATION DE G0DDD ", 1800.0), LEVEL)
        pump(self.r, 5)
        self.assertEqual(by_channel(self.events.drain()), {})
        self.r.set(pskChannels=[1800.0])
        got = []

        def heard():
            # The station loops: added part way through an over, the next
            # over is the first whole one.
            got.extend(self.events.drain())
            return "LATE STATION DE G0DDD" in by_channel(got).get(1800.0, "")
        pump(self.r, 90, until=heard)
        self.assertIn("LATE STATION DE G0DDD", by_channel(got).get(1800.0, ""))
        # Taken off again: nothing more from it.
        self.r.set(pskChannels=[])
        pump(self.r, 3)
        self.events.drain()
        pump(self.r, 20)
        self.assertNotIn(1800.0, by_channel(self.events.drain()))

    def test_psk125_receives_and_transmits(self):
        # New in the mode list beside PSK31/63, and psk.py's encoder sends it.
        from ohscore import modes_glue
        self.assertEqual(modes_glue.available(["psk125"])["psk125"]["encode"], True)
        self.r.set(mode="psk125")
        self.r.dev.add_station("fast", DIAL, psk_air("PSK125 TEST DE G4EEE ", 1000.0, "psk125"), LEVEL)
        got = []

        def heard():
            got.extend(self.events.drain())
            return "G4EEE" in by_channel(got, "psk125").get(1000.0, "")
        pump(self.r, 90, until=heard)
        self.assertIn("PSK125 TEST DE G4EEE", by_channel(got, "psk125").get(1000.0, ""))


@unittest.skipUnless(RUST_PSK, PARKED)
class PskAsASession(unittest.TestCase):
    def test_one_session_copies_several_stations_away_from_the_dial(self):
        r = radio(vfo=DIAL)
        self.addCleanup(close, r)
        r.start()
        there = DIAL + 20_000.0           # another USB dial inside the span
        r.dev.add_station("a", there, psk_air("STATION ALPHA ALPHA ", 1000.0, "psk63"), LEVEL)
        r.dev.add_station("b", there, psk_air("STATION BRAVO BRAVO ", 1700.0, "psk63"), LEVEL)
        # The session's frequency is the middle of the two; its channels are
        # offsets from there, as on api/decoders.
        mid = there + 1350.0
        sess = r.decoders.start("psk", mid, {"baud": 62.5, "channels": "-350,350"})
        self.assertEqual((sess["decoder"], sess["panel"]), ("psk", "text"))

        def texts():
            out = {}
            for it in r.decoders.session(sess["id"])["results"]:
                if it.get("type") == "text":
                    k = -350.0 if float(it["offsetHz"]) < 0 else 350.0
                    out[k] = out.get(k, "") + it["text"]
            return out
        pump(r, 90, until=lambda: "BRAVO BRAVO" in texts().get(350.0, "") and "ALPHA ALPHA" in
             texts().get(-350.0, ""))
        got = texts()
        self.assertIn("STATION ALPHA ALPHA", got.get(-350.0, ""), got)
        self.assertIn("STATION BRAVO BRAVO", got.get(350.0, ""), got)
        view = r.decoders.session(sess["id"])
        self.assertEqual([c["offsetHz"] for c in view["meta"]["channels"]], [-350.0, 350.0])
        self.assertEqual(view["stats"]["channels"], 2)
        # A waterfall click on a third station: the session follows live.
        self.assertEqual(r.decoders.configure(sess["id"], {"channels": "-350,350,900"})["params"]["channels"],
                         "-350,350,900")


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class SstvAsTheMode(unittest.TestCase):
    def test_a_picture_builds_row_by_row_and_lands_in_the_data_folder(self):
        r = radio(mode="sstv")
        self.addCleanup(close, r)
        events = r.subscribe("events", 50000)
        r.start()
        air, sent = sstv_air("robot36")
        r.dev.add_station("sstv", DIAL, air, LEVEL)
        got = []

        def done():
            got.extend(e for e in events.drain() if e.get("mode") == "sstv")
            return any(e.get("state") == "done" for e in got)
        pump(r, 120, until=done)
        states = [e["state"] for e in got]
        self.assertEqual(states[0], "start", states[:3])
        start = got[0]
        self.assertEqual((start["fmt"], start["width"], start["height"]), ("robot36", 320, 240))
        lines = [e for e in got if e["state"] == "line"]
        # Progressive: the rows come as they are read, top down the first
        # time, before the picture is done, each a whole row of RGB.
        first_seen = []
        for e in lines:
            if e["line"] not in first_seen:
                first_seen.append(e["line"])
        self.assertEqual(first_seen, sorted(first_seen))
        self.assertGreaterEqual(len(first_seen), 230)
        self.assertEqual(len(base64.b64decode(lines[0]["row"])), 320 * 3)
        self.assertTrue(all(e["name"] == start["name"] and e["of"] == 240 for e in lines))
        self.assertLess(states.index("line"), states.index("done"))
        done_ev = next(e for e in got if e["state"] == "done")
        self.assertEqual(done_ev["name"], start["name"])
        self.assertTrue(done_ev["file"].endswith(".png"))
        self.assertTrue(os.path.isfile(done_ev["path"]))
        self.assertEqual(os.path.dirname(done_ev["path"]), str(r.sstv_dir()))
        # The picture is the one sent (shack_sdr's own score of it): at this
        # level about 15-16 dB PSNR, the README's 6-10 dB-SNR figure; a
        # picture of noise, or of the wrong rows, scores well under 10.
        from shack_sdr import sstv
        with open(done_ev["path"], "rb") as f:
            png = f.read()
        self.assertGreater(sstv.score(sent, sstv.png_rgb(png))["psnr"], 12.0)
        self.assertIn(done_ev["file"], [f["name"] for f in r.decoders.files()])


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class SstvAsASession(unittest.TestCase):
    def test_a_session_sends_rows_and_keeps_the_picture(self):
        r = radio()
        self.addCleanup(close, r)
        r.start()
        there = DIAL + 30_000.0
        air, _sent = sstv_air("robot36")
        r.dev.add_station("sstv", there, air, LEVEL)
        # IQ centred on the 1900 Hz leader: the dial plus 1900 (shack_sdr
        # sstv.IQ_CENTRE_HZ).
        sess = r.decoders.start("sstv", there + 1900.0)
        self.assertEqual(sess["panel"], "image")
        pump(r, 120, until=lambda: any(i.get("event") == "done" for i in r.decoders.session(sess["id"])["results"]))
        res = [i for i in r.decoders.session(sess["id"])["results"] if i.get("type") == "image"]
        start = next(i for i in res if i["event"] == "start")
        self.assertEqual((start["width"], start["height"]), (320, 240))
        rows = [i for i in res if i["event"] == "lines"]
        self.assertTrue(rows)
        self.assertEqual(len(base64.b64decode(rows[0]["rgb"])) % (320 * 3), 0)
        done = next(i for i in res if i["event"] == "done")
        self.assertNotIn("path", done)           # a client names it, never places it
        names = [f["name"] for f in r.decoders.files()]
        self.assertIn(done["file"], names)
        self.assertTrue(r.decoders.file(done["file"]).startswith(b"\x89PNG"))
        self.assertIsNone(r.decoders.file("../" + done["file"]))
        self.assertIsNone(r.decoders.file("nothing.png"))
        view = r.decoders.session(sess["id"])
        self.assertEqual(view["meta"]["state"], "done")
        self.assertEqual(view["meta"]["file"], done["file"])


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
@unittest.skipIf(sdr.PSK_ON_SHACK_SDR, "the Rust PSK decoder is switched on")
class PskAsShipped(unittest.TestCase):
    """With the Rust PSK decoder switched off (ohscore/sdr.py
    PSK_ON_SHACK_SDR): the PSK modes decode with psk.py as before
    milestone 2, `psk` is no decoder session, and there is no pskChannels."""

    def test_the_mode_copies_with_psk_py_and_psk_sessions_are_not_offered(self):
        from ohscore.decoders import Refused
        r = radio(mode="psk31")
        self.addCleanup(close, r)
        events = r.subscribe("events", 20000)
        r.start()
        r.dev.add_station("own", DIAL, psk_air("CQ CQ DE G4AAA G4AAA K ", 1000.0), LEVEL)
        got = []

        def heard():
            got.extend(e for e in events.drain() if e.get("mode") == "psk31")
            return "G4AAA G4AAA K" in "".join(e.get("text", "") for e in got)
        pump(r, 90, until=heard)
        self.assertIn("CQ CQ DE G4AAA G4AAA K", "".join(e.get("text", "") for e in got))
        self.assertNotIn("channel", got[0])
        self.assertEqual(type(r.decoder).__module__, "ohscore.modes.psk")
        self.assertEqual(r.decoders.sessions(), [])               # no "vfo": psk.py is not a session
        self.assertNotIn("psk", [e["id"] for e in r.decoders.catalogue()])
        with self.assertRaises(Refused) as cm:
            r.decoders.start("psk", DIAL + 1000.0)
        self.assertEqual(cm.exception.code, "unknown_decoder")
        self.assertNotIn("pskChannels", r.state())


class FilesCap(unittest.TestCase):
    """decoderFilesKeep, on files laid out as the host names them: no
    decoding needed to test what is deleted."""

    @unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
    def test_the_oldest_host_pictures_go_and_older_ones_stay(self):
        r = radio(decoderFilesKeep=2)
        self.addCleanup(close, r)
        d = r.sstv_dir()
        d.mkdir(parents=True, exist_ok=True)
        png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC")
        made = [f"ds_00{k}a_sstv_20261023-10{k}000Z_robot36.png" for k in range(4)]
        for k, name in enumerate(made):
            (d / name).write_bytes(png)
            t = time.time() - 1000 + 100 * k
            os.utime(d / name, (t, t))
        (d / "sstv_robot36_0001.png").write_bytes(png)      # sstv.py's, from before
        r.start()                                          # the host's start prunes
        left = sorted(p.name for p in d.iterdir())
        self.assertEqual(left, sorted(made[2:] + ["sstv_robot36_0001.png"]))
        self.assertEqual(sorted(f["name"] for f in r.decoders.files()), left)
        # And the listing is newest first.
        names = [f["name"] for f in r.decoders.files() if f["name"].startswith("ds_")]
        self.assertEqual(names, [made[3], made[2]])


if __name__ == "__main__":
    unittest.main()
